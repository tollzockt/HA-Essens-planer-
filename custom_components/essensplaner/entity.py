"""Base entity for the Essensplaner integration."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, NAME
from .manager import EssensplanerManager


class EssensplanerEntity(Entity):
    """Entity that updates whenever the manager data changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: EssensplanerManager, key: str) -> None:
        """Initialize the entity."""
        self.manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name=NAME,
            manufacturer=NAME,
            model="Meal planner",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to data updates."""
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.async_add_listener(self._handle_manager_update))

    @callback
    def _handle_manager_update(self) -> None:
        self.async_write_ha_state()
