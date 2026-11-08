"""Media source of the receipt photos (1.4): only for the AI Task that reads a receipt.

The files are kept outside the media folders (every Home Assistant user may browse those).
The AI Task resolves an attachment through a media source and needs the local path, so
"media-source://essensplaner/receipt/<file>" resolves to the file of a pending upload or
a saved receipt; its URL is the admin-only image view. Browsing lists nothing, the ids
are random and only admins get them (upload view, receipt websockets and services).
"""

from __future__ import annotations

from homeassistant.components.media_player import BrowseError, MediaClass, MediaType
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN, NAME
from .receipts import IMAGE_URL, MEDIA_SOURCE_RECEIPT, _loaded_manager


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """The receipts media source."""
    return ReceiptMediaSource(hass)


class ReceiptMediaSource(MediaSource):
    """Receipt photos for the AI Task (not browsable)."""

    name = f"{NAME} – Kassenzettel"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        """The file of an uploaded or saved receipt."""
        kind, _, name = (item.identifier or "").partition("/")
        manager = _loaded_manager(self.hass)
        found = (
            manager.receipts.file_info(name)
            if manager is not None and kind == MEDIA_SOURCE_RECEIPT
            else None
        )
        if found is None:
            raise Unresolvable("Kassenzettel nicht gefunden")
        path, content_type, ident = found
        if not await self.hass.async_add_executor_job(path.is_file):
            raise Unresolvable("Kassenzettel nicht gefunden")
        return PlayMedia(IMAGE_URL.format(receipt_id=ident), content_type, path=path)

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        """Nothing to browse: receipts are only shown in the Essensplaner panel (admins)."""
        if item.identifier:
            raise BrowseError("Kassenzettel sind nur im Essensplaner-Panel zu sehen.")
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaType.IMAGE,
            title=self.name,
            can_play=False,
            can_expand=True,
            children=[],
            children_media_class=MediaClass.IMAGE,
        )
