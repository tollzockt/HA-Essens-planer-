# Changelog

## 1.4.0

Preise und Angebote direkt von den Ketten, alle Angebote deiner Läden, Kassenzettel als echte
Ladenpreise, Drogerien als Läden – und alle Einstellungen im Panel. Deine Daten und
Einstellungen bleiben erhalten; alle neuen Online-Quellen sind aus, bis du sie einschaltest.
Wer den eingebauten Sprachagenten nutzt, kopiert `custom_sentences/de/essensplaner.yaml` erneut
(neue Ketten). HACS-Release: `v1.4.0`.

### Einstellungen im Panel
- **⚙️ oben rechts im Panel** öffnet alle Einstellungen (am Handy als ganze Seite, am PC als
  großes Fenster): Allgemein, Budget & Planung, Angebote & Preisquellen, Läden & Einkauf und
  Kassenzettel, jedes Feld mit kurzer Erklärung. Geprüft wird wie bisher (Bereiche, mindestens
  eine Mahlzeit, marktguru braucht eine Postleitzahl oder Läden mit Postleitzahl); Fehler
  stehen direkt am Feld, gespeichert werden nur geänderte Werte. Danach lädt der Essensplaner
  neu, das Panel verbindet sich von selbst wieder. Nur für Administratoren. Neue Websockets
  `essensplaner/get_settings` und `essensplaner/save_settings`.
- **„Konfigurieren“ unter Einstellungen → Geräte & Dienste** hat nur noch einen Schalter:
  „Panel in der Seitenleiste anzeigen“ – damit kommst du immer wieder an die Einstellungen.
  Alle anderen Werte bleiben beim Speichern dort unverändert. Die Einrichtung
  (Beispielrezepte, Portionen) ist gleich geblieben.
- Die neuen Quellen (EDEKA-Angebote, ALDI-SÜD-Preise, KI-Aufgabe für Kassenzettel) gibt es nur
  in den Einstellungen des Panels, ebenso REWE-Onlinepreise und marktguru (mit dem
  AGB-Hinweis direkt am Schalter). Für neue Installationen ist alles aus.
- Fehlermeldungen, Sprachantworten und Hinweise im Panel verweisen auf die Einstellungen im
  Panel statt auf „Konfigurieren“; Hinweise wie „Einschalten: ⚙️ Angebote & Preisquellen“
  öffnen den passenden Bereich.

### Drogerien als Läden
- **Rossmann, dm, Müller und Budni** gibt es als Ketten: in der Filialsuche (OpenStreetMap,
  Drogerien sind dort `shop=chemist`), beim Speichern von Hand, in den Einstellungen, per Sprache
  („Was kaufe ich bei Rossmann?“, „Was kaufe ich in der Drogerie?“, „Was hat Rossmann im
  Angebot?“) und bei Angeboten. Ein „Müller“-Leuchtengeschäft oder -Optiker wird nicht als
  Drogerie erkannt.
- Neue Abteilungen **„Drogerie & Körperpflege“** und **„Haushalt & Reinigung“** mit gut 30
  Richtwerten (Zahnpasta, Duschgel, Waschmittel in Waschladungen, Toilettenpapier in Rollen …).
  „Crème fraîche“ bleibt ein Milchprodukt.
- Bei „Hauptladen + Ausnahmen“ kommen diese Artikel in deine Drogerie; Lebensmittel nur für
  ein echtes Angebot. Eine Drogerie wird nie automatisch Hauptladen, Drogerie-Angebote
  („Babyöl“) zählen nie für Lebensmittel.
- Eine Drogerie, die in 1.3 als andere Kette gespeichert wurde (z. B. „ROSSMANN
  Drogeriemarkt“ als Marktkauf), wird beim Update auf die richtige Kette umgestellt; die
  Prospektpreise, die 1.3 dafür von Marktkauf gelernt hatte, werden verworfen (keine
  „Marktkauf“-Spalte in der Preisliste). Offene Artikel aus 1.3 wie „Toilettenpapier“ oder
  „Zahnpasta“ bekommen ihre neue Abteilung (und kommen in die Drogerie), Rezeptzeilen wie
  „1 Rolle Blätterteig“ die neue Einheit Rolle.

### Preise und Angebote direkt von den Ketten
- **ALDI-SÜD-Onlinepreise** (experimentell, Einstellung „ALDI-SÜD-Preise“ unter ⚙️ →
  Angebote & Preisquellen, standardmäßig aus): einmal pro Woche Normalpreise von der
  ALDI-SÜD-Website für deine ALDI-SÜD-Filiale (die nächste ALDI-Filiale wird über die Lage
  deiner Filiale – auf ca. 100 m gerundet – bzw. von Zuhause – auf ca. 1 km gerundet –
  bestimmt; „🔗 ALDI-Filiale verknüpfen“ / `find_aldi_stores`). Reduzierte Artikel: der Streichpreis wird als Normalpreis
  gelernt, der reduzierte Preis ist bis Samstag ein Angebot. Auch „Artikel hinzufügen“ sucht
  bei ALDI SÜD live. Die ALDI-SÜD-Wochenangebote („Wochenangebote“) sind abrufbar und kommen in
  die Angebotsübersicht.
- **EDEKA-Angebote deines Markts** (Einstellung „EDEKA-Angebote“ unter ⚙️ → Angebote &
  Preisquellen, standardmäßig aus): täglich die Prospekt-Angebote deines EDEKA-Markts von
  edeka.de – mit Packung, Grundpreis, Gültigkeit, PAYBACK-/App-Hinweis und Pfand als Hinweis.
  Passende Angebote zählen für Planung, Budget und Einkaufsliste dieser Filiale. Markt
  verknüpfen: „🔎 EDEKA-Markt suchen“ / `find_edeka_markets`, dann `save_branch` mit
  `edeka_market_id` – die Angebote werden etwa eine Minute danach geladen.
- Die Angebotsbilder lädt dein Browser von `offer-images.api.edeka` (EDEKA) bzw.
  `dm.emea.cms.aldi.cx` (ALDI SÜD), wie bisher die marktguru-Bilder von `cdn.marktguru.de`.
- `refresh_prices` kennt die Quellen `aldi` und `edeka`; neue Aktionen `find_aldi_stores` und
  `find_edeka_markets`. Beide Ketten pausieren 7 Tage, wenn sie automatische Abfragen ablehnen;
  es wird nichts umgangen.
- **REWE-Onlinepreise:** ist ein gesuchter Artikel gerade reduziert, wird der Streichpreis
  als Normalpreis gelernt und der reduzierte Preis ist bis Samstag ein Angebot deiner
  REWE-Filiale (auch unter „Alle Angebote meiner Läden“ und in der Preisliste). Eine
  öffentliche Liste aller Angebote eines REWE-Markts gibt es nicht (Bot-Prüfung) – die
  übrigen REWE-Angebote kommen weiter über marktguru oder von dir.

### Alle Angebote deiner Läden (Angebotskatalog)
- Der Essensplaner kennt jetzt **alle aktuellen und kommenden Angebote deiner gespeicherten
  Läden**, nicht nur die zu deinen Rezepten: EDEKA (dein Markt) und ALDI SÜD
  (Wochenangebote) direkt von den Ketten, die übrigen Ketten über marktguru – nur wenn du
  marktguru eingeschaltet hast. Ketten, für die marktguru nur Prospektbilder hat (oft NORMA
  oder EDEKA), bekommen die Prospektseiten als Bilder mit Link zum Prospekt.
- **Viel weniger Abfragen bei marktguru:** statt einer Suche je Zutat (bis zu ~90 am Tag) wird
  je Kette und Postleitzahl der ganze Prospekt geladen – für sechs Läden etwa 10–15 Anfragen,
  alle 3 Tage und zum neuen Prospekt (Samstag, Sonntag und Montag je einmal – REWE und Netto
  veröffentlichen die neue Woche erst am Sonntag). Ein fehlgeschlagener Abruf wird beim
  nächsten Tagesabruf wiederholt, nicht im Minutentakt. Der Abgleich mit Rezepten,
  Merkliste, Einkaufsliste und Preisliste passiert lokal – auch für das, was du nach dem
  Abruf auf die Einkaufsliste setzt, planst oder als Preis einträgst (etwa eine halbe Minute
  später, ohne neue Anfrage; ebenso beim täglichen Check und mit „Angebote aktualisieren“
  in der Sperrstunde: „Angebote neu abgeglichen“). „Angebote aktualisieren“ fragt
  höchstens einmal pro Stunde (außer deine Läden haben sich geändert). Lehnt marktguru ab,
  wird 7 Tage pausiert – auch die Live-Suche und „Artikel hinzufügen“. Schaltest du marktguru
  aus, verschwinden seine Angebote sofort.
- Angebote werden nach dem Produkt selbst zugeordnet, nicht nach Sorte oder Füllung:
  „Skyr Drink Erdbeere“ ist kein Erdbeer-Angebot, ALDIs „Apfelmus 360 g, Apfel“ kein Apfel,
  „Granatapfel“ kein Apfel, „Kräuterbutter“ keine Butter, „Kaffeemilch“ und „Buttermilch“
  keine Milch, „Geschirrreiniger“ kein WC-Reiniger; Sorten nach dem Komma sind keine eigenen
  Produkte („Buitoni Pizza, Salami oder Schinken“ ist Pizza, „Knorr Fix, Spaghetti
  Bolognese oder Lasagne“ keine Spaghetti), eine Liste von Produkten schon („Tomaten,
  Gurken oder Paprika“); gelernte Normalpreise
  stammen nur von Angeboten des Produkts selbst. Lebensmittel bei Drogerien (Kaffee, Riegel,
  Haferdrink) erscheinen unter „Lebensmittel“.
- „TK-Erbsen“, „TK-Spinat“ & Co. bekommen ihre Angebote auch, wenn „tiefgefroren“ nur in der
  Beschreibung steht (EDEKA, marktguru). Aufzählungen wie „iglo Rahm-, Würz- oder
  Blatt-Spinat“, „Birkel’s No. 1, 7-Hühnchen oder 3 Glocken Nudeln“, „Joghurt oder Pudding“
  und gefüllte Nudeln („Gefüllte Kartoffel Gnocchi“) behalten ihre Zutat. Die EDEKA-Angebote
  für Rezepte und Einkaufsliste werden genauso zugeordnet wie in der Gesamtübersicht
  („Granatäpfel“, „Ingwer Shot“, „Kondensmilch“ zählen nicht als Äpfel, Ingwer, Milch).
- Selbst eingetragene Angebote (z. B. aus dem NORMA-Prospekt) und die reduzierten Artikel von
  ALDI SÜD und REWE stehen auch unter „Alle Angebote meiner Läden“ bei ihrem Laden und in der
  Preisliste; ein mit „📌 Merken“ übernommenes Angebot erscheint dort nur einmal. Die
  Prospektseiten eines Ladens bleiben dabei sichtbar, damit du das nächste Angebot eintragen
  kannst. Ein Angebot „Butter 250 g“ gilt für Butter (250 g), nicht für eine eigene Zeile.
- **Normalpreise aus dem ganzen Prospekt:** Streichpreise, Lidls „Normalpreis: 1.35“ und die
  Streichpreise von ALDI SÜD werden für alle Artikel der Preisliste gelernt (mit
  Plausibilitätsprüfung), nicht nur für gesuchte Zutaten.
- App-Preise („mit Lidl Plus App 1,59 €“, Rossmann-Coupons, Preise nur mit App), REWE-Bonus
  und „nur online“ werden erkannt und als Hinweis gezeigt; nur-online-Angebote zählen nicht
  für Planung und Preise. Jedes Angebot hat eine Art (Lebensmittel, Getränk, Drogerie,
  Haushalt, Non-Food).
- **Preisliste:** in jeder Zelle steht zusätzlich das aktuelle Angebot dieses Ladens (nur
  Anzeige, es wird nie als Normalpreis gespeichert); jeder gespeicherte Laden ist eine
  Spalte – auch Drogerien ohne Preise.
- Ein Angebot aus der Gesamtübersicht kann direkt auf die Einkaufsliste (mit Laden, Preis und
  Packung des Angebots).
- Die Live-Suche fragt marktguru nur noch nach deinen Ketten.
- Für die Angebotsseite: neuer Websocket `essensplaner/store_offers` (Filter nach Laden,
  aktuell/kommend, Lebensmittel/Drogerie/Haushalt, Suche, „nur meine Zutaten“, Sortierung,
  Seiten). Der Katalog liegt in einer eigenen Datei (`.storage/essensplaner.catalog.<id>`)
  und wird mit der Integration gelöscht; in den Diagnose-Daten stehen nur Anzahlen.
- **marktguru nur auf eigenes Risiko:** die AGB von marktguru (Stand Februar 2026) untersagen
  das automatische Auslesen und erlauben nur die private Nutzung. Das steht jetzt deutlich
  am Schalter in den Einstellungen, in der Preisquellen-Karte und im README; marktguru ist
  nur noch eine Ergänzung zu den direkten Quellen der Ketten. Neue Installationen: aus. Wer
  marktguru schon nutzt, behält seine Einstellung.

### Kassenzettel
- **Kassenzettel speichern und die echten Preise übernehmen** (statt geschätzter Preise):
  eingefügten Text liest der Essensplaner lokal (REWE, EDEKA, Lidl, ALDI, Netto, Norma,
  Penny, Kaufland, Rossmann, dm – Mengen-, Gewichts-, Pfand-, Rabatt- und Stornozeilen),
  Fotos und PDFs optional eine **KI-Aufgabe** (AI Task) – neue Option „KI-Aufgabe für
  Kassenzettel-Fotos“, standardmäßig keine. Der KI wird nur das Bild geschickt.
- Laden und Filiale kommen aus dem Kopf des Kassenzettels (Kette, Postleitzahl, Straße),
  Abkürzungen wie „H-MILCH 1,5%“, „HACKFL.GEM.“, „BIO EIER 10ER“, „EIER BOD.10ER M“ oder
  „PASS.TOMATEN“ werden den Artikeln zugeordnet, die Packung aus der Zeile oder dem
  Ladenpreis. Unbekanntes ordnest du zu oder ignorierst es; die Zuordnung wird für die
  nächsten Kassenzettel gemerkt. Auch Text aus der Text-Erkennung am Handy, die Name und Preis
  trennt (abwechselnd oder als zwei Spalten), wird gelesen.
- Nach dem Prüfen werden die Preise **eigene Preise des Ladens** (Quelle „Kassenzettel“
  mit Datum und Verlauf, in der Preisliste „🧾 Kassenzettel 07.11.“). Ein neuerer
  Kassenzettel ersetzt einen älteren Preis, ein später eingetippter Preis bleibt. Ein
  Angebotspreis des Ladens an diesem Tag (gleiche Zutat, auf den Cent derselbe Preis und –
  wenn beide sie nennen – dieselbe Marke) wird nicht zum Normalpreis (nur Verlauf); mit
  `regular` („trotzdem als Normalpreis“) doch. „Mit Preisen löschen“ stellt den Preis davor
  wieder her (eingetippt oder älterer Kassenzettel), ebenso erneutes Speichern, wenn eine
  Zeile inzwischen als Angebot bekannt ist. Eindeutig abgekürzte Wörter („WEIZENM.“,
  „MARGAR.“, „CHAMPIGN.“, „SONNENBL.OEL“) werden zugeordnet, kurze Abkürzungen nur
  vorgeschlagen – ebenso Wörter, die der Essensplaner nur als Nebennamen eines Richtwerts
  kennt („BUTTERSCHM.“ ist Butterschmalz, keine Butter; „RAEUCHERL.“ kein Lachsfilet).
- Neue Aktionen `receipt_parse_text`, `receipt_scan`, `receipt_save`, `get_receipts` und
  `delete_receipt`; für das Panel die Websockets `essensplaner/receipts`, `receipt_parse`,
  `receipt_save`, `receipt_delete` und der Foto-Upload `/api/essensplaner/receipt_upload`
  (alles nur für Administratoren, höchstens 10 MB, JPG/PNG/WebP/PDF). Bis zu 200
  Kassenzettel in `.storage/essensplaner.receipts.<id>`, Fotos in
  `.storage/essensplaner_receipts/` – nicht im Medienordner, den jeder Benutzer durchsuchen
  kann; die KI-Aufgabe bekommt sie über eine eigene Medienquelle, die nichts auflistet.
  Beides wird mit der Integration gelöscht (andere Dateien nicht).

### Panel
- **Angebote:** Umschalter „🍽️ Für meine Rezepte“ (wie bisher) und „🏪 Alle Angebote meiner
  Läden“: Läden als Chips (mehrere wählbar, wird gemerkt), Aktuell / Ab nächster Woche / Alle,
  Lebensmittel / Drogerie & Haushalt / Alles, Suche, Sortierung (Ersparnis, Preis, Grundpreis,
  Name, Laden), Karten mit Bild, Marke, Packung, Streich- bzw. Normalpreis, App-Preis,
  PAYBACK, „nur online“, Grundpreis und Gültigkeit („ab Mo 09.11.“, „bis Sa“), „➕ Auf die
  Einkaufsliste“ (in diesen Laden) und „📌 Merken“, 60 Angebote je Seite. Läden mit nur
  Prospektbildern (z. B. NORMA) zeigen vier Seiten, „Prospekt öffnen ↗“ und „Angebot aus
  Prospekt eintragen“. Je Laden steht die Quelle (EDEKA direkt, ALDI SÜD direkt, marktguru
  inoffiziell); ist keine eingeschaltet, sagt die Seite, welche.
- **Läden & Preise:** „EDEKA-Markt suchen“ und „ALDI-Filiale verknüpfen“ an der Filiale,
  Drogerien mit 🧴-Kennzeichen, Preisquellen REWE, ALDI SÜD, EDEKA und marktguru (mit dem
  AGB-Hinweis) samt „Preise/Angebote aktualisieren“. Die Preisliste zeigt das aktuelle
  Angebot unter dem Preis („🏷️ 1,19 € bis Sa“, ohne Normalpreis „kein Normalpreis bekannt“)
  und lässt sich auf Lebensmittel bzw. Drogerie & Haushalt einschränken.
- **Kassenzettel:** neuer Bereich in „Läden & Preise“ und Knopf „🧾 Kassenzettel“ in der
  Einkaufsliste: Foto aufnehmen bzw. Foto/PDF wählen (große Fotos werden vor dem Hochladen
  verkleinert), „🤖 Mit KI auslesen“ oder Text einfügen, Prüfen mit Artikel-Auswahl,
  „ignorieren“, Packung, Preis, Laden, Datum und Summenprüfung, dann „Preise übernehmen“;
  Liste der gespeicherten Kassenzettel mit Bild, Ansicht und Löschen (mit oder ohne Preise).
- `essensplaner/store_offers` kennt die Art `nonfood` (Drogerie und Haushalt zusammen).

### Korrekturen
- Alle Abfragen senden die ehrliche Kennung `HA-Essensplaner/1.4` (marktguru und der
  Rezept-Import gaben sich bisher als Browser aus).
- marktguru-Angebote beginnen und enden am richtigen Tag (die Zeitstempel sind UTC: ein
  Angebot „ab Montag“ begann bisher schon am Sonntag); der Platzhalter „thisisnobrand123“
  erscheint nicht mehr als Marke. Angebotsbilder kommen von `cdn.marktguru.de`.
- Mehrfachpackungen in Litern („12 x 1 Liter“) werden als 12 l erkannt.
- Öffnest du das Panel nach dem Update, bevor Home Assistant neu gestartet ist, zeigt es
  „bitte neu starten“, statt die neuen Bereiche immer wieder abzufragen.
- Alle Textfelder der Aktionen haben ein Beispiel in den Entwicklerwerkzeugen.
- Verknüpft der Essensplaner die ALDI-SÜD-Filiale selbst, startet das keinen zweiten
  vollständigen Angebotsabruf (marktguru wird nicht doppelt gefragt).
- Markennamen als Artikel („Persil“, „Zewa“, „Somat“, „Tempo“, „Elmex“, „Nivea“ …) kommen in
  die Abteilungen Haushalt bzw. Drogerie – und damit bei „Hauptladen + Ausnahmen“ in die
  Drogerie („Froschschenkel“ bleibt ein Lebensmittel).

### Jarvis
- „Wo ist Butter am günstigsten?“ nennt nur echte Preise der Läden (eigene, Kassenzettel,
  gelernte, Angebote) – nie einen Richtwert als Ladenpreis oder als günstigsten. Kennt er
  nur einen Preis: „Ich kenne nur den Preis bei REWE: 2,29 €“, keinen: „Für Butter kenne ich
  noch keinen Ladenpreis (Richtwert 1,99 € für 250 g)“. `compare_prices` sortiert die Läden
  ohne eigenen Preis ans Ende, `cheapest` gilt nur unter echten Preisen, neu sind `estimate`
  und `tied`. Ein Angebot des Ladens zählt auch, wenn es teurer als der Richtwert ist (im
  Sprachvergleich und in der Laden-Auswahl ⇄). Kosten mehrere Läden gleich wenig, nennt er nur
  diese („Butter gibt es bei REWE und bei Lidl für 1,99 €. Bei Netto 2,49 €.“) – „überall“
  nur, wenn wirklich jeder Laden diesen Preis hat.
- Produktfragen zu Angeboten („Wo ist Kaffee im Angebot?“) suchen das Produkt selbst – keine
  Kaffeemaschine, kein Granatapfel für „Äpfel“, keine Butter-Spekulatius für „Butter“. Die
  Suche im Panel findet weiter jeden Text.
- „Was hat Norma im Angebot?“ sagt, wenn es für den Laden nur den Prospekt als Bilder gibt,
  wo er im Panel steht; bei EDEKA zusätzlich, dass die Einstellung „EDEKA-Angebote“ die
  einzelnen Angebote bringt.
- Neues Tool `essensplaner_set_price`: „Butter kostet bei Netto 1,79 Euro“ speichert den
  Normalpreis des Ladens (bleibt, mit der üblichen Packung; „Butter 250 g“ ist Butter in
  250 g); `essensplaner_add_offer` ist ausdrücklich für befristete Angebote. Mit den deutschen
  Sätzen auch für den eingebauten Sprachagenten (Datei erneut kopieren): der Preis endet mit
  „Euro“, „€“ oder „Cent“ („1 Euro 79“ geht auch), eine bloße Zahl nur nach „Merk dir“.
  Fragen wie „Was kostet bei Lidl 1 kg Hackfleisch?“ speichern nie einen Preis – mit „lokale
  Verarbeitung bevorzugen“ beantwortet sie der Gesprächsagent.

## 1.3.2

Die Preisquellen funktionieren wieder – deine Daten bleiben erhalten, es gibt keine neuen Optionen.

### REWE-Onlinepreise (experimentell)
- REWE hat seinen Onlineshop umgebaut: Preise kommen jetzt von `www.rewe.de/shop` und nur, wenn
  neben der Markt-ID der **Abholservice** mitgeschickt wird – ohne ihn lieferte REWE keine
  Treffer. Getestet mit echten Märkten (z. B. Butter, Milch, Eier, Hackfleisch, Spaghetti).
- **„Markt suchen“** nutzt die neue REWE-Marktsuche (die alte Adresse gibt es nicht mehr), zur
  Not die Liste der Abholmärkte.
- Eine **Pause aus 1.3.0/1.3.1** („Unerwartete Antwort … nächster Versuch ab …“) zählt nicht mehr:
  die Preise werden etwa 2½ Minuten nach dem Neustart abgerufen (danach wie bisher höchstens
  einmal pro Woche) – oder sofort mit „🔄 Preise aktualisieren“.
- Liefert ein Markt gar keine Artikel (falsche Markt-ID), heißt es jetzt klar „Der REWE-Markt …
  liefert keine Artikel – bitte … Markt suchen“, und es wird nur einen Tag pausiert.

### Filialsuche (OpenStreetMap)
- Die Suche ist **deutlich schlanker** (eine einfache Abfrage je Gebiet, die Ketten werden in
  Home Assistant erkannt) und wird vom öffentlichen Server auch zu Stoßzeiten angenommen.
- Ist der Server ausgelastet („at capacity“, 429/502/503/504, Verbindungsabbruch), wird nach
  5 und 15 Sekunden erneut gefragt, zuletzt ein Ersatzserver; jede Anfrage darf bis zu
  90 Sekunden dauern (vorher 40) – die Suche kann daher 1–3 Minuten brauchen.

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
