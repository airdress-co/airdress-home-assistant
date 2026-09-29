"""The base entity for Airdress."""

from typing import TYPE_CHECKING, override

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import CONF_MACHINE_ID, DOMAIN, signal_connection

if TYPE_CHECKING:
    from . import AirdressConfigEntry


class AirdressEntity(Entity):
    """An entity of one linked airdress, available while its channel is up.

    A planned re-dial (the operator ends every channel after an hour) does not
    make it unavailable: see :meth:`AirdressHub.connection_changed`.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: AirdressConfigEntry) -> None:
        """Initialize the entity."""
        self._entry = entry
        machine_id = entry.data[CONF_MACHINE_ID]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, machine_id)},
            name=entry.title,
            manufacturer="Airdress",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    @override
    def available(self) -> bool:
        """Whether the channel to the operator is up, or back within the grace."""
        return self._entry.runtime_data.hub.available

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the channel's state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_connection(self._entry.entry_id),
                self._async_connection_changed,
            )
        )

    @callback
    def _async_connection_changed(self, up: bool) -> None:
        self.async_write_ha_state()
