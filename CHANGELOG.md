# Changelog

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
