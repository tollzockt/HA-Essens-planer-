"""Jarvis answers: item lookup, "immer"-stores, split off, price comparison (review fixes)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.essensplaner.const import CONF_SPLIT_MODE

from .test_stores import _setup


async def _intent(hass: HomeAssistant, intent_type: str, **slots) -> intent.IntentResponse:
    return await intent.async_handle(
        hass,
        "test",
        intent_type,
        {key: {"value": value} for key, value in slots.items()},
        language="de",
    )


async def _speech(hass: HomeAssistant, intent_type: str, **slots) -> str:
    return (await _intent(hass, intent_type, **slots)).speech["plain"]["speech"]


def _branches(manager) -> tuple[dict, dict]:
    aldi = manager.save_branch({"store": "Aldi Süd", "postcode": "80331"})
    lidl = manager.save_branch({"store": "Lidl", "postcode": "85748", "label": "Lidl Arbeit"})
    return aldi, lidl


async def test_item_lookup_whole_words(hass: HomeAssistant, setup_integration) -> None:
    """ "Milch" is not "Kokosmilch", "Reis" not "Eier"; "immer" works without the item."""
    manager = setup_integration.runtime_data
    _branches(manager)
    coconut = manager.shopping_add("400 ml Kokosmilch")
    eggs = manager.shopping_add("10 Eier")
    hack = manager.shopping_add("500 g Hähnchenbrustfilet")

    speech = await _speech(
        hass, "essensplaner_set_shopping_store", item="Milch", store="Lidl", always=True
    )
    assert speech == "Okay, Milch kaufst du ab jetzt immer bei Lidl Arbeit."
    assert manager.store_preferences == {"milch": "lidl"}
    assert "store_override" not in coconut

    await _speech(
        hass, "essensplaner_set_shopping_store", item="den Reis", store="Lidl", always=True
    )
    assert manager.store_preferences == {"milch": "lidl", "reis": "lidl"}
    assert "store_override" not in eggs
    # a new milk item goes to Lidl right away
    milk = manager.shopping_add("1 l Milch")
    assert (milk["retailer"], milk["store_reason"]) == ("lidl", "preferred")

    response = await _intent(hass, "essensplaner_set_shopping_store", item="Kaffee", store="Lidl")
    assert response.response_type == intent.IntentResponseType.ERROR
    assert manager.find_shopping_item("Hähnchen") is hack  # compound of the same product
    assert await _speech(
        hass, "essensplaner_set_shopping_store", item="Kaffee", store="automatisch", always=True
    ) == ("Okay, für Kaffee merke ich mir keinen Laden mehr.")


async def test_add_item_at_own_branch_label(hass: HomeAssistant, setup_integration) -> None:
    """ "Setz Butter bei Lidl Arbeit auf die Einkaufsliste" (item wildcard with the label)."""
    manager = setup_integration.runtime_data
    _aldi, lidl = _branches(manager)
    await _speech(hass, "essensplaner_add_shopping_item", item="Butter bei Lidl Arbeit")
    item = manager.shopping[-1]
    assert (item["summary"], item["branch_id"], item["store_reason"]) == (
        "Butter",
        lidl["id"],
        "manual",
    )
    await _speech(hass, "essensplaner_add_shopping_item", item="Brötchen bei Bedarf")
    assert manager.shopping[-1]["summary"] == "Brötchen bei Bedarf"


async def test_split_off_reasons(
    hass: HomeAssistant, config_entry: MockConfigEntry, freezer
) -> None:
    """With a main store but the split switched off, the answer says so (no symbols)."""
    await _setup(hass, config_entry, freezer, **{CONF_SPLIT_MODE: "off"})
    manager = config_entry.runtime_data
    _branches(manager)
    manager.shopping_add("Butter")
    speech = await _speech(hass, "essensplaner_get_shopping_list", store="Aldi")
    assert speech.startswith(
        "Die Aufteilung nach Läden ist ausgeschaltet (im Essensplaner-Panel unter "
        "Einstellungen, Läden und Einkauf). "
    )
    response = await _intent(hass, "essensplaner_set_shopping_store", item="Butter", store="Lidl")
    assert response.response_type == intent.IntentResponseType.ERROR
    assert response.speech["plain"]["speech"] == (
        "Die Aufteilung nach Läden ist ausgeschaltet (im Essensplaner-Panel unter "
        "Einstellungen, Läden und Einkauf)."
    )


async def test_errors_are_speakable(hass: HomeAssistant, setup_integration) -> None:
    """Error answers contain no arrows or ampersands."""
    response = await _intent(hass, "essensplaner_set_shopping_store", item="Butter", store="REWE")
    text = response.speech["plain"]["speech"]
    assert response.response_type == intent.IntentResponseType.ERROR
    assert "Hauptladen" in text
    assert "→" not in text and "&" not in text
    from custom_components.essensplaner.manager import ERROR_MESSAGES_DE

    assert "→" not in ERROR_MESSAGES_DE["store_split_off"]


async def test_compare_speech_per_kilo(hass: HomeAssistant, setup_integration) -> None:
    """Different pack sizes: the price per kilo is said; several packs as "2 mal"."""
    manager = setup_integration.runtime_data
    _branches(manager)
    manager.set_store_price("Lidl", "Butter", 3.49, 500, "g")
    manager.set_store_price("Aldi Süd", "Butter", 1.99, 250, "g")
    assert await _speech(hass, "essensplaner_compare_prices", item="Butter") == (
        "Am günstigsten gibt es Butter bei Lidl Arbeit: 3,49 € (500 g, 6,98 € pro Kilo). "
        "Bei Aldi Süd 1,99 € (250 g, 7,96 € pro Kilo)."
    )
    assert await _speech(hass, "essensplaner_compare_prices", item="1 kg Butter") == (
        "Am günstigsten gibt es Butter bei Lidl Arbeit: 6,98 € (2 mal 500 g). "
        "Bei Aldi Süd 7,96 € (4 mal 250 g)."
    )
