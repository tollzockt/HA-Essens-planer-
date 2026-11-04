# 🍽️ Essensplaner für Home Assistant

Ein Essensplaner mit **Rezeptsammlung, Wochenplan und automatischer Einkaufsliste**, im Stil von Apps wie Piatto, aber komplett lokal in Home Assistant und **per Sprache bzw. Chat über „Jarvis“ (oder jeden anderen Assist- bzw. LLM-Agenten) steuerbar**.

> „Hey Jarvis, was gibt es heute zu essen?“ · „Plane Lasagne für Freitag.“ · „Schlag mir was Vegetarisches vor.“ · „Was brauche ich für Chili con Carne?“ · „Erstelle die Einkaufsliste.“

## Funktionen

| Bereich | Was es kann |
|---|---|
| 📖 **Rezepte** | Eigene Rezepte mit Zutaten, Schritten, Zeiten, Kategorien, Bild, Favoriten und Bewertung. **Import per Link** von Chefkoch, Lecker, Eat Smarter, BBC Good Food & allen Seiten mit schema.org-Rezepten. Portionen werden automatisch umgerechnet. 15 Beispielrezepte zum Start. |
| 🗓️ **Wochenplan** | Frühstück, Mittag, Snack und Abendessen pro Tag, mit Rezept oder Freitext („Pizza bestellen“). Woche **automatisch füllen**, wobei Favoriten und lange nicht Gekochtes bevorzugt werden und keine Wiederholungen vorkommen. |
| 🛒 **Einkaufsliste** | Wird aus dem Plan erzeugt: Zutaten werden **zusammengefasst** (500 g + 0,7 kg → 1,2 kg), auf Portionen skaliert, **nach Supermarkt-Abteilung sortiert**, Vorratszutaten (Salz, Pfeffer …) weggelassen. Abgehakte Einträge bleiben beim Neuerstellen abgehakt. Optional zusätzlich in eine andere To-do-Liste kopieren (z. B. Bring!). |
| 🗣️ **Jarvis / Assist / LLM** | 12 Intents, die automatisch als **Tools für LLM-Agenten** (inkl. MCP-Server) erscheinen, plus deutsche Sätze für den eingebauten Sprachagenten. |
| 📱 **App in der Seitenleiste** | Panel „Essensplaner“ mit Wochenplan, Rezepten und Einkaufsliste, passend zu Hell/Dunkel-Theme und Handy. |
| 🏠 **Entitäten** | Sensoren (heute, morgen, nächste Mahlzeit, Wochenplan, Rezepte), Kalender und To-do-Liste, also nutzbar in Dashboards und Automationen. |

## Installation

### HACS (empfohlen)
1. HACS → ⋮ → **Benutzerdefinierte Repositories** → `https://github.com/tollzockt/HA-Essens-planer-`, Typ **Integration**.
2. „Essensplaner“ installieren und Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Essensplaner.**

### Manuell
Ordner `custom_components/essensplaner` nach `/config/custom_components/essensplaner` kopieren, neu starten, Integration hinzufügen.

## 🤖 Jarvis & andere Sprachassistenten

Der Essensplaner registriert **Intents**. Home Assistant stellt jeden registrierten Intent über die *Assist*-LLM-API automatisch als **Tool** bereit:

* **LLM-Agenten** (OpenAI, Anthropic, Google, Ollama, Hermes …) mit aktivierter Option „Home Assistant steuern → Assist“ sehen die Tools sofort.
* Der **Model-Context-Protocol-Server** (Integration „MCP Server“ mit LLM-API *Assist*) gibt die Tools an externe Agenten weiter, z. B. an **Jarvis/Hermes-Agent**, Claude Desktop & Co.
* Für den **eingebauten Agenten** ohne LLM gibt es fertige deutsche Sätze (siehe unten).

### Empfohlene Einrichtung für Jarvis
1. Integration installieren (Intents sind standardmäßig aktiv, Option „Sprachassistent / LLM-Tools“).
2. Unter **Einstellungen → Sprachassistenten → Entitäten freigeben** diese Entitäten für Assist freigeben, damit Jarvis den Plan auch „sieht“:
   `sensor.essensplaner_today`, `sensor.essensplaner_tomorrow`, `sensor.essensplaner_next_meal`, `sensor.essensplaner_week_plan`, `todo.essensplaner_shopping_list`, `calendar.essensplaner_meal_plan`.
3. Fertig. Wenn Jarvis über den MCP-Server auf Home Assistant zugreift, tauchen die Tools `essensplaner_*` nach einem Neuladen der Tool-Liste auf.

Optional im System-Prompt des Agenten: *„Für Fragen zu Essen, Rezepten, Wochenplan und Einkaufsliste nutze die Tools `essensplaner_*`.“*

### Tools / Intents

| Tool | Beispiel |
|---|---|
| `essensplaner_get_meals` | „Was gibt es heute/morgen Abend/am Freitag zu essen?“ |
| `essensplaner_get_week_plan` | „Wie sieht der Essensplan diese Woche aus?“ |
| `essensplaner_plan_meal` | „Plane Lasagne für Freitag zum Abendessen.“ |
| `essensplaner_remove_meal` | „Lösche das Essen von morgen.“ |
| `essensplaner_suggest_recipes` | „Was soll ich heute kochen?“ · „Schlag mir was Schnelles vor.“ |
| `essensplaner_get_recipe` | „Was brauche ich für Chili con Carne für 6 Personen?“ · „Lies mir das Rezept vor.“ |
| `essensplaner_search_recipes` | „Welche Rezepte habe ich mit Hähnchen?“ |
| `essensplaner_create_shopping_list` | „Erstelle die Einkaufsliste für die Woche.“ |
| `essensplaner_auto_plan` | „Plane mir die nächste Woche (vegetarisch).“ |
| `essensplaner_add_recipe` | „Speichere ein Rezept Rührei mit 3 Eiern, Butter und Salz.“ |
| `essensplaner_import_recipe` | „Importiere das Rezept von https://www.chefkoch.de/…“ |
| `essensplaner_mark_cooked` | „Wir haben heute Linsensuppe gekocht.“ |

Datumsangaben werden in natürlicher Sprache verstanden: *heute, morgen, übermorgen, heute Abend, morgen früh, Freitag, nächsten Montag, nächste Woche, in 3 Tagen, 24.12., 2026-11-20*.

### Eingebauter Sprachagent (ohne LLM)
Datei [`custom_sentences/de/essensplaner.yaml`](custom_sentences/de/essensplaner.yaml) nach `/config/custom_sentences/de/` kopieren und Home Assistant neu starten.

## Entitäten

| Entität | Inhalt |
|---|---|
| `sensor.essensplaner_today` / `_tomorrow` | Geplante Gerichte; Attribute je Mahlzeit (`fruehstueck`, `mittagessen`, `abendessen` …) |
| `sensor.essensplaner_next_meal` | Nächste Mahlzeit mit Zutaten (auf Portionen skaliert) und Zubereitung, Bild als Entity-Picture |
| `sensor.essensplaner_week_plan` | Anzahl geplanter Mahlzeiten (7 Tage), Plan als Attribut `days` / `summary` |
| `sensor.essensplaner_recipes` | Anzahl Rezepte; Namen, Favoriten, Kategorien |
| `calendar.essensplaner_meal_plan` | Alle Mahlzeiten als Termine (Termine anlegen/löschen plant bzw. entfernt Mahlzeiten) |
| `todo.essensplaner_shopping_list` | Die Einkaufsliste |

## Aktionen (Services)

Alle Aktionen liefern optional eine Antwort (`response_variable`) und verstehen natürliche Datumsangaben.

| Aktion | Zweck |
|---|---|
| `essensplaner.add_recipe` / `update_recipe` / `delete_recipe` | Rezepte verwalten |
| `essensplaner.import_recipe` | Rezept von URL importieren |
| `essensplaner.get_recipes` / `get_recipe` | Suchen / Rezept (skaliert) abrufen |
| `essensplaner.plan_meal` / `remove_meal` / `get_plan` | Wochenplan |
| `essensplaner.suggest_recipes` / `auto_plan` | Vorschläge / automatisch planen |
| `essensplaner.generate_shopping_list` | Einkaufsliste erzeugen |
| `essensplaner.mark_cooked` | Als gekocht merken (bessere Vorschläge) |

```yaml
action: essensplaner.plan_meal
data:
  date: morgen
  meal: abendessen
  recipe: Lasagne
  servings: 4
```

```yaml
action: essensplaner.get_recipe
data:
  recipe: Chili con Carne
  servings: 6
response_variable: rezept
```

Weitere Beispiele: [`examples/automations.yaml`](examples/automations.yaml) (Erinnerung ans Abendessen, Einkaufsliste am Samstag, Woche automatisch füllen) und [`examples/dashboard.yaml`](examples/dashboard.yaml).

## Optionen
*Einstellungen → Geräte & Dienste → Essensplaner → Konfigurieren*: Standard-Portionen, verwendete Mahlzeiten und Uhrzeiten, Standard-Mahlzeit, Vorratsschrank, Einkaufsliste zusätzlich in eine andere To-do-Liste kopieren, Intents an/aus, Panel an/aus.

## Daten
Alles wird lokal in `/config/.storage/essensplaner.<entry_id>` gespeichert und ist Teil der normalen Home-Assistant-Backups. Das Event `essensplaner_updated` wird bei jeder Änderung ausgelöst.

## Entwicklung

```bash
pip install -r requirements_test.txt
pip install hassil home-assistant-intents  # Versionen passend zu components/conversation/manifest.json
pytest
```

Lizenz: MIT
