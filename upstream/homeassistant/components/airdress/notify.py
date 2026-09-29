"""Messages for the owner, delivered to the home's conversation in Airdress.

Each message is stored in the owner's "Home" conversation on the operator and
reaches the owner's phones like any other message, muted or not as the owner
chose there. The operator bounds how many it takes (a few a minute, a couple
of hundred a day by default); past that a message is refused, never queued.
"""

import asyncio
from typing import override

from airdress_home import ChannelClosed, models as outcome

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AirdressConfigEntry
from .const import CONF_MACHINE_ID, DOMAIN
from .entity import AirdressEntity

PARALLEL_UPDATES = 0

NOTIFY_TIMEOUT = 10.0
"""Seconds to wait for the operator to answer a message."""

_REFUSALS = {
    outcome.RATE_LIMITED: "notify_rate_limited",
    outcome.DISABLED: "notify_disabled",
    outcome.TOO_LONG: "notify_too_long",
    outcome.REJECTED: "notify_rejected",
    outcome.FAILED: "notify_failed",
}


class AirdressNotify(AirdressEntity, NotifyEntity):
    """The owner's Home conversation."""

    _attr_supported_features = NotifyEntityFeature.TITLE
    _attr_translation_key = "conversation"

    def __init__(self, entry: AirdressConfigEntry) -> None:
        """Initialize the notify entity."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.data[CONF_MACHINE_ID]}-conversation"

    @override
    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message to the owner's Home conversation."""
        session = self._entry.runtime_data.session
        try:
            async with asyncio.timeout(NOTIFY_TIMEOUT):
                result = await session.notify(message, title)
        except (ChannelClosed, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="notify_not_connected"
            ) from err
        if result != outcome.DELIVERED:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=_REFUSALS.get(result, "notify_failed"),
            )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AirdressConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Home conversation."""
    async_add_entities([AirdressNotify(entry)])
