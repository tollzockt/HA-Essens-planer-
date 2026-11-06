# Changelog

## 1.3.1

Fehlerbehebungen zu 1.3.0 – deine Daten bleiben erhalten, es gibt keine neuen Optionen.

### Einkauf nach Laden
- Offene Artikel werden **automatisch neu verteilt**, wenn sich Filialen, Hauptladen, Preise,
  Angebote oder die Laden-Optionen ändern (auch nach einem Neustart und wenn ein Angebot über
  Nacht endet); „🔄 Läden neu zuordnen“ macht das weiterhin von Hand. Pausierte Filialen verlieren
  die Ladenwahl, bis sie wieder aktiv sind.
- Ein Artikel **ohne Preis im Hauptladen** (z. B. Kaffee) wandert, wenn ein anderer Laden genau
  dieses Produkt im Angebot hat – auch als Markenangebot („Jacobs Krönung“, Röstkaffee), nicht für
  „Eiskaffee“ oder „Milchkaffee“. Bei mehreren Angeboten zählt der Preis pro kg, Liter bzw. Stück,
  nicht die kleinste Packung. Ein „Eiskaffee“-Angebot im Hauptladen ist kein Preis für Kaffee und
  hält ihn dort auch nicht fest.
- **Angetippte Angebote**: Ein Angebot des Hauptladens ist keine Ladenwahl (der Artikel bleibt
  automatisch); ein Angebot eines anderen Ladens hält den Artikel dort, bis das Angebot endet.
  Gilt ein Angebot nur bei einer weiteren Filiale einer Kette (z. B. „Lidl Arbeit“ mit anderer
  Postleitzahl), landet der Artikel dort – und der Angebotspreis gilt nur in dieser Filiale.
- **„Extra-Laden lohnt sich ab“** schickt Angebote nicht mehr in den Hauptladen zurück, wenn du in
  dem Laden ohnehin einkaufst (ein Artikel dort von Hand gewählt oder „immer hier“) – sofort, wenn
  du einen Laden wählst, einen Artikel hinzufügst oder wieder „Automatisch“ einstellst.
- **„Immer in diesem Laden kaufen“** merkt sich auch eine weitere Filiale einer Kette (z. B. „Lidl
  Arbeit“ neben „Lidl Zuhause“); bisher landete das Produkt beim nächsten Mal in der ersten
  Filiale der Kette.
- Eine **eigene Notiz an einem erzeugten Artikel** (z. B. in der To-do-App von Home Assistant
  eingetragen) bleibt erhalten, wenn die Liste automatisch neu verteilt wird.
- Ein Angebot, das **erst ab heute gilt** (Prospekt der nächsten Woche, „Gültig ab“), verteilt die
  Liste kurz nach Mitternacht neu.
- Mit der Aufteilung **„Aus“** gilt ein gewählter Preis bzw. eine gewählte Packung (z. B. 500 g
  aus der Artikelsuche) wieder.
- Einträge aus 1.2 wie „Butter (2 EL + 25 g)“ behalten einen Preis in den Läden.

### Artikelsuche
- Ein Treffer des Hauptladens setzt keine feste Ladenwahl mehr; Preis und Packung werden nur für
  ladenspezifische Treffer übernommen (Angebot, Live-Treffer, eigener oder gelernter Preis).
  Live-Prospektangebote zählen als Angebot.
- Lokale und Live-Treffer stehen in einer Rangliste: Angebote des gesuchten Artikels zuerst,
  andere Produkte (Butterkekse, Erdnussbutter, Kokosmilch, Dosentomaten) danach.
- Enter fügt den getippten Text hinzu, auch wenn vorher ein Treffer markiert war.

### Jarvis
- Die Satzdatei kennt die Formulierungen der eingebauten Einkaufsliste („setzt“, „meine Liste“,
  „hinzufügen“) und eigene Filial-Bezeichnungen („Lidl Arbeit“, „Hauptladen“), auch bei
  Angebotsfragen: „Welche Angebote gibt es bei Lidl?“, „Was ist im Hauptladen im Angebot?“, „Wo ist
  Butter bei Lidl Arbeit im Angebot?“.
- Ein Angebot für den **„Hauptladen“** oder eine eigene Filial-Bezeichnung („Im Hauptladen gibt es
  Butter für 1,49 Euro“) gilt für genau diese Filiale; ein Preis für „Hauptladen“ wird der
  Ladenpreis des Hauptladens (bisher ein allgemeiner Preis für alle Läden). „Was kaufe ich immer
  bei Lidl Arbeit?“ nennt die Produkte dieser Filiale.
- „Kauf Hackfleisch bei Lidl“ findet „Rinderhackfleisch“, „Tomaten“ die „Cherrytomaten“, wenn es
  das einzige dieser Art auf der Liste ist – „Milch“ aber nicht „Buttermilch“ oder „Kokosmilch“,
  „Zucker“ nicht „Puderzucker“.
- „Kaffee kaufe ich immer bei Lidl“ klappt auch, wenn Kaffee gerade nicht auf der Liste steht.
  „Was kaufe ich immer bei Lidl?“ zählt alle gemerkten Produkte auf (Kokosmilch neben Milch) und
  merkt sich nichts für „was“.
- Mengen in Worten („zwei Liter Milch“, „einen Liter Milch“, „ein Pfund Hackfleisch“) werden als
  Zahl übernommen.
- „Erstelle die Einkaufsliste“ sagt, wie viele Artikel in welchen Laden kommen und was die
  Angebote sparen.
- „Bei Lidl gibt es Hähnchenbrust für 4,99 Euro“ ohne „bis …“: Das Angebot gilt bis zum
  kommenden Samstag (Ende der Prospektwoche), und Jarvis sagt das („gültig bis Samstag“). Bisher
  galt es für immer und schickte den Artikel dauerhaft in diesen Laden.
- Preisvergleiche ohne Menge rechnen pro kg; gesprochene Fehler ohne Sonderzeichen; ein klarer
  Hinweis, wenn die Aufteilung nach Laden aus ist.

### Preise & Angebote
- **Frische und Dosentomaten** werden auch bei Angeboten und Ladenpreisen getrennt (ebenso
  Kokos-, Butter- und Hafermilch von Milch); unter dem alten Schlüssel gespeicherte Preise werden
  beim Update umgezogen. Ein einfaches „Aldi“ folgt deiner Aldi-Filiale.
- **Eier-Angebote** werden erkannt („Frische Eier 10 Stück“, auch mit Gewichtsklasse „Größe M
  (53-63 g), 10 Stück“, „Gewichtsklasse M (53 g bis unter 63 g)“ oder „Größe L (ab 63 g)“) –
  Schoko-Eier, Eierlikör, Überraschungseier oder Eier-Nudeln nicht.
- **Gelernte Normalpreise**: Prospekt- und REWE-Preise nach Gewicht werden auch für Produkte mit
  Richtwert je Stück gelernt, wenn es das Produkt selbst ist (Baguette, Weißkohl, Hefe …) – nicht
  „Pesto Basilikum“ für einen Bund Basilikum, „Gurken-Dill“ für Dill oder „Kartoffelsalat“ für
  Salat. Nicht gelernt wird ein Stückpreis für ein Produkt mit Richtwert nach Gewicht (z. B.
  Butter), ein 100-g-Beutel für Eier oder für Produkte ohne Richtwert ein anderes Produkt
  („Eiskaffee“ für Kaffee).
- Angebote ohne Packungsgröße (per Sprache) oder mit „10 Stück“ zählen für Preise und Läden; ein
  Preis ohne Packung gilt für die übliche Packung des Ladens.
- marktguru sucht auch bis zu 10 Artikel, die du selbst auf die Liste gesetzt hast. Eine **neue
  Filiale** mit neuer Postleitzahl (oder Kette) wird etwa eine Minute nach dem Speichern
  abgefragt, nicht erst am nächsten Morgen – auch wenn gerade eine Abfrage läuft.
- Ohne Enddatum gespeicherte Angebote (aus 1.2 / 1.3.0) enden mit der laufenden Prospektwoche.
- Einen Ladenpreis setzen behält den allgemeinen eigenen Preis; eine Ladenzelle zurücksetzen
  löscht ihn nicht mehr.
- Filialsuche (OpenStreetMap), REWE-Preise und Rezeptimport lesen Antworten vollständig (Suche
  und Preise brachen teils ab); nur eine Angebotsaktualisierung zur Zeit; „Preise aktualisieren“
  für REWE frühestens 6 Stunden nach dem letzten Abruf; nach einem Neuladen der Integration
  überschreiben späte Ergebnisse nichts mehr.

### Panel
- Die Kopfzeile über „Artikel hinzufügen“ bleibt stehen (kein Durchtippen beim Scrollen).
- Angebote-Tab **„🛒 Merken“**: Mit Läden kommt das Angebot mit Preis und Packung in seinen Laden.
- Preisliste je Laden: **„＋ „…“ als Artikel anlegen“** für Artikel ohne Richtwert (z. B. Kaffee).
- Ladenwahl ⇄: Eine weitere Filiale derselben Kette zeigt die Preise der Kette (Angebote nur, wo
  sie gelten).
- **„⭐ Immer hier gekauft“** unter „Meine Läden“: die gemerkten Läden je Produkt, nach Kette
  sortiert – auch für Produkte, die gerade nicht auf der Liste stehen –, mit ✕ zum Vergessen.
- Filialsuche: Filter je Kette mit Anzahl der Treffer.
- Preistexte folgen der Reihenfolge der Preisliste: Im Laden geht ein gelernter Ladenpreis dem
  eigenen allgemeinen Preis vor.
- REWE-Markt-ID: Speichern ohne Änderung löscht die ID nicht mehr; Entfernen fragt nach.
- Auf- und zugeklappte Abschnitte im Tab „Läden & Preise“ merken sich nur echte Klicks.

### Doku
- README und Upgrade-Hinweise: Die Satzdatei übernimmt die Sätze der eingebauten Einkaufsliste;
  die Live-Artikelsuche sendet, was du tippst, an marktguru; Ladenzellen ohne Hauptladen.
- Diagnose-Daten schwärzen auch Postleitzahlen, Orte, Namen und Zonen-Namen.
- Release für diese Version: **v1.3.1**.

### Upgrade-Hinweise
- Nach dem Update Home Assistant neu starten und den Browser einmal neu laden (Strg+F5 bzw.
  App-Cache leeren). Für den eingebauten Sprachagenten ohne LLM die Datei
  `custom_sentences/de/essensplaner.yaml` erneut nach `/config/custom_sentences/de/` kopieren.
- **Achtung, Satzdatei:** Die neue Datei übernimmt die Sätze der eingebauten Einkaufsliste von
  Home Assistant („Setz Milch auf die Einkaufsliste“, „Füge Milch zu meiner Einkaufsliste
  hinzu“ …). Sie landen dann auf der Essensplaner-Liste, nicht mehr auf der eingebauten
  Einkaufsliste bzw. einer damit synchronisierten Liste. Wer das nicht möchte, löscht in der
  kopierten Datei den Block `essensplaner_add_shopping_item`.

## 1.3.0

### Neu
- **Filialen – deine Läden**: Filialen von Aldi Süd/Nord, Lidl, REWE, EDEKA, Penny, Netto, Kaufland,
  Norma, Globus und Marktkauf im neuen Panel-Tab **„🏪 Läden & Preise“** speichern – per
  **OpenStreetMap-Suche** rund um deine Zonen (Standard: Zuhause und Zonen mit „Arbeit“/„Work“ im
  Namen, z. B. `zone.home`, `zone.arbeit`, `zone.arbeit_2`), **auf dem Arbeitsweg** (Luftlinie
  Zuhause → Zone) oder **von Hand**. Die erste Filiale wird automatisch dein **Hauptladen**;
  Reihenfolge, Bezeichnung („Lidl Arbeit“) und Hauptladen lassen sich ändern.
- **Angebote je Filiale**: marktguru sucht für die Postleitzahlen deiner Filialen (bis zu 4),
  Angebote zeigen, für welche Filiale sie gelten.
- **Hauptladen + Ausnahmen**: Die Einkaufsliste kommt komplett in den Hauptladen – nur Angebote
  (ab 0,30 € Ersparnis) und Artikel, die woanders mit echtem Ladenpreis **mindestens 1,00 € oder
  20 % günstiger** sind, wandern in deine anderen Läden. Schwellen, „Extra-Laden lohnt sich ab“ und
  der Modus (Aus · Alles im Hauptladen · Hauptladen + Ausnahmen) sind einstellbar.
- **Einkaufsliste nach Laden**: Umschalter „Nach Laden | Nach Abteilung“, je Laden offene
  Artikel, Zwischensumme und Ersparnis; der Teilen-Text ist nach Laden gruppiert. In der To-do-
  Liste steht der Laden in der Beschreibung („🏪 Aldi Süd · …“).
- **Ladenwahl je Artikel** (⇄): Preise aller Läden ansehen, Laden von Hand wählen, „Automatisch“
  oder **„immer hier kaufen“**; die Wahl bleibt beim Neuerstellen der Liste erhalten.
  „🔄 Läden neu zuordnen“ verteilt alle offenen Artikel neu.
- **Preisliste je Laden**: Richtwert und die Preise von Aldi, Lidl, REWE … nebeneinander, der
  günstigste ist markiert, jede Zelle lässt sich bearbeiten. Reihenfolge je Laden: eigener
  Ladenpreis → gelernter Ladenpreis → eigener allgemeiner Preis → gelernter allgemeiner Preis →
  Richtwert.
- **Gelernte Normalpreise aus Prospekten**: Aus den Angeboten („statt 2,49 €“) lernt der
  Essensplaner den Normalpreis **je Laden**, mit **Verlauf** (bis zu 12 Einträge) und
  Plausibilitätsprüfung; gelernte Preise gelten 180 Tage.
- **REWE-Onlinepreise (experimentell, standardmäßig aus)**: Normalpreise aus dem REWE-Onlineshop
  für deine REWE-Filiale (Markt-ID über „Markt suchen“), wöchentlich. Lehnt REWE automatische
  Abfragen ab, wird 7 Tage pausiert – gelernte Preise bleiben.
- **Artikelsuche im Feld „Artikel hinzufügen“**: Beim Tippen erscheinen passende Artikel deines
  Hauptladens mit Preis, Packung und 🏷️ Angebot (aus Preisliste, Richtwerten, Angeboten und
  zuletzt gekauften Artikeln, optional live) – antippen fügt den Artikel mit Preis und Laden
  hinzu, Enter wie bisher.
- **Neue Jarvis-Befehle** (auch als LLM-Tools):
  - „Was muss ich bei Aldi kaufen?“ · „Was kaufe ich bei Lidl?“ · „Was steht für REWE auf der
    Einkaufsliste?“ → „Bei Aldi Süd kaufst du 3 Artikel für ungefähr 7,47 €: …“
  - „Wo ist Butter am günstigsten?“ · „Vergleiche die Preise für Hackfleisch.“ → „Am günstigsten
    gibt es Butter bei Lidl: 1,59 € (250 g).“ (`essensplaner_compare_prices`)
  - „Kauf die Butter bei REWE.“ · „Milch kaufe ich immer bei Lidl.“
    (`essensplaner_set_shopping_store`)
  - „Setz Butter auf die Einkaufsliste.“ · „Füge Kaffee zur Einkaufsliste hinzu.“ → mit Preis und
    Laden (`essensplaner_add_shopping_item`)
- **Neue Sensoren**: `sensor.essensplaner_shopping_stores` (Läden mit offenen Artikeln, je Laden
  Artikel, Zwischensumme und Ersparnis) und `sensor.essensplaner_shopping_total` (geschätzte
  Summe der Einkaufsliste in €).
- **Neue Aktionen**: `find_branches`, `save_branch`, `remove_branch`, `get_branches`,
  `set_shopping_store`, `assign_shopping_stores`, `compare_prices`, `get_store_prices`,
  `refresh_prices`, `find_rewe_markets`, `add_shopping_item`. Erweitert: `set_price` (Preis je
  Laden), `get_shopping_list` (Laden), `generate_shopping_list` (Antwort mit Läden),
  `refresh_offers`/`search_offers` (Postleitzahlen der Filialen).
- **Optionen, neuer Schritt „Läden & Einkauf“**: Modus und Schwellen der Aufteilung, Zonen,
  Umkreis und Arbeitsweg für die Filialsuche, REWE-Onlinepreise an/aus.

### Verbessert
- Von Hand hinzugefügte Artikel bekommen einen Preis (Hauptladen bzw. gewählter Laden); wird der
  Text eines Eintrags geändert, werden Menge und Preis neu berechnet.
- Packungsgrößen von Angeboten werden aus dem Grundpreis abgeleitet (statt pauschal 1 kg).
- Diagnose-Daten schwärzen Koordinaten, Straßen, Bezeichnungen, Entfernungen, Filial- und
  Markt-IDs.
- Schneller bei vielen Angeboten und Rezepten.
- Panel auf Handy und Tablet: alle Knöpfe und Felder sind mindestens 40 px hoch; farbige Hinweise
  (Angebot, gespart, Fehler) sind im hellen und dunklen Design besser lesbar.
- Nach einem Update ohne Neustart zeigt das Panel „bitte Home Assistant neu starten“ statt eines
  unverständlichen Fehlers.

### Behoben
- Selbst eingetragene Angebote konnten dieselbe ID bekommen (Löschen entfernte dann zwei).
- Die Option „Einkaufsliste kopieren nach“ lässt sich wieder leeren.
- **Frische und gehackte Tomaten** werden nicht mehr verwechselt: Frische Tomaten wurden mit dem
  Preis gehackter Tomaten (Dose) gerechnet, beide landeten als ein Eintrag auf der Einkaufsliste
  und ein Prospektpreis für frische Tomaten galt auch für Dosentomaten.

### Datenschutz
- Alles bleibt lokal, solange du keine Online-Funktion nutzt.
- **OpenStreetMap** (`overpass-api.de`): nur wenn du die Filialsuche startest; gesendet werden die
  auf ca. 100 m gerundeten Koordinaten deiner Zonen. Ergebnisse werden 30 Tage gespeichert,
  höchstens eine Suche alle 2 Minuten. Daten © OpenStreetMap-Mitwirkende (ODbL).
- **marktguru.de** (wie bisher, nur wenn eingeschaltet): Postleitzahlen deiner Filialen bzw. aus
  den Optionen und Suchbegriffe.
- **REWE** (nur wenn eingeschaltet): Markt-ID und Suchbegriffe an `shop.rewe.de`; „Markt suchen“
  sendet die Postleitzahl an `www.rewe.de`.

### Upgrade-Hinweise
- Die Daten werden beim ersten Start **automatisch übernommen**: eigene Preise mit Laden landen
  zusätzlich in der Preisliste dieses Ladens, Angebote bekommen ihren Laden. Filialen werden
  nicht automatisch angelegt – bis du welche speicherst, gelten wie bisher Postleitzahl und
  Supermärkte aus den Optionen, und die Einkaufsliste bleibt eine Liste wie in 1.2.
- Nach dem Update Home Assistant neu starten und den Browser einmal neu laden (Strg+F5 bzw.
  App-Cache leeren). Für den eingebauten Sprachagenten ohne LLM die Datei
  `custom_sentences/de/essensplaner.yaml` erneut nach `/config/custom_sentences/de/` kopieren.
- **Zurück auf 1.2** geht, aber Filialen, Ladenpreise und Preisverlauf gehen dabei verloren –
  vorher ein Backup machen.

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
