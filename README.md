# 🍽️ Essensplaner für Home Assistant

Ein Essensplaner mit **107 Rezepten, Wochenplan, Kochmodus, Einkaufsliste mit Preisen, Wochenbudget, Supermarkt-Angeboten und deinen Läden (Hauptladen + Ausnahmen)**, im Stil von Apps wie Piatto, aber komplett lokal in Home Assistant und **per Sprache bzw. Chat über „Jarvis“ (oder jeden anderen Assist- bzw. LLM-Agenten) steuerbar**.

> „Hey Jarvis, was gibt es heute zu essen?“ · „Plane mir die Woche günstig.“ · „Welche Angebote gibt es diese Woche?“ · „Wie viel Budget habe ich noch?“ · „Was kann ich mit Hähnchen und Reis kochen?“ · „Erstelle die Einkaufsliste.“ · „Was muss ich bei Aldi kaufen?“ · „Wo ist Butter am günstigsten?“

**Inhalt:** [Funktionen](#funktionen) · [Installation](#installation) · [Jarvis](#-jarvis--andere-sprachassistenten) · [Dashboard-Karte](#️-dashboard-karte) · [Preise, Budget & Angebote](#-preise-budget--angebote) · [Läden, Filialen & Preise](#-läden-filialen--preise) · [Datenschutz](#-datenschutz) · [Blueprints](#-blueprints) · [Entitäten](#entitäten) · [Aktionen](#aktionen-services) · [Optionen](#optionen)

![Wochenplan](docs/images/wochenplan.png)

## Funktionen

| Bereich | Was es kann |
|---|---|
| 📖 **Rezepte** | Eigene Rezepte mit Zutaten, Schritten, Zeiten, Kategorien, Bild, Favoriten und ⭐ Bewertung. **Import per Link** von Chefkoch, Lecker, Eat Smarter, BBC Good Food & allen Seiten mit schema.org-Rezepten. Portionen werden automatisch umgerechnet. Sortieren nach „günstigste“, „zuletzt gekocht“, „schnellste“, „beste Bewertung“ … **107 Rezepte** zum Start (Klassiker, vegetarisch/vegan, Suppen, Pasta, international, Fisch, Frühstück, Kuchen). **Export/Import** als JSON. |
| 🗓️ **Wochenplan** | Frühstück, Mittag, Snack und Abendessen, mit Rezept oder Freitext („Pizza bestellen“), Kosten je Mahlzeit. **Drag & Drop** (belegte Plätze werden getauscht), **„Letzte Woche übernehmen“**, Woche **automatisch planen** – *ausgewogen*, *günstig* (Budget), *Angebote nutzen* oder *Abwechslung*: Favoriten und lange nicht Gekochtes werden bevorzugt, ähnliche Gerichte an aufeinanderfolgenden Tagen und „Nie vorschlagen“-Zutaten vermieden. |
| 💶 **Preise & Budget** | Richtpreise für über 200 Zutaten, eigene Preise – auch **je Laden** (Preisliste Aldi, Lidl, REWE … nebeneinander), **gelernte Normalpreise** aus Prospekten mit Verlauf, optional REWE-Onlinepreise (experimentell). Kosten pro Rezept/Portion/Woche, **Wochenbudget** mit Restbudget. |
| 🏪 **Läden & Filialen** | Deine Filialen per **OpenStreetMap-Suche** rund um Zuhause und Arbeit, **auf dem Arbeitsweg** oder von Hand. **Hauptladen + Ausnahmen**: alles in den Hauptladen, nur Angebote und deutlich günstigere Artikel in andere Läden. Angebote für die Postleitzahlen deiner Filialen. |
| 🏷️ **Angebote** | **Aktuelle und kommende Angebote** von Aldi Süd/Nord, Lidl, REWE, EDEKA, Penny, Netto, Kaufland … (optional über marktguru.de nach Postleitzahl, täglich automatisch) oder selbst eingetragen. Angebote fließen in Rezeptkosten, Planung und Einkaufsliste ein; Normalpreise werden aus den Prospekten gelernt. Live-Preissuche im Panel. |
| 👩‍🍳 **Kochmodus** | Vollbild Schritt für Schritt mit großer Schrift, Zutaten zum Abhaken, **Timer aus dem Rezepttext** („15 Minuten köcheln“ → ⏱ mit Signalton). Der Bildschirm bleibt an. Blättern per Wischen oder Pfeiltasten. |
| 🧊 **Was kann ich kochen?** | Rezepte zu den Zutaten, die du da hast, mit Angabe, was noch fehlt. |
| 🛒 **Einkaufsliste** | Wird aus dem Plan erzeugt: Zutaten werden **zusammengefasst** (500 g + 0,7 kg → 1,2 kg), auf Portionen skaliert, **nach Supermarkt-Abteilung sortiert**, Vorratszutaten (Salz, Pfeffer …) weggelassen. Abgehakte Einträge bleiben beim Neuerstellen abgehakt. **Preis je Artikel und Gesamtsumme**, Angebots-Hinweise („🏷️ Lidl 4,99 €“), **nach Laden** mit Zwischensumme oder nach Abteilung, **Ladenwahl je Artikel**, **Artikelsuche beim Tippen** (Preis, Packung, Angebot), **Liste leeren**, Fortschrittsbalken, Teilen (Teilen-Menü des Geräts) bzw. Kopieren als Text, optional Kopie in eine andere To-do-Liste (z. B. Bring!). |
| 🗣️ **Jarvis / Assist / LLM** | 22 Intents, die automatisch als **Tools für LLM-Agenten** (inkl. MCP-Server) erscheinen, plus deutsche Sätze für den eingebauten Sprachagenten. |
| 📱 **App in der Seitenleiste** | Panel „Essensplaner“ mit Heute-Karte, Wochenplan, Rezepten, Einkaufsliste, Angeboten und „🏪 Läden & Preise“, passend zu Hell/Dunkel-Theme und Handy. |
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

### Updates
HACS installiert **GitHub-Releases**, nicht einfach den neuesten Stand des Repositorys. Für jede neue Version wird deshalb ein Release mit dem Tag `vX.Y.Z` erstellt – für diese Version **`v1.3.1`**. Dann erscheint das Update unter *Einstellungen → Updates* bzw. in HACS (falls es nicht von selbst auftaucht: in HACS beim Essensplaner über ⋮ die Informationen aktualisieren). Danach Home Assistant neu starten und den Browser einmal neu laden (Strg+F5 bzw. App-Cache leeren).

**Update auf 1.3:** Deine Daten werden beim ersten Start automatisch übernommen (eigene Preise mit Laden landen zusätzlich in der Preisliste dieses Ladens). Bis du Filialen anlegst, verhält sich alles wie in 1.2. Neu in den Optionen ist der Schritt **„Läden & Einkauf“**. Nutzt du den eingebauten Sprachagenten ohne LLM, kopiere [`custom_sentences/de/essensplaner.yaml`](custom_sentences/de/essensplaner.yaml) erneut (neue Sätze) – **Achtung:** Mit der neuen Datei landet „Setz Milch auf die Einkaufsliste“ (und jede andere Formulierung von Home Assistants eingebauter Einkaufsliste) auf der Essensplaner-Liste statt auf der eingebauten Einkaufsliste bzw. einer damit synchronisierten Liste (z. B. Bring!), siehe [Eingebauter Sprachagent](#eingebauter-sprachagent-ohne-llm). Zurück auf 1.2 geht, aber Filialen, Ladenpreise und Preisverlauf gehen dabei verloren – vorher ein Backup machen.

## 🤖 Jarvis & andere Sprachassistenten

Der Essensplaner registriert **Intents**. Home Assistant stellt jeden registrierten Intent über die *Assist*-LLM-API automatisch als **Tool** bereit:

* **LLM-Agenten** (OpenAI, Anthropic, Google, Ollama, Hermes …) mit aktivierter Option „Home Assistant steuern → Assist“ sehen die Tools sofort.
* Der **Model-Context-Protocol-Server** (Integration „MCP Server“ mit LLM-API *Assist*) gibt die Tools an externe Agenten weiter, z. B. an **Jarvis/Hermes-Agent**, Claude Desktop & Co.
* Für den **eingebauten Agenten** ohne LLM gibt es fertige deutsche Sätze (siehe unten).

### Empfohlene Einrichtung für Jarvis
1. Integration installieren (Intents sind standardmäßig aktiv, Option „Sprachassistent / LLM-Tools“).
2. Unter **Einstellungen → Sprachassistenten → Entitäten freigeben** diese Entitäten für Assist freigeben, damit Jarvis den Plan auch „sieht“:
   `sensor.essensplaner_today`, `sensor.essensplaner_tomorrow`, `sensor.essensplaner_next_meal`, `sensor.essensplaner_week_plan`, `todo.essensplaner_shopping_list`, `calendar.essensplaner_meal_plan` – und für den Einkauf nach Laden `sensor.essensplaner_shopping_stores` und `sensor.essensplaner_shopping_total`.
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
| `essensplaner_get_shopping_list` | „Was steht auf der Einkaufsliste?“ · „Was muss ich einkaufen?“ · „Was muss ich bei Aldi kaufen?“ · „Was kaufe ich im Hauptladen?“ |
| `essensplaner_add_shopping_item` | „Setz Butter auf die Einkaufsliste.“ · „Füge Kaffee zur Einkaufsliste hinzu.“ (mit Preis und Laden) |
| `essensplaner_set_shopping_store` | „Kauf die Butter bei REWE.“ · „Milch kaufe ich immer bei Lidl.“ · „Was kaufe ich immer bei Lidl?“ |
| `essensplaner_compare_prices` | „Wo ist Butter am günstigsten?“ · „Vergleiche die Preise für Hackfleisch.“ |
| `essensplaner_clear_shopping_list` | „Lösche die Einkaufsliste.“ · „Entferne die erledigten Einträge.“ |
| `essensplaner_auto_plan` | „Plane mir die nächste Woche (vegetarisch).“ · „Plane die Woche günstig / mit den Angeboten.“ |
| `essensplaner_get_offers` | „Welche Angebote gibt es diese Woche?“ · „Wo ist Butter im Angebot?“ · „Was ist im Hauptladen im Angebot?“ · „Wo ist Butter bei Lidl Arbeit im Angebot?“ |
| `essensplaner_add_offer` | „Bei Lidl gibt es Hähnchenbrust für 4,99 Euro das Kilo bis Samstag.“ |
| `essensplaner_get_costs` | „Was kostet der Essensplan diese Woche?“ · „Wie viel Budget habe ich noch?“ |
| `essensplaner_add_recipe` | „Speichere ein Rezept Rührei mit 3 Eiern, Butter und Salz.“ |
| `essensplaner_import_recipe` | „Importiere das Rezept von https://www.chefkoch.de/…“ |
| `essensplaner_mark_cooked` | „Wir haben heute Linsensuppe gekocht.“ |

Antworten klingen z. B. so: *„Bei Aldi Süd kaufst du 3 Artikel für ungefähr 7,47 €: …“* · *„Am günstigsten gibt es Butter bei Lidl: 1,59 € (250 g).“* · *„Ich habe Butter auf die Einkaufsliste gesetzt – bei Aldi Süd etwa 1,79 €.“* Läden versteht Jarvis als Kette (Aldi, Aldi Süd, Lidl, REWE, EDEKA, Penny, Netto, Kaufland, Norma, Globus, Marktkauf), als eigene Bezeichnung („Lidl Arbeit“) oder als „Hauptladen“ – auch bei Angeboten. Mengen dürfen in Worten kommen („zwei Liter Milch“, „drei Packungen Butter“); „Hackfleisch“ findet auf der Liste auch „Rinderhackfleisch“ und „Tomaten“ die „Cherrytomaten“, wenn es das einzige dieser Art ist – „Milch“ aber nicht „Buttermilch“ oder „Kokosmilch“.

Datumsangaben werden in natürlicher Sprache verstanden: *heute, morgen, übermorgen, heute Abend, morgen früh, Freitag, nächsten Montag, nächste Woche, in 3 Tagen, 24.12., 2026-11-20*.

### Eingebauter Sprachagent (ohne LLM)
Datei [`custom_sentences/de/essensplaner.yaml`](custom_sentences/de/essensplaner.yaml) nach `/config/custom_sentences/de/` kopieren und Home Assistant neu starten.

Die Datei übernimmt auch die Sätze der **eingebauten Einkaufsliste** von Home Assistant: „Setz Milch auf die Einkaufsliste“, „Füge Milch zu meiner Einkaufsliste hinzu“, „Milch auf die Liste“ usw. landen dann – mit Laden und Preis – auf der **Essensplaner-Liste**, nicht mehr auf der eingebauten Einkaufsliste und nicht in einer Liste, die du mit ihr synchronisierst. Willst du das nicht, lösche in der kopierten Datei den Block `essensplaner_add_shopping_item`. Mit „Bevorzugt lokale Befehle“ gilt das auch für einen LLM-Agenten wie Jarvis.

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

<!-- screenshot: optionen-budget-angebote.png -->

- **Wochenbudget** in Euro (0 = aus) – Panel, Sensoren und Jarvis zeigen Kosten und Restbudget; „günstig“ planen hält die Woche im Rahmen.
- **Planungsart**: ausgewogen · günstig · Angebote nutzen · Abwechslung.
- **Online-Angebote**: *marktguru.de* + **Postleitzahl** + Auswahl der **Supermärkte**. Die Integration fragt einmal täglich (morgens) die Angebote zu den Zutaten deiner Rezepte ab – aktuelle **und kommende** (ab nächster Woche) –, zu bis zu 10 offenen Artikeln, die du selbst auf die Einkaufsliste gesetzt hast, und optional zu einer **Merkliste** (z. B. „Kaffee, Butter“). Hast du [Filialen](#-läden-filialen--preise) gespeichert, wird für deren Postleitzahlen und Ketten gesucht (bis zu 4 Postleitzahlen); die Postleitzahl in den Optionen darf dann leer bleiben.
- Ohne Online-Quelle: Angebote im Panel oder per Sprache eintragen („Bei Lidl gibt es …“). Ohne „Gültig bis“ bzw. „bis …“ gilt ein Angebot bis zum kommenden Samstag (Ende der Prospektwoche).

**Wie genau sind die Preise?** Die Richtpreise sind typische Discounter-Preise (Schätzwerte). Sie werden ersetzt durch deine eigenen Preise (Panel → 🏪 Läden & Preise → Preisliste) und durch Normalpreise, die aus Prospekt-Angeboten gelernt werden – mit Hauptladen gelten die Preise dieses Ladens (siehe unten). Rezeptkosten rechnen anteilig (was verbraucht wird), die Einkaufsliste mit ganzen Packungen.

> ⚠️ **Hinweis zu marktguru.de:** Es gibt keine offizielle Schnittstelle der Supermärkte. Die Integration nutzt die inoffizielle Web-Schnittstelle von marktguru.de, die sich jederzeit ändern kann – bitte nur für private Zwecke. Home Assistant braucht dafür Internetzugriff auf `www.marktguru.de` und `api.marktguru.de`. Ist die Quelle nicht erreichbar, bleiben die zuletzt geladenen Angebote erhalten und der Fehler wird angezeigt.

## 🏪 Läden, Filialen & Preise

Im Panel gibt es den Tab **„🏪 Läden & Preise“**. Dort legst du deine Filialen an, wählst den **Hauptladen** und pflegst die **Preisliste je Laden**. Ohne Filialen verhält sich alles wie in 1.2.

![Läden & Preise](docs/images/laeden-preise.png)

### Hauptladen + Ausnahmen
Die Einkaufsliste kommt **komplett in deinen Hauptladen**. Nur wenn sich ein anderer deiner Läden wirklich lohnt, wandert ein Artikel dorthin:

- ein **Angebot**, das mindestens **0,30 €** spart, oder
- ein **echter Ladenpreis** (eigener oder gelernter Preis, kein Richtwert), der mindestens **1,00 €** *oder* **20 %** günstiger ist – und immer mindestens 0,20 €.

Hat der Hauptladen für einen Artikel gar keinen Preis (z. B. Kaffee, für den es keinen Richtwert gibt), reicht ein Angebot genau dieses Produkts in einem anderen Laden („Kaffee Crema“, nicht „Eiskaffee“ oder „Milchkaffee“). Bei mehreren Angeboten gewinnt der niedrigste Preis pro kg, Liter bzw. Stück. Optional: **„Extra-Laden lohnt sich ab“** – spart ein zusätzlicher Laden insgesamt weniger, kommt alles zurück in den Hauptladen (Standard 0 = aus); ein Laden, in dem du ohnehin einkaufst (ein Artikel dort von Hand gewählt oder „immer hier“), zählt nicht als Extra-Laden. Alle Schwellen stellst du in den Optionen ein (Schritt **„Läden & Einkauf“**), ebenso den Modus: *Aus – eine Liste wie bisher* · *Alles im Hauptladen* · *Hauptladen + Ausnahmen (empfohlen)*. Die Aufteilung startet, sobald du einen Hauptladen hast; die **erste Filiale wird automatisch Hauptladen**.

In der Einkaufsliste schaltest du um zwischen **„Nach Laden“** (je Laden Artikel, Zwischensumme und Ersparnis) und **„Nach Abteilung“**. Mit **⇄** an einem Artikel siehst du die Preise aller Läden und wählst den Laden selbst, „Automatisch“ oder **„Immer in diesem Laden kaufen“** (im Laden markiert mit „immer hier“; das gilt für genau diese Filiale, z. B. „Lidl Arbeit“). Deine Wahl bleibt beim Neuerstellen der Liste erhalten. Offene Artikel werden **automatisch neu verteilt**, sobald sich Filialen, Hauptladen, Preise, Angebote oder die Laden-Optionen ändern (auch wenn ein Angebot über Nacht endet); **„🔄 Läden neu zuordnen“** macht das von Hand. In der To-do-Liste steht der Laden in der Beschreibung („🏪 Aldi Süd · …“).

| Einkauf nach Laden | Ladenwahl ⇄ | Handy |
|---|---|---|
| ![Einkauf nach Laden](docs/images/einkauf-nach-laden.png) | ![Ladenwahl](docs/images/ladenwahl.png) | ![Einkauf nach Laden auf dem Handy](docs/images/handy-einkauf-nach-laden.png) |

### Filialen finden
- **In der Nähe suchen (OpenStreetMap):** sucht Aldi, Lidl, REWE, EDEKA, Penny, Netto, Kaufland, Norma, Globus und Marktkauf im **Umkreis deiner Zonen** (Standard 3 km). Ohne Auswahl sind das *Zuhause* und alle Zonen mit „Arbeit“ bzw. „Work“ im Namen (z. B. `zone.home`, `zone.arbeit`, `zone.arbeit_2`). Mit **Arbeitsweg** werden auch Läden entlang der Strecke von Zuhause zu diesen Zonen gefunden (Luftlinie, Standard bis 800 m daneben). Treffer zeigen die Entfernung zu Zuhause bzw. zum Arbeitsweg; „＋ Hinzufügen“ übernimmt sie in deine Läden. Ergebnisse werden 30 Tage gemerkt, neu gesucht wird höchstens alle 2 Minuten.
- **Manuell hinzufügen:** Kette, Straße, Postleitzahl und Ort – z. B. wenn ein Laden bei OpenStreetMap fehlt oder bei „Aldi“ unklar ist, ob Süd oder Nord.
- Die **Postleitzahl** einer Filiale ist wichtig: Für sie werden die Angebote gesucht. Mit Online-Angeboten wird eine neue Postleitzahl (oder Kette) etwa eine Minute nach dem Speichern abgefragt, danach täglich.
- Zonen, Umkreis und Arbeitsweg stellst du in den Optionen ein (Schritt „Läden & Einkauf“).

![Filialsuche mit OpenStreetMap](docs/images/filialsuche.png)

### Preisliste je Laden
Die Preisliste zeigt je Zutat den Richtwert und die Preise deiner Läden nebeneinander, der günstigste ist markiert; jede Zelle lässt sich bearbeiten (auf dem Handy ein Laden + „Günstigster“, der Richtwert steht unter dem Artikel). Welcher Preis gilt, wird je Laden in dieser Reihenfolge entschieden:

1. dein **eigener Ladenpreis** (z. B. „Butter bei Aldi Süd 1,79 €“)
2. **gelernter Ladenpreis** (höchstens 180 Tage alt; REWE-Onlinepreis vor Prospekt-Normalpreis)
3. dein **eigener allgemeiner Preis**
4. **gelernter allgemeiner Preis**
5. **Richtwert**

Gültige Angebote des Ladens werden zusätzlich verglichen (in ganzen Packungen; ein Angebot ohne Packungsgröße gilt für die übliche Packung des Ladens). Ohne ladenspezifische Preise kostet ein Artikel überall gleich viel und wird deshalb nie verschoben. Hast du zwei Filialen derselben Kette (z. B. REWE zu Hause und bei der Arbeit), zählt ein Angebot, das nur für die zweite gefunden wurde, für diese Filiale.

Mit Hauptladen (Filialen) gilt ein Preis in einer Ladenzelle nur für diesen Laden – dein allgemeiner Preis (Spalte Richtwert) bleibt dabei unverändert. Ohne Filialen (Spalten aus den Angebots-Läden der Optionen) wird er wie in 1.2 zusätzlich dein allgemeiner Preis, mit dem Laden als Hinweis; ein allgemeiner Preis ohne Laden bleibt aber stehen.

![Preisliste je Laden](docs/images/preisliste-je-laden.png)

### Gelernte Normalpreise aus Prospekten
Viele Angebote nennen den Normalpreis („statt 2,49 €“). Daraus lernt der Essensplaner den Preis **je Laden**, mit **Verlauf** (bis zu 12 Einträge) und einer Plausibilitätsprüfung gegen den Richtwert. Quelle ist die inoffizielle marktguru.de-Suche (siehe oben) – nur wenn Online-Angebote eingeschaltet sind.

### REWE-Onlinepreise (experimentell)
Standardmäßig **aus**. Eingeschaltet (Optionen → „Läden & Einkauf“) holt der Essensplaner einmal pro Woche Normalpreise aus dem REWE-Onlineshop für deine REWE-Filiale. Der Knopf „Preise aktualisieren“ fragt nach einem erfolgreichen Abruf frühestens 6 Stunden später erneut. Dafür braucht die Filiale eine **Markt-ID** (Knopf „Markt suchen“ an der REWE-Filiale bzw. Aktion `essensplaner.find_rewe_markets`).

> ⚠️ Das ist eine **inoffizielle Schnittstelle** des REWE-Onlineshops: Markt-ID und Suchbegriffe (Zutaten, Artikel der Einkaufsliste, deine Artikelsuche) gehen an `shop.rewe.de`. Lehnt REWE automatische Abfragen ab, wird **7 Tage pausiert**; gelernte Preise bleiben. Es kann jederzeit aufhören zu funktionieren – Schutzmechanismen werden bewusst nicht umgangen.

### Artikelsuche beim Hinzufügen
Tippst du im Feld **„Artikel hinzufügen“**, erscheinen passende Artikel deines Hauptladens mit Preis, Packung und 🏷️ Angebot – aus der Preisliste, den Richtwerten, gültigen Angeboten und deinen zuletzt gekauften Artikeln. Mit Online-Angeboten (bzw. REWE-Onlinepreisen bei einem REWE-Hauptladen) wird zusätzlich live gesucht. Antippen fügt den Artikel **mit Preis und Laden** hinzu; Enter ohne Auswahl übernimmt den Text wie bisher.

![Artikelsuche beim Hinzufügen](docs/images/artikelsuche.png)

## 🔒 Datenschutz
Alles bleibt lokal in Home Assistant, solange du keine Online-Funktion nutzt. Gesendet wird nur:

| Dienst | Wann | Was |
|---|---|---|
| OpenStreetMap (`overpass-api.de`) | nur wenn du die Filialsuche startest | Koordinaten deiner Zonen, auf ca. 100 m gerundet |
| marktguru.de | nur mit Online-Angeboten (täglich, Live-Suche, Artikelsuche) | Postleitzahlen (Filialen bzw. Optionen) und Suchbegriffe – auch, was du in „Artikel hinzufügen“ tippst (ab 3 Zeichen) |
| REWE (`shop.rewe.de`) | nur mit REWE-Onlinepreisen (wöchentlich, Knopf „Preise aktualisieren“, Artikelsuche) | Markt-ID und Suchbegriffe |
| REWE (`www.rewe.de`) | nur bei „Markt suchen“ | Postleitzahl |

Daten © OpenStreetMap-Mitwirkende (ODbL). In den Diagnose-Daten sind Koordinaten, Straßen, Postleitzahlen, Orte, Namen, Bezeichnungen, Entfernungen, Zonen-Namen, Filial- und Markt-IDs geschwärzt; übrig bleiben Kette, Hauptladen-Markierung und Anzahlen.

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
| `sensor.essensplaner_shopping_stores` | Anzahl Läden mit offenen Artikeln; Attribut `stores` je Laden mit offenen Artikeln, Zwischensumme, Ersparnis und Artikeln, dazu `main_store` |
| `sensor.essensplaner_shopping_total` | Geschätzte Summe der offenen Einkaufsliste (€); Artikel mit/ohne Preis, Angebote, Ersparnis durch die Ladenwahl |

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
| `essensplaner.generate_shopping_list` / `get_shopping_list` | Einkaufsliste erzeugen (mit Läden) / abrufen (optional nur ein Laden) |
| `essensplaner.add_shopping_item` | Artikel mit Laden und Preis auf die Einkaufsliste setzen |
| `essensplaner.set_shopping_store` / `assign_shopping_stores` | Laden für einen Artikel festlegen („immer hier“) / alle offenen Artikel neu zuordnen |
| `essensplaner.mark_cooked` | Als gekocht merken (bessere Vorschläge) |
| `essensplaner.export_recipes` / `import_recipes` | Backup & Teilen |
| `essensplaner.import_starter_recipes` | Fehlende mitgelieferte Rezepte (107) ergänzen |
| `essensplaner.clear_shopping_list` | Einkaufsliste leeren (alle / erledigte / aus dem Plan) |
| `essensplaner.get_costs` | Kosten & Restbudget |
| `essensplaner.set_price` | Eigenen Preis für eine Zutat festlegen (optional für einen Laden) |
| `essensplaner.get_store_prices` / `compare_prices` | Preisliste je Laden / Preis eines Produkts in deinen Läden vergleichen |
| `essensplaner.find_branches` | Filialen bei OpenStreetMap suchen (Zonen, Umkreis, Arbeitsweg) |
| `essensplaner.save_branch` / `remove_branch` / `get_branches` | Filialen anlegen/ändern, entfernen, abrufen |
| `essensplaner.refresh_prices` | Preise jetzt aus einer Online-Quelle holen (`offers` = Angebote, `rewe` = REWE-Onlinepreise) |
| `essensplaner.find_rewe_markets` | REWE-Märkte und ihre Markt-IDs zu einer Postleitzahl finden |
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

```yaml
action: essensplaner.get_shopping_list
data:
  store: Aldi Süd   # oder "Hauptladen", "Lidl Arbeit"
response_variable: einkauf   # einkauf.selection: Artikel, Zwischensumme, Ersparnis
```

Weitere Beispiele: [`examples/automations.yaml`](examples/automations.yaml).

## Optionen
*Einstellungen → Geräte & Dienste → Essensplaner → Konfigurieren*:
- Standard-Portionen, verwendete Mahlzeiten und Uhrzeiten, Standard-Mahlzeit
- Vorratsschrank: Zutaten, die nie auf die Einkaufsliste kommen
- **Nie vorschlagen**: z. B. „Fisch, Pilze“
- **Geplantes automatisch als gekocht zählen** (Standard: an)
- Schritt 2 **Budget & Angebote**: Wochenbudget, Planungsart, Online-Angebote, Postleitzahl, Supermärkte, Merkliste
- Schritt 3 **Läden & Einkauf**: Einkaufsliste nach Läden (Aus · Alles im Hauptladen · Hauptladen + Ausnahmen), Schwellen (Standard: 1,00 € oder 20 %, Angebot ab 0,30 €, Extra-Laden ab 0 € = aus), Zonen, Umkreis (3 km) und Arbeitsweg (800 m) für die Filialsuche, REWE-Onlinepreise (experimentell, aus). Die Filialen selbst wählst du im Panel.

<!-- screenshot: optionen-laeden.png -->
- Einkaufsliste zusätzlich in eine andere To-do-Liste kopieren
- Intents an/aus, Panel an/aus

## Daten
Alles wird lokal in `/config/.storage/essensplaner.<entry_id>` gespeichert und ist Teil der normalen Home-Assistant-Backups. Das Event `essensplaner_updated` wird bei jeder Änderung ausgelöst. Für die Fehlersuche gibt es Diagnose-Daten (Gerät → ⋮ → Diagnosedaten herunterladen) – ohne Koordinaten, Adressen (Straße, Postleitzahl, Ort), Namen und IDs deiner Filialen; auch die Postleitzahl aus den Optionen ist geschwärzt.

## Entwicklung

```bash
pip install -r requirements_test.txt
pip install hassil home-assistant-intents  # Versionen passend zu components/conversation/manifest.json
pytest
```

Änderungen: [CHANGELOG.md](CHANGELOG.md) · Lizenz: MIT
