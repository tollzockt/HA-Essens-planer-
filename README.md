# 🍽️ Essensplaner für Home Assistant

Ein Essensplaner mit **107 Rezepten, Wochenplan, Kochmodus, Einkaufsliste mit Preisen, Wochenbudget und Supermarkt-Angeboten**, im Stil von Apps wie Piatto, aber komplett lokal in Home Assistant und **per Sprache bzw. Chat über „Jarvis“ (oder jeden anderen Assist- bzw. LLM-Agenten) steuerbar**.

> „Hey Jarvis, was gibt es heute zu essen?“ · „Plane mir die Woche günstig.“ · „Welche Angebote gibt es diese Woche?“ · „Wie viel Budget habe ich noch?“ · „Was kann ich mit Hähnchen und Reis kochen?“ · „Erstelle die Einkaufsliste.“

![Wochenplan](docs/images/wochenplan.png)

## Funktionen

| Bereich | Was es kann |
|---|---|
| 📖 **Rezepte** | Eigene Rezepte mit Zutaten, Schritten, Zeiten, Kategorien, Bild, Favoriten und ⭐ Bewertung. **Import per Link** von Chefkoch, Lecker, Eat Smarter, BBC Good Food & allen Seiten mit schema.org-Rezepten. Portionen werden automatisch umgerechnet. Sortieren nach „günstigste“, „zuletzt gekocht“, „schnellste“, „beste Bewertung“ … **107 Rezepte** zum Start (Klassiker, vegetarisch/vegan, Suppen, Pasta, international, Fisch, Frühstück, Kuchen). **Export/Import** als JSON. |
| 🗓️ **Wochenplan** | Frühstück, Mittag, Snack und Abendessen, mit Rezept oder Freitext („Pizza bestellen“), Kosten je Mahlzeit. **Drag & Drop** (belegte Plätze werden getauscht), **„Letzte Woche übernehmen“**, Woche **automatisch planen** – *ausgewogen*, *günstig* (Budget), *Angebote nutzen* oder *Abwechslung*: Favoriten und lange nicht Gekochtes werden bevorzugt, ähnliche Gerichte an aufeinanderfolgenden Tagen und „Nie vorschlagen“-Zutaten vermieden. |
| 💶 **Preise & Budget** | Richtpreise für über 200 Zutaten, eigene Preise, Kosten pro Rezept/Portion/Woche, **Wochenbudget** mit Restbudget. |
| 🏷️ **Angebote** | **Aktuelle und kommende Angebote** von Aldi Süd/Nord, Lidl, REWE, EDEKA, Penny, Netto, Kaufland … (optional über marktguru.de nach Postleitzahl, täglich automatisch) oder selbst eingetragen. Angebote fließen in Rezeptkosten, Planung und Einkaufsliste ein; Normalpreise werden aus den Prospekten gelernt. Live-Preissuche im Panel. |
| 👩‍🍳 **Kochmodus** | Vollbild Schritt für Schritt mit großer Schrift, Zutaten zum Abhaken, **Timer aus dem Rezepttext** („15 Minuten köcheln“ → ⏱ mit Signalton). Der Bildschirm bleibt an. Blättern per Wischen oder Pfeiltasten. |
| 🧊 **Was kann ich kochen?** | Rezepte zu den Zutaten, die du da hast, mit Angabe, was noch fehlt. |
| 🛒 **Einkaufsliste** | Wird aus dem Plan erzeugt: Zutaten werden **zusammengefasst** (500 g + 0,7 kg → 1,2 kg), auf Portionen skaliert, **nach Supermarkt-Abteilung sortiert**, Vorratszutaten (Salz, Pfeffer …) weggelassen. Abgehakte Einträge bleiben beim Neuerstellen abgehakt. **Preis je Artikel und Gesamtsumme**, Angebots-Hinweise („🏷️ Lidl 4,99 €“), **Liste leeren**, Fortschrittsbalken, Teilen (Teilen-Menü des Geräts) bzw. Kopieren als Text, optional Kopie in eine andere To-do-Liste (z. B. Bring!). |
| 🗣️ **Jarvis / Assist / LLM** | 19 Intents, die automatisch als **Tools für LLM-Agenten** (inkl. MCP-Server) erscheinen, plus deutsche Sätze für den eingebauten Sprachagenten. |
| 📱 **App in der Seitenleiste** | Panel „Essensplaner“ mit Heute-Karte, Wochenplan, Rezepten und Einkaufsliste, passend zu Hell/Dunkel-Theme und Handy. |
| 🖼️ **Dashboard-Karte** | `custom:essensplaner-card` (Heute · Nächste Mahlzeit · Woche), ideal fürs Küchen- oder Esszimmer-Tablet. |
| 🏠 **Entitäten & Blueprints** | Sensoren, Kalender, To-do-Liste und Buttons, dazu fertige Blueprints für Essens-Erinnerung und Wochen-Routine. |

| Angebote & Budget | Rezept mit Kosten & Angebot |
|---|---|
| ![Angebote](docs/images/angebote.png) | ![Rezeptkosten](docs/images/rezept-kosten.png) |

| Kochmodus | Was kann ich kochen? |
|---|---|
| ![Kochmodus](docs/images/kochmodus.png) | ![Was kann ich kochen](docs/images/was-kann-ich-kochen.png) |

| Rezepte | Handy | Einkaufsliste |
|---|---|---|
| ![Rezepte](docs/images/rezepte.png) | ![Handy](docs/images/handy-wochenplan.png) | ![Einkaufsliste](docs/images/handy-einkaufsliste.png) |

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
| `essensplaner_move_meal` | „Verschiebe die Lasagne auf Samstag.“ · „Tausche Montag und Dienstag.“ |
| `essensplaner_remove_meal` | „Lösche das Essen von morgen.“ |
| `essensplaner_suggest_recipes` | „Was soll ich heute kochen?“ · „Schlag mir was Schnelles vor.“ |
| `essensplaner_cook_with` | „Was kann ich mit Hähnchen, Reis und Paprika kochen?“ |
| `essensplaner_get_recipe` | „Was brauche ich für Chili con Carne für 6 Personen?“ · „Lies mir das Rezept vor.“ |
| `essensplaner_search_recipes` | „Welche Rezepte habe ich mit Hähnchen?“ |
| `essensplaner_create_shopping_list` | „Erstelle die Einkaufsliste für die Woche.“ |
| `essensplaner_get_shopping_list` | „Was steht auf der Einkaufsliste?“ · „Was muss ich einkaufen?“ |
| `essensplaner_clear_shopping_list` | „Lösche die Einkaufsliste.“ · „Entferne die erledigten Einträge.“ |
| `essensplaner_auto_plan` | „Plane mir die nächste Woche (vegetarisch).“ · „Plane die Woche günstig / mit den Angeboten.“ |
| `essensplaner_get_offers` | „Welche Angebote gibt es diese Woche?“ · „Wo ist Butter im Angebot?“ |
| `essensplaner_add_offer` | „Bei Lidl gibt es Hähnchenbrust für 4,99 Euro das Kilo bis Samstag.“ |
| `essensplaner_get_costs` | „Was kostet der Essensplan diese Woche?“ · „Wie viel Budget habe ich noch?“ |
| `essensplaner_add_recipe` | „Speichere ein Rezept Rührei mit 3 Eiern, Butter und Salz.“ |
| `essensplaner_import_recipe` | „Importiere das Rezept von https://www.chefkoch.de/…“ |
| `essensplaner_mark_cooked` | „Wir haben heute Linsensuppe gekocht.“ |

Datumsangaben werden in natürlicher Sprache verstanden: *heute, morgen, übermorgen, heute Abend, morgen früh, Freitag, nächsten Montag, nächste Woche, in 3 Tagen, 24.12., 2026-11-20*.

### Eingebauter Sprachagent (ohne LLM)
Datei [`custom_sentences/de/essensplaner.yaml`](custom_sentences/de/essensplaner.yaml) nach `/config/custom_sentences/de/` kopieren und Home Assistant neu starten.

## 🖼️ Dashboard-Karte

Die Karte wird von der Integration automatisch geladen. Im Dashboard: **Karte hinzufügen → „Essensplaner“** (mit visuellem Editor).

![Dashboard-Karte](docs/images/dashboard-karte.png)

```yaml
type: custom:essensplaner-card
mode: next              # today | next | week
show_ingredients: true  # nur bei "next"
# title: Heute bei uns  # optional, "" blendet die Kopfzeile aus
# days: 7               # nur bei "week"
# start: monday         # "today" (Standard) oder "monday"
```

Ein ganzes Beispiel-Dashboard steht in [`examples/dashboard.yaml`](examples/dashboard.yaml).

## 💶 Preise, Budget & Angebote

*Einstellungen → Geräte & Dienste → Essensplaner → Konfigurieren → (zweiter Schritt) Budget & Angebote*:

- **Wochenbudget** in Euro (0 = aus) – Panel, Sensoren und Jarvis zeigen Kosten und Restbudget; „günstig“ planen hält die Woche im Rahmen.
- **Planungsart**: ausgewogen · günstig · Angebote nutzen · Abwechslung.
- **Online-Angebote**: *marktguru.de* + **Postleitzahl** + Auswahl der **Supermärkte**. Die Integration fragt einmal täglich (morgens) die Angebote zu den Zutaten deiner Rezepte ab – aktuelle **und kommende** (ab nächster Woche) – und optional zu einer **Merkliste** (z. B. „Kaffee, Butter“).
- Ohne Online-Quelle: Angebote im Panel oder per Sprache eintragen („Bei Lidl gibt es …“).

**Wie genau sind die Preise?** Die Richtpreise sind typische Discounter-Preise (Schätzwerte). Sie werden ersetzt durch deine eigenen Preise (Panel → Angebote → 💶 Preise) und durch Normalpreise, die aus Prospekt-Angeboten gelernt werden. Rezeptkosten rechnen anteilig (was verbraucht wird), die Einkaufsliste mit ganzen Packungen.

> ⚠️ **Hinweis zu marktguru.de:** Es gibt keine offizielle Schnittstelle der Supermärkte. Die Integration nutzt die inoffizielle Web-Schnittstelle von marktguru.de, die sich jederzeit ändern kann – bitte nur für private Zwecke. Home Assistant braucht dafür Internetzugriff auf `www.marktguru.de` und `api.marktguru.de`. Ist die Quelle nicht erreichbar, bleiben die zuletzt geladenen Angebote erhalten und der Fehler wird angezeigt.

## 🧩 Blueprints

| Blueprint | Was er macht | Import |
|---|---|---|
| **Erinnerung ans Essen** | Zur gewünschten Uhrzeit Push-Nachricht und/oder Sprachausgabe („Heute zum Abendessen gibt es Lasagne – das dauert etwa 90 Minuten.“) | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftollzockt%2FHA-Essens-planer-%2Fblob%2FHEAD%2Fblueprints%2Fautomation%2Fessensplaner%2Ferinnerung.yaml) |
| **Wochen-Routine** | Einmal pro Woche freie Mahlzeiten füllen, die Einkaufsliste erstellen und eine Zusammenfassung schicken | [![Import](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftollzockt%2FHA-Essens-planer-%2Fblob%2FHEAD%2Fblueprints%2Fautomation%2Fessensplaner%2Fwochenroutine.yaml) |

## Entitäten

| Entität | Inhalt |
|---|---|
| `sensor.essensplaner_today` / `_tomorrow` | Geplante Gerichte; Attribute je Mahlzeit (`fruehstueck`, `mittagessen`, `abendessen` …), Bild als Entity-Picture |
| `sensor.essensplaner_next_meal` | Nächste Mahlzeit mit Zutaten (auf Portionen skaliert) und Zubereitung |
| `sensor.essensplaner_week_plan` | Anzahl geplanter Mahlzeiten (7 Tage), Plan als Attribut `days` / `summary` |
| `sensor.essensplaner_recipes` | Anzahl Rezepte; Namen, Favoriten, Kategorien |
| `calendar.essensplaner_meal_plan` | Alle Mahlzeiten als Termine (Termine anlegen/löschen plant bzw. entfernt Mahlzeiten) |
| `todo.essensplaner_shopping_list` | Die Einkaufsliste |
| `button.essensplaner_create_shopping_list` | Einkaufsliste für die nächsten 7 Tage erstellen |
| `button.essensplaner_auto_plan_week` | Freie Plätze der nächsten 7 Tage automatisch füllen |
| `sensor.essensplaner_week_cost` | Geschätzte Kosten des Plans dieser Woche (€), Budget, Kosten je Tag |
| `sensor.essensplaner_budget_remaining` | Restbudget der Woche (€) |
| `sensor.essensplaner_offers` | Anzahl aktueller Angebote, die zu deinen Rezepten passen; Top-Angebote als Attribut |

## Aktionen (Services)

Alle Aktionen liefern optional eine Antwort (`response_variable`) und verstehen natürliche Datumsangaben.

| Aktion | Zweck |
|---|---|
| `essensplaner.add_recipe` / `update_recipe` / `delete_recipe` | Rezepte verwalten |
| `essensplaner.import_recipe` | Rezept von URL importieren |
| `essensplaner.get_recipes` / `get_recipe` | Suchen / Rezept (skaliert) abrufen |
| `essensplaner.find_by_ingredients` | Rezepte zu vorhandenen Zutaten |
| `essensplaner.plan_meal` / `remove_meal` / `get_plan` | Wochenplan |
| `essensplaner.move_meal` / `copy_plan` | Verschieben/Tauschen, Wochen kopieren |
| `essensplaner.suggest_recipes` / `auto_plan` | Vorschläge / automatisch planen |
| `essensplaner.generate_shopping_list` / `get_shopping_list` | Einkaufsliste erzeugen / abrufen |
| `essensplaner.mark_cooked` | Als gekocht merken (bessere Vorschläge) |
| `essensplaner.export_recipes` / `import_recipes` | Backup & Teilen |
| `essensplaner.import_starter_recipes` | Fehlende mitgelieferte Rezepte (107) ergänzen |
| `essensplaner.clear_shopping_list` | Einkaufsliste leeren (alle / erledigte / aus dem Plan) |
| `essensplaner.get_costs` | Kosten & Restbudget |
| `essensplaner.set_price` | Eigenen Preis für eine Zutat festlegen |
| `essensplaner.refresh_offers` / `get_offers` / `search_offers` | Angebote laden, abrufen, live suchen |
| `essensplaner.add_offer` / `remove_offer` | Angebot eintragen / löschen |

```yaml
action: essensplaner.plan_meal
data:
  date: morgen
  meal: abendessen
  recipe: Lasagne
  servings: 4
```

```yaml
action: essensplaner.find_by_ingredients
data:
  ingredients: Hähnchen, Reis, Paprika
response_variable: ideen
```

Weitere Beispiele: [`examples/automations.yaml`](examples/automations.yaml).

## Optionen
*Einstellungen → Geräte & Dienste → Essensplaner → Konfigurieren*:
- Standard-Portionen, verwendete Mahlzeiten und Uhrzeiten, Standard-Mahlzeit
- Vorratsschrank: Zutaten, die nie auf die Einkaufsliste kommen
- **Nie vorschlagen**: z. B. „Fisch, Pilze“
- **Geplantes automatisch als gekocht zählen** (Standard: an)
- Schritt 2 **Budget & Angebote**: Wochenbudget, Planungsart, Online-Angebote, Postleitzahl, Supermärkte, Merkliste
- Einkaufsliste zusätzlich in eine andere To-do-Liste kopieren
- Intents an/aus, Panel an/aus

## Daten
Alles wird lokal in `/config/.storage/essensplaner.<entry_id>` gespeichert und ist Teil der normalen Home-Assistant-Backups. Das Event `essensplaner_updated` wird bei jeder Änderung ausgelöst. Für die Fehlersuche gibt es Diagnose-Daten (Gerät → ⋮ → Diagnosedaten herunterladen).

## Entwicklung

```bash
pip install -r requirements_test.txt
pip install hassil home-assistant-intents  # Versionen passend zu components/conversation/manifest.json
pytest
```

Änderungen: [CHANGELOG.md](CHANGELOG.md) · Lizenz: MIT
