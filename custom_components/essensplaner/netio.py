"""Reading HTTP answers (shared by the OpenStreetMap, REWE and recipe import clients)."""

from __future__ import annotations

from typing import Any

CHUNK_SIZE = 64 * 1024


class BodyTooLarge(Exception):
    """The answer is bigger than allowed."""


async def async_read_body(resp: Any, limit: int, truncate: bool = False) -> bytes:
    """The whole body of an aiohttp response, at most `limit` bytes.

    resp.content.read(n) only returns what has arrived so far (often the first network
    segment), so the body is read chunk by chunk until the end. A bigger answer raises
    BodyTooLarge, or with truncate=True the first `limit` bytes are returned.
    """
    length = getattr(resp, "content_length", None)
    if not truncate and length is not None and length > limit:
        raise BodyTooLarge(length)
    chunks: list[bytes] = []
    size = 0
    async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
        if size + len(chunk) > limit:
            if not truncate:
                raise BodyTooLarge(size + len(chunk))
            chunks.append(chunk[: limit - size])
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)
