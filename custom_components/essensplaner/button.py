"""Buttons for one-tap actions (dashboards, wall tablets)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import EssensplanerEntity
from .manager import EssensplanerManager
from .services import async_sync_shopping


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons."""
    manager: EssensplanerManager = entry.runtime_data
    async_add_entities([ShoppingListButton(manager), AutoPlanButton(manager)])


class ShoppingListButton(EssensplanerEntity, ButtonEntity):
    """Create the shopping list for the next 7 days."""

    _attr_icon = "mdi:cart-plus"

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the button."""
        super().__init__(manager, "create_shopping_list")

    async def async_press(self) -> None:
        """Generate the list."""
        result = self.manager.generate_shopping_list(self.manager.today(), 7)
        if target := self.manager.sync_entity:
            await async_sync_shopping(self.hass, target, result["items"])


class AutoPlanButton(EssensplanerEntity, ButtonEntity):
    """Fill the empty slots of the next 7 days."""

    _attr_icon = "mdi:auto-fix"

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the button."""
        super().__init__(manager, "auto_plan_week")

    async def async_press(self) -> None:
        """Plan the week."""
        self.manager.auto_plan(self.manager.today(), 7)
