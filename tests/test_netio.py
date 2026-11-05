"""HTTP answers that arrive in several network segments are read completely."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import aiohttp
from aiohttp import web
import pytest

from custom_components.essensplaner import branches, recipe_import, rewe
from custom_components.essensplaner.netio import BodyTooLarge, async_read_body

ELEMENTS = [
    {
        "type": "node",
        "id": i,
        "lat": 48.1 + i / 1e4,
        "lon": 11.5,
        "tags": {
            "shop": "supermarket",
            "name": "Lidl",
            "addr:street": f"Straße {i}",
            "addr:postcode": "80331",
            "addr:city": "München",
        },
    }
    for i in range(300)
]
OVERPASS_BODY = json.dumps({"version": 0.6, "elements": ELEMENTS}).encode()
PRODUCTS_BODY = json.dumps(
    {
        "_embedded": {
            "products": [
                {
                    "id": str(i),
                    "productName": f"ja! Butter {i}",
                    "_embedded": {
                        "articles": [
                            {
                                "_embedded": {
                                    "listing": {
                                        "pricing": {
                                            "currentRetailPrice": 199,
                                            "grammage": "250g (1 kg = 7,96 €)",
                                        }
                                    }
                                }
                            }
                        ]
                    },
                }
                for i in range(20)
            ]
        },
        "padding": "x" * 60000,
    }
).encode()
MARKETS_BODY = json.dumps(
    [
        {
            "wwIdent": str(1000 + i),
            "companyName": "REWE Markt GmbH",
            "contactStreet": f"Hauptstraße {i}",
            "contactZipCode": "80331",
            "contactCity": "München",
        }
        for i in range(25)
    ]
    + [{"padding": "x" * 40000}]
).encode()
RECIPE_PAGE = (
    "<html><head>"
    + "<!--"
    + "x" * 50000
    + "-->"
    + '<script type="application/ld+json">'
    + json.dumps(
        {
            "@type": "Recipe",
            "name": "Langsame Suppe",
            "recipeIngredient": ["1 Zwiebel", "500 g Kartoffeln"],
            "recipeInstructions": "Alles kochen.",
        }
    )
    + "</script></head><body></body></html>"
).encode()


async def _stream(request: web.Request, body: bytes, content_type: str) -> web.StreamResponse:
    """Send the body in small pieces with pauses (like a slow network)."""
    resp = web.StreamResponse(headers={"Content-Type": content_type})
    await resp.prepare(request)  # chunked transfer encoding, no length
    for start in range(0, len(body), 8192):
        await resp.write(body[start : start + 8192])
        await asyncio.sleep(0.01)
    await resp.write_eof()
    return resp


def _handler(body: bytes, content_type: str):
    async def handle(request: web.Request) -> web.StreamResponse:
        return await _stream(request, body, content_type)

    return handle


@pytest.fixture
async def server(socket_enabled):
    """A local web server (127.0.0.1) that streams the answers."""
    app = web.Application()
    app.router.add_post("/api/interpreter", _handler(OVERPASS_BODY, "application/json"))
    app.router.add_get("/api/products", _handler(PRODUCTS_BODY, "application/json"))
    app.router.add_get("/api/markets", _handler(MARKETS_BODY, "application/json"))
    app.router.add_get("/rezept", _handler(RECIPE_PAGE, "text/html; charset=utf-8"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    async with aiohttp.ClientSession() as session:
        yield f"http://127.0.0.1:{port}", session
    await runner.cleanup()


async def test_overpass_answer_in_pieces(server) -> None:
    """The OpenStreetMap search reads answers bigger than one network segment."""
    base, session = server
    with (
        patch.object(branches, "OVERPASS_URL", f"{base}/api/interpreter"),
        patch.object(branches, "async_get_clientsession", lambda hass: session),
    ):
        data = await branches.async_overpass_query(None, "[out:json];")
    assert len(data["elements"]) == 300


async def test_rewe_answers_in_pieces(server) -> None:
    """REWE product and market searches are read completely (no 7-day pause)."""
    base, session = server
    with patch.object(rewe, "async_get_clientsession", lambda hass: session):
        client = rewe.ReweClient(None)
        data = await client.async_get_json(f"{base}/api/products", {})
        assert len(data["_embedded"]["products"]) == 20
        with patch.object(rewe, "MARKETS_URL", f"{base}/api/markets"):
            markets = await client.async_search_markets("80331")
    assert len(markets) == 25


async def test_recipe_page_in_pieces(server) -> None:
    """A recipe page whose JSON-LD comes after the first segment is still found."""
    base, session = server
    with patch.object(recipe_import, "async_get_clientsession", lambda hass: session):
        recipe = await recipe_import.async_fetch_recipe(None, f"{base}/rezept")
    assert recipe["name"] == "Langsame Suppe"


class _Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, size: int):
        for chunk in self._chunks:
            yield chunk


class _Response:
    def __init__(self, chunks: list[bytes], length: int | None = None) -> None:
        self.content = _Content(chunks)
        self.content_length = length


async def test_read_body_limit() -> None:
    """Too big answers are refused (or cut with truncate)."""
    assert await async_read_body(_Response([b"ab", b"cd"]), 4) == b"abcd"
    with pytest.raises(BodyTooLarge):
        await async_read_body(_Response([b"ab", b"cd", b"e"]), 4)
    with pytest.raises(BodyTooLarge):
        await async_read_body(_Response([], length=10), 4)
    assert await async_read_body(_Response([b"ab", b"cd", b"e"]), 3, truncate=True) == b"abc"
