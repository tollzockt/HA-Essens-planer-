# Changelog

## 1.2.1
- Nach einem Update werden die **neu mitgelieferten Rezepte automatisch ergänzt**
  (von dir gelöschte Rezepte bleiben gelöscht, eigene Rezepte bleiben unverändert).
- Panel → Rezepte → „Sichern & Teilen“: Knopf **„Fehlende Rezepte hinzufügen“**.

## 1.2.0

### Neu
- **107 Rezepte** statt 15: deutsche Alltagsklassiker, vegetarisch/vegan, Suppen & Eintöpfe,
  Pasta & international, Fisch, Frühstück, Kuchen & Snacks (eigene Texte). Bestehende
  Installationen holen sich fehlende Rezepte mit „Rezeptsammlung ergänzen“
  (`essensplaner.import_starter_recipes`).
- **Preise & Kosten**: Richtpreise für über 200 Zutaten (typische Discounter-Preise), eigene
  Preise, Kosten pro Rezept, Portion, Tag und Woche; Einkaufsliste mit Preis je Artikel
  (ganze Packungen) und Gesamtsumme.
- **Wochenbudget** mit Restbudget-Anzeige, Sensoren `sensor.essensplaner_week_cost` und
  `sensor.essensplaner_budget_remaining`.
- **Supermarkt-Angebote** (Aldi Süd/Nord, Lidl, REWE, EDEKA, Penny, Netto, Kaufland, Norma …):
  aktuelle **und kommende** Angebote über die (inoffizielle) marktguru.de-Suche nach
  Postleitzahl – optional, täglich automatisch – oder selbst eingetragen. Normalpreise
  werden aus den Prospekten gelernt. Sensor `sensor.essensplaner_offers`.
- **Planung mit Budget, Angeboten und Abwechslung**: Strategien *ausgewogen*, *günstig*,
  *Angebote nutzen*, *Abwechslung*; ähnliche Gerichte (z. B. zweimal Pasta) an aufeinander
  folgenden Tagen werden vermieden.
- Panel: neuer Tab **„Angebote & Budget“** (Budget-Übersicht, Angebote je Markt, Live-
  Preissuche, Angebote eintragen, Preise bearbeiten), Kosten im Wochenplan und in jedem
  Rezept, Sortierung „Günstigste zuerst“, Dialog „Woche automatisch planen“ mit Strategie.
- Jarvis: „Was kostet der Essensplan?“, „Wie viel Budget habe ich noch?“, „Welche Angebote
  gibt es diese Woche?“, „Bei Lidl gibt es Hähnchenbrust für 4,99 €“, „Plane die Woche
  günstig“, „Lösche die Einkaufsliste“.
- Neue Aktionen: `clear_shopping_list`, `import_starter_recipes`, `refresh_offers`,
  `search_offers`, `get_offers`, `add_offer`, `remove_offer`, `set_price`, `get_costs`.

### Behoben
- **Die Einkaufsliste ließ sich nicht leeren** – jetzt per Knopf „Liste leeren“, Aktion
  `essensplaner.clear_shopping_list` oder Sprachbefehl.

### Verbessert
- Zutaten mit Akzenten („Crème fraîche“) und weitere Produkte werden der richtigen
  Supermarkt-Abteilung zugeordnet; mehrdeutige Rezeptnamen („Bolognese“) bevorzugen
  Favoriten und Klassiker.
- Dashboard-Karte zeigt Wochenkosten und Budget.

## 1.1.0

### Neu
- **Kochmodus** im Panel: Vollbild, Schritt für Schritt mit großer Schrift, Zutaten zum Abhaken,
  Timer werden aus dem Text erkannt („15 Minuten köcheln“ → ⏱ Timer mit Signalton), der Bildschirm
  bleibt an, Wischen/Pfeiltasten zum Blättern, „Fertig“ merkt sich das Gericht als gekocht.
- **Dashboard-Karte** `custom:essensplaner-card` (Heute · Nächste Mahlzeit · Woche) mit
  visuellem Editor – wird automatisch geladen, keine Ressource nötig.
- **Drag & Drop** im Wochenplan, Verschieben/Tauschen auch im Dialog (für Handy).
- **„Letzte Woche übernehmen“** und Aktion `essensplaner.copy_plan`.
- **„Was kann ich kochen?“** – Rezepte nach vorhandenen Zutaten, inkl. was noch fehlt
  (`essensplaner.find_by_ingredients`, Jarvis: „Was kann ich mit Hähnchen und Reis kochen?“).
- Neue Jarvis-/Assist-Befehle: Einkaufsliste vorlesen, Mahlzeiten verschieben/tauschen,
  Kochen mit Resten.
- **Sternebewertung**, Sortierung (zuletzt/häufig gekocht, schnellste, beste Bewertung …),
  Rezept teilen.
- **Export/Import** von Rezepten (JSON) für Backup und zum Teilen.
- **Einkaufsliste**: Fortschrittsbalken, Teilen/Kopieren als Text, Aktion `get_shopping_list`.
- **Buttons** „Einkaufsliste erstellen“ und „Woche automatisch planen“ für Dashboards.
- **Blueprints**: Essens-Erinnerung (Push/Sprachausgabe) und Wochen-Routine.
- Option **„Nie vorschlagen“** (z. B. „Fisch, Pilze“) für Vorschläge und automatische Planung.
- Option **„Geplantes automatisch als gekocht zählen“** – bessere Vorschläge ohne Klicken.
- Diagnose-Daten für die Fehlersuche.

### Verbessert
- Neue Heute-Karte im Panel mit Begrüßung, nächster Mahlzeit und Vorschau auf die nächsten Tage.
- Mahlzeiten farblich unterschieden, Rezeptbilder im Wochenplan, Feinschliff für Handy & Dark Mode.
- Gesprochene Gerichte mit Artikel („die Lasagne“) werden erkannt.
- „Als gekocht markieren“ zählt dasselbe Essen nicht doppelt.

## 1.0.0
- Erste Version: Rezepte, Wochenplan, Einkaufsliste, Intents für Jarvis/Assist, Panel.
