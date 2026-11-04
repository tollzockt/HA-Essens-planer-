"""Shopping list as a todo entity."""

from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import EssensplanerEntity
from .manager import EssensplanerManager


def _status(status: TodoItemStatus | str | None) -> str | None:
    if status is None:
        return None
    return status.value if isinstance(status, TodoItemStatus) else str(status)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the shopping list."""
    async_add_entities([ShoppingListEntity(entry.runtime_data)])


class ShoppingListEntity(EssensplanerEntity, TodoListEntity):
    """The Essensplaner shopping list."""

    _attr_icon = "mdi:cart"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, manager: EssensplanerManager) -> None:
        """Initialize the list."""
        super().__init__(manager, "shopping_list")

    @property
    def todo_items(self) -> list[TodoItem]:
        """Items of the list."""
        return [
            TodoItem(
                uid=item["uid"],
                summary=item["summary"],
                status=TodoItemStatus(item.get("status", "needs_action")),
                description=item.get("description") or None,
            )
            for item in self.manager.shopping
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item."""
        self.manager.shopping_add(
            item.summary or "",
            description=item.description,
            status=_status(item.status) or TodoItemStatus.NEEDS_ACTION.value,
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update an item."""
        assert item.uid
        self.manager.shopping_update(
            item.uid,
            summary=item.summary,
            status=_status(item.status),
            description=item.description,
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items."""
        self.manager.shopping_delete(uids)

    async def async_move_todo_item(self, uid: str, previous_uid: str | None = None) -> None:
        """Re-order an item."""
        self.manager.shopping_move(uid, previous_uid)
