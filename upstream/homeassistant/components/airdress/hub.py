"""This installation's side of the channel: what it shares and what it runs.

Every request the operator sends is checked here before anything runs, whatever
the operator decided: the target must be shared at the level the request needs,
a sensitive target must be opted in on this side too, and an action may only
address entities of its own domain. Actions run as the Airdress system user,
which is not an administrator.
"""

import asyncio
from typing import TYPE_CHECKING, Any

from airdress_home import Features, Shared, SharedEntity, Track, models as outcome
import probatio

from homeassistant.const import ATTR_ENTITY_ID, __version__ as HA_VERSION
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
    split_entity_id,
)
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.json import json_bytes
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import slugify
from homeassistant.util.json import json_loads

from .const import (
    AVAILABILITY_GRACE,
    CALL_TIMEOUT,
    CONF_OBSERVE,
    CONF_OPERATE,
    CONF_SENSITIVE,
    DOMAIN,
    EVENT_OPERATE,
    LOGGER,
    signal_connection,
    signal_emit,
    signal_features,
    signal_track,
)
from .sensitive import device_class_of, entity_is_sensitive

if TYPE_CHECKING:
    from airdress_home import HomeSession

TARGET_KEYS = frozenset({"entity_id", "device_id", "area_id", "floor_id", "label_id"})
"""Keys that would address something other than the call's own targets."""


def _is_slug(value: str) -> bool:
    return bool(value) and slugify(value) == value


class AirdressHub:
    """The handler the channel hands the operator's requests to."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        user_id: str,
        options: dict[str, Any],
    ) -> None:
        """Initialize the handler."""
        self.hass = hass
        self.entry_id = entry_id
        self.user_id = user_id
        self._session: HomeSession | None = None
        self._wanted: dict[str, tuple[str, ...]] = {}
        """What the operator asked to have streamed: entity -> attributes."""
        self._unsubscribe: CALLBACK_TYPE | None = None
        self._streaming: frozenset[str] = frozenset()
        self.available = False
        """Whether entities are available: the channel is up, or went down
        less than :data:`AVAILABILITY_GRACE` seconds ago."""
        self._unavailable_later: CALLBACK_TYPE | None = None
        self.update_options(options)

    def attach(self, session: HomeSession) -> None:
        """The session observed entities are streamed on."""
        self._session = session

    @callback
    def update_options(self, options: dict[str, Any]) -> None:
        """Take what the user shares, at which level."""
        self.operate: frozenset[str] = frozenset(options.get(CONF_OPERATE, []))
        self.observe: frozenset[str] = self.operate | frozenset(
            options.get(CONF_OBSERVE, [])
        )
        self.sensitive_allowed: frozenset[str] = frozenset(
            options.get(CONF_SENSITIVE, [])
        )
        self._async_update_observing()

    @callback
    def _async_update_observing(self) -> None:
        """Stream exactly the entities the operator asked for and the user shares."""
        streaming = frozenset(e for e in self._wanted if self._observable(e))
        if streaming == self._streaming:
            return
        self.async_stop_observing()
        self._streaming = streaming
        if streaming:
            self._unsubscribe = async_track_state_change_event(
                self.hass, sorted(streaming), self._async_state_changed
            )

    @callback
    def async_stop_observing(self) -> None:
        """Stop streaming."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._streaming = frozenset()

    def _frame_state(self, state: State) -> dict[str, Any]:
        """A state as the operator receives it: only the attributes it keeps."""
        keep = self._wanted.get(state.entity_id, ())
        attributes = {k: v for k, v in state.attributes.items() if k in keep}
        return {
            "state": state.state,
            # Through Home Assistant's encoder, so every value is plain JSON.
            "attributes": json_loads(json_bytes(attributes)),
            "lastChanged": state.last_changed.isoformat(),
        }

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """An observed entity changed; the operator keeps the newest per entity."""
        session, new = self._session, event.data["new_state"]
        entity_id = event.data["entity_id"]
        if session is None or new is None or entity_id not in self._streaming:
            return
        old = event.data["old_state"]
        self.hass.async_create_background_task(
            session.send_state(
                entity_id,
                self._frame_state(new),
                None if old is None else self._frame_state(old),
            ),
            f"airdress observe {entity_id}",
        )

    def _own(self, entity_id: str) -> bool:
        """Whether Airdress itself created the entity, such as the owner's tracker.

        Its own entities are never shared back: observing the tracker would
        echo the owner's location to the operator that sent it.
        """
        entry = er.async_get(self.hass).async_get(entity_id)
        return entry is not None and entry.platform == DOMAIN

    def _operable(self, entity_id: str) -> bool:
        return entity_id in self.operate and not self._own(entity_id)

    def _observable(self, entity_id: str) -> bool:
        return entity_id in self.observe and not self._own(entity_id)

    def _shared_entity(self, entity_id: str) -> SharedEntity:
        return SharedEntity(entity_id, device_class_of(self.hass, entity_id))

    def shared(self) -> Shared:
        """What is shared, and at which level; never a name or a value."""
        return Shared(
            integration_version=str(
                async_get_loaded_integration(self.hass, DOMAIN).version or HA_VERSION
            ),
            hub_version=HA_VERSION,
            operate=tuple(
                self._shared_entity(e)
                for e in sorted(self.operate)
                if self._operable(e)
            ),
            observe=tuple(
                self._shared_entity(e)
                for e in sorted(self.observe)
                if self._observable(e)
            ),
        )

    @callback
    def revoked(self) -> None:
        """The operator revoked this installation; reloading reports it."""
        LOGGER.warning("The Airdress operator revoked this Home Assistant")
        self.hass.config_entries.async_schedule_reload(self.entry_id)

    @callback
    def lapsed(self) -> None:
        """The owner's approval of this installation lapsed; reloading reports it."""
        LOGGER.warning(
            "The Airdress operator's approval of this Home Assistant has lapsed"
        )
        self.hass.config_entries.async_schedule_reload(self.entry_id)

    @callback
    def connection_changed(self, up: bool) -> None:
        """The channel came up or went down.

        The operator ends every channel after an hour and the hub dials again
        at once: a planned re-dial, over in about a second. Entities stay
        available through it; they become unavailable only when the channel
        stays down for :data:`AVAILABILITY_GRACE` seconds.
        """
        if up:
            LOGGER.info("Connected to the Airdress operator")
            self._cancel_unavailable()
            self._set_available(True)
            return
        LOGGER.info("Disconnected from the Airdress operator; reconnecting")
        if self.available and self._unavailable_later is None:
            self._unavailable_later = async_call_later(
                self.hass, AVAILABILITY_GRACE, self._async_still_down
            )

    @callback
    def _async_still_down(self, _now: Any) -> None:
        self._unavailable_later = None
        self._set_available(False)

    @callback
    def _cancel_unavailable(self) -> None:
        if self._unavailable_later is not None:
            self._unavailable_later()
            self._unavailable_later = None

    @callback
    def _set_available(self, available: bool) -> None:
        if available == self.available:
            return
        self.available = available
        async_dispatcher_send(self.hass, signal_connection(self.entry_id), available)

    @callback
    def async_stop(self) -> None:
        """The entry is unloading: nothing is scheduled past it."""
        self._cancel_unavailable()

    @callback
    def features(self, features: Features) -> None:
        """The operator declared what its Home offers this installation."""
        if features.dropped:
            LOGGER.debug("The operator declared %s malformed events", features.dropped)
        self._wanted = {
            entity: tuple(features.observe_attributes.get(entity, ()))
            for entity in features.observe
        }
        self._async_update_observing()
        async_dispatcher_send(self.hass, signal_features(self.entry_id), features)

    @callback
    def emit(
        self, event: str, event_type: str, data: dict[str, Any] | None, function: str
    ) -> None:
        """The operator emitted an event; the event entity decides if it knows it."""
        async_dispatcher_send(
            self.hass, signal_emit(self.entry_id), event, event_type, data, function
        )

    @callback
    def track(self, track: Track) -> None:
        """Move the owner's tracker; the tracker platform decides if it knows it."""
        async_dispatcher_send(self.hass, signal_track(self.entry_id), track)

    def _refusal(
        self, action: str, targets: list[str], data: dict[str, Any] | None
    ) -> str | None:
        """Why this call may not run, or ``None``."""
        domain, _, service = action.partition(".")
        if (
            not _is_slug(domain)
            or not _is_slug(service)
            or (data is not None and not TARGET_KEYS.isdisjoint(data))
            or any(split_entity_id(t)[0] != domain for t in targets if "." in t)
            or any("." not in t for t in targets)
        ):
            return outcome.REJECTED
        if not all(self._operable(t) for t in targets):
            return outcome.NOT_EXPOSED
        if any(self.hass.states.get(t) is None for t in targets):
            return outcome.NOT_FOUND
        if any(
            t not in self.sensitive_allowed and entity_is_sensitive(self.hass, t)
            for t in targets
        ):
            return outcome.SENSITIVE_REFUSED
        if not self.hass.services.has_service(domain, service):
            return outcome.REJECTED
        return None

    async def call(
        self,
        action: str,
        targets: list[str],
        data: dict[str, Any] | None,
        function: str,
    ) -> tuple[str, Any]:
        """Run ``action`` on ``targets``, if everything on this side allows it."""
        if (refused := self._refusal(action, targets, data)) is not None:
            LOGGER.debug("Refused a call from the operator: %s", refused)
            return refused, None
        domain, _, service = action.partition(".")
        context = Context(user_id=self.user_id)
        self.hass.bus.async_fire(
            EVENT_OPERATE,
            {"function": function, "action": action, ATTR_ENTITY_ID: targets},
            context=context,
        )
        try:
            async with asyncio.timeout(CALL_TIMEOUT):
                await self.hass.services.async_call(
                    domain,
                    service,
                    {**(data or {}), ATTR_ENTITY_ID: targets},
                    blocking=True,
                    context=context,
                )
        except ServiceNotFound, ServiceValidationError, Unauthorized, probatio.Invalid:
            return outcome.REJECTED, None
        except HomeAssistantError, TimeoutError:
            return outcome.FAILED, None
        return outcome.OK, None

    async def read(self, entity: str) -> tuple[str, str | None, str | None]:
        """Read the state of an entity shared for observing."""
        if not self._observable(entity):
            return outcome.NOT_EXPOSED, None, None
        if (state := self.hass.states.get(entity)) is None:
            return outcome.NOT_FOUND, None, None
        return outcome.OK, state.state, state.last_changed.isoformat()
