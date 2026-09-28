"""This installation's side of the channel: what it shares and what it runs.

Every request the operator sends is checked here before anything runs, whatever
the operator decided: the target must be shared at the level the request needs,
a sensitive target must be opted in on this side too, and an action may only
address entities of its own domain. Actions run as the Airdress system user,
which is not an administrator.
"""

import asyncio
from typing import Any

from airdress_home import Features, Shared, SharedEntity, Track, models as outcome
import probatio

from homeassistant.const import ATTR_ENTITY_ID, __version__ as HA_VERSION
from homeassistant.core import Context, HomeAssistant, callback, split_entity_id
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.loader import async_get_loaded_integration
from homeassistant.util import slugify

from .const import (
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
)
from .sensitive import device_class_of, entity_is_sensitive

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
        self.update_options(options)

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

    def _shared_entity(self, entity_id: str) -> SharedEntity:
        return SharedEntity(entity_id, device_class_of(self.hass, entity_id))

    def shared(self) -> Shared:
        """What is shared, and at which level; never a name or a value."""
        return Shared(
            integration_version=str(
                async_get_loaded_integration(self.hass, DOMAIN).version or HA_VERSION
            ),
            hub_version=HA_VERSION,
            operate=tuple(self._shared_entity(e) for e in sorted(self.operate)),
            observe=tuple(self._shared_entity(e) for e in sorted(self.observe)),
        )

    @callback
    def revoked(self) -> None:
        """The operator revoked this installation; reloading reports it."""
        LOGGER.warning("The Airdress operator revoked this Home Assistant")
        self.hass.config_entries.async_schedule_reload(self.entry_id)

    @callback
    def connection_changed(self, up: bool) -> None:
        """The channel came up or went down."""
        if up:
            LOGGER.info("Connected to the Airdress operator")
        else:
            LOGGER.info("Disconnected from the Airdress operator; reconnecting")
        async_dispatcher_send(self.hass, signal_connection(self.entry_id), up)

    @callback
    def features(self, features: Features) -> None:
        """The operator declared what its Home offers this installation."""
        if features.dropped:
            LOGGER.debug("The operator declared %s malformed events", features.dropped)
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
        """Drop a tracker position: this release has no tracker to move."""
        LOGGER.debug("Dropped a tracker position: no tracker is set up")

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
        if not all(t in self.operate for t in targets):
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
        if entity not in self.observe:
            return outcome.NOT_EXPOSED, None, None
        if (state := self.hass.states.get(entity)) is None:
            return outcome.NOT_FOUND, None, None
        return outcome.OK, state.state, state.last_changed.isoformat()
