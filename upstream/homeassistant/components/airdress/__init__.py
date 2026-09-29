"""The Airdress integration: let an airdress's functions reach this home.

Home Assistant is enrolled with the owner's operator as a machine and holds a
channel open to it; the operator cannot dial in. Functions on the operator can
then run actions on — and read — exactly the entities shared here, and emit
events to it. The protocol is ``airdress-home``'s; this integration adapts it.
"""

from dataclasses import dataclass
from typing import Any

import aiohttp
from airdress_home import (
    ChannelClosed,
    Enrollment,
    HomeDisabled,
    HomeNotLinked,
    HomeSession,
    MachineClient,
    MachineKey,
    NotAuthorized,
)
from airdress_home.channel import Hint, for_client

from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    CONF_KID,
    CONF_MACHINE_ID,
    CONF_MACHINE_KEY,
    CONF_OPERATOR,
    CONF_OPERATOR_KEY,
    CONF_RECORD_LOCATION,
    CONF_USER_ID,
    DOMAIN,
    LOGGER,
    REAUTH_REFUSAL,
    SYSTEM_USER_NAME,
)
from .hub import AirdressHub

PLATFORMS: list[Platform] = [Platform.DEVICE_TRACKER, Platform.EVENT, Platform.NOTIFY]

HINTS_VERSION = 1


class TransportHints:
    """Which transport worked on which network, in Home Assistant's storage.

    Holds no address: a network is a digest the library computes.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the store."""
        self._store: Store[dict[str, Any]] = Store(
            hass, HINTS_VERSION, f"{DOMAIN}.{entry_id}.transport"
        )

    async def load(self) -> dict[str, Hint]:
        """The stored hints."""
        raw = await self._store.async_load() or {}
        return {
            key: hint
            for key, value in raw.items()
            if (hint := Hint.from_json(value)) is not None
        }

    async def save(self, hints: dict[str, Hint]) -> None:
        """Replace the stored hints."""
        await self._store.async_save({k: v.to_json() for k, v in hints.items()})

    async def async_remove(self) -> None:
        """Forget every hint."""
        await self._store.async_remove()


@dataclass
class AirdressData:
    """What a loaded entry holds."""

    session: HomeSession
    hub: AirdressHub
    record_location: bool
    """The recording option the tracker was set up with."""


type AirdressConfigEntry = ConfigEntry[AirdressData]


async def _async_system_user(hass: HomeAssistant, entry: AirdressConfigEntry) -> str:
    """The non-admin system user Airdress's actions run as, created once."""
    if (user_id := entry.data.get(CONF_USER_ID)) is not None and (
        await hass.auth.async_get_user(user_id)
    ) is not None:
        return str(user_id)
    user = await hass.auth.async_create_system_user(
        SYSTEM_USER_NAME, group_ids=[GROUP_ID_USER], local_only=True
    )
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_USER_ID: user.id}
    )
    return user.id


async def async_setup_entry(hass: HomeAssistant, entry: AirdressConfigEntry) -> bool:
    """Set up Airdress from a config entry."""
    enrollment = Enrollment(
        operator=entry.data[CONF_OPERATOR],
        machine_id=entry.data[CONF_MACHINE_ID],
        kid=entry.data[CONF_KID],
        operator_key=entry.data[CONF_OPERATOR_KEY],
    )
    pinned = enrollment.pinned_key
    if pinned is None or len(pinned) != 32:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="no_pinned_key"
        )
    client = MachineClient(
        async_get_clientsession(hass),
        MachineKey.from_b64(entry.data[CONF_MACHINE_KEY]),
        enrollment,
    )
    user_id = await _async_system_user(hass, entry)
    hub = AirdressHub(hass, entry.entry_id, user_id, dict(entry.options))
    session = HomeSession(
        for_client(
            client,
            hints=TransportHints(hass, entry.entry_id),
            on_event=_log_transport_event,
        ),
        hub,
        pinned,
        on_connection=hub.connection_changed,
        on_revoked=hub.revoked,
        on_lapsed=hub.lapsed,
    )
    try:
        await session.open()
    except HomeDisabled as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="home_disabled"
        ) from err
    except HomeNotLinked as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="not_linked"
        ) from err
    except NotAuthorized as err:
        if err.kind is not None:
            # Say which, so a revoked machine is not first offered a renewal
            # the operator will refuse. The failure below then finds this
            # reauth already started.
            entry.async_start_reauth(
                hass, data={**entry.data, REAUTH_REFUSAL: err.kind}
            )
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="not_authorized"
        ) from err
    except (ChannelClosed, aiohttp.ClientError, TimeoutError) as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="cannot_connect"
        ) from err

    hub.attach(session)
    entry.runtime_data = AirdressData(
        session=session,
        hub=hub,
        record_location=bool(entry.options.get(CONF_RECORD_LOCATION, False)),
    )
    entry.async_on_unload(hub.async_stop_observing)
    entry.async_on_unload(hub.async_stop)
    entry.async_on_unload(session.stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(hass, session.run(), "airdress channel")
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: AirdressConfigEntry
) -> None:
    """Tell the operator what is shared now; a new recording option reloads."""
    if (
        bool(entry.options.get(CONF_RECORD_LOCATION, False))
        != entry.runtime_data.record_location
    ):
        # The tracker's recorded attributes are fixed per entity class.
        hass.config_entries.async_schedule_reload(entry.entry_id)
        return
    entry.runtime_data.hub.update_options(dict(entry.options))
    await entry.runtime_data.session.share()


def _log_transport_event(event: dict[str, Any]) -> None:
    """Say which transport the channel rides, and why it changed."""
    LOGGER.info(
        "Airdress channel: %s %s",
        event.get("kind", ""),
        {k: v for k, v in event.items() if k not in ("kind", "t")},
    )


async def async_unload_entry(hass: HomeAssistant, entry: AirdressConfigEntry) -> bool:
    """Unload a config entry; the channel closes."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: AirdressConfigEntry) -> None:
    """Remove the system user the entry's actions ran as, and the hints."""
    await TransportHints(hass, entry.entry_id).async_remove()
    if (user_id := entry.data.get(CONF_USER_ID)) is not None and (
        user := await hass.auth.async_get_user(user_id)
    ) is not None:
        await hass.auth.async_remove_user(user)
