"""Test helper: serve marktguru offers through the catalog endpoints of 1.4 (discovery, one
catalog per chain variant, leaflet lists) – offers given in the search format of the 1.3
tests (_mg_offer) are converted to the short catalog format."""

from __future__ import annotations

import re
from typing import Any

from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.essensplaner.catalog import (
    LEAFLETS_PATH,
    PUBLISHERS_PATH,
    RETAILER_OFFERS_PATH,
)
from custom_components.essensplaner.offers import MARKTGURU_API

PUBLISHERS_URL = f"{MARKTGURU_API}{PUBLISHERS_PATH}"
LEAFLETS_RE = re.compile(re.escape(MARKTGURU_API) + r"/industries/[\w-]+/leaflets")


def catalog_url(unique_name: str) -> str:
    """URL of a chain variant's catalog."""
    return f"{MARKTGURU_API}{RETAILER_OFFERS_PATH.format(name=unique_name)}"


def leaflets_url(industry: str) -> str:
    """URL of an industry's leaflet list."""
    return f"{MARKTGURU_API}{LEAFLETS_PATH.format(industry=industry)}"


def publisher_id(unique_name: str) -> int:
    """A stable numeric id of a chain variant."""
    return 100000 + sum(ord(c) * (i + 1) for i, c in enumerate(unique_name)) % 90000


def short_offer(raw: dict[str, Any]) -> dict[str, Any]:
    """A search-format offer (advertisers, validityDates) in the catalog format."""
    if "retailer" in raw:
        return raw
    advertiser = (raw.get("advertisers") or [{}])[0]
    validity = (raw.get("validityDates") or [{}])[0]
    unique = advertiser.get("uniqueName") or ""
    return {
        "id": raw["id"],
        "description": raw.get("description") or "",
        "product": {"id": 1, "name": (raw.get("product") or {}).get("name")},
        "retailer": {
            "id": publisher_id(unique),
            "name": advertiser.get("name"),
            "uniqueName": unique,
        },
        "brand": raw.get("brand") or {"name": ""},
        "unit": raw.get("unit") or {"shortName": "Stk"},
        "price": raw["price"],
        "oldPrice": raw.get("oldPrice") or 0.0,
        "referencePrice": raw.get("referencePrice") or 0,
        "volume": 0,
        "quantity": 1,
        "validFrom": validity.get("from"),
        "validTo": validity.get("to"),
    }


def publishers_answer(unique_names: list[str]) -> dict[str, Any]:
    """A discovery answer listing these chain variants."""
    return {
        "totalResults": len(unique_names),
        "skippedResults": 0,
        "results": [
            {"id": f"retailers/{publisher_id(u)}", "uniqueName": u, "name": u.title()}
            for u in unique_names
        ],
    }


def mock_catalog(
    aioclient_mock: AiohttpClientMocker,
    offers: list[dict[str, Any]] | dict[str, list[dict[str, Any]]],
    leaflets: list[dict[str, Any]] | None = None,
) -> None:
    """Register discovery and catalog answers: offers (search or catalog format) at every
    postcode, or {postcode: offers}; leaflet lists answer `leaflets` (default none)."""
    by_zip = offers if isinstance(offers, dict) else {None: offers}
    for zip_code, items in by_zip.items():
        params = {"zipCode": zip_code} if zip_code else None
        variants: dict[str, list[dict[str, Any]]] = {}
        for raw in items:
            short = short_offer(raw)
            variants.setdefault(short["retailer"]["uniqueName"], []).append(short)
        aioclient_mock.get(PUBLISHERS_URL, params=params, json=publishers_answer(list(variants)))
        for unique, found in variants.items():
            aioclient_mock.get(
                catalog_url(unique),
                params=params,
                json={"totalResults": len(found), "skippedResults": 0, "results": found},
            )
    aioclient_mock.get(LEAFLETS_RE, json={"totalResults": 0, "results": leaflets or []})


def catalog_calls(aioclient_mock: AiohttpClientMocker) -> list[Any]:
    """The catalog requests made (discovery, catalogs, leaflets)."""
    return [
        c
        for c in aioclient_mock.mock_calls
        if "/publishers" in str(c[1]) or "/leaflets" in str(c[1])
    ]


def mock_offer_answers(
    aioclient_mock: AiohttpClientMocker,
    json: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> None:
    """The same offers for the live search (1.3 tests) and the catalog of 1.4."""
    aioclient_mock.get(f"{MARKTGURU_API}/offers/search", params=params, json=json)
    zip_code = (params or {}).get("zipCode")
    results = json.get("results") or []
    mock_catalog(aioclient_mock, {zip_code: results} if zip_code else results)
