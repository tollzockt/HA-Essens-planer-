/*
 * Essensplaner – sidebar panel for Home Assistant.
 * Plain web component (no build step, no external dependencies).
 */

import {
  CATEGORY_ICONS,
  CATEGORY_ORDER,
  DOMAIN,
  MEAL_STYLE,
  MONTHS,
  WEEKDAYS,
  addDays,
  beep,
  dishEmoji,
  esc,
  eur,
  shortDate,
  findTimers,
  fold,
  formatClock,
  fromIso,
  greeting,
  isoWeek,
  mondayOf,
  relativeDay,
  stars,
  toIso,
  upcomingMeal,
  weekdayIndex,
} from "./essensplaner-common.js";

const SORTS = {
  fav: "Favoriten zuerst",
  name: "A – Z",
  recent: "Zuletzt gekocht",
  often: "Am häufigsten gekocht",
  quick: "Schnellste zuerst",
  rating: "Beste Bewertung",
  new: "Neueste zuerst",
  cheap: "Günstigste zuerst",
};
const STRATEGY_LABELS = {
  balanced: ["⚖️ Ausgewogen", "Abwechslung, Favoriten, Budget und Angebote im Mix"],
  cheap: ["💶 Günstig", "möglichst preiswert, passend zum Wochenbudget"],
  offers: ["🏷️ Angebote nutzen", "Rezepte mit aktuellen Angeboten bevorzugen"],
  variety: ["🌈 Abwechslung", "möglichst verschiedene Gerichte und Zutaten"],
  seasonal: ["🍂 Saisonal", "was gerade Saison hat – Gemüse, Obst, Feste – und Angebote"],
};

/* Stores & prices (1.3). Helpers live here (not in common.js) so a cached old common.js
 * can never break the panel after an update. */
const RETAILER_STYLE = {
  "aldi-sued": ["#1c3f94", "AS"],
  "aldi-nord": ["#00a0e2", "AN"],
  lidl: ["#0050aa", "L"],
  rewe: ["#cc071e", "R"],
  edeka: ["#f2b705", "E"],
  penny: ["#cd1414", "P"],
  "netto-marken-discount": ["#ffd400", "N"],
  kaufland: ["#e10915", "K"],
  norma: ["#d6001c", "No"],
  globus: ["#00664f", "G"],
  marktkauf: ["#00519e", "M"],
  rossmann: ["#c8102e", "R"],
  "dm-drogerie-markt": ["#002e6e", "dm"],
  "mueller-drogeriemarkt": ["#f39200", "M"],
  budnikowsky: ["#e2001a", "B"],
};
const LIGHT_RETAILERS = new Set(["edeka", "netto-marken-discount"]);
const PRICE_SOURCE = {
  user: "✏️ eigener Preis",
  receipt: "🧾 Kassenzettel",
  leaflet: "📰 Prospekt",
  offer_regular: "📰 Prospekt",
  rewe_online: "🛒 REWE online",
  aldi_online: "🛒 ALDI SÜD online",
  offer: "🏷️ Angebot",
  default: "Richtwert",
};
// live article hits that are shop prices, not leaflet offers
const SHOP_PROVIDERS = { rewe_online: "🛒 REWE online", aldi_online: "🛒 ALDI SÜD online" };
// a branch linked to its store on the chain's own web site (REWE / ALDI SÜD prices, EDEKA
// offers); the data-action names "rewe-…" come from 1.3, where only REWE had one
const STORE_LINKS = {
  rewe: { field: "rewe_market_id", ws: "rewe_markets", list: "markets", source: "rewe", title: "🛒 REWE-Markt-ID", name: "REWE", placeholder: "z. B. 1940178", mode: "numeric", search: "🔎 Markt suchen", none: "Keine REWE-Märkte für PLZ", saved: "🛒 REWE-Markt", removed: "REWE-Markt-ID entfernt", unlink: "Dann gibt es dort keine REWE-Onlinepreise und keine Online-Suche mehr." },
  edeka: { field: "edeka_market_id", ws: "edeka_markets", list: "markets", source: "edeka", title: "🏷️ EDEKA-Markt-ID", name: "EDEKA", placeholder: "z. B. 2600001", mode: "numeric", search: "🔎 EDEKA-Markt suchen", none: "Keine EDEKA-Märkte für PLZ", saved: "🏷️ EDEKA-Markt", removed: "EDEKA-Markt-ID entfernt", unlink: "Dann gibt es dort keine EDEKA-Angebote mehr." },
  "aldi-sued": { field: "aldi_service_point", ws: "aldi_stores", list: "stores", source: "aldi", title: "🛒 ALDI-SÜD-Filiale", name: "ALDI SÜD", placeholder: "z. B. B402", mode: "text", search: "🔗 ALDI-Filiale verknüpfen", none: "Keine ALDI-SÜD-Filialen gefunden", saved: "🛒 ALDI-SÜD-Filiale", removed: "ALDI-SÜD-Filiale entfernt – die nächste wird automatisch bestimmt", unlink: "Dann wird beim nächsten Abruf die nächste Filiale automatisch bestimmt." },
};
const ARTICLE_SOURCE = {
  offer: "🏷️ Angebot",
  store: "✏️ eigener Preis",
  learned: "📰 gelernter Preis",
  default: "Richtwert",
  history: "🕘 schon mal gekauft",
};
// article hits whose price/pack is the store's own (sent with the article); estimates and
// old articles are priced by the list at the store the item ends up at
const STORE_PRICE_HITS = new Set(["offer", "live", "store", "learned"]);
const REASON_CHIP = {
  offer: ["🏷️ Angebot", "offer", "Hier im Angebot"],
  cheaper: ["💶 günstiger", "cheap", "Hier deutlich günstiger als im Hauptladen"],
  manual: ["📌 manuell", "", "Von dir hier einsortiert"],
  preferred: ["⭐ immer hier", "", "Kaufst du immer in diesem Laden"],
  favorite: ["⭐ Lieblingsprodukt", "", "Dein Lieblingsprodukt gibt es in diesem Laden"],
  // "drugstore" (1.4: Drogerie / Haushalt at the drugstore) needs no chip: like the main
  // store's items, the store card says it
};
const PRICE_UNITS = ["g", "ml", "Stück", "kg", "l", "Bund", "Pck.", "Dose", "Kopf", "Rolle", "WL"];
// 1.4 aisles of a drugstore (a local copy: a cached old common.js must not break the panel)
const NONFOOD_AISLES = ["Drogerie & Körperpflege", "Haushalt & Reinigung"];
const RADIUS_CHOICES = [1, 2, 3, 5, 10, 15];
const STALE_CHANGES = new Set(["prices", "offers", "branches", "price_sources"]);
// leading amount of a typed article ("2 Liter Milch", "500 g Hack") – kept when a hit is added
const QTY_RE =
  /^\s*(\d+(?:[.,]\d+)?(?:\s*[x×]\s*\d+(?:[.,]\d+)?)?\s*(?:(?:kg|g|mg|ml|cl|l|liter|stück|stk|st|pck|packungen|packung|pkg|dosen|dose|bund|flaschen|flasche|becher|gläser|glas|tüten|tüte|beutel|netz|el|tl|prise|zehen|zehe|scheiben|scheibe|rollen|rolle|wl)(?![a-zäöüß])\.?)?\s+)(?=\S)/i;

const distText = (m) => {
  const n = Number(m);
  if (!Number.isFinite(n)) return "";
  return n < 1000 ? `${Math.max(10, Math.round(n / 10) * 10)} m` : `${(n / 1000).toFixed(1).replace(".", ",")} km`;
};
const unitPriceText = (price, base) => {
  if (price == null || !base) return "";
  if (base === "g") return `${eur(price * 1000)}/kg`;
  if (base === "ml") return `${eur(price * 1000)}/l`;
  return `${eur(price)}/${base}`;
};
const packText = (amount, unit) => {
  const n = Number(amount);
  if (!unit || !Number.isFinite(n) || n <= 0) return "";
  const fmt = (v) => String(Math.round(v * 100) / 100).replace(".", ",");
  if (unit === "g" && n >= 1000) return `${fmt(n / 1000)} kg`;
  if (unit === "ml" && n >= 1000) return `${fmt(n / 1000)} l`;
  if (unit === "Rolle" && n !== 1) return `${fmt(n)} Rollen`;
  return `${fmt(n)} ${unit}`;
};
const dayText = (iso) => {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
};
const timeText = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" });
};
// chain <option>s, supermarkets and drugstores (1.4: kind) in two groups
const chainOptions = (retailers, selected) => {
  const option = (r) => `<option value="${esc(r.id)}" ${r.id === selected ? "selected" : ""}>${esc(r.name)}</option>`;
  const drug = retailers.filter((r) => r.kind === "drugstore");
  if (!drug.length) return retailers.map(option).join("");
  const food = retailers.filter((r) => r.kind !== "drugstore");
  return `<optgroup label="Supermärkte">${food.map(option).join("")}</optgroup><optgroup label="Drogerien">${drug.map(option).join("")}</optgroup>`;
};
const retailerDot = (retailer, name = "") => {
  const [color, short] = RETAILER_STYLE[retailer] || ["#757575", (name || "?").slice(0, 1).toUpperCase()];
  return `<span class="rdot" style="background:${color};color:${LIGHT_RETAILERS.has(retailer) ? "#1a1a1a" : "#fff"}" aria-hidden="true">${esc(short)}</span>`;
};
const splitQuantity = (text) => {
  const value = String(text || "");
  const m = value.match(QTY_RE);
  return m ? { prefix: m[1].replace(/\s+$/, "") + " ", query: value.slice(m[0].length).trim() } : { prefix: "", query: value.trim() };
};

/** Error text for the user; a new command the running backend does not know yet means
 * the files were updated (HACS) but Home Assistant was not restarted. */
const errText = (err) =>
  err?.code === "unknown_command"
    ? "Diese Funktion ist neu – bitte Home Assistant einmal neu starten, damit das Update vollständig geladen ist."
    : err?.message || err?.code || String(err);

/* 1.4: all offers of the saved stores (Angebote tab), receipts, settings in the panel */
const OFFER_SORTS = { saving: "Ersparnis", price: "Preis", unit_price: "Grundpreis", name: "Name", store: "Laden" };
const OFFER_KINDS = [
  ["food", "🍽️ Lebensmittel"],
  ["nonfood", "🧴 Drogerie & Haushalt"],
  ["all", "Alles"],
];
const OFFER_SOURCE_LABEL = { edeka: "EDEKA direkt", aldi_weekly: "ALDI SÜD direkt", aldi_online: "ALDI SÜD direkt", marktguru: "marktguru (inoffiziell)", manual: "selbst eingetragen" };
const OFFER_PAGE = 60;
// after saving the settings: wait, then retry loading the data (the entry reloads)
// receipts loaded per request ("Mehr anzeigen" loads more) and the most the backend keeps
const RECEIPT_FETCH_STEP = 50;
const RECEIPT_FETCH_MAX = 200;
/** A receipt saved from a PDF (no <img> for it). */
const isPdfReceipt = (r) => /pdf/i.test(r?.content_type || "") || /\.pdf$/i.test(r?.image || "");
const SETTINGS_RELOAD_DELAYS = [700, 500, 700, 1000, 1500, 2000, 2000, 3000, 3000, 4000, 5000, 5000];
const MG_WARNING = "marktguru untersagt laut AGB das automatische Auslesen – Nutzung auf eigenes Risiko, nur privat.";
const RECEIPT_UPLOAD_URL = "/api/essensplaner/receipt_upload";
const RECEIPT_MAX_BYTES = 10 * 1024 * 1024;
// receipts.OFFER_TOLERANCE: a receipt line is at an offer's price only to the cent
const RECEIPT_OFFER_TOLERANCE = 0.01;
const WD_SHORT = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
const pad2 = (n) => String(n).padStart(2, "0");
/** "ab Mo 09.11." (not valid yet), "bis Sa" (this week) or "bis Sa 14.11.". */
const validText = (o, today) => {
  const day = (iso) => {
    const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
    return Number.isNaN(d.getTime()) ? null : d;
  };
  const from = o.valid_from && day(o.valid_from);
  if (from && o.valid_from.slice(0, 10) > today) return `ab ${WD_SHORT[from.getDay()]} ${pad2(from.getDate())}.${pad2(from.getMonth() + 1)}.`;
  const to = o.valid_to && day(o.valid_to);
  if (!to) return "";
  const days = Math.round((to - day(today)) / 86400000);
  if (days < 0) return "abgelaufen";
  if (days === 0) return "nur heute";
  return days < 7 ? `bis ${WD_SHORT[to.getDay()]}` : `bis ${WD_SHORT[to.getDay()]} ${pad2(to.getDate())}.${pad2(to.getMonth() + 1)}.`;
};
const num = (v) => (v == null || v === "" ? "" : String(v).replace(".", ","));
const parseNum = (v) => Number(String(v ?? "").trim().replace(/\s*€$/, "").replace(",", "."));

/* settings view (1.4): sections and a short German help per field; ranges, defaults and
 * the validation come from the backend (options_schema.py). Home Assistant's own options
 * dialog (Geräte & Dienste → Konfigurieren) only toggles the sidebar panel since 1.4. */
const SETTINGS_SECTIONS = [
  ["general", "🏠 Allgemein"],
  ["planning", "💶 Budget & Planung"],
  ["offers", "🏷️ Angebote & Preisquellen"],
  ["stores", "🏪 Läden & Einkauf"],
  ["receipts", "🧾 Kassenzettel"],
  ["ai", "🤖 KI"],
];
const SETTING_INFO = {
  default_servings: ["Portionen", "Wird beim Planen von Mahlzeiten verwendet."],
  default_meal: ["Standard-Mahlzeit", "Wird genommen, wenn keine Mahlzeit genannt wird (z. B. „Plane Lasagne für Freitag“)."],
  enabled_meals: ["Aktive Mahlzeiten", "Welche Mahlzeiten du planst (mindestens eine)."],
  time_fruehstueck: ["Frühstück", "Uhrzeit für den Kalender und „Nächste Mahlzeit“."],
  time_mittagessen: ["Mittagessen", ""],
  time_snack: ["Snack", ""],
  time_abendessen: ["Abendessen", ""],
  pantry_staples: ["Vorratszutaten", "Kommagetrennt – diese Zutaten landen nie auf der Einkaufsliste, z. B. „Salz, Pfeffer, Öl“."],
  excluded: ["Ausgeschlossene Zutaten", "Kommagetrennt – Vorschläge und automatische Planung meiden sie, z. B. „Fisch, Pilze“."],
  auto_mark_cooked: ["Automatisch als gekocht markieren", "Nach Ablauf des Tages zählen geplante Rezepte als gekocht (bessere Vorschläge)."],
  shopping_sync_entity: ["Einkaufsliste kopieren nach", "Optional: eine weitere To-do-Liste (z. B. Bring!), die die Einträge ebenfalls bekommt."],
  register_intents: ["Sprachbefehle registrieren", "Damit Assist, Jarvis und andere Sprachassistenten den Planer nutzen können."],
  show_panel: ["Panel in der Seitenleiste", "Ausgeschaltet verschwindet der Eintrag „Essensplaner“ (und damit diese Einstellungen) nach dem Speichern aus der Seitenleiste – wieder einschalten unter Einstellungen → Geräte & Dienste → Essensplaner → Konfigurieren."],
  weekly_budget: ["Wochenbudget", "Euro pro Woche fürs Essen, 0 = kein Budget.", "€"],
  plan_strategy: ["Planungsart", "Für die automatische Planung und Vorschläge."],
  season_aware: ["Saison berücksichtigen", "Vorschläge und automatische Planung bevorzugen Gerichte mit Zutaten, die gerade Saison haben (z. B. Spargel im Mai, Kürbis im Herbst), und Gerichte zur Zeit des Jahres (Advent, Grillzeit, Ostern). Die Planungsart „Saisonal“ nutzt die Saison immer."],
  occasions_in_budget: ["Anlässe im Wochenbudget", "Die Kosten von Anlässen (Filmabend, Grillen, Weihnachtsessen …) zählen zum Wochenbudget."],
  drinks_alcohol: ["Getränkevorschläge mit Alkohol", "Auch Wein, Bier, Sekt & Co. vorschlagen. Alkoholfreie Getränke sind immer dabei."],
  offers_source: ["marktguru-Angebote (inoffiziell)", "Nur eine Ergänzung zu den direkten Quellen der Ketten (EDEKA-Angebote, ALDI SÜD, REWE-Onlinepreise) – für Läden ohne eigene Angebotsquelle (Lidl, REWE, Netto, Penny, Kaufland, NORMA, Rossmann, dm …): etwa 2–3× pro Woche alle Angebote deiner Läden, außerdem Live-Suche in „Artikel hinzufügen“. Standardmäßig aus."],
  zip_code: ["Postleitzahl", "Für die Angebote in deiner Nähe. Kann leer bleiben, wenn deine Läden eine Postleitzahl haben."],
  offer_stores: ["Läden (ohne gespeicherte Filialen)", "Nur Angebote dieser Ketten. Hast du Filialen gespeichert, zählen deren Ketten."],
  offers_watchlist: ["Merkliste", "Zusätzliche Produkte, deren Angebote du sehen willst, kommagetrennt (z. B. „Kaffee, Butter“)."],
  rewe_online_prices: ["REWE-Onlinepreise", "⚠️ Experimentell: Markt-ID und Suchbegriffe gehen höchstens einmal pro Woche an www.rewe.de. Lehnt REWE ab, wird 7 Tage pausiert. Braucht eine REWE-Filiale mit Markt-ID."],
  aldi_online_prices: ["ALDI-SÜD-Preise", "⚠️ Experimentell: die Lage deiner ALDI-SÜD-Filiale und Suchbegriffe gehen höchstens einmal pro Woche an ALDI SÜD; reduzierte Artikel und Wochenangebote werden Angebote. Braucht eine ALDI-SÜD-Filiale."],
  all_leaflets: ["Prospekte aller Filialen", "Mit marktguru: die Prospekte (als Bilder) aller gespeicherten Filialen im Tab „Angebote“ – je Postleitzahl und Branche eine Anfrage, etwa zweimal pro Woche (höchstens 12 je Abruf). Ohne marktguru gibt es je Kette einen Link zu ihrer Prospektseite."],
  edeka_offers: ["EDEKA-Angebote", "Einmal am Tag die Prospekt-Angebote deines EDEKA-Markts von www.edeka.de (nur die Markt-ID wird gesendet). Inoffizielle Schnittstelle; lehnt EDEKA ab, wird 7 Tage pausiert. Braucht eine EDEKA-Filiale mit Markt-ID."],
  store_split_mode: ["Aufteilungsmodus", "Wie die Einkaufsliste auf deine Läden verteilt wird. Wirkt, sobald du einen Hauptladen hast."],
  store_split_min_saving: ["Woanders günstiger ab", "Ein Artikel wandert in einen anderen Laden, wenn er dort mindestens so viel günstiger ist.", "€"],
  store_split_min_percent: ["… oder günstiger ab", "… oder mindestens so viel Prozent günstiger (eine Bedingung reicht).", "%"],
  store_split_offer_min: ["Angebot lohnt sich ab", "Ein Angebot in einem anderen Laden zählt ab dieser Ersparnis.", "€"],
  store_split_trip_min: ["Extra-Laden lohnt sich ab", "Spart ein zusätzlicher Laden insgesamt weniger, kommt alles zurück in den Hauptladen. 0 = aus.", "€"],
  branch_zones: ["Zonen für die Filialsuche", "Um diese Zonen sucht „In der Nähe suchen“. Keine gewählt = automatisch: Zuhause und Zonen mit „Arbeit“/„Work“ im Namen."],
  branch_radius_km: ["Umkreis", "Suchradius um jede Zone.", "km"],
  branch_route: ["Arbeitsweg einbeziehen", "Auch Läden entlang der Strecke von Zuhause zu den anderen Zonen finden."],
  branch_route_radius_m: ["Korridor am Arbeitsweg", "So weit darf ein Laden höchstens neben dem Arbeitsweg liegen.", "m"],
  receipt_ai_task_entity: ["KI-Aufgabe für Kassenzettel-Fotos", "Optional: eine KI-Aufgabe (z. B. Claude, OpenAI, Google Gemini oder Ollama mit Bildverarbeitung) liest Fotos und PDFs. Sie bekommt nur das Bild des Kassenzettels. Leer: die KI aus „🤖 KI“, wenn sie eine KI-Aufgabe ist. Ohne KI kannst du den Text einfügen – er wird lokal gelesen."],
  ai_entity: ["KI (über Home Assistant)", "Eine KI-Aufgabe (ai_task) oder ein Gesprächsagent (conversation, z. B. Jarvis). Die KI ordnet und ergänzt nur die Vorschläge der Regeln und wird nur auf Knopfdruck gefragt."],
  ai_features: ["KI nutzen für", "Ohne Haken arbeitet die Funktion nur nach Regeln."],
};
/* where the choices of entity / select / multi fields come from (keys of get_settings'
 * choices) – the field type and limits come from the backend (options_schema.py) */
const ENTITY_CHOICES = {
  shopping_sync_entity: { list: "todo_entities", none: "– keine –", empty: "Keine weitere To-do-Liste gefunden." },
  receipt_ai_task_entity: { list: "ai_task_entities", none: "– keine (nur Text einfügen) –", empty: "Keine KI-Aufgabe gefunden – richte z. B. Anthropic (Claude), OpenAI, Google Gemini oder Ollama in Home Assistant ein." },
  ai_entity: { list: "ai_entities", none: "– keine KI –", empty: "Keine KI gefunden – richte z. B. Anthropic (Claude), OpenAI, Google Gemini oder Ollama in Home Assistant ein (Einstellungen → Geräte & Dienste).", groups: { ai_task: "🧠 KI-Aufgaben", conversation: "💬 Gesprächsagenten" } },
};
const SELECT_CHOICES = { default_meal: "meals", plan_strategy: "strategies", store_split_mode: "split_modes", offers_source: "offers_sources" };
const MULTI_CHOICES = { enabled_meals: "meals", offer_stores: "stores", ai_features: "ai_features" };
const AI_KIND_LABELS = { ai_task: "KI-Aufgabe", conversation: "Gesprächsagent" };

const safeUrl = (url) => {
  const u = String(url || "").trim();
  if (!/^(https?:\/\/|\/)/i.test(u)) return "";
  return encodeURI(u).replace(/['"()\\]/g, (c) => "%" + c.charCodeAt(0).toString(16));
};
const bg = (url) => (safeUrl(url) ? `style="background-image:url('${safeUrl(url)}')"` : "");
const httpLink = (url) => (/^https?:\/\//i.test(String(url || "")) ? String(url) : "");

const STYLE = `
  :host {
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, "Noto Sans", sans-serif);
    --ep-radius: var(--ha-card-border-radius, 14px);
    --ep-card: var(--card-background-color, #fff);
    --ep-divider: var(--divider-color, rgba(0,0,0,.12));
    --ep-primary: var(--primary-color, #03a9f4);
    --ep-on-primary: var(--text-primary-color, #fff);
    --ep-secondary-text: var(--secondary-text-color, #727272);
    --ep-accent-bg: color-mix(in srgb, var(--ep-primary) 12%, transparent);
    --ep-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.10), 0 1px 2px rgba(0,0,0,.06));
    --ep-warm: #e2553f;
    /* status colours mixed with the text colour: darker on light, lighter on dark themes (contrast) */
    --ep-green: color-mix(in srgb, #2e7d32 65%, var(--primary-text-color, #212121));
    --ep-orange: color-mix(in srgb, #e65100 58%, var(--primary-text-color, #212121));
    --ep-red: color-mix(in srgb, #c62828 58%, var(--primary-text-color, #212121));
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  button { font-family: inherit; }
  header {
    position: sticky; top: 0; z-index: 7; /* above .addrow (4) and its .suggest, below .overlay (10) */
    background: var(--app-header-background-color, var(--ep-primary));
    color: var(--app-header-text-color, #fff);
    box-shadow: 0 2px 6px rgba(0,0,0,.15);
  }
  .toolbar { display: flex; align-items: center; height: 56px; padding: 0 12px; gap: 8px; }
  .toolbar .title { font-size: 20px; font-weight: 400; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tabs { display: flex; gap: 2px; padding: 0 8px; overflow-x: auto; scrollbar-width: none; }
  .tab {
    background: none; border: none; color: inherit; opacity: .72; cursor: pointer;
    padding: 10px 14px 9px; font-size: 14px; font-weight: 500; letter-spacing: .02em;
    border-bottom: 3px solid transparent; white-space: nowrap; display: flex; gap: 6px; align-items: center;
    transition: opacity .15s;
  }
  .tab:hover { opacity: .95; }
  .tab.active { opacity: 1; border-bottom-color: currentColor; }
  @media (max-width: 600px) { .tab .long { display: none; } }
  .tab .count { font-size: 11px; background: rgba(255,255,255,.25); border-radius: 999px; padding: 1px 7px; }
  main { padding: 16px; max-width: 1440px; margin: 0 auto; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 14px; }
  .spacer { flex: 1; }
  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    border: 1px solid var(--ep-divider); background: var(--ep-card); color: var(--primary-text-color);
    border-radius: 999px; padding: 8px 14px; font-size: 14px; cursor: pointer; text-decoration: none;
    transition: border-color .15s, background .15s, transform .05s;
  }
  .btn:hover { border-color: var(--ep-primary); }
  .btn:active { transform: scale(.98); }
  .btn[disabled] { opacity: .45; pointer-events: none; }
  .btn.primary { background: var(--ep-primary); border-color: var(--ep-primary); color: var(--ep-on-primary); }
  .btn.ghost { background: transparent; }
  .btn.danger { color: color-mix(in srgb, var(--error-color, #db4437) 75%, var(--primary-text-color, #212121)); }
  .btn.small { padding: 4px 11px; font-size: 13px; }
  .btn.big { padding: 12px 20px; font-size: 16px; }
  .icon { background: none; border: none; cursor: pointer; color: inherit; font-size: 18px; width: 36px; height: 36px; border-radius: 50%; line-height: 1; display: inline-flex; align-items: center; justify-content: center; }
  .icon:hover { background: var(--ep-accent-bg); }
  input, select, textarea {
    font: inherit; color: var(--primary-text-color);
    background: var(--input-fill-color, var(--ep-card));
    border: 1px solid var(--ep-divider); border-radius: 10px; padding: 9px 11px;
  }
  textarea { width: 100%; min-height: 120px; resize: vertical; line-height: 1.45; }
  input:focus, select:focus, textarea:focus { outline: 2px solid var(--ep-primary); outline-offset: -1px; }
  .card { background: var(--ep-card); border-radius: var(--ep-radius); box-shadow: var(--ep-shadow); border: var(--ha-card-border-width, 0) solid var(--ep-divider); }
  .meta { font-size: 12.5px; color: var(--ep-secondary-text); }
  .hint { font-size: 12.5px; color: var(--ep-secondary-text); }
  .stars { color: #f4b400; letter-spacing: 1px; font-size: 13px; }
  .stars span:not(.on) { opacity: .25; }
  .starbtn { background: none; border: none; font-size: 26px; cursor: pointer; color: #f4b400; opacity: .3; padding: 0 2px; }
  .starbtn.on { opacity: 1; }
  .starbtn:hover { transform: scale(1.15); }

  /* hero */
  .hero {
    position: relative; overflow: hidden; display: flex; gap: 18px; align-items: center;
    padding: 18px 20px; margin-bottom: 16px; min-height: 140px;
    background: linear-gradient(120deg, color-mix(in srgb, var(--hero-color, var(--ep-primary)) 22%, var(--ep-card)), var(--ep-card) 70%);
  }
  .hero.img { color: #fff; background-size: cover; background-position: center; }
  .hero.img::before { content: ""; position: absolute; inset: 0; background: linear-gradient(90deg, rgba(0,0,0,.72), rgba(0,0,0,.25)); }
  .hero > * { position: relative; }
  .hero .bigemoji { font-size: 64px; line-height: 1; filter: drop-shadow(0 4px 8px rgba(0,0,0,.15)); }
  .hero .kicker { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; opacity: .8; font-weight: 600; }
  .hero .htitle { font-size: 26px; font-weight: 600; line-height: 1.15; margin: 4px 0 6px; }
  .hero .hmeta { font-size: 14px; opacity: .85; }
  .hero .hactions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .hero.img .btn:not(.primary) { background: rgba(255,255,255,.15); color: #fff; border-color: rgba(255,255,255,.35); backdrop-filter: blur(4px); }
  .hero .side { margin-left: auto; display: flex; flex-direction: column; gap: 6px; min-width: 190px; }
  .hero .mini { display: flex; gap: 8px; align-items: center; font-size: 13px; background: color-mix(in srgb, var(--ep-card) 70%, transparent); border-radius: 10px; padding: 6px 10px; color: var(--primary-text-color); }
  .hero .mini b { font-weight: 600; }
  @media (max-width: 760px) { .hero { flex-wrap: wrap; } .hero .side { display: none; } .hero .htitle { font-size: 21px; } .hero .bigemoji { font-size: 46px; } }

  /* week */
  .weeklabel { font-size: 18px; font-weight: 500; text-align: center; padding: 0 6px; }
  .progress { height: 6px; border-radius: 999px; background: var(--ep-divider); overflow: hidden; min-width: 90px; flex: 0 1 160px; }
  .progress > div { height: 100%; background: var(--ep-primary); border-radius: inherit; transition: width .3s; }
  .week { display: grid; grid-template-columns: repeat(7, minmax(150px, 1fr)); gap: 12px; }
  @media (max-width: 1180px) { .week { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); } }
  .day { padding: 12px; display: flex; flex-direction: column; gap: 8px; transition: box-shadow .15s; }
  .day.today { box-shadow: 0 0 0 2px var(--ep-primary), var(--ep-shadow); }
  .day.past { opacity: .66; }
  .dayhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; }
  .dayhead .wd { font-weight: 600; font-size: 15px; }
  .dayhead .dt { color: var(--ep-secondary-text); font-size: 13px; white-space: nowrap; }
  .badge { margin-left: auto; font-size: 11px; background: var(--ep-primary); color: var(--ep-on-primary); border-radius: 999px; padding: 2px 8px; }
  .slot { border-radius: 10px; transition: background .12s, outline-color .12s; outline: 2px dashed transparent; outline-offset: 2px; }
  .slot.over { outline-color: var(--ep-primary); background: var(--ep-accent-bg); }
  .slot .label { font-size: 10.5px; text-transform: uppercase; letter-spacing: .07em; color: var(--ep-secondary-text); margin: 2px 0 4px; display: flex; align-items: center; gap: 5px; }
  .slot .label i { width: 7px; height: 7px; border-radius: 50%; background: var(--meal-color); display: inline-block; }
  .meal {
    width: 100%; text-align: left; border: none; cursor: pointer; font: inherit; color: inherit;
    background: color-mix(in srgb, var(--meal-color) 13%, var(--ep-card)); border-left: 4px solid var(--meal-color);
    border-radius: 9px; padding: 8px 9px; display: flex; gap: 9px; align-items: center; transition: transform .1s, box-shadow .15s;
  }
  .meal:hover { box-shadow: 0 2px 8px rgba(0,0,0,.12); }
  .meal.dragging { opacity: .4; }
  .meal .thumb { width: 38px; height: 38px; border-radius: 8px; flex: none; display: flex; align-items: center; justify-content: center; font-size: 22px; background: var(--ep-card) center/cover no-repeat; }
  .meal .t { font-weight: 500; line-height: 1.2; font-size: 14px; }
  .meal .s { font-size: 11.5px; color: var(--ep-secondary-text); margin-top: 2px; }
  .meal.cooked .t { text-decoration: line-through; opacity: .65; }
  .meal.free { border-left-style: dashed; }
  .add { width: 100%; border: 1px dashed var(--ep-divider); background: none; color: var(--ep-secondary-text); border-radius: 9px; padding: 9px; cursor: pointer; font: inherit; font-size: 13px; transition: all .15s; }
  .add:hover { border-color: var(--meal-color, var(--ep-primary)); color: var(--meal-color, var(--ep-primary)); background: color-mix(in srgb, var(--meal-color, var(--ep-primary)) 7%, transparent); }
  .add span { opacity: 0; transition: opacity .15s; }
  .add:hover span { opacity: 1; }

  /* recipes */
  .recipes { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
  .recipe { cursor: pointer; overflow: hidden; display: flex; flex-direction: column; transition: transform .15s, box-shadow .15s; }
  .recipe:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0,0,0,.14); }
  .recipe .img { height: 136px; background: var(--ep-accent-bg) center/cover no-repeat; display: flex; align-items: center; justify-content: center; font-size: 54px; position: relative; }
  .recipe .fav { position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,.35); color: #fff; width: 32px; height: 32px; font-size: 17px; }
  .recipe .fav.on { color: #ffd54f; }
  .recipe .body { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
  .recipe .name { font-weight: 600; font-size: 15px; line-height: 1.25; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { font-size: 11.5px; border-radius: 999px; padding: 3px 9px; background: var(--ep-accent-bg); color: var(--primary-text-color); border: none; cursor: pointer; font-family: inherit; }
  .chip.active { background: var(--ep-primary); color: var(--ep-on-primary); }
  .tagrow { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 4px; scrollbar-width: thin; }
  .tagrow .chip { flex: none; }

  /* shopping */
  .shopping { max-width: 780px; margin: 0 auto; }
  .shopstat { display: flex; align-items: center; gap: 12px; padding: 14px 16px; margin-bottom: 14px; }
  .shopstat .num { font-size: 26px; font-weight: 600; }
  .shopstat .progress { flex: 1 1 auto; height: 8px; }
  .group { margin-bottom: 12px; padding: 4px 0; overflow: hidden; }
  .group h3 { margin: 0; padding: 10px 16px 8px; font-size: 14px; font-weight: 600; color: var(--ep-secondary-text); display: flex; gap: 8px; align-items: center; }
  .item { display: flex; align-items: center; gap: 12px; padding: 9px 12px 9px 16px; border-top: 1px solid var(--ep-divider); }
  .item input[type=checkbox] { width: 22px; height: 22px; accent-color: var(--ep-primary); flex: none; cursor: pointer; }
  .item .txt { flex: 1; min-width: 0; }
  .item .sum { font-size: 15px; }
  .item .desc { font-size: 12px; color: var(--ep-secondary-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .item.done .sum { text-decoration: line-through; opacity: .55; }
  .item .icon { opacity: .5; }
  .item:hover .icon { opacity: 1; }
  .empty { text-align: center; color: var(--ep-secondary-text); padding: 48px 16px; }
  .empty .big { font-size: 52px; margin-bottom: 8px; }

  /* modal */
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 10; display: flex; align-items: center; justify-content: center; padding: 16px; animation: fade .12s ease-out; }
  @keyframes fade { from { opacity: 0; } }
  @keyframes pop { from { transform: translateY(12px) scale(.98); opacity: 0; } }
  .modal { background: var(--ep-card); color: var(--primary-text-color); border-radius: var(--ep-radius); width: min(660px, 100%); max-height: calc(100vh - 32px); overflow: auto; box-shadow: 0 14px 48px rgba(0,0,0,.35); animation: pop .16s ease-out; }
  .modal .mhead { display: flex; align-items: center; gap: 8px; padding: 16px 16px 8px; position: sticky; top: 0; background: var(--ep-card); z-index: 1; }
  .modal .mhead h2 { margin: 0; font-size: 20px; font-weight: 500; flex: 1; }
  .modal .mbody { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 12px; }
  .modal .mfoot { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px 16px; justify-content: flex-end; border-top: 1px solid var(--ep-divider); position: sticky; bottom: 0; background: var(--ep-card); }
  .modal .heroimg { height: 190px; border-radius: 12px; background: var(--ep-accent-bg) center/cover no-repeat; display: flex; align-items: center; justify-content: center; font-size: 76px; }
  .modal h4 { margin: 4px 0; font-size: 15px; }
  .modal ul, .modal ol { margin: 0; padding-left: 22px; line-height: 1.6; }
  .modal ol li { margin-bottom: 6px; }
  .section { border: 1px solid var(--ep-divider); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  label.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ep-secondary-text); }
  label.field input, label.field select, label.field textarea { color: var(--primary-text-color); font-size: 15px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .picklist { display: flex; flex-direction: column; max-height: 300px; overflow: auto; border: 1px solid var(--ep-divider); border-radius: 10px; }
  .pick { text-align: left; background: none; border: none; border-bottom: 1px solid var(--ep-divider); padding: 10px 12px; cursor: pointer; font: inherit; color: inherit; display: flex; gap: 8px; align-items: center; }
  .pick:last-child { border-bottom: none; }
  .pick:hover, .pick.sel { background: var(--ep-accent-bg); }
  .pick.sel { box-shadow: inset 3px 0 0 var(--ep-primary); }
  .pick .m { margin-left: auto; font-size: 12px; color: var(--ep-secondary-text); }
  .stepper { display: inline-flex; align-items: center; gap: 4px; }
  .stepper input { width: 60px; text-align: center; }
  .result { display: flex; gap: 12px; padding: 10px 12px; border-radius: 10px; cursor: pointer; border: 1px solid var(--ep-divider); }
  .result:hover { border-color: var(--ep-primary); }
  .result .thumb { width: 54px; height: 54px; border-radius: 10px; flex: none; background: var(--ep-accent-bg) center/cover; display: flex; align-items: center; justify-content: center; font-size: 28px; }
  .result .bar { height: 5px; border-radius: 999px; background: var(--ep-divider); margin-top: 6px; overflow: hidden; }
  .result .bar div { height: 100%; background: #3fa34d; }
  .error { color: var(--error-color, #db4437); padding: 24px; }
  .loading { padding: 40px; text-align: center; color: var(--ep-secondary-text); }

  /* costs & offers */
  .cost { font-size: 11px; font-weight: 600; color: var(--ep-green); white-space: nowrap; }
  .tagoffer { font-size: 11px; background: color-mix(in srgb, #ef6c00 15%, transparent); color: var(--ep-orange); border-radius: 6px; padding: 0 5px; margin-left: 4px; white-space: nowrap; }
  .budget { display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px; font-size: 13px; font-weight: 500; background: color-mix(in srgb, #2e7d32 14%, transparent); color: var(--ep-green); }
  .budget.warn { background: color-mix(in srgb, #ef6c00 16%, transparent); color: var(--ep-orange); }
  .budget.over { background: color-mix(in srgb, #c62828 16%, transparent); color: var(--ep-red); }
  .price { font-size: 13px; color: var(--ep-secondary-text); white-space: nowrap; text-align: right; }
  .price .o { display: block; font-size: 11px; color: var(--ep-orange); }
  .offers { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
  .offer { display: flex; gap: 12px; padding: 12px; align-items: flex-start; }
  .offer .oimg { width: 64px; height: 64px; border-radius: 10px; flex: none; background: #fff center/contain no-repeat; display: flex; align-items: center; justify-content: center; font-size: 30px; border: 1px solid var(--ep-divider); }
  .offer .ot { font-weight: 600; line-height: 1.25; }
  .offer .store { display: inline-block; font-size: 11px; font-weight: 600; border-radius: 6px; padding: 1px 7px; background: var(--ep-accent-bg); margin: 3px 0; }
  .offer .pr { font-size: 18px; font-weight: 700; color: var(--ep-red); }
  .offer .old { text-decoration: line-through; color: var(--ep-secondary-text); font-size: 13px; margin-left: 6px; }
  .offer .disc { background: #c62828; color: #fff; font-size: 11px; font-weight: 700; border-radius: 6px; padding: 1px 6px; margin-left: 6px; }
  .offer .acts { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
  .budgetcard { padding: 16px; display: grid; grid-template-columns: auto 1fr; gap: 6px 18px; align-items: center; margin-bottom: 14px; }
  .budgetcard .big { font-size: 28px; font-weight: 700; }
  .bars { display: flex; gap: 6px; align-items: flex-end; height: 56px; grid-column: 1 / -1; }
  .bars div { flex: 1; background: color-mix(in srgb, var(--ep-primary) 55%, transparent); border-radius: 6px 6px 2px 2px; position: relative; min-height: 3px; }
  .bars div span { position: absolute; bottom: -18px; left: 0; right: 0; text-align: center; font-size: 11px; color: var(--ep-secondary-text); }
  .infobox { padding: 14px 16px; margin-bottom: 14px; border-left: 4px solid var(--ep-primary); }
  .costbox { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: baseline; }
  .costbox .big { font-size: 20px; font-weight: 700; color: var(--ep-green); }
  .strategy { display: flex; flex-direction: column; gap: 6px; }
  .strategy label { display: flex; gap: 10px; align-items: flex-start; padding: 9px 11px; border: 1px solid var(--ep-divider); border-radius: 10px; cursor: pointer; }
  .strategy label:has(input:checked) { border-color: var(--ep-primary); background: var(--ep-accent-bg); }
  .pricerow { display: grid; grid-template-columns: 1fr auto auto; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--ep-divider); }

  /* cooking mode */
  .cook { position: fixed; inset: 0; z-index: 20; background: var(--primary-background-color, #fafafa); color: var(--primary-text-color); display: grid; grid-template-rows: auto 1fr auto auto; animation: fade .15s; }
  .cook-head { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--ep-card); box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  .cook-head .t { font-size: 19px; font-weight: 600; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .cook-main { display: grid; grid-template-columns: minmax(240px, 320px) 1fr; gap: 16px; padding: 16px; overflow: hidden; min-height: 0; }
  .cook-ing { overflow: auto; padding: 14px; }
  .cook-ing h4 { margin: 0 0 8px; }
  .cook-ing label { display: flex; gap: 10px; align-items: flex-start; padding: 7px 4px; border-bottom: 1px solid var(--ep-divider); cursor: pointer; font-size: 15px; line-height: 1.35; }
  .cook-ing label input { width: 20px; height: 20px; flex: none; accent-color: var(--ep-primary); margin-top: 1px; }
  .cook-ing label.done { opacity: .45; text-decoration: line-through; }
  .cook-step { display: flex; flex-direction: column; justify-content: center; padding: 24px clamp(16px, 4vw, 56px); overflow: auto; user-select: none; }
  .cook-step .n { font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: var(--ep-primary); font-weight: 700; margin-bottom: 14px; }
  .cook-step .txt { font-size: clamp(22px, 3.1vw, 36px); line-height: 1.38; font-weight: 400; }
  .cook-step .tsugg { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 22px; }
  .cook-timers { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 16px 10px; }
  .timer { display: flex; align-items: center; gap: 8px; padding: 8px 8px 8px 14px; border-radius: 999px; background: var(--ep-card); box-shadow: var(--ep-shadow); font-variant-numeric: tabular-nums; }
  .timer b { font-size: 18px; }
  .timer.done { background: var(--ep-warm); color: #fff; animation: pulse 1s infinite; }
  @keyframes pulse { 50% { transform: scale(1.04); } }
  .cook-foot { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--ep-card); box-shadow: 0 -1px 4px rgba(0,0,0,.08); }
  .dots { flex: 1; display: flex; justify-content: center; gap: 6px; flex-wrap: wrap; }
  .dots button { width: 10px; height: 10px; border-radius: 50%; border: none; background: var(--ep-divider); cursor: pointer; padding: 0; }
  .dots button.on { background: var(--ep-primary); transform: scale(1.3); }
  .dots button.past { background: color-mix(in srgb, var(--ep-primary) 45%, var(--ep-divider)); }
  .cook-ing-toggle { display: none; }
  @media (max-width: 760px) {
    .cook-main { grid-template-columns: 1fr; grid-template-rows: auto 1fr; padding: 10px; gap: 10px; }
    .cook-ing { max-height: 34vh; display: none; }
    .cook-ing.open { display: block; }
    .cook-ing-toggle { display: inline-flex; }
    .cook-step { padding: 12px; }
  }
  /* stores & prices (1.3) */
  .rdot { width: 30px; height: 30px; border-radius: 9px; flex: none; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; letter-spacing: -.02em; }
  .rdot.sm { width: 22px; height: 22px; border-radius: 7px; font-size: 10px; }
  .rdot.xs { width: 18px; height: 18px; border-radius: 6px; font-size: 8.5px; }
  .bdg { display: inline-flex; align-items: center; gap: 3px; font-size: 11.5px; line-height: 1.5; border-radius: 999px; padding: 1px 8px; background: var(--ep-accent-bg); color: var(--primary-text-color); white-space: nowrap; }
  .bdg.star { background: var(--ep-primary); color: var(--ep-on-primary); }
  .bdg.warn { background: color-mix(in srgb, #ef6c00 16%, transparent); color: var(--ep-orange); }
  .bdg.ok { background: color-mix(in srgb, #2e7d32 15%, transparent); color: var(--ep-green); }
  .bdg.bad { background: color-mix(in srgb, #c62828 15%, transparent); color: var(--ep-red); }
  .badges { display: flex; flex-wrap: wrap; gap: 5px; }
  .seg { display: inline-flex; border: 1px solid var(--ep-divider); border-radius: 999px; overflow: hidden; background: var(--ep-card); }
  .seg button { border: none; background: none; color: inherit; font: inherit; font-size: 14px; padding: 8px 14px; min-height: 40px; cursor: pointer; white-space: nowrap; }
  .seg button.on { background: var(--ep-primary); color: var(--ep-on-primary); }
  .stores { max-width: 1100px; margin: 0 auto; }
  details.sec { margin-bottom: 14px; scroll-margin-top: 112px; }
  details.sec > summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 8px; padding: 14px 16px; font-size: 17px; font-weight: 500; user-select: none; }
  details.sec > summary::-webkit-details-marker { display: none; }
  details.sec > summary::after { content: "▾"; margin-left: auto; opacity: .55; transition: transform .15s; }
  details.sec:not([open]) > summary::after { transform: rotate(-90deg); }
  details.sec > summary .meta { font-weight: 400; }
  .secbody { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 12px; min-width: 0; }
  .branchgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 12px; }
  .branch { border: 1px solid var(--ep-divider); border-radius: 12px; padding: 12px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .branch.main { border-color: var(--ep-primary); box-shadow: 0 0 0 1px var(--ep-primary); }
  .branch.off > :not(.bacts):not(.badges) { opacity: .55; }
  .bhead { display: flex; gap: 10px; align-items: center; min-width: 0; }
  .bhead .bname { font-weight: 600; line-height: 1.25; overflow-wrap: anywhere; }
  .baddr { font-size: 12.5px; color: var(--ep-secondary-text); overflow-wrap: anywhere; }
  .bacts { display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: center; margin-top: auto; }
  .bacts .icons { display: inline-flex; margin-left: auto; }
  .bacts .icon { width: 40px; height: 40px; }
  .bacts .icon[disabled] { opacity: .25; pointer-events: none; }
  .switch { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; min-height: 40px; }
  .switch input { width: 18px; height: 18px; accent-color: var(--ep-primary); }
  .rewebox { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; }
  .rewebox input { width: 120px; padding: 6px 9px; }
  .markets { display: flex; flex-direction: column; gap: 4px; }
  .market { display: flex; gap: 8px; align-items: center; font-size: 13px; border: 1px solid var(--ep-divider); border-radius: 9px; padding: 6px 8px; }
  .market span { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  details.prefbox { border: 1px solid var(--ep-divider); border-radius: 12px; padding: 0 12px; }
  details.prefbox[open] { padding-bottom: 12px; }
  details.prefbox > summary { cursor: pointer; display: flex; align-items: center; gap: 8px; min-height: 44px; font-weight: 500; }
  details.prefbox > summary .meta { font-weight: 400; }
  details.prefbox > .hint { margin: 0 0 8px; }
  .prefrow { display: flex; gap: 10px; align-items: flex-start; padding: 6px 0; border-top: 1px solid var(--ep-divider); min-width: 0; }
  .prefitems { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .prefchip { display: inline-flex; align-items: center; gap: 2px; border-radius: 999px; background: var(--ep-accent-bg); padding-left: 11px; font-size: 13.5px; max-width: 100%; overflow-wrap: anywhere; }
  .prefchip .icon { width: 32px; height: 32px; font-size: 14px; flex: none; }
  .zonechips, .chainchips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .zonechips .chip, .chainchips .chip { font-size: 13px; padding: 7px 12px; min-height: 36px; }
  .chainchips .chip { display: inline-flex; align-items: center; gap: 5px; }
  .osmlist { display: flex; flex-direction: column; gap: 6px; }
  .osm { display: flex; gap: 10px; align-items: center; border: 1px solid var(--ep-divider); border-radius: 10px; padding: 8px 10px; min-width: 0; }
  .osm .info { flex: 1; min-width: 0; }
  .osm .info b { font-weight: 600; }
  .osm .btn { flex: none; }
  .notice { font-size: 13px; padding: 9px 12px; border-radius: 10px; background: var(--ep-accent-bg); }
  .notice.warn { background: color-mix(in srgb, #ef6c00 13%, transparent); }
  .notice.err { background: color-mix(in srgb, #c62828 13%, transparent); color: var(--ep-red); }
  .formgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; align-items: end; }
  .formgrid input, .formgrid select { width: 100%; }
  .pmtools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .pmtools input[type=search] { flex: 1 1 200px; min-width: 0; }
  .pmwrap { overflow-x: auto; border: 1px solid var(--ep-divider); border-radius: 12px; max-width: 100%; }
  table.pm { border-collapse: collapse; width: 100%; font-size: 13.5px; }
  .pm th { text-align: left; padding: 8px 6px; font-size: 12.5px; font-weight: 600; border-bottom: 1px solid var(--ep-divider); white-space: nowrap; background: var(--ep-card); }
  .pm th .rdot { vertical-align: middle; margin-right: 4px; }
  .pm td { padding: 3px; border-bottom: 1px solid var(--ep-divider); vertical-align: top; }
  .pm tr:last-child td { border-bottom: none; }
  .pm td.pname { padding: 8px 6px 8px 10px; font-weight: 500; min-width: 120px; overflow-wrap: anywhere; }
  .pm td.pname .meta { font-weight: 400; display: block; }
  .cell { width: 100%; min-width: 86px; min-height: 42px; text-align: left; background: none; border: 1px solid transparent; border-radius: 8px; padding: 4px 7px; font: inherit; color: inherit; cursor: pointer; display: flex; flex-direction: column; justify-content: center; }
  .cell:hover { border-color: var(--ep-primary); }
  .cell .p { font-weight: 600; white-space: nowrap; }
  .cell .s { font-size: 11px; color: var(--ep-secondary-text); white-space: nowrap; }
  .cell.none .p { font-weight: 400; color: var(--ep-secondary-text); }
  .cell.best { background: color-mix(in srgb, #2e7d32 15%, transparent); }
  .cell.best .p { color: var(--ep-green); }
  .cell.stale { opacity: .6; }
  .cell.static { cursor: default; }
  .cell.static:hover { border-color: transparent; }
  .srcgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
  .srcgrid .section h4 { margin: 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  /* shopping per store */
  .storehead { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; padding: 12px 16px 10px; }
  .storehead .sname { font-weight: 600; font-size: 15px; color: var(--primary-text-color); overflow-wrap: anywhere; }
  .storehead .sstat { margin-left: auto; font-size: 13px; color: var(--ep-secondary-text); text-align: right; }
  .storehead .save { color: var(--ep-green); font-weight: 600; white-space: nowrap; }
  .aisle { padding: 7px 16px 3px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--ep-secondary-text); border-top: 1px solid var(--ep-divider); }
  .aisle + .item { border-top: none; }
  .reason { font-size: 11px; border-radius: 6px; padding: 0 6px; margin-left: 4px; background: var(--ep-accent-bg); white-space: nowrap; vertical-align: 1px; }
  .reason.offer { background: color-mix(in srgb, #ef6c00 16%, transparent); color: var(--ep-orange); }
  .reason.cheap { background: color-mix(in srgb, #2e7d32 15%, transparent); color: var(--ep-green); }
  .item .swap { font-size: 17px; }
  .price .sv { display: block; font-size: 11px; color: var(--ep-green); }
  .addrow { position: relative; z-index: 4; }
  .addwrap { flex: 1 1 220px; min-width: 0; }
  .addwrap input { width: 100%; min-height: 42px; }
  .suggest { position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 6; background: var(--ep-card); color: var(--primary-text-color); border: 1px solid var(--ep-divider); border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.25); max-height: min(58vh, 440px); overflow-y: auto; overscroll-behavior: contain; }
  .suggest[hidden] { display: none; }
  .sugg { display: flex; gap: 10px; align-items: center; width: 100%; min-height: 50px; text-align: left; background: none; border: none; border-top: 1px solid var(--ep-divider); padding: 7px 12px; font: inherit; color: inherit; cursor: pointer; }
  .sugg:first-of-type { border-top: none; }
  .sugg.sel, .sugg:hover { background: var(--ep-accent-bg); }
  .sugg.sel { box-shadow: inset 3px 0 0 var(--ep-primary); }
  .sugg .st { flex: 1; min-width: 0; }
  .sugg .t { font-weight: 500; overflow-wrap: anywhere; }
  .sugg .t .meta { font-weight: 400; }
  .sugg .sub { font-size: 12px; color: var(--ep-secondary-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sugg .sp { text-align: right; white-space: nowrap; flex: none; }
  .sugg .sp b { font-size: 15px; }
  .sugg .sp .meta { display: block; font-size: 11px; }
  .shint { padding: 8px 12px; font-size: 12.5px; color: var(--ep-secondary-text); }
  .shint.top { border-bottom: 1px solid var(--ep-divider); display: flex; gap: 6px; align-items: center; }
  .branchtags { display: flex; flex-wrap: wrap; gap: 4px; margin: 2px 0; }
  .branchtags .bdg { font-size: 11px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
  .hintcard { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
  .hintcard > span { flex: 1; min-width: 0; line-height: 1.9; }
  .pick .pi { flex: 1; min-width: 0; }
  .pick .pi .sub { font-size: 12px; color: var(--ep-secondary-text); }
  .pick .pp { text-align: right; white-space: nowrap; }
  .pick .pp b { font-size: 15px; }
  @media (max-width: 600px) {
    .item { gap: 8px; padding: 9px 6px 9px 12px; }
    .storehead .sstat { margin-left: 0; text-align: left; width: 100%; }
    details.sec > summary { padding: 13px 12px; font-size: 16px; }
    .secbody { padding: 0 12px 14px; }
    .branchgrid { grid-template-columns: 1fr; }
    .seg button { padding: 8px 11px; font-size: 13.5px; }
  }
  @media (max-width: 600px) { main { padding: 10px; } .grid2 { grid-template-columns: 1fr; } .weeklabel { font-size: 16px; } .btn { padding: 7px 12px; } }
  /* the checkbox of a shopping item: 40 px tap area without changing the row layout */
  .item .chk { flex: none; width: 40px; height: 40px; margin: -9px; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
  .addwrap input { scroll-margin-top: 120px; }
  /* 1.4: gear, settings view */
  .toolbar .gear { width: 44px; height: 44px; font-size: 21px; color: inherit; flex: none; }
  .toolbar .gear:hover { background: rgba(255,255,255,.16); }
  .toolbar .gear.off { opacity: .45; cursor: not-allowed; }
  .sview { position: fixed; inset: 0; z-index: 12; background: rgba(0,0,0,.45); display: flex; align-items: center; justify-content: center; padding: 16px; animation: fade .12s ease-out; }
  .spage { background: var(--primary-background-color, #fafafa); color: var(--primary-text-color); width: min(1040px, 100%); height: min(900px, calc(100vh - 32px)); border-radius: var(--ep-radius); box-shadow: 0 14px 48px rgba(0,0,0,.35); display: grid; grid-template-rows: auto 1fr auto; overflow: hidden; animation: pop .16s ease-out; }
  .shead { display: flex; align-items: center; gap: 8px; padding: 10px 12px 10px 18px; background: var(--ep-card); border-bottom: 1px solid var(--ep-divider); }
  .shead h2 { margin: 0; font-size: 20px; font-weight: 500; flex: 1; min-width: 0; }
  .smain { display: grid; grid-template-columns: 230px 1fr; min-height: 0; }
  .snav { display: flex; flex-direction: column; gap: 4px; padding: 14px 10px; border-right: 1px solid var(--ep-divider); background: var(--ep-card); overflow-y: auto; }
  .snav button { text-align: left; border: none; background: none; color: inherit; font: inherit; font-size: 14.5px; padding: 10px 12px; min-height: 42px; border-radius: 10px; cursor: pointer; display: flex; gap: 6px; align-items: center; }
  .snav button:hover { background: var(--ep-accent-bg); }
  .snav button.on { background: var(--ep-accent-bg); box-shadow: inset 3px 0 0 var(--ep-primary); font-weight: 600; }
  .snav .nerr { margin-left: auto; background: var(--error-color, #db4437); color: #fff; border-radius: 999px; font-size: 11px; padding: 0 7px; }
  .sbody { overflow-y: auto; padding: 16px 20px 28px; scroll-behavior: smooth; min-width: 0; }
  .ssec { margin-bottom: 18px; padding: 14px 16px; scroll-margin-top: 8px; }
  .ssec > h3 { margin: 0 0 4px; font-size: 17px; font-weight: 600; }
  .ssec > .hint { margin: 0 0 8px; }
  .sfield { display: flex; flex-direction: column; gap: 5px; padding: 11px 0; border-top: 1px solid var(--ep-divider); min-width: 0; }
  .ssec > h3 + .sfield, .ssec > .hint + .sfield { border-top: none; }
  .sfield > .flabel { font-weight: 500; font-size: 14.5px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .sfield .fhelp { font-size: 12.5px; color: var(--ep-secondary-text); line-height: 1.4; }
  .aitestrow { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
  .aitestrow .aitest { flex: 1 1 220px; min-width: 0; }
  .aitestrow .aitest:empty { display: none; }
  .sfield .ferr { font-size: 13px; color: var(--ep-red); font-weight: 500; }
  .sfield.invalid input, .sfield.invalid select, .sfield.invalid textarea { outline: 2px solid var(--error-color, #db4437); outline-offset: -1px; }
  .sfield.invalid .chips, .sfield.invalid .choice { outline: 2px solid var(--error-color, #db4437); outline-offset: 2px; border-radius: 10px; }
  .sfield .fin { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .sfield .fin input:not([type=checkbox]):not([type=radio]) { width: 140px; }
  .sfield .fin .unit { color: var(--ep-secondary-text); font-size: 14px; }
  .sfield input.wide, .sfield textarea, .sfield select.wide { width: 100%; max-width: 560px; }
  .sfield textarea { min-height: 64px; }
  .sfield .switch { font-size: 14.5px; font-weight: 500; }
  .sfield .switch input { width: 20px; height: 20px; }
  .sgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 0 14px; }
  .sgrid .sfield { border-top: none; }
  .choice { display: flex; flex-direction: column; gap: 6px; max-width: 620px; }
  .choice label { display: flex; gap: 10px; align-items: flex-start; padding: 9px 11px; border: 1px solid var(--ep-divider); border-radius: 10px; cursor: pointer; min-height: 42px; font-size: 14px; }
  .choice label:has(input:checked) { border-color: var(--ep-primary); background: var(--ep-accent-bg); }
  .choice input { margin-top: 2px; accent-color: var(--ep-primary); }
  label.chip.pick2 { display: inline-flex; gap: 5px; align-items: center; font-size: 13px; padding: 7px 12px; min-height: 38px; cursor: pointer; }
  label.chip.pick2 input { width: 16px; height: 16px; accent-color: var(--ep-primary); margin: 0; }
  label.chip.pick2:has(input:checked) { background: var(--ep-primary); color: var(--ep-on-primary); }
  .sfoot { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px; background: var(--ep-card); border-top: 1px solid var(--ep-divider); }
  .sfoot .sstate { flex: 1; min-width: 160px; font-size: 13px; color: var(--ep-secondary-text); }
  .sfoot .sstate.err { color: var(--ep-red); font-weight: 500; }
  .sbanner { padding: 14px 16px; margin-bottom: 14px; display: flex; gap: 10px; align-items: center; }
  @media (max-width: 700px) {
    .sview { padding: 0; }
    .spage { width: 100%; height: 100%; border-radius: 0; }
    .smain { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
    .snav { flex-direction: row; overflow-x: auto; padding: 8px; border-right: none; border-bottom: 1px solid var(--ep-divider); scrollbar-width: none; }
    .snav button { flex: none; white-space: nowrap; padding: 8px 12px; }
    .snav button.on { box-shadow: inset 0 -3px 0 var(--ep-primary); }
    .sbody { padding: 10px 10px 24px; }
    .ssec { padding: 12px; }
    .sfield .fin input:not([type=checkbox]):not([type=radio]) { width: 120px; }
    .sfoot .sstate { min-width: 100%; order: -1; }
    .sfoot .btn { flex: 1; justify-content: center; }
  }

  /* 1.4: Angebote tab – all offers of the saved stores */
  .somode { margin-bottom: 12px; display: flex; max-width: 100%; }
  .somode button { flex: 1 1 0; overflow: hidden; text-overflow: ellipsis; }
  .narrow-only { display: none; }
  @media (max-width: 600px) { .wide-only { display: none; } .narrow-only { display: inline; } }
  .sochips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 10px; }
  .sochips .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; padding: 6px 12px 6px 7px; min-height: 38px; }
  .sochips .chip.all { padding-left: 12px; }
  .sochips .chip .n { font-size: 11px; opacity: .8; }
  .sotools { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
  .sotools input[type=search] { flex: 1 1 220px; min-width: 0; }
  .srcline { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12.5px; color: var(--ep-secondary-text); margin: 0 0 10px; }
  .srcline > span { display: inline-flex; gap: 5px; align-items: center; }
  .soffers { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
  .soffer { display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
  .soffer .sotop { display: flex; gap: 10px; padding: 10px 12px 0; align-items: flex-start; }
  .soffer .soimg { width: 76px; height: 76px; flex: none; border-radius: 10px; background: #fff; border: 1px solid var(--ep-divider); display: flex; align-items: center; justify-content: center; font-size: 30px; overflow: hidden; }
  .soffer .soimg img { width: 100%; height: 100%; object-fit: contain; }
  .soffer .sot { flex: 1; min-width: 0; }
  .soffer .brand { font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--ep-secondary-text); overflow-wrap: anywhere; }
  .soffer .pname { font-weight: 600; line-height: 1.25; overflow-wrap: anywhere; }
  .soffer .pack { font-size: 12.5px; color: var(--ep-secondary-text); overflow-wrap: anywhere; }
  .soffer .soprice { padding: 6px 12px 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 8px; }
  .soffer .pr { font-size: 20px; font-weight: 700; color: var(--ep-red); }
  .soffer .old { text-decoration: line-through; color: var(--ep-secondary-text); font-size: 13px; }
  .soffer .disc { background: #c62828; color: #fff; font-size: 11px; font-weight: 700; border-radius: 6px; padding: 1px 6px; }
  .soffer .up { font-size: 12px; color: var(--ep-secondary-text); }
  .soffer .someta { padding: 4px 12px 0; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
  .soffer .sostore { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; max-width: 100%; overflow-wrap: anywhere; }
  .soffer .acts { display: flex; gap: 6px; padding: 8px 12px 12px; margin-top: auto; flex-wrap: wrap; }
  .soffer .acts .btn { flex: 1 1 auto; justify-content: center; }
  .soffer.later { opacity: .9; }
  .leaflets { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; margin-bottom: 14px; }
  .leaflet { padding: 12px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .leaflet .lfhead { display: flex; gap: 8px; align-items: center; font-weight: 600; overflow-wrap: anywhere; }
  .leaflet .lfpages { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
  .leaflet .lfpages a { display: block; aspect-ratio: 3 / 4; border-radius: 8px; overflow: hidden; border: 1px solid var(--ep-divider); background: var(--ep-accent-bg); }
  .leaflet .lfpages img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .leaflet .lfacts { display: flex; flex-wrap: wrap; gap: 6px; }
  /* price list: offer under the price, offer-only cells, drugstore columns */
  .cell .o { font-size: 11px; color: var(--ep-orange); white-space: nowrap; font-weight: 600; }
  .cell.offeronly .p { color: var(--ep-orange); }
  .cell.dim { opacity: .45; }
  .pm th.drug { background: color-mix(in srgb, #8e24aa 7%, var(--ep-card)); }
  /* receipts */
  .rlist { display: flex; flex-direction: column; gap: 6px; }
  .rrow { display: flex; gap: 10px; align-items: center; border: 1px solid var(--ep-divider); border-radius: 10px; padding: 6px 8px; min-width: 0; }
  .rrow .rthumb { width: 46px; height: 46px; border-radius: 8px; flex: none; background: var(--ep-accent-bg) center/cover no-repeat; display: flex; align-items: center; justify-content: center; font-size: 22px; overflow: hidden; }
  .rrow .rthumb img { width: 100%; height: 100%; object-fit: cover; }
  .rrow .rinfo { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .rrow .rsum { text-align: right; white-space: nowrap; }
  .rpick { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .rpreview { max-height: 220px; border-radius: 10px; border: 1px solid var(--ep-divider); max-width: 100%; object-fit: contain; background: #fff; }
  .rhead { display: grid; grid-template-columns: 2fr 1fr; gap: 10px; }
  .rtable { display: flex; flex-direction: column; border: 1px solid var(--ep-divider); border-radius: 10px; overflow: hidden; }
  .rline { display: grid; grid-template-columns: minmax(120px, 1.1fr) minmax(150px, 1.4fr) 150px 92px; gap: 8px; align-items: center; padding: 7px 10px; border-top: 1px solid var(--ep-divider); }
  .rline:first-child { border-top: none; }
  .rline.headrow { background: var(--ep-accent-bg); font-size: 12px; font-weight: 600; color: var(--ep-secondary-text); }
  .rline .src { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; white-space: pre-line; }
  .rline input { width: 100%; min-width: 0; padding: 7px 8px; }
  .rline .art { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .rline .packin { display: flex; gap: 4px; }
  .rline .packin input { width: 70px; }
  .rline .packin select { padding: 7px 4px; min-width: 0; flex: 1; }
  .rline.ignored > :not(.art) { opacity: .62; }
  .rline.ignored .src { text-decoration: line-through; }
  .rline.ignored .art input:not([type=checkbox]) { opacity: .62; }
  .rline .ign { font-size: 12.5px; display: inline-flex; gap: 6px; align-items: center; cursor: pointer; min-height: 30px; align-self: flex-start; }
  .rline .ign input { width: 18px; height: 18px; flex: none; margin: 0; accent-color: var(--ep-primary); }
  .rline .rwarn { font-size: 11.5px; color: var(--ep-orange); }
  .rline .rown { grid-column: 2 / -1; text-align: right; }
  .rline .rown:empty { display: none; }
  .rline .packin :disabled { opacity: .62; }
  .rhead .rneed { font-size: 13px; color: var(--ep-red); font-weight: 500; }
  .rhead select.invalid { outline: 2px solid var(--error-color, #db4437); outline-offset: -1px; }
  .rtotal { display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; font-size: 14px; }
  details.srcbox { margin: 0 0 10px; font-size: 12.5px; color: var(--ep-secondary-text); }
  details.srcbox > summary { cursor: pointer; min-height: 40px; display: flex; align-items: center; }
  details.srcbox .srcline { margin: 4px 0 0; flex-direction: column; }
  .lfnote { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; margin-bottom: 10px; }
  @media (max-width: 700px) {
    .sochips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: thin; padding-bottom: 4px; }
    .sochips .chip { flex: none; }
    .rhead { grid-template-columns: 1fr; }
    .rline { grid-template-columns: 1fr 1fr; }
    .rline .src { grid-column: 1 / -1; }
    .rline .art { grid-column: 1 / -1; }
    .rline .rown { grid-column: 1 / -1; text-align: left; }
    .rline.headrow { display: none; }
    .soffers { grid-template-columns: 1fr; }
    .leaflets { grid-template-columns: 1fr; }
  }
  /* touch screens: every control at least 40 px high */
  @media (pointer: coarse) {
    .rline .ign { min-height: 40px; }
    .sochips .chip, label.chip.pick2 { min-height: 40px; }
    .btn, .btn.small, .add { min-height: 40px; }
    .btn.small { padding: 6px 12px; }
    .icon, .bacts .icon, .recipe .fav, .prefchip .icon { width: 40px; height: 40px; }
    button.chip, label.chip, .zonechips .chip, .chainchips .chip { min-height: 40px; display: inline-flex; align-items: center; gap: 4px; }
    input:not([type=checkbox]):not([type=radio]), select { min-height: 40px; }
    .rewebox input { padding: 8px 10px; }
  }
`;

class EssensplanerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = this._pref("tab", "plan");
    this._sort = this._pref("sort", "fav");
    this._weekStart = null;
    this._data = null;
    this._search = "";
    this._tag = "";
    this._favOnly = false;
    this._modal = null;
    this._cook = null;
    this._unsub = null;
    this._reloadTimer = null;
    this._dataJson = null;
    this._pendingChanges = new Set();
    // stores tab (1.3)
    this._storePrices = null;
    this._priceQuery = "";
    this._priceLimit = 50;
    this._priceStore = null;
    this._branchSearch = undefined;
    this._searchZones = null;
    this._searchRoute = null;
    this._searchRadius = null;
    this._searchChains = new Set(); // chain filter of the search results (empty = all)
    this._searching = false;
    this._searchError = null;
    this._manual = { store: "", label: "", street: "", postcode: "", city: "" };
    this._reweInput = {};
    this._reweMarkets = {};
    this._refreshing = new Set();
    // Angebote tab (1.4): "für meine Rezepte" or all offers of the saved stores
    this._offersMode = this._pref("offers_mode", "recipes");
    let soBranches = [];
    try {
      soBranches = JSON.parse(this._pref("offers_branches", "[]")) || [];
    } catch (e) {
      soBranches = [];
    }
    this._so = {
      when: "current",
      kind: this._pref("offers_kind", "all"),
      sort: this._pref("offers_sort", "saving"),
      query: "",
      branches: new Set(Array.isArray(soBranches) ? soBranches : []),
      result: null,
      offers: [],
      loading: false,
      error: null,
      stale: true,
      seq: 0,
    };
    this._priceKind = "all"; // price list rows: all | food | nonfood
    // receipts (1.4): list of the stores tab and the capture dialog
    this._receipts = null;
    this._receiptsLoading = false;
    this._receiptsError = null;
    this._receipt = null;
    // settings view (1.4, ⚙️)
    this._settings = null;
    try {
      this._secOpen = JSON.parse(this._pref("sections", "{}")) || {};
    } catch (e) {
      this._secOpen = {};
    }
    // article search in "Artikel hinzufügen"
    this._addText = "";
    this._suggest = { open: false, query: "", results: [], loading: false, index: -1, store: null, error: null, live: false };
    this._suggestSeq = 0;
    this._suggestTimer = null;
    this._narrowQuery = window.matchMedia ? window.matchMedia("(max-width: 700px)") : null;
    this._onNarrow = () => {
      if (this._tab === "stores") this._renderPriceMatrix();
    };
    this._onKey = (ev) => this._handleKey(ev);
    this._onViewport = () => {
      if (this._suggest.open) this._fitSuggest(undefined, undefined, true);
    };
    this._onVisibility = () => {
      if (this._cook && document.visibilityState === "visible") this._acquireWakeLock();
    };
  }

  /* ------------------------------------------------------------ HA props */
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._init();
    if (this._menuButton) this._menuButton.hass = hass;
    this._updateGear();
  }

  /** Settings are for admins (the websockets refuse others): a hint instead. */
  _isAdmin() {
    return this._hass?.user?.is_admin !== false;
  }

  _updateGear() {
    const gear = this._gear;
    if (!gear) return;
    const admin = this._isAdmin();
    gear.classList.toggle("off", !admin);
    gear.setAttribute("aria-disabled", admin ? "false" : "true");
    gear.title = admin ? "Einstellungen" : "Einstellungen – nur für Administratoren";
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menuButton) this._menuButton.narrow = narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    window.addEventListener("keydown", this._onKey);
    document.addEventListener("visibilitychange", this._onVisibility);
    this._narrowQuery?.addEventListener?.("change", this._onNarrow);
    window.visualViewport?.addEventListener("resize", this._onViewport);
    if (this._hass && !this._unsub && this._data) this._subscribe();
    // removed while the integration reloaded after saving the settings: fetch everything again
    if (this._hass && this._data && this._reloadOnConnect) {
      this._reloadOnConnect = false;
      this._forgetLoaded();
      this._load();
    }
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
    document.removeEventListener("visibilitychange", this._onVisibility);
    this._narrowQuery?.removeEventListener?.("change", this._onNarrow);
    window.visualViewport?.removeEventListener("resize", this._onViewport);
    if (this._unsub) {
      Promise.resolve(this._unsub).then((unsub) => typeof unsub === "function" && unsub());
      this._unsub = null;
    }
    this._closeCooking(true);
  }

  _pref(key, fallback) {
    try {
      return localStorage.getItem(`essensplaner-${key}`) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  _setPref(key, value) {
    try {
      localStorage.setItem(`essensplaner-${key}`, value);
    } catch (e) {
      /* ignore */
    }
  }

  /* ------------------------------------------------------------ data */
  async _init() {
    this._renderShell();
    await this._load();
    this._subscribe();
  }

  async _load() {
    const changes = this._pendingChanges;
    this._pendingChanges = new Set();
    try {
      const data = await this._hass.callWS({ type: `${DOMAIN}/data` });
      const json = JSON.stringify(data);
      const pricesStale = !changes.size || [...changes].some((c) => STALE_CHANGES.has(c) || !c);
      const offersStale = !changes.size || [...changes].some((c) => ["offers", "branches", "price_sources", ""].includes(c));
      if (offersStale) this._so.stale = true;
      if (changes.has("receipts") || changes.has("prices")) this._receiptsStale = true;
      if (json === this._dataJson && this._data) {
        if (offersStale && this._tab === "offers" && this._offersMode === "stores" && !this._so.loading) this._fetchStoreOffers();
        // nothing changed: no re-render (keeps typing smooth) – but store prices are not part
        // of the data, so a changed price (e.g. set by voice) still refreshes the price list
        if (changes.size && pricesStale) {
          this._priceList = null;
          if (this._tab === "stores") this._fetchStorePrices();
          else this._storePricesStale = true;
        }
        return;
      }
      this._dataJson = json;
      this._data = data;
      this._costs = {};
      if (!this._weekStart) this._weekStart = mondayOf(fromIso(this._data.today));
      if (pricesStale) {
        this._storePricesStale = true;
        this._priceList = null;
      }
      this._renderContent();
    } catch (err) {
      this._content.innerHTML = `<div class="error">Essensplaner konnte nicht geladen werden: ${esc(
        err.message || err.code || err
      )}<br><br>Ist die Integration eingerichtet?</div>`;
    }
  }

  /** Change events of the integration – only while the panel is on the page (a removed
   *  panel would otherwise keep loading all data on every change). */
  async _subscribe() {
    if (this._unsub || this._subscribing || !this.isConnected) return;
    this._subscribing = true;
    try {
      const unsub = await this._hass.connection.subscribeMessage((ev) => this._scheduleReload(ev?.change), {
        type: `${DOMAIN}/subscribe`,
      });
      if (this.isConnected) this._unsub = unsub;
      else if (typeof unsub === "function") unsub(); // removed meanwhile
    } catch (err) {
      /* integration not loaded – ignore */
    } finally {
      this._subscribing = false;
    }
  }

  _scheduleReload(change) {
    this._pendingChanges.add(change || "");
    clearTimeout(this._reloadTimer);
    this._reloadTimer = setTimeout(() => this._load(), 250);
  }

  /** call_service with response, without the error toast (caller handles errors). */
  async _callService(service, data) {
    const result = await this._hass.callWS({
      type: "call_service",
      domain: DOMAIN,
      service,
      service_data: data,
      return_response: true,
    });
    return result.response;
  }

  async _service(service, data, withResponse = false) {
    try {
      if (withResponse) {
        const result = await this._hass.callWS({
          type: "call_service",
          domain: DOMAIN,
          service,
          service_data: data,
          return_response: true,
        });
        return result.response;
      }
      await this._hass.callService(DOMAIN, service, data);
      return null;
    } catch (err) {
      this._toast(errText(err));
      throw err;
    }
  }

  async _todo(service, data) {
    const entity = this._data?.entities?.shopping_list;
    if (!entity) return;
    try {
      await this._hass.callService("todo", service, { entity_id: entity, ...data });
    } catch (err) {
      this._toast(errText(err));
    }
  }

  _toast(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }));
  }

  _recipe(id) {
    return this._data?.recipes.find((r) => r.id === id);
  }

  _today() {
    return this._data?.today || toIso(new Date());
  }

  _mealLabel(id) {
    return this._data.all_meals.find((m) => m.id === id)?.label || id;
  }

  _dateLabel(iso) {
    const d = fromIso(iso);
    return `${WEEKDAYS[weekdayIndex(d)]}, ${d.getDate()}. ${MONTHS[d.getMonth()]}`;
  }

  _mealColor(id) {
    return MEAL_STYLE[id]?.color || "var(--ep-primary)";
  }

  /* ------------------------------------------------------------ shell */
  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <header>
        <div class="toolbar"><span class="menu"></span><div class="title">🍽️ Essensplaner</div><button class="icon gear" data-gear title="Einstellungen" aria-label="Einstellungen">⚙️</button></div>
        <div class="tabs">
          <button class="tab" data-tab="plan">🗓️ Wochenplan</button>
          <button class="tab" data-tab="recipes">📖 Rezepte <span class="count" data-count="recipes"></span></button>
          <button class="tab" data-tab="shopping">🛒 Einkaufsliste <span class="count" data-count="shopping"></span></button>
          <button class="tab" data-tab="offers">💶 Angebote<span class="long"> & Budget</span> <span class="count" data-count="offers"></span></button>
          <button class="tab" data-tab="stores">🏪 Läden<span class="long"> & Preise</span></button>
        </div>
      </header>
      <main><div class="loading">Lade …</div></main>
      <div class="modalroot"></div>
      <div class="settingsroot"></div>
      <div class="cookroot"></div>
      <input type="file" accept=".json,application/json" class="fileinput" hidden>`;
    this._content = this.shadowRoot.querySelector("main");
    this._modalRoot = this.shadowRoot.querySelector(".modalroot");
    this._cookRoot = this.shadowRoot.querySelector(".cookroot");
    this._settingsRoot = this.shadowRoot.querySelector(".settingsroot");
    this._gear = this.shadowRoot.querySelector("[data-gear]");
    this._gear.addEventListener("click", () => this._openSettings());
    this._updateGear();
    const menu = document.createElement("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;
    this.shadowRoot.querySelector(".menu").appendChild(menu);
    this._menuButton = menu;
    this.shadowRoot.querySelectorAll(".tab").forEach((tab) =>
      tab.addEventListener("click", () => this._goTab(tab.dataset.tab))
    );
    const c = this._content;
    c.addEventListener("click", (ev) => this._onClick(ev));
    c.addEventListener("input", (ev) => this._onInput(ev));
    c.addEventListener("change", (ev) => this._onChange(ev));
    c.addEventListener("keydown", (ev) => {
      if (ev.target.dataset?.focuskey === "additem" && this._suggestKey(ev)) return;
      if (ev.key === "Enter" && ev.target.dataset.input === "so-query") {
        ev.preventDefault();
        clearTimeout(this._soTimer);
        this._fetchStoreOffers();
        return;
      }
      if (ev.key === "Enter" && ev.target.dataset.enter) {
        ev.preventDefault();
        this._run(ev.target.dataset.enter, ev.target);
      }
    });
    // suggestions: keep the focus in the input while tapping a hit (mousedown comes before blur)
    c.addEventListener("mousedown", (ev) => {
      if (ev.target.closest?.(".suggest")) ev.preventDefault();
    });
    c.addEventListener("focusout", (ev) => {
      if (ev.target.dataset?.focuskey !== "additem") return;
      clearTimeout(this._blurTimer);
      this._blurTimer = setTimeout(() => {
        if (this.shadowRoot.activeElement?.dataset?.focuskey !== "additem") this._closeSuggest();
      }, 180);
    });
    // remember which sections of the stores tab are open
    c.addEventListener(
      "toggle",
      (ev) => {
        const sec = ev.target;
        const key = sec?.dataset?.sec;
        // the browser also fires "toggle" for a <details open> it just rendered: only a change
        // of the shown state is the user's choice (a default stays a default)
        if (!key || sec.open === (sec.dataset.open === "1")) return;
        sec.dataset.open = sec.open ? "1" : "0";
        this._secOpen[key] = sec.open;
        this._setPref("sections", JSON.stringify(this._secOpen));
      },
      true
    );
    // drag & drop in the week plan
    c.addEventListener("dragstart", (ev) => {
      const meal = ev.target.closest?.("[data-drag-date]");
      if (!meal) return;
      ev.dataTransfer.setData("text/plain", JSON.stringify({ date: meal.dataset.dragDate, meal: meal.dataset.dragMeal }));
      ev.dataTransfer.effectAllowed = "move";
      meal.classList.add("dragging");
    });
    c.addEventListener("dragend", () => {
      c.querySelectorAll(".dragging, .over").forEach((el) => el.classList.remove("dragging", "over"));
    });
    c.addEventListener("dragover", (ev) => {
      const slot = ev.target.closest?.("[data-drop-date]");
      if (!slot) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      slot.classList.add("over");
    });
    c.addEventListener("dragleave", (ev) => {
      const slot = ev.target.closest?.("[data-drop-date]");
      if (slot && !slot.contains(ev.relatedTarget)) slot.classList.remove("over");
    });
    c.addEventListener("drop", async (ev) => {
      const slot = ev.target.closest?.("[data-drop-date]");
      if (!slot) return;
      ev.preventDefault();
      slot.classList.remove("over");
      let src;
      try {
        src = JSON.parse(ev.dataTransfer.getData("text/plain"));
      } catch (e) {
        return;
      }
      const to = { date: slot.dataset.dropDate, meal: slot.dataset.dropMeal };
      if (!src?.date || (src.date === to.date && src.meal === to.meal)) return;
      await this._service("move_meal", { from_date: src.date, from_meal: src.meal, to_date: to.date, to_meal: to.meal });
    });
    this.shadowRoot.querySelector(".fileinput").addEventListener("change", (ev) => this._importFile(ev));
  }

  _renderContent() {
    if (!this._data) return;
    this.shadowRoot.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === this._tab));
    if (this._shownTab !== this._tab) {
      // keep the active tab visible in the scrollable tab bar (phones)
      this._shownTab = this._tab;
      const bar = this.shadowRoot.querySelector(".tabs");
      const active = bar?.querySelector(".tab.active");
      if (bar && active && bar.scrollWidth > bar.clientWidth) {
        const left = active.offsetLeft - bar.offsetLeft;
        if (left < bar.scrollLeft || left + active.offsetWidth > bar.scrollLeft + bar.clientWidth) bar.scrollLeft = Math.max(0, left - 24);
      }
    }
    const open = (this._data.shopping || []).filter((i) => i.status !== "completed").length;
    this.shadowRoot.querySelector('[data-count="recipes"]').textContent = this._data.recipes.length;
    const shopCount = this.shadowRoot.querySelector('[data-count="shopping"]');
    shopCount.textContent = open;
    shopCount.style.display = open ? "" : "none";
    const offerCount = (this._data.offers || []).filter((o) => o.current && o.recipe_count).length;
    const oc = this.shadowRoot.querySelector('[data-count="offers"]');
    oc.textContent = offerCount;
    oc.style.display = offerCount ? "" : "none";
    const focused = this.shadowRoot.activeElement;
    const focusKey = focused?.dataset?.focuskey;
    const caret = focused?.selectionStart;
    if (this._tab !== "shopping") this._suggest.open = false;
    if (this._tab === "recipes") this._content.innerHTML = this._renderRecipes();
    else if (this._tab === "shopping") this._content.innerHTML = this._renderShopping();
    else if (this._tab === "offers") this._content.innerHTML = this._renderOffers();
    else if (this._tab === "stores") this._content.innerHTML = this._renderStores();
    else this._content.innerHTML = this._renderPlan();
    if (focusKey) {
      const el = this._content.querySelector(`[data-focuskey="${CSS.escape(focusKey)}"]`);
      if (el) {
        el.focus();
        if (caret != null && el.setSelectionRange) {
          try {
            el.setSelectionRange(caret, caret);
          } catch (e) {
            /* input type without a caret */
          }
        }
      }
    }
  }

  _goTab(tab, section) {
    this._tab = tab;
    this._setPref("tab", tab);
    if (section) {
      this._secOpen[section] = true;
      this._setPref("sections", JSON.stringify(this._secOpen));
    }
    // the stores tab loads its last search afterwards, which changes the height above the
    // section: scroll again once it is there (see _ensureStoresData)
    this._renderContent();
    const loading = this._branchSearchLoading || this._storePricesLoading;
    this._pendingScroll = section && tab === "stores" && loading ? section : null;
    if (section) this._content.querySelector(`#sec-${section}`)?.scrollIntoView({ block: "start", behavior: this._pendingScroll ? "auto" : "smooth" });
  }

  /** Scroll to the section requested by _goTab again after the stores tab data arrived. */
  _flushScroll() {
    const section = this._pendingScroll;
    if (!section) return;
    if (this._tab !== "stores") {
      this._pendingScroll = null;
      return;
    }
    this._content.querySelector(`#sec-${section}`)?.scrollIntoView({ block: "start" });
    if (!this._branchSearchLoading && !this._storePricesLoading) this._pendingScroll = null;
  }

  /* ------------------------------------------------------------ plan */
  _renderHero() {
    const now = new Date();
    const up = upcomingMeal(this._data, now);
    const greet = greeting(now);
    const week = this._data.plan;
    const today = this._today();
    const minis = [];
    for (let i = 1; i <= 3; i++) {
      const iso = toIso(addDays(fromIso(today), i));
      const entries = Object.entries(week[iso] || {});
      const main = entries.find(([m]) => m === this._data.default_meal) || entries[0];
      minis.push(
        `<div class="mini"><b>${esc(relativeDay(iso, today).split(",")[0])}</b><span>${main ? esc(main[1].title) : '<span class="meta">noch frei</span>'}</span></div>`
      );
    }
    const side = `<div class="side">${minis.join("")}</div>`;
    if (!up) {
      return `<div class="card hero">
          <div class="bigemoji">🧑‍🍳</div>
          <div>
            <div class="kicker">${esc(greet)}!</div>
            <div class="htitle">Für die nächsten Tage ist noch nichts geplant.</div>
            <div class="hmeta">Lass dir die Woche automatisch füllen oder such dir etwas aus.</div>
            <div class="hactions">
              <button class="btn primary" data-action="auto-plan-next">✨ Nächste 7 Tage planen</button>
              <button class="btn" data-action="add-entry" data-date="${today}" data-meal="${this._data.default_meal}" data-suggest="1">💡 Vorschlag für heute</button>
            </div>
          </div>${side}</div>`;
    }
    const recipe = this._recipe(up.entry.recipe_id);
    const when = relativeDay(up.date, today);
    const img = recipe?.image && safeUrl(recipe.image);
    const meta = [
      up.time ? `${up.time} Uhr` : "",
      up.entry.servings ? `${up.entry.servings} Portionen` : "",
      recipe?.total_time ? `⏱ ${recipe.total_time} min` : "",
      up.entry.note || "",
    ].filter(Boolean);
    return `<div class="card hero ${img ? "img" : ""}" style="--hero-color:${this._mealColor(up.meal)};${img ? `background-image:url('${img}')` : ""}">
        ${img ? "" : `<div class="bigemoji">${recipe ? dishEmoji(recipe.name) : "📝"}</div>`}
        <div>
          <div class="kicker">${esc(greet)}! · ${esc(when)} · ${esc(this._mealLabel(up.meal))}</div>
          <div class="htitle">${esc(up.entry.title)}</div>
          <div class="hmeta">${esc(meta.join(" · "))}</div>
          <div class="hactions">
            ${recipe ? `<button class="btn primary" data-action="cook" data-id="${esc(recipe.id)}" data-date="${up.date}" data-meal="${up.meal}" data-servings="${up.entry.servings || ""}">👩‍🍳 Kochmodus</button>` : ""}
            ${recipe ? `<button class="btn" data-action="open-recipe" data-id="${esc(recipe.id)}" data-servings="${up.entry.servings || ""}">📖 Rezept</button>` : ""}
            <button class="btn" data-action="open-entry" data-date="${up.date}" data-meal="${up.meal}">✏️ Ändern</button>
          </div>
        </div>${side}</div>`;
  }

  _renderPlan() {
    const start = this._weekStart;
    const end = addDays(start, 6);
    const today = this._today();
    const label = `KW ${isoWeek(start)} · ${start.getDate()}.${start.getMonth() === end.getMonth() ? "" : " " + MONTHS[start.getMonth()]} – ${end.getDate()}. ${MONTHS[end.getMonth()]}`;
    let planned = 0;
    let days = "";
    const weekCosts = this._weekCostMap(start);
    for (let i = 0; i < 7; i++) {
      const day = addDays(start, i);
      const iso = toIso(day);
      const meals = this._data.plan[iso] || {};
      const slotIds = [...this._data.meals.map((m) => m.id), ...Object.keys(meals).filter((id) => !this._data.meals.some((m) => m.id === id))];
      const slots = slotIds
        .map((mealId) => {
          const entry = meals[mealId];
          const color = this._mealColor(mealId);
          let inner;
          if (entry) {
            planned += 1;
            const recipe = this._recipe(entry.recipe_id);
            const sub = [entry.servings ? `👥 ${entry.servings}` : "", recipe?.total_time ? `⏱ ${recipe.total_time} min` : "", entry.note || ""].filter(Boolean).join(" · ");
            const mc = weekCosts?.[iso]?.[mealId];
            const costHtml = mc?.cost != null ? `<span class="cost">≈ ${eur(mc.cost)}</span>${mc.on_offer?.length ? `<span class="tagoffer" title="Im Angebot: ${esc(mc.on_offer.join(", "))}">🏷️ ${mc.on_offer.length}</span>` : ""}` : "";
            const thumb = recipe?.image && safeUrl(recipe.image)
              ? `<span class="thumb" ${bg(recipe.image)}></span>`
              : `<span class="thumb">${entry.cooked ? "✅" : recipe ? dishEmoji(recipe.name) : "📝"}</span>`;
            inner = `<button class="meal ${recipe ? "" : "free"} ${entry.cooked ? "cooked" : ""}" draggable="true" data-drag-date="${iso}" data-drag-meal="${mealId}" data-action="open-entry" data-date="${iso}" data-meal="${mealId}" title="Klicken zum Bearbeiten, ziehen zum Verschieben">
                ${thumb}<span><div class="t">${esc(entry.title)}</div>${sub || costHtml ? `<div class="s">${esc(sub)} ${costHtml}</div>` : ""}</span>
              </button>`;
          } else {
            inner = `<button class="add" data-action="add-entry" data-date="${iso}" data-meal="${mealId}">＋ <span>hinzufügen</span></button>`;
          }
          return `<div class="slot" style="--meal-color:${color}" data-drop-date="${iso}" data-drop-meal="${mealId}"><div class="label"><i></i>${esc(this._mealLabel(mealId))}</div>${inner}</div>`;
        })
        .join("");
      const cls = iso === today ? "today" : iso < today ? "past" : "";
      days += `<div class="card day ${cls}">
          <div class="dayhead"><span class="wd">${WEEKDAYS[i]}</span><span class="dt">${day.getDate()}. ${MONTHS[day.getMonth()]}</span>${iso === today ? '<span class="badge">Heute</span>' : ""}</div>
          ${slots}
        </div>`;
    }
    const capacity = 7 * this._data.meals.length;
    const pct = capacity ? Math.min(100, Math.round((planned / capacity) * 100)) : 0;
    return `
      ${this._renderHero()}
      <div class="row">
        <button class="icon" data-action="week" data-delta="-7" title="Vorherige Woche">◀</button>
        <div class="weeklabel">${esc(label)}</div>
        <button class="icon" data-action="week" data-delta="7" title="Nächste Woche">▶</button>
        <button class="btn small" data-action="week" data-delta="0">Heute</button>
        <div class="progress" title="${planned} von ${capacity} Mahlzeiten geplant"><div style="width:${pct}%"></div></div>
        <span class="meta">${planned}/${capacity} geplant</span>
        ${this._budgetPill(start)}
        <span class="spacer"></span>
        <button class="btn" data-action="copy-week" title="Plan der Vorwoche in diese Woche übernehmen">⧉ Letzte Woche übernehmen</button>
        <button class="btn" data-action="auto-plan">✨ Automatisch planen</button>
        <button class="btn primary" data-action="shopping-from-week">🛒 Einkaufsliste</button>
      </div>
      <div class="week">${days}</div>
      <p class="hint" style="text-align:center;margin-top:14px">Tipp: Mahlzeiten mit der Maus auf einen anderen Tag ziehen – belegte Plätze werden getauscht.</p>`;
  }

  _weekCostMap(start) {
    const key = toIso(start);
    if (!this._costs) this._costs = {};
    if (!(key in this._costs)) {
      this._costs[key] = null;
      this._service("get_costs", { start_date: key, days: 7 }, true)
        .then((res) => {
          this._costs[key] = res;
          if (this._tab === "plan" && toIso(this._weekStart) === key) this._renderContent();
        })
        .catch(() => {});
    }
    const res = this._costs[key];
    if (!res) return null;
    const map = {};
    for (const day of res.days || []) {
      map[day.date] = {};
      for (const m of day.meals || []) map[day.date][m.meal] = m;
    }
    map.total = res.total;
    map.savings = res.savings;
    return map;
  }

  _budgetPill(start) {
    const res = this._costs?.[toIso(start)];
    if (!res) return "";
    const budget = this._data.economy?.budget;
    if (!budget) return res.total ? `<span class="budget" title="Geschätzte Kosten der geplanten Rezepte">💶 ≈ ${eur(res.total)}</span>` : "";
    const ratio = res.total / budget;
    const cls = ratio > 1 ? "over" : ratio > 0.85 ? "warn" : "";
    return `<span class="budget ${cls}" title="Geschätzte Kosten / Wochenbudget">💶 ${eur(res.total)} / ${eur(budget)}</span>`;
  }

  _weekRemaining() {
    const today = fromIso(this._today());
    const start = this._weekStart < today ? today : this._weekStart;
    const end = addDays(this._weekStart, 6);
    const days = Math.round((end - start) / 86400000) + 1;
    return { start: toIso(start), days: Math.max(days, 0) };
  }

  /* ------------------------------------------------------------ recipes */
  _filteredRecipes() {
    const q = fold(this._search).trim();
    const list = this._data.recipes.filter((r) => {
      if (this._favOnly && !r.favorite) return false;
      if (this._tag && !(r.tags || []).some((t) => fold(t) === fold(this._tag))) return false;
      if (!q) return true;
      const hay = fold([r.name, ...(r.tags || []), ...(r.ingredients || []).map((i) => i.name)].join(" "));
      return q.split(/\s+/).every((w) => hay.includes(w));
    });
    const byName = (a, b) => a.name.localeCompare(b.name, "de");
    const sorters = {
      fav: (a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0) || byName(a, b),
      name: byName,
      recent: (a, b) => (b.last_cooked || "").localeCompare(a.last_cooked || "") || byName(a, b),
      often: (a, b) => (b.cooked_count || 0) - (a.cooked_count || 0) || byName(a, b),
      quick: (a, b) => (a.total_time || 9999) - (b.total_time || 9999) || byName(a, b),
      cheap: (a, b) => (this._data.recipe_costs?.[a.id] ?? 99) - (this._data.recipe_costs?.[b.id] ?? 99) || byName(a, b),
      rating: (a, b) => (b.rating || 0) - (a.rating || 0) || byName(a, b),
      new: (a, b) => (b.created || "").localeCompare(a.created || "") || byName(a, b),
    };
    return list.sort(sorters[this._sort] || sorters.fav);
  }

  _renderRecipes() {
    const tags = [...new Set(this._data.recipes.flatMap((r) => r.tags || []))].sort((a, b) => a.localeCompare(b, "de"));
    const recipes = this._filteredRecipes();
    const cards = recipes
      .map((r) => {
        const perServing = this._data.recipe_costs?.[r.id];
        const meta = [r.total_time ? `⏱ ${r.total_time} min` : "", perServing ? `💶 ≈ ${eur(perServing)}/Port.` : "", r.cooked_count ? `🍳 ${r.cooked_count}×` : ""].filter(Boolean).join(" · ");
        return `<div class="card recipe" data-action="open-recipe" data-id="${esc(r.id)}">
            <div class="img" ${bg(r.image)}>${safeUrl(r.image) ? "" : dishEmoji(r.name)}
              <button class="icon fav ${r.favorite ? "on" : ""}" data-action="toggle-fav" data-id="${esc(r.id)}" title="Favorit">${r.favorite ? "★" : "☆"}</button>
            </div>
            <div class="body">
              <div class="name">${esc(r.name)}</div>
              ${r.rating ? `<div class="stars">${stars(r.rating)}</div>` : ""}
              ${meta ? `<div class="meta">${meta}</div>` : ""}
              <div class="chips">${(r.tags || []).slice(0, 4).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
            </div>
          </div>`;
      })
      .join("");
    return `
      <div class="row">
        <input type="search" placeholder="🔍 Rezepte oder Zutaten suchen …" value="${esc(this._search)}" data-input="search" data-focuskey="search" style="flex:1;min-width:200px">
        <select data-change="sort" title="Sortierung">${Object.entries(SORTS).map(([k, v]) => `<option value="${k}" ${k === this._sort ? "selected" : ""}>${v}</option>`).join("")}</select>
        <button class="btn ${this._favOnly ? "primary" : ""}" data-action="fav-only">★ Favoriten</button>
      </div>
      <div class="row">
        <button class="btn primary" data-action="new-recipe">＋ Neues Rezept</button>
        <button class="btn" data-action="import">🌐 Von URL importieren</button>
        <button class="btn" data-action="cook-with">🧊 Was kann ich kochen?</button>
        <span class="spacer"></span>
        <button class="btn ghost" data-action="backup">💾 Sichern & Teilen</button>
      </div>
      <div class="row chips tagrow">
        <button class="chip ${this._tag ? "" : "active"}" data-action="tag" data-tag="">Alle (${this._data.recipes.length})</button>
        ${tags.map((t) => `<button class="chip ${fold(t) === fold(this._tag) ? "active" : ""}" data-action="tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}
      </div>
      ${recipes.length ? `<div class="recipes">${cards}</div>` : `<div class="empty"><div class="big">📖</div>Keine Rezepte gefunden.</div>`}`;
  }

  /* ------------------------------------------------------------ shopping */
  _splitActive() {
    return Boolean(this._data?.store_split?.active);
  }

  _byStore() {
    return this._splitActive() && this._pref("shopmode", "store") === "store";
  }

  _branch(id) {
    return id ? (this._data?.branches || []).find((b) => b.id === id) : undefined;
  }

  /** Branches for display: main branch first, then by priority (= order in data). */
  _orderedBranches() {
    const list = [...(this._data?.branches || [])];
    return [...list.filter((b) => b.main), ...list.filter((b) => !b.main)];
  }

  _retailerName(id) {
    return (this._data?.economy?.retailers || []).find((r) => r.id === id)?.name || id || "";
  }

  _retailerKind(id) {
    return (this._data?.economy?.retailers || []).find((r) => r.id === id)?.kind || null;
  }

  _catRank(cat) {
    const i = CATEGORY_ORDER.indexOf(cat || "Sonstiges");
    return i === -1 ? 99 : i;
  }

  _openItemsByStore() {
    const open = (this._data.shopping || []).filter((i) => i.status !== "completed");
    const known = new Set((this._data.branches || []).map((b) => b.id));
    const groupOf = (i) => (known.has(i.branch_id) ? i.branch_id : null);
    const groups = [...(this._data.shopping_stores || [])];
    const missing = open.filter((i) => !groups.some((g) => g.branch_id === groupOf(i)));
    if (missing.length) {
      // e.g. items added a moment ago: shown in their store (or "Ohne Laden") until the next update
      for (const id of [...new Set(missing.map(groupOf))]) {
        const b = this._branch(id);
        const list = missing.filter((i) => groupOf(i) === id);
        const priced = list.filter((i) => i.price != null);
        groups.push({ branch_id: id, retailer: b?.retailer || null, label: b?.label || "Ohne Laden", main: Boolean(b?.main), open: list.length, priced: priced.length, subtotal: priced.reduce((a, i) => a + i.price, 0), saving: 0 });
      }
    }
    return groups.map((group) => ({
      group,
      items: open
        .filter((i) => groupOf(i) === group.branch_id)
        .sort((a, b) => this._catRank(a.category) - this._catRank(b.category)),
    }));
  }

  _renderShopping() {
    const items = this._data.shopping || [];
    const open = items.filter((i) => i.status !== "completed");
    const done = items.filter((i) => i.status === "completed");
    const split = this._splitActive();
    const byStore = this._byStore();
    const groups = {};
    for (const item of open) (groups[item.category || "Sonstiges"] ||= []).push(item);
    const describe = (item) => {
      const parts = (item.description || "")
        .split(" · ")
        .map((p) => p.trim())
        .filter((p) => p && !p.startsWith("≈ ") && !p.startsWith("🏷️ ") && !(byStore && p.startsWith("🏪 ")));
      return parts.filter((p) => !(item.status !== "completed" && p === item.category)).join(" · ");
    };
    const renderItem = (item) => {
      const isOpen = item.status !== "completed";
      const reason = byStore && isOpen ? REASON_CHIP[item.store_reason] : null;
      const saving = byStore && isOpen && item.saving > 0 ? `<span class="sv">spart ${eur(item.saving)}</span>` : "";
      const offer = item.offer ? `<span class="o">🏷️ ${byStore ? "Angebot" : esc(item.offer.store || "Angebot")}</span>` : "";
      return `
      <div class="item ${isOpen ? "" : "done"}">
        <label class="chk"><input type="checkbox" data-change="toggle-item" data-uid="${esc(item.uid)}" ${isOpen ? "" : "checked"} aria-label="${esc(item.summary)} erledigt"></label>
        <div class="txt"><div class="sum">${esc(item.summary)}${reason && item.store_reason !== "offer" ? `<span class="reason ${reason[1]}" title="${esc(reason[2])}">${reason[0]}</span>` : ""}</div>${describe(item) ? `<div class="desc">${esc(describe(item))}</div>` : ""}</div>
        ${item.price != null ? `<div class="price">≈ ${eur(item.price)}${offer}${saving}</div>` : ""}
        ${split && isOpen ? `<button class="icon swap" data-action="pick-store" data-uid="${esc(item.uid)}" title="Laden wählen" aria-label="Laden wählen">⇄</button>` : ""}
        <button class="icon" data-action="delete-item" data-uid="${esc(item.uid)}" title="Entfernen" aria-label="Entfernen">✕</button>
      </div>`;
    };
    let listHtml;
    if (byStore) {
      listHtml = this._openItemsByStore()
        .filter(({ items: list }) => list.length)
        .map(({ group, items: list }) => {
          let lastCat = null;
          const rows = list
            .map((item) => {
              const cat = item.category || "Sonstiges";
              const head = cat !== lastCat ? `<div class="aisle">${CATEGORY_ICONS[cat] || "🛒"} ${esc(cat)}</div>` : "";
              lastCat = cat;
              return head + renderItem(item);
            })
            .join("");
          const stats = [`${list.length} offen`, group.priced ? `≈ ${eur(group.subtotal)}` : ""].filter(Boolean).join(" · ");
          return `<div class="card group storecard">
            <div class="storehead">${group.branch_id ? retailerDot(group.retailer, group.label) : '<span class="rdot" style="background:var(--ep-divider)">?</span>'}<span class="sname">${esc(group.label)}</span>${group.main ? '<span class="bdg star">⭐ Hauptladen</span>' : ""}
              <span class="sstat">${stats}${group.saving > 0 ? ` · <span class="save">🏷️ spart ${eur(group.saving)}</span>` : ""}</span></div>
            ${rows}</div>`;
        })
        .join("");
    } else {
      listHtml = Object.keys(groups)
        .sort((a, b) => this._catRank(a) - this._catRank(b))
        .map((cat) => `<div class="card group"><h3>${CATEGORY_ICONS[cat] || "🛒"} ${esc(cat)} <span class="meta">${groups[cat].length}</span></h3>${groups[cat].map(renderItem).join("")}</div>`)
        .join("");
    }
    const total = items.length;
    const pct = total ? Math.round((done.length / total) * 100) : 0;
    const priced = open.filter((i) => i.price != null);
    const sum = priced.reduce((acc, i) => acc + i.price, 0);
    const offersUsed = open.filter((i) => i.offer).length;
    const branches = this._data.branches || [];
    const mode = this._data.store_split?.mode;
    let hint = "";
    if (!split && !branches.length && this._pref("storehint", "on") !== "off") {
      hint = `<div class="notice hintcard"><span>🏪 <b>Tipp:</b> Wähle im Tab <button class="btn small" data-action="go-tab" data-tab="stores" data-sec="mine">🏪 Läden & Preise</button> deinen Hauptladen, dann wird die Liste nach Läden sortiert.</span><button class="icon" data-action="hide-storehint" title="Tipp ausblenden" aria-label="Tipp ausblenden">✕</button></div>`;
    } else if (!split && mode === "off") {
      hint = `<div class="hint" style="margin-bottom:10px">ℹ️ Die Aufteilung nach Läden ist in den Einstellungen ausgeschaltet. Einschalten: ${this._settingsLink("stores", "⚙️ Läden & Einkauf")}</div>`;
    }
    return `<div class="shopping">
      ${total ? `<div class="card shopstat"><span class="num">${open.length}</span><span class="meta">offen<br>${done.length} erledigt</span><div class="progress"><div style="width:${pct}%"></div></div><span class="meta">${pct}%</span>${priced.length ? `<span class="meta" style="text-align:right"><b style="font-size:16px;color:var(--primary-text-color)">≈ ${eur(sum)}</b><br>${offersUsed ? `🏷️ ${offersUsed} im Angebot · ` : ""}ganze Packungen</span>` : ""}</div>` : ""}
      ${hint}
      <div class="row addrow">
        <div class="addwrap">
          <input placeholder="${window.innerWidth < 600 ? "Artikel, z. B. „2 Liter Milch“" : "Artikel hinzufügen, z. B. „2 Liter Milch“"}" aria-label="Artikel hinzufügen" data-enter="add-item" data-focuskey="additem" data-input="additem" value="${esc(this._addText)}" autocomplete="off" autocapitalize="sentences" enterkeyhint="done" role="combobox" aria-autocomplete="list" aria-expanded="${this._suggest.open ? "true" : "false"}">
          <div class="suggest" role="listbox" ${this._suggest.open ? "" : "hidden"}>${this._suggest.open ? this._suggestHtml() : ""}</div>
        </div>
        <button class="btn primary" data-action="add-item">Hinzufügen</button>
      </div>
      <div class="row">
        ${split ? `<div class="seg" role="group" aria-label="Sortierung"><button class="${byStore ? "on" : ""}" data-action="shop-mode" data-mode="store">🏪 Nach Laden</button><button class="${byStore ? "" : "on"}" data-action="shop-mode" data-mode="aisle">🧺 Nach Abteilung</button></div>` : ""}
        <button class="btn" data-action="shopping-next-week">🗓️ Aus Plan (7 Tage) erstellen</button>
        ${open.length ? `<button class="btn" data-action="share-list">📤 Teilen / Kopieren</button>` : ""}
        ${split && open.length ? `<button class="btn" data-action="assign-stores" title="Alle offenen Artikel neu auf die Läden verteilen">🔄 Läden neu zuordnen</button>` : ""}
        ${this._isAdmin() ? `<button class="btn" data-action="receipt-new" title="Kassenzettel fotografieren oder Text einfügen – seine Preise werden die Preise des Ladens">🧾 Kassenzettel</button>` : ""}
        <span class="spacer"></span>
        ${done.length ? `<button class="btn ghost" data-action="clear-done">🧹 Erledigte entfernen (${done.length})</button>` : ""}
        ${total ? `<button class="btn danger" data-action="clear-all">🗑 Liste leeren</button>` : ""}
      </div>
      ${open.length ? listHtml : `<div class="empty"><div class="big">${done.length ? "🎉" : "🛒"}</div>${done.length ? "Alles erledigt!" : "Die Einkaufsliste ist leer."}<br><span class="hint">Plane Mahlzeiten und erstelle die Liste per Knopfdruck – oder sag „Jarvis, erstelle die Einkaufsliste“.</span></div>`}
      ${done.length ? `<div class="card group"><h3>✅ Erledigt</h3>${done.map(renderItem).join("")}</div>` : ""}
    </div>`;
  }

  _shoppingText() {
    if (this._byStore()) {
      return this._openItemsByStore()
        .filter(({ items }) => items.length)
        .map(({ group, items }) => {
          const extra = [group.priced ? `≈ ${eur(group.subtotal)}` : "", group.saving > 0 ? `spart ${eur(group.saving)}` : ""].filter(Boolean).join(", ");
          return `🏪 ${group.label}${extra ? ` (${extra})` : ""}\n${items.map((i) => `• ${i.summary}${i.offer ? " 🏷️" : ""}`).join("\n")}`;
        })
        .join("\n\n");
    }
    const groups = {};
    for (const item of this._data.shopping.filter((i) => i.status !== "completed")) (groups[item.category || "Sonstiges"] ||= []).push(item.summary);
    return Object.entries(groups)
      .sort((a, b) => this._catRank(a[0]) - this._catRank(b[0]))
      .map(([cat, list]) => `${CATEGORY_ICONS[cat] || "🛒"} ${cat}\n${list.map((s) => `• ${s}`).join("\n")}`)
      .join("\n\n");
  }

  /* ------------------------------------------------------------ article search ("Artikel hinzufügen") */
  _suggestInput() {
    return this._content.querySelector('[data-focuskey="additem"]');
  }

  _expectLive() {
    const eco = this._data?.economy || {};
    return (
      eco.offers_source === "marktguru" ||
      (eco.price_sources?.rewe?.enabled && eco.main_retailer === "rewe") ||
      (eco.price_sources?.aldi?.enabled && eco.main_retailer === "aldi-sued")
    );
  }

  _scheduleSuggest() {
    clearTimeout(this._suggestTimer);
    const { query } = splitQuantity(this._addText);
    if (query.length < 2) {
      this._suggestSeq += 1; // drop answers still on their way
      this._closeSuggest();
      return;
    }
    this._suggestTimer = setTimeout(() => this._runSuggest(query), 300);
  }

  async _runSuggest(query) {
    const seq = ++this._suggestSeq;
    const live = this._expectLive() && query.length >= 3;
    const s = this._suggest;
    const opening = !s.open;
    Object.assign(s, { open: true, query, loading: true, live, error: null });
    if (s.lastQuery !== query) s.index = -1;
    this._renderSuggest();
    if (opening) this._fitSuggest(undefined, undefined, true);
    let localDone = false;
    try {
      const local = await this._hass.callWS({ type: `${DOMAIN}/article_search`, query, live: false });
      if (seq !== this._suggestSeq) return;
      localDone = true;
      this._setSuggestResults(local, query, live);
      if (!live) return;
      const online = await this._hass.callWS({ type: `${DOMAIN}/article_search`, query, live: true });
      if (seq !== this._suggestSeq) return;
      if (online.superseded) {
        s.loading = false;
      } else {
        this._setSuggestResults(online, query, false);
        s.error = online.error ? `Online-Suche: ${online.error}` : null;
      }
    } catch (err) {
      if (seq !== this._suggestSeq) return;
      Object.assign(s, { loading: false, error: `${localDone ? "Online-Suche: " : ""}${errText(err)}` });
    }
    this._renderSuggest();
  }

  _setSuggestResults(res, query, stillLoading) {
    const s = this._suggest;
    const ident = (r) => r && `${r.title}|${r.pack}|${r.source}|${r.offer?.id || ""}`;
    const current = ident(s.results[s.index]);
    s.results = res?.results || [];
    s.store = res?.store || null;
    s.loading = stillLoading;
    s.lastQuery = query;
    s.index = current ? s.results.findIndex((r) => ident(r) === current) : -1;
    if (s.open) this._renderSuggest();
  }

  _closeSuggest() {
    clearTimeout(this._suggestTimer);
    if (!this._suggest.open) return;
    this._suggest.open = false;
    this._suggest.index = -1;
    this._renderSuggest();
  }

  _renderSuggest(scroll = false) {
    const box = this._content.querySelector(".suggest");
    const input = this._suggestInput();
    if (!box) return;
    const open = this._suggest.open;
    box.hidden = !open;
    box.innerHTML = open ? this._suggestHtml() : "";
    input?.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) this._fitSuggest(box, input);
    const sel = scroll && box.querySelector(".sugg.sel");
    if (sel) {
      const top = sel.offsetTop;
      if (top < box.scrollTop) box.scrollTop = top;
      else if (top + sel.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = top + sel.offsetHeight - box.clientHeight;
    }
  }

  /** Keep the suggestions above the bottom of the visible area (phone keyboard). */
  _fitSuggest(box = this._content.querySelector(".suggest"), input = this._suggestInput(), makeRoom = false) {
    if (!box || box.hidden || !input) return;
    const vv = window.visualViewport;
    const bottom = vv ? vv.offsetTop + vv.height : window.innerHeight;
    let space = bottom - input.getBoundingClientRect().bottom - 12;
    if (makeRoom && space < 240) {
      // too close to the keyboard / bottom: move the field up (below the sticky header)
      input.scrollIntoView({ block: "start" });
      space = bottom - input.getBoundingClientRect().bottom - 12;
    }
    box.style.maxHeight = `${Math.round(Math.max(140, Math.min(440, space)))}px`;
  }

  _suggestHtml() {
    const s = this._suggest;
    const store = s.store;
    const head = store
      ? `<div class="shint top">${retailerDot(store.retailer, store.retailer_name).replace('class="rdot"', 'class="rdot sm"')}<span>Artikel bei <b>${esc(store.label)}</b>${store.main ? " (Hauptladen)" : ""}</span></div>`
      : "";
    const rows = s.results
      .map((r, i) => {
        const shop = SHOP_PROVIDERS[r.provider];
        const offer = r.offer && !shop;
        const sourceHint =
          r.source === "live"
            ? shop
              ? shop
              : "🏷️ Prospekt (online)"
            : ARTICLE_SOURCE[r.source] || "";
        const until = offer && r.offer?.valid_to ? ` bis ${shortDate(r.offer.valid_to)}` : "";
        const where = r.retailer ? this._retailerName(r.retailer) : "Allgemein";
        const sub = [where, sourceHint + until, r.count > 1 ? `${r.count}× gekauft` : ""].filter(Boolean).join(" · ");
        return `<button class="sugg ${i === s.index ? "sel" : ""}" data-sugg="${i}" role="option" aria-selected="${i === s.index}" tabindex="-1">
          <span class="st"><div class="t">${esc(r.title)}${r.pack ? ` <span class="meta">${esc(r.pack)}</span>` : ""}${offer ? ' <span class="tagoffer">🏷️ Angebot</span>' : ""}</div><div class="sub">${esc(sub)}</div></span>
          <span class="sp">${r.price != null ? `<b>${eur(r.price)}</b>` : '<span class="meta">kein Preis</span>'}${r.unit_price != null && r.base && r.base !== "Stück" ? `<span class="meta">${esc(unitPriceText(r.unit_price, r.base))}</span>` : ""}</span>
        </button>`;
      })
      .join("");
    let foot = "";
    if (s.loading) foot = `<div class="shint">⏳ Suche …</div>`;
    else if (!s.results.length) foot = `<div class="shint">Keine Treffer – Enter fügt den Text hinzu</div>`;
    if (s.error) foot += `<div class="shint">⚠️ ${esc(s.error)}</div>`;
    return head + rows + foot;
  }

  /** Arrow keys / Enter / Escape in the add field. Returns true if handled. */
  _suggestKey(ev) {
    const s = this._suggest;
    if (ev.key === "Escape") {
      if (!s.open) return false;
      ev.preventDefault();
      ev.stopPropagation();
      this._closeSuggest();
      return true;
    }
    if (ev.key === "ArrowDown" && !s.open) {
      // closed with Escape: arrow down opens the suggestions again
      const { query } = splitQuantity(this._addText);
      if (query.length < 2) return false;
      ev.preventDefault();
      clearTimeout(this._suggestTimer);
      this._runSuggest(query);
      return true;
    }
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      if (!s.open || !s.results.length) return false;
      ev.preventDefault();
      const n = s.results.length;
      s.index = ev.key === "ArrowDown" ? (s.index + 1) % n : s.index <= 0 ? n - 1 : s.index - 1;
      this._renderSuggest(true);
      return true;
    }
    if (ev.key === "Enter" && s.open && s.index >= 0 && s.results[s.index]) {
      ev.preventDefault();
      this._addSuggestion(s.index).catch(() => {});
      return true;
    }
    return false;
  }

  async _addSuggestion(index) {
    const s = this._suggest;
    const r = s.results[index];
    if (!r) return;
    const { prefix } = splitQuantity(this._addText);
    // typed amount wins over the amount of a remembered article ("3 Milch" + "2 Liter Milch")
    const data = { item: (prefix ? `${prefix}${splitQuantity(r.title).query || r.title}` : r.title).trim() };
    // A hit of the searched store (the main store) is no store choice: the item stays in the
    // automatic assignment ("Hauptladen + Ausnahmen") and still moves to a better offer
    // elsewhere. Only a hit of another store (or of a retailer without branches) names it.
    let store = null;
    if (r.branch_id) store = r.branch_id !== (s.store?.branch_id || null) ? r.branch_id : null;
    else if (!this._splitActive()) store = r.retailer || null;
    if (store) data.store = store;
    if (STORE_PRICE_HITS.has(r.source)) {
      if (r.price != null) data.price = r.price;
      if (r.pack) data.pack = r.pack;
    }
    // saved offers (a live leaflet offer has the id it is saved under by the offer refresh)
    const leaflet = r.source === "offer" || (r.source === "live" && !SHOP_PROVIDERS[r.provider]);
    if (leaflet && r.offer?.id) data.offer_id = r.offer.id;
    const typed = this._addText;
    this._addText = "";
    this._suggestSeq += 1;
    const input = this._suggestInput();
    if (input) input.value = "";
    this._closeSuggest();
    let res;
    try {
      res = await this._service("add_shopping_item", data, true);
    } catch (err) {
      // keep what was typed so nothing is lost
      this._addText = typed;
      const field = this._suggestInput();
      if (field && !field.value) field.value = typed;
      throw err;
    }
    // where and for how much it was put on the list (it may have gone to another store)
    const item = res?.item || {};
    const label = item.store_label || (r.retailer ? this._retailerName(r.retailer) : "");
    const cost = item.price ?? data.price;
    const price = cost != null ? ` für ${data.price != null ? "" : "≈ "}${eur(cost)}` : "";
    this._toast(`🛒 ${data.item}${data.pack ? ` (${data.pack})` : ""}${price}${label ? ` bei ${label}` : ""} hinzugefügt`);
  }

  async _share(title, text) {
    try {
      if (navigator.share) {
        await navigator.share({ title, text });
        return;
      }
    } catch (e) {
      if (e?.name === "AbortError") return;
    }
    try {
      await navigator.clipboard.writeText(text);
      this._toast("In die Zwischenablage kopiert 📋");
    } catch (e) {
      this._toast("Kopieren nicht möglich");
    }
  }

  /* ------------------------------------------------------------ events */
  _handleKey(ev) {
    if (this._settings && !this._modal) {
      if (ev.key === "Escape") {
        ev.preventDefault();
        this._closeSettings();
      }
      return;
    }
    if (this._cook) {
      if (ev.key === "Escape") this._closeCooking();
      else if (ev.key === "ArrowRight" || ev.key === " ") {
        ev.preventDefault();
        this._cookGo(1);
      } else if (ev.key === "ArrowLeft") this._cookGo(-1);
      return;
    }
    if (ev.key === "Escape" && this._modal) this._requestCloseModal();
  }

  _onInput(ev) {
    const t = ev.target;
    const kind = t.dataset.input;
    if (kind === "search") {
      this._search = t.value;
      this._renderContent();
    } else if (kind === "additem") {
      this._addText = t.value;
      // typed on: Enter adds the typed text (not the hit highlighted before) until new hits come
      if (this._suggest.index !== -1) {
        this._suggest.index = -1;
        this._renderSuggest();
      }
      this._scheduleSuggest();
    } else if (kind === "price-filter") {
      this._priceQuery = t.value;
      this._priceLimit = 50;
      clearTimeout(this._priceTimer);
      this._priceTimer = setTimeout(() => this._fetchStorePrices(), 300);
    } else if (kind === "manual") {
      this._manual[t.dataset.field] = t.value;
    } else if (kind === "so-query") {
      this._so.query = t.value;
      clearTimeout(this._soTimer);
      this._soTimer = setTimeout(() => this._fetchStoreOffers(), 350);
    } else if (kind === "rewe-id") {
      this._reweInput[t.dataset.id] = t.value;
      const b = this._branch(t.dataset.id);
      const link = STORE_LINKS[b?.retailer] || STORE_LINKS.rewe;
      const save = t.parentElement?.querySelector('[data-action="rewe-save"]');
      if (save) save.hidden = t.value.trim() === (b?.[link.field] || "");
    }
  }

  async _onChange(ev) {
    const t = ev.target;
    const kind = t.dataset.change;
    try {
      if (kind === "toggle-item") {
        await this._todo("update_item", { item: t.dataset.uid, status: t.checked ? "completed" : "needs_action" });
      } else if (kind === "sort") {
        this._sort = t.value;
        this._setPref("sort", t.value);
        this._renderContent();
      } else if (kind === "branch-selected") {
        const b = this._branch(t.dataset.id);
        const checked = t.checked;
        // pausing the main store also removes it as main store: ask first
        if (b?.main && !checked && !confirm(`„${b.label}“ ist dein Hauptladen. Pausierst du ihn, ist er nicht mehr Hauptladen – wähle dann einen anderen, sonst wird die Einkaufsliste nicht nach Läden aufgeteilt. Trotzdem pausieren?`)) {
          t.checked = true;
          return;
        }
        const res = await this._service("save_branch", { id: t.dataset.id, selected: checked }, true);
        this._applyBranch(res?.branch);
        if (b) this._toast(checked ? `▶️ ${b.label} ist wieder aktiv` : b.main ? `⏸ ${b.label} pausiert – bitte einen neuen Hauptladen wählen` : `⏸ ${b.label} pausiert – wird bei Einkauf und Angeboten nicht genutzt`);
      } else if (kind === "search-route") {
        this._searchRoute = t.checked;
      } else if (kind === "search-radius") {
        this._searchRadius = Number(t.value);
      } else if (kind === "price-store") {
        this._priceStore = t.value;
        this._renderPriceMatrix();
      } else if (kind === "so-sort") {
        this._so.sort = t.value;
        this._setPref("offers_sort", t.value);
        this._fetchStoreOffers();
      } else if (kind === "manual") {
        this._manual[t.dataset.field] = t.value;
      }
    } catch (e) {
      if (kind === "branch-selected") this._renderContent(); // undo the checkbox
    }
  }

  _onClick(ev) {
    const sugg = ev.target.closest("[data-sugg]");
    if (sugg && this._content.contains(sugg)) {
      ev.stopPropagation();
      this._addSuggestion(Number(sugg.dataset.sugg)).catch(() => {});
      return;
    }
    const el = ev.target.closest("[data-action]");
    if (!el || !this._content.contains(el)) return;
    ev.stopPropagation();
    this._run(el.dataset.action, el);
  }

  /** Run an action; errors were already shown as a toast by _service. */
  _run(action, el) {
    Promise.resolve()
      .then(() => this._action(action, el))
      .catch(() => {});
  }

  async _action(action, el) {
    const d = el.dataset;
    switch (action) {
      case "week":
        this._weekStart = d.delta === "0" ? mondayOf(fromIso(this._today())) : addDays(this._weekStart, Number(d.delta));
        this._renderContent();
        break;
      case "add-entry":
        this._openPicker(d.date, d.meal, null, Boolean(d.suggest));
        break;
      case "open-entry":
        this._openEntry(d.date, d.meal);
        break;
      case "cook":
        this._openCooking(d.id, Number(d.servings) || undefined, d.date ? { date: d.date, meal: d.meal } : null);
        break;
      case "auto-plan": {
        const { start, days } = this._weekRemaining();
        if (!days) return this._toast("Diese Woche liegt in der Vergangenheit.");
        this._openAutoPlan(start, days);
        break;
      }
      case "auto-plan-next": {
        const res = await this._service("auto_plan", { start_date: this._today(), days: 7, meals: [this._data.default_meal] }, true);
        this._toast(res?.planned?.length ? `✨ ${res.planned.length} Mahlzeiten eingeplant` : "Keine passenden Rezepte gefunden");
        break;
      }
      case "copy-week": {
        const res = await this._service("copy_plan", { source_start: toIso(addDays(this._weekStart, -7)), target_start: toIso(this._weekStart), days: 7 }, true);
        this._toast(res?.copied?.length ? `⧉ ${res.copied.length} Mahlzeiten aus der Vorwoche übernommen` : "In der Vorwoche war nichts geplant (oder alles ist schon belegt).");
        break;
      }
      case "shopping-from-week": {
        const { start, days } = this._weekRemaining();
        if (!days) return this._toast("Diese Woche liegt in der Vergangenheit.");
        const res = await this._service("generate_shopping_list", { start_date: start, days }, true);
        this._toast(`🛒 ${res?.items?.length || 0} Artikel für ${res?.meals || 0} Mahlzeiten`);
        this._tab = "shopping";
        this._setPref("tab", "shopping");
        this._renderContent();
        break;
      }
      case "shopping-next-week": {
        const res = await this._service("generate_shopping_list", { start_date: this._today(), days: 7 }, true);
        this._toast(`🛒 ${res?.items?.length || 0} Artikel für ${res?.meals || 0} Mahlzeiten`);
        break;
      }
      case "share-list":
        await this._share("Einkaufsliste", this._shoppingText());
        break;
      case "tag":
        this._tag = d.tag;
        this._renderContent();
        break;
      case "fav-only":
        this._favOnly = !this._favOnly;
        this._renderContent();
        break;
      case "toggle-fav": {
        const r = this._recipe(d.id);
        if (r) await this._service("update_recipe", { recipe: r.id, favorite: !r.favorite });
        break;
      }
      case "open-recipe":
        this._openRecipe(d.id, Number(d.servings) || undefined);
        break;
      case "new-recipe":
        this._openEditor(null);
        break;
      case "import":
        this._openImport();
        break;
      case "cook-with":
        this._openCookWith();
        break;
      case "backup":
        this._openBackup();
        break;
      case "add-item": {
        const input = this._content.querySelector('[data-focuskey="additem"]');
        const value = input?.value.trim();
        if (!value) return;
        input.value = "";
        this._addText = "";
        this._suggestSeq += 1;
        this._closeSuggest();
        await this._todo("add_item", { item: value });
        break;
      }
      case "hide-storehint":
        this._setPref("storehint", "off");
        this._renderContent();
        break;
      case "shop-mode":
        this._setPref("shopmode", d.mode);
        this._renderContent();
        break;
      case "go-tab":
        this._goTab(d.tab, d.sec);
        break;
      case "open-sec":
        this._secOpen[d.sec] = true;
        this._renderContent();
        this._content.querySelector(`#sec-${d.sec}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
        break;
      case "assign-stores": {
        el.disabled = true;
        try {
          const res = await this._service("assign_shopping_stores", {}, true);
          this._toast(res?.active ? `🔄 ${res.assigned} Artikel neu auf die Läden verteilt` : "Die Aufteilung nach Läden ist aus.");
        } finally {
          el.disabled = false;
        }
        break;
      }
      case "pick-store":
        await this._openStorePicker(d.uid);
        break;
      case "branch-main": {
        const res = await this._service("save_branch", { id: d.id, main: true }, true);
        this._toast(`⭐ ${res?.branch?.label || "Laden"} ist jetzt dein Hauptladen`);
        break;
      }
      case "branch-move":
        await this._moveBranch(d.id, Number(d.delta));
        break;
      case "pref-forget":
        await this._forgetStorePref(el, d.key);
        break;
      case "branch-edit":
        this._openBranchEditor(d.id);
        break;
      case "branch-remove": {
        const b = this._branch(d.id);
        if (!b || !confirm(`„${b.label}“ aus deinen Läden entfernen?`)) return;
        await this._service("remove_branch", { branch: d.id }, true);
        this._toast(`🗑 ${b.label} entfernt`);
        if (this._branchSearch?.results?.length) this._refreshSearchFlags();
        break;
      }
      case "rewe-search":
        await this._searchReweMarkets(d.id);
        break;
      case "rewe-pick":
      case "rewe-save": {
        const b = this._branch(d.id);
        const link = STORE_LINKS[b?.retailer] || STORE_LINKS.rewe;
        const stored = b?.[link.field] || "";
        let value = d.market;
        if (action === "rewe-save") {
          // what the field shows (Enter in the field or the button next to it)
          const field = el.matches('[data-input="rewe-id"]') ? el : el.parentElement?.querySelector('[data-input="rewe-id"]');
          value = String(field ? field.value : this._reweInput[d.id] ?? stored).trim();
        }
        if (value === stored) {
          // unchanged (e.g. Enter / "Done" on the phone keyboard without editing): nothing to save
          delete this._reweInput[d.id];
          const save = el.parentElement?.querySelector('[data-action="rewe-save"]');
          if (save) save.hidden = true;
          break;
        }
        if (!value && !confirm(`${link.title.replace(/^\S+ /, "")} von „${b?.label || "diesem Laden"}“ entfernen? ${link.unlink}`)) break;
        const res = await this._service("save_branch", { id: d.id, [link.field]: value }, true);
        delete this._reweInput[d.id];
        delete this._reweMarkets[d.id];
        this._toast(value ? `${link.saved} ${value} gespeichert` : link.removed);
        // show the new id at once (not the old one until the next update)
        if (!this._applyBranch(res?.branch || { id: d.id, [link.field]: value })) this._renderContent();
        break;
      }
      case "zone-toggle": {
        const zones = this._zoneSelection();
        if (zones.has(d.zone)) zones.delete(d.zone);
        else zones.add(d.zone);
        this._renderContent();
        break;
      }
      case "chain-toggle": {
        const chains = this._searchChains;
        if (!d.chain) chains.clear();
        else if (chains.has(d.chain)) chains.delete(d.chain);
        else chains.add(d.chain);
        this._renderContent();
        break;
      }
      case "osm-search":
        await this._findBranches(d.refresh === "1");
        break;
      case "osm-add":
        await this._addOsmBranch(d.id);
        break;
      case "manual-save":
        await this._saveManualBranch();
        break;
      case "price-cell":
        this._openPriceCell(d.key, d.store || null);
        break;
      case "price-new":
        this._openPriceCell(null, null, this._priceQuery.trim());
        break;
      case "price-more":
        this._priceLimit += 50;
        this._renderPriceMatrix();
        break;
      case "refresh-source":
        await this._refreshSource(el, d.source);
        break;
      case "delete-item":
        await this._todo("remove_item", { item: d.uid });
        break;
      case "clear-all": {
        if (!confirm("Die ganze Einkaufsliste löschen?")) return;
        const res = await this._service("clear_shopping_list", { mode: "all" }, true);
        this._toast(`🗑 ${res?.removed || 0} Einträge entfernt`);
        break;
      }
      case "offers-when":
        this._offersWhen = d.when;
        this._renderContent();
        break;
      case "offers-store":
        this._offersStore = d.store;
        this._renderContent();
        break;
      case "offers-mine":
        this._offersMine = !this._offersMine;
        this._renderContent();
        break;
      case "refresh-offers": {
        if (this._refreshing.has("offers-tab")) return;
        this._refreshing.add("offers-tab");
        el.disabled = true;
        el.textContent = "⏳ Lade Angebote …";
        try {
          const res = await this._service("refresh_offers", {}, true);
          this._toast(this._offersRefreshText(res));
        } finally {
          this._refreshing.delete("offers-tab");
          this._so.stale = true;
          if (this._tab === "offers") this._renderContent();
        }
        break;
      }
      case "add-offer":
        this._openOfferForm({ store: d.store || "" });
        break;
      case "offers-mode":
        this._offersMode = d.mode === "stores" ? "stores" : "recipes";
        this._setPref("offers_mode", this._offersMode);
        this._renderContent();
        break;
      case "so-store": {
        const so = this._so;
        let picked = this._soPicked(so.result?.stores);
        if (d.only) picked = new Set([d.branch]);
        else if (!d.branch) picked.clear();
        else if (picked.has(d.branch)) picked.delete(d.branch);
        else picked.add(d.branch);
        // every store picked = all stores
        if (picked.size && picked.size === (so.result?.stores || []).length) picked.clear();
        so.branches = picked;
        this._saveSoBranches();
        this._renderStoreOfferParts();
        this._fetchStoreOffers();
        break;
      }
      case "so-when":
        this._so.when = d.when;
        this._renderContent();
        this._fetchStoreOffers();
        break;
      case "so-kind":
        this._so.kind = d.kind;
        this._setPref("offers_kind", d.kind);
        this._renderContent();
        this._fetchStoreOffers();
        break;
      case "so-more":
        if (!this._so.loading) await this._fetchStoreOffers(true);
        break;
      case "so-add":
        await this._soAdd(el, d.id);
        break;
      case "so-pin":
        await this._soPin(el, d.id);
        break;
      case "so-edeka-search": {
        // Läden & Preise: the EDEKA market search of this store (its link box)
        this._goTab("stores", "mine");
        await this._searchReweMarkets(d.id);
        this._pendingScroll = null;
        const box = [...this._content.querySelectorAll('[data-action="rewe-search"]')].find((x) => x.dataset.id === d.id);
        box?.closest(".branch")?.scrollIntoView({ block: "start" });
        break;
      }
      case "open-settings":
        this._openSettings(d.sec || null);
        break;
      case "receipt-new":
        this._openReceipt();
        break;
      case "receipt-show":
        this._showReceipt(d.id);
        break;
      case "receipt-delete":
        this._deleteReceipt(d.id);
        break;
      case "receipts-more": {
        this._receiptLimit = (this._receiptLimit || 10) + 20;
        const loaded = this._receipts?.receipts?.length || 0;
        if (this._receiptLimit > loaded && loaded < (this._receipts?.count || 0) && !this._receiptsLoading) {
          // older receipts than the loaded ones: fetch more (the backend keeps up to 200)
          this._receiptFetchLimit = Math.min(RECEIPT_FETCH_MAX, Math.max(this._receiptLimit, loaded + RECEIPT_FETCH_STEP));
          this._fetchReceipts();
        }
        this._renderReceiptSection();
        break;
      }
      case "price-kind":
        this._priceKind = d.kind;
        this._renderPriceMatrix();
        this._content.querySelectorAll('[data-action="price-kind"]').forEach((b) => {
          b.classList.toggle("on", b.dataset.kind === d.kind);
          b.setAttribute("aria-pressed", String(b.dataset.kind === d.kind));
        });
        break;
      case "remove-offer":
        await this._service("remove_offer", { id: d.id });
        break;
      case "offer-to-list": {
        const o = (this._data.offers || []).find((x) => x.id === d.id);
        if (!o) break;
        if (!this._splitActive() || !o.id) {
          // without stores (1.2): the offer's store and price are part of the text
          await this._todo("add_item", { item: `${o.title} (${o.store} ${eur(o.price)})` });
          this._toast("🛒 Auf die Einkaufsliste gesetzt");
          break;
        }
        // with stores: the item is put at the offer's branch with the offer price and pack
        const res = await this._service("add_shopping_item", { item: o.title, offer_id: o.id }, true);
        const item = res?.item || {};
        const cost = item.price;
        const price = cost != null ? ` für ${cost === o.price ? "" : "≈ "}${eur(cost)}` : "";
        const label = item.store_label ? ` bei ${item.store_label}` : "";
        this._toast(`🛒 ${item.summary || o.title}${price}${label} auf die Einkaufsliste gesetzt`);
        break;
      }
      case "offer-recipes": {
        const o = (this._data.offers || []).find((x) => x.id === d.id);
        if (o) this._openCookWith(o.product || o.title);
        break;
      }
      case "open-recipe-name": {
        const r = this._data.recipes.find((x) => x.name === d.name);
        if (r) this._openRecipe(r.id);
        break;
      }
      case "live-search":
        this._liveSearch();
        break;
      case "open-prices":
        this._openPrices();
        break;
      case "clear-done":
        await this._todo("remove_completed_items", {});
        break;
      default:
        break;
    }
  }

  /* ------------------------------------------------------------ modals */
  /** opts.sticky (or a function returning it): a tap beside the dialog does not close it;
   *  opts.guard(): false keeps it open when it is closed with ✕, a [data-close] button or
   *  Escape. */
  _showModal(title, body, footer, onMount, opts = {}) {
    this._modalRoot.innerHTML = `
      <div class="overlay">
        <div class="modal" role="dialog" aria-label="${esc(title)}">
          <div class="mhead"><h2>${esc(title)}</h2><button class="icon" data-close title="Schließen">✕</button></div>
          <div class="mbody">${body}</div>
          ${footer ? `<div class="mfoot">${footer}</div>` : ""}
        </div>
      </div>`;
    const overlay = this._modalRoot.querySelector(".overlay");
    overlay.addEventListener("click", (ev) => {
      const sticky = typeof opts.sticky === "function" ? opts.sticky() : opts.sticky;
      if (ev.target.closest("[data-close]") || (ev.target === overlay && !sticky)) this._requestCloseModal();
    });
    this._modal = { root: overlay, guard: opts.guard || null };
    if (onMount) onMount(overlay);
  }

  _requestCloseModal() {
    const guard = this._modal?.guard;
    if (guard && !guard()) return;
    this._closeModal();
  }

  _closeModal() {
    this._modalRoot.innerHTML = "";
    this._modal = null;
    // a closed receipt dialog stays closed when its upload / reading finishes
    this._receipt = null;
  }

  _mealOptions(selected) {
    return this._data.all_meals.map((m) => `<option value="${m.id}" ${m.id === selected ? "selected" : ""}>${esc(m.label)}</option>`).join("");
  }

  _openPicker(date, meal, current, autoSuggest = false) {
    const servings = current?.servings || this._data.default_servings;
    let selected = current?.recipe_id || null;
    let query = "";
    const listHtml = () => {
      const q = fold(query).trim();
      const items = this._data.recipes
        .filter((r) => !q || fold(r.name).includes(q) || (r.tags || []).some((t) => fold(t).includes(q)))
        .sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0) || a.name.localeCompare(b.name, "de"))
        .slice(0, 80);
      if (!items.length) return `<div class="pick" style="cursor:default">Kein Rezept gefunden – wird als Freitext eingetragen.</div>`;
      return items
        .map((r) => `<button class="pick ${r.id === selected ? "sel" : ""}" data-pick="${esc(r.id)}">${dishEmoji(r.name)} ${esc(r.name)}${r.favorite ? ' <span class="stars"><span class="on">★</span></span>' : ""}<span class="m">${r.total_time ? r.total_time + " min" : ""}</span></button>`)
        .join("");
    };
    const body = `
      <div class="hint" style="display:flex;align-items:center;gap:6px"><i style="width:9px;height:9px;border-radius:50%;background:${this._mealColor(meal)};display:inline-block"></i>${esc(this._dateLabel(date))} · ${esc(this._mealLabel(meal))}</div>
      <input type="search" placeholder="Rezept suchen oder Freitext („Pizza bestellen“) …" class="q" value="${esc(current && !current.recipe_id ? current.title : "")}">
      <div class="row" style="margin:0"><button class="btn small suggest">💡 Vorschläge</button><span class="suggestions chips"></span></div>
      <div class="picklist">${listHtml()}</div>
      <div class="grid2">
        <label class="field">Portionen<input type="number" min="1" max="50" class="servings" value="${servings}"></label>
        <label class="field">Notiz<input class="note" value="${esc(current?.note || "")}" placeholder="optional"></label>
      </div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">📅 Einplanen</button>`;
    this._showModal(current ? "Mahlzeit ändern" : "Mahlzeit planen", body, footer, (root) => {
      const q = root.querySelector(".q");
      const list = root.querySelector(".picklist");
      q.focus();
      q.addEventListener("input", () => {
        query = q.value;
        selected = null;
        list.innerHTML = listHtml();
      });
      q.addEventListener("keydown", (ev) => ev.key === "Enter" && root.querySelector(".save").click());
      list.addEventListener("click", (ev) => {
        const pick = ev.target.closest("[data-pick]");
        if (!pick) return;
        selected = pick.dataset.pick;
        list.innerHTML = listHtml();
      });
      list.addEventListener("dblclick", (ev) => {
        if (ev.target.closest("[data-pick]")) root.querySelector(".save").click();
      });
      const suggest = async () => {
        const res = await this._service("suggest_recipes", { count: 4, meal, date }, true);
        root.querySelector(".suggestions").innerHTML =
          (res?.recipes || []).map((r) => `<button class="chip" data-sugg="${esc(r.id)}">${dishEmoji(r.name)} ${esc(r.name)}</button>`).join("") ||
          '<span class="hint">Keine passenden Rezepte</span>';
      };
      root.querySelector(".suggest").addEventListener("click", suggest);
      if (autoSuggest) suggest();
      root.querySelector(".suggestions").addEventListener("click", (ev) => {
        const chip = ev.target.closest("[data-sugg]");
        if (!chip) return;
        selected = chip.dataset.sugg;
        query = "";
        q.value = "";
        list.innerHTML = listHtml();
        list.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
      });
      root.querySelector(".save").addEventListener("click", async () => {
        const data = { date, meal, servings: Number(root.querySelector(".servings").value) || undefined };
        const note = root.querySelector(".note").value.trim();
        if (note) data.note = note;
        if (selected) data.recipe = selected;
        else if (q.value.trim()) data.title = q.value.trim();
        else return this._toast("Bitte ein Rezept auswählen oder einen Text eingeben.");
        await this._service("plan_meal", data);
        this._closeModal();
      });
    });
  }

  _openEntry(date, meal) {
    const entry = (this._data.plan[date] || {})[meal];
    if (!entry) return;
    const recipe = this._recipe(entry.recipe_id);
    const body = `
      <div class="hint" style="display:flex;align-items:center;gap:6px"><i style="width:9px;height:9px;border-radius:50%;background:${this._mealColor(meal)};display:inline-block"></i>${esc(this._dateLabel(date))} · ${esc(this._mealLabel(meal))}</div>
      <div class="heroimg" ${recipe ? bg(recipe.image) : ""}>${recipe && safeUrl(recipe.image) ? "" : recipe ? dishEmoji(recipe.name) : "📝"}</div>
      <div class="meta" style="font-size:14px">${[entry.servings ? `👥 ${entry.servings} Portionen` : "", recipe?.total_time ? `⏱ ${recipe.total_time} min` : "", entry.cooked ? "✅ gekocht" : ""].filter(Boolean).join(" · ")}</div>
      ${entry.note ? `<div>📝 ${esc(entry.note)}</div>` : ""}
      ${!recipe ? `<div class="hint">Freitext ohne Rezept – Zutaten landen nicht auf der Einkaufsliste.</div>` : ""}
      <div class="section">
        <h4>Verschieben / Tauschen</h4>
        <div class="grid2">
          <label class="field">Neuer Tag<input type="date" class="mdate" value="${date}"></label>
          <label class="field">Mahlzeit<select class="mmeal">${this._mealOptions(meal)}</select></label>
        </div>
        <div><button class="btn small move">↪ Verschieben</button> <span class="hint">Ist der Platz belegt, werden beide getauscht.</span></div>
      </div>`;
    const footer = `
      <button class="btn danger remove">🗑 Entfernen</button>
      <button class="btn change">✏️ Ändern</button>
      ${entry.cooked ? "" : `<button class="btn cooked">✅ Gekocht</button>`}
      ${recipe ? `<button class="btn showr">📖 Rezept</button><button class="btn primary cookbtn">👩‍🍳 Kochmodus</button>` : ""}`;
    this._showModal(entry.title, body, footer, (root) => {
      root.querySelector(".remove").addEventListener("click", async () => {
        await this._service("remove_meal", { date, meal });
        this._closeModal();
      });
      root.querySelector(".change").addEventListener("click", () => this._openPicker(date, meal, entry));
      root.querySelector(".cooked")?.addEventListener("click", async () => {
        await this._service("mark_cooked", { date, meal });
        this._closeModal();
      });
      root.querySelector(".showr")?.addEventListener("click", () => this._openRecipe(recipe.id, entry.servings, { date, meal }));
      root.querySelector(".cookbtn")?.addEventListener("click", () => {
        this._closeModal();
        this._openCooking(recipe.id, entry.servings, { date, meal });
      });
      root.querySelector(".move").addEventListener("click", async () => {
        const toDate = root.querySelector(".mdate").value;
        const toMeal = root.querySelector(".mmeal").value;
        if (!toDate || (toDate === date && toMeal === meal)) return;
        await this._service("move_meal", { from_date: date, from_meal: meal, to_date: toDate, to_meal: toMeal });
        this._toast(`↪ ${entry.title}: ${this._dateLabel(toDate)}, ${this._mealLabel(toMeal)}`);
        this._closeModal();
      });
    });
  }

  _recipeText(r) {
    const lines = [`${r.name} (${r.servings} Portionen)`, ""];
    if (r.ingredient_lines?.length) lines.push("Zutaten:", ...r.ingredient_lines.map((l) => `• ${l}`), "");
    if (r.steps?.length) lines.push("Zubereitung:", ...r.steps.map((s, i) => `${i + 1}. ${s}`));
    if (httpLink(r.source_url)) lines.push("", r.source_url);
    return lines.join("\n");
  }

  async _openRecipe(id, servingsOverride, ctx) {
    const base = this._recipe(id);
    if (!base) return;
    let servings = servingsOverride || base.servings || this._data.default_servings;
    const render = async () => {
      const res = await this._service("get_recipe", { recipe: id, servings }, true);
      const r = res?.recipe || base;
      const current = this._recipe(id) || base;
      const body = `
        <div class="heroimg" ${bg(r.image)}>${safeUrl(r.image) ? "" : dishEmoji(r.name)}</div>
        <div class="row" style="margin:0;justify-content:space-between">
          <span class="stepper">👥 <button class="icon minus" title="Weniger">−</button><input type="number" class="servings" min="1" max="50" value="${servings}"><button class="icon plus" title="Mehr">＋</button> Portionen</span>
          <span class="rating">${stars(current.rating, true)}</span>
        </div>
        <div class="meta">${[r.prep_time ? `Vorbereitung ${r.prep_time} min` : "", r.cook_time ? `Kochen ${r.cook_time} min` : "", r.total_time ? `Gesamt ${r.total_time} min` : "", current.cooked_count ? `🍳 ${current.cooked_count}× gekocht${current.last_cooked ? `, zuletzt ${this._dateLabel(current.last_cooked)}` : ""}` : ""].filter(Boolean).join(" · ")}</div>
        <div class="chips">${(r.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        ${r.cost ? `<div class="section"><div class="costbox"><span class="big">≈ ${eur(r.cost.total)}</span><span class="meta">${eur(r.cost.per_serving)} pro Portion${r.cost.savings ? ` · 🏷️ ${eur(r.cost.savings)} gespart` : ""} · Schätzung</span></div>${r.cost.on_offer?.length ? `<div class="meta">🏷️ Im Angebot: ${r.cost.on_offer.map((o) => `${esc(o.ingredient)} (${esc(o.store)} ${eur(o.price)}${o.valid_to ? ` bis ${shortDate(o.valid_to)}` : ""})`).join(", ")}</div>` : ""}${r.cost.unknown?.length ? `<div class="hint">Ohne Preis: ${esc(r.cost.unknown.join(", "))}</div>` : ""}</div>` : ""}
        <div><h4>Zutaten</h4>${(r.ingredient_lines || []).length ? `<ul>${r.ingredient_lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : '<div class="hint">Keine Zutaten hinterlegt.</div>'}</div>
        <div><h4>Zubereitung</h4>${(r.steps || []).length ? `<ol>${r.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>` : '<div class="hint">Keine Schritte hinterlegt.</div>'}</div>
        ${r.notes ? `<div><h4>Notizen</h4><div>${esc(r.notes)}</div></div>` : ""}
        ${httpLink(r.source_url) ? `<div><a class="btn small" href="${esc(httpLink(r.source_url))}" target="_blank" rel="noreferrer">🔗 Originalrezept</a></div>` : ""}
        <div class="section">
          <h4>Einplanen</h4>
          <div class="grid2">
            <label class="field">Datum<input type="date" class="pdate" value="${esc(ctx?.date || this._today())}"></label>
            <label class="field">Mahlzeit<select class="pmeal">${this._mealOptions(ctx?.meal || this._data.default_meal)}</select></label>
          </div>
          <div><button class="btn primary plan">📅 Einplanen</button></div>
        </div>`;
      const footer = `
        <button class="btn danger delete" title="Löschen">🗑</button>
        <button class="btn share" title="Rezept teilen">📤</button>
        <button class="btn fav">${current.favorite ? "★ Favorit" : "☆ Favorit"}</button>
        <button class="btn edit">✏️ Bearbeiten</button>
        <button class="btn primary cookbtn">👩‍🍳 Kochmodus</button>`;
      this._showModal(r.name, body, footer, (root) => {
        const input = root.querySelector(".servings");
        const set = (v) => {
          servings = Math.max(1, Math.min(50, v || 1));
          render();
        };
        root.querySelector(".minus").addEventListener("click", () => set(servings - 1));
        root.querySelector(".plus").addEventListener("click", () => set(servings + 1));
        input.addEventListener("change", () => set(Number(input.value)));
        root.querySelector(".rating").addEventListener("click", async (ev) => {
          const star = ev.target.closest("[data-rate]");
          if (!star) return;
          const value = Number(star.dataset.rate);
          const rating = value === current.rating ? 0 : value;
          await this._service("update_recipe", { recipe: id, rating });
          current.rating = rating;
          root.querySelector(".rating").innerHTML = stars(rating, true);
        });
        root.querySelector(".plan").addEventListener("click", async () => {
          const date = root.querySelector(".pdate").value;
          const meal = root.querySelector(".pmeal").value;
          if (!date) return;
          await this._service("plan_meal", { date, meal, recipe: id, servings });
          this._toast(`📅 ${r.name}: ${this._dateLabel(date)}, ${this._mealLabel(meal)}`);
          this._closeModal();
        });
        root.querySelector(".fav").addEventListener("click", async () => {
          await this._service("update_recipe", { recipe: id, favorite: !current.favorite });
          current.favorite = !current.favorite;
          root.querySelector(".fav").textContent = current.favorite ? "★ Favorit" : "☆ Favorit";
        });
        root.querySelector(".share").addEventListener("click", () => this._share(r.name, this._recipeText(r)));
        root.querySelector(".edit").addEventListener("click", () => this._openEditor(this._recipe(id)));
        root.querySelector(".cookbtn").addEventListener("click", () => {
          this._closeModal();
          this._openCooking(id, servings, ctx);
        });
        root.querySelector(".delete").addEventListener("click", async () => {
          if (!confirm(`Rezept „${r.name}“ wirklich löschen?`)) return;
          await this._service("delete_recipe", { recipe: id });
          this._closeModal();
        });
      });
    };
    await render();
  }

  _ingredientLine(i) {
    const fmt = (n) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100).replace(".", ","));
    const parts = [];
    if (i.amount != null) parts.push(fmt(i.amount));
    if (i.unit) parts.push(i.unit);
    parts.push(i.name);
    let text = parts.join(" ");
    if (i.note) text += ` (${i.note})`;
    return text;
  }

  _openEditor(recipe) {
    const r = recipe || {};
    const body = `
      <label class="field">Name<input class="name" value="${esc(r.name || "")}" placeholder="z. B. Spaghetti Bolognese"></label>
      <div class="grid2">
        <label class="field">Portionen<input type="number" min="1" max="100" class="servings" value="${esc(r.servings || this._data.default_servings)}"></label>
        <label class="field">Gesamtzeit (Minuten)<input type="number" min="0" class="time" value="${esc(r.total_time ?? "")}"></label>
      </div>
      <label class="field">Kategorien (kommagetrennt)<input class="tags" value="${esc((r.tags || []).join(", "))}" placeholder="Hauptgericht, vegetarisch, schnell"></label>
      <label class="field">Zutaten – eine pro Zeile, z. B. „400 g Spaghetti“<textarea class="ingredients" placeholder="400 g Spaghetti&#10;1 Zwiebel&#10;2 EL Olivenöl">${esc((r.ingredients || []).map((i) => this._ingredientLine(i)).join("\n"))}</textarea></label>
      <label class="field">Zubereitung – ein Schritt pro Zeile (Zeitangaben wie „10 Minuten“ werden im Kochmodus zu Timern)<textarea class="steps">${esc((r.steps || []).join("\n"))}</textarea></label>
      <label class="field">Notizen<textarea class="notes" style="min-height:60px">${esc(r.notes || "")}</textarea></label>
      <div class="grid2">
        <label class="field">Bild-URL<input class="image" value="${esc(r.image || "")}" placeholder="https://…"></label>
        <label class="field">Quelle<input class="source" value="${esc(r.source_url || "")}" placeholder="https://…"></label>
      </div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">💾 Speichern</button>`;
    this._showModal(recipe ? "Rezept bearbeiten" : "Neues Rezept", body, footer, (root) => {
      root.querySelector(".name").focus();
      root.querySelector(".save").addEventListener("click", async () => {
        const v = (sel) => root.querySelector(sel).value;
        const name = v(".name").trim();
        if (!name) return this._toast("Bitte einen Namen eingeben.");
        const data = {
          name,
          servings: Number(v(".servings")) || this._data.default_servings,
          tags: v(".tags"),
          ingredients: v(".ingredients"),
          steps: v(".steps"),
          notes: v(".notes"),
          image: v(".image").trim(),
          source_url: v(".source").trim(),
        };
        const time = v(".time");
        if (time !== "") data.total_time = Number(time);
        const res = recipe
          ? await this._service("update_recipe", { recipe: recipe.id, ...data }, true)
          : await this._service("add_recipe", data, true);
        this._closeModal();
        if (res?.recipe?.id) setTimeout(() => this._openRecipe(res.recipe.id), 350);
      });
    });
  }

  _openImport() {
    const body = `
      <div class="hint">Funktioniert mit Seiten, die Rezepte im schema.org-Format bereitstellen – z. B. Chefkoch, Lecker, Eat Smarter, Kitchen Stories, BBC Good Food …</div>
      <input type="url" class="url" placeholder="https://www.chefkoch.de/rezepte/…">
      <label class="field">Zusätzliche Kategorien (optional)<input class="tags" placeholder="z. B. Hauptgericht"></label>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary go">🌐 Importieren</button>`;
    this._showModal("Rezept importieren", body, footer, (root) => {
      const url = root.querySelector(".url");
      url.focus();
      const go = async () => {
        const value = url.value.trim();
        if (!value) return;
        const btn = root.querySelector(".go");
        btn.disabled = true;
        btn.textContent = "⏳ Importiere …";
        try {
          const data = { url: value };
          const tags = root.querySelector(".tags").value.trim();
          if (tags) data.tags = tags;
          const res = await this._service("import_recipe", data, true);
          this._closeModal();
          this._toast(`${res.recipe.name} ${res.created ? "importiert" : "aktualisiert"} ✓`);
          setTimeout(() => this._openRecipe(res.recipe.id), 350);
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "🌐 Importieren";
        }
      };
      root.querySelector(".go").addEventListener("click", go);
      url.addEventListener("keydown", (ev) => ev.key === "Enter" && go());
    });
  }

  _openCookWith(prefill = "") {
    const body = `
      <div class="hint">Was hast du noch im Kühlschrank? Ich suche passende Rezepte und sage dir, was noch fehlt.</div>
      <div class="row" style="margin:0">
        <input class="have" placeholder="z. B. Hähnchen, Reis, Paprika" style="flex:1">
        <button class="btn primary go">🔍 Suchen</button>
      </div>
      <div class="results" style="display:flex;flex-direction:column;gap:8px"></div>`;
    this._showModal("Was kann ich kochen?", body, "", (root) => {
      const input = root.querySelector(".have");
      input.value = prefill;
      input.focus();
      const go = async () => {
        if (!input.value.trim()) return;
        const res = await this._service("find_by_ingredients", { ingredients: input.value, count: 8 }, true);
        const list = res?.recipes || [];
        root.querySelector(".results").innerHTML = list.length
          ? list
              .map(
                (r) => `<div class="result" data-open="${esc(r.id)}">
                  <div class="thumb" ${bg(r.image)}>${safeUrl(r.image) ? "" : dishEmoji(r.name)}</div>
                  <div style="flex:1;min-width:0">
                    <div style="font-weight:600">${esc(r.name)}</div>
                    <div class="meta">✓ nutzt ${esc(r.uses.join(", "))}${r.total_time ? ` · ⏱ ${r.total_time} min` : ""}</div>
                    <div class="meta">${r.missing.length ? `fehlt: ${esc(r.missing.slice(0, 6).join(", "))}${r.missing.length > 6 ? ` +${r.missing.length - 6}` : ""}` : "🎉 Du hast alles da!"}</div>
                    <div class="bar"><div style="width:${Math.round(r.coverage * 100)}%"></div></div>
                  </div>
                </div>`
              )
              .join("")
          : `<div class="empty" style="padding:20px"><div class="big">🤷</div>Dazu habe ich kein passendes Rezept.</div>`;
      };
      root.querySelector(".go").addEventListener("click", go);
      input.addEventListener("keydown", (ev) => ev.key === "Enter" && go());
      if (prefill) go();
      root.querySelector(".results").addEventListener("click", (ev) => {
        const card = ev.target.closest("[data-open]");
        if (card) this._openRecipe(card.dataset.open);
      });
    });
  }

  _openBackup() {
    const body = `
      <div class="section">
        <h4>💾 Rezepte exportieren</h4>
        <div class="hint">Lädt alle ${this._data.recipes.length} Rezepte als JSON-Datei herunter – als Backup oder zum Teilen mit Freunden, die auch den Essensplaner nutzen.</div>
        <div><button class="btn export">⬇ Exportieren</button></div>
      </div>
      <div class="section">
        <h4>📚 Rezeptsammlung ergänzen</h4>
        <div class="hint">Fügt alle mitgelieferten Rezepte hinzu, die in deiner Sammlung fehlen (z. B. nach einem Update).</div>
        <div><button class="btn starter">📚 Fehlende Rezepte hinzufügen</button></div>
      </div>
      <div class="section">
        <h4>📥 Rezepte importieren</h4>
        <div class="hint">JSON-Datei aus einem Export auswählen. Rezepte mit gleichem Namen werden übersprungen.</div>
        <div><button class="btn importfile">📂 Datei auswählen</button></div>
      </div>`;
    this._showModal("Sichern & Teilen", body, "", (root) => {
      root.querySelector(".export").addEventListener("click", async () => {
        const res = await this._service("export_recipes", {}, true);
        const blob = new Blob([JSON.stringify(res, null, 2)], { type: "application/json" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `essensplaner-rezepte-${this._today()}.json`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      });
      root.querySelector(".importfile").addEventListener("click", () => this.shadowRoot.querySelector(".fileinput").click());
      root.querySelector(".starter").addEventListener("click", async () => {
        const res = await this._service("import_starter_recipes", {}, true);
        this._toast(res?.added?.length ? `📚 ${res.added.length} Rezepte hinzugefügt` : "Alle mitgelieferten Rezepte sind schon da.");
        this._closeModal();
      });
    });
  }

  async _importFile(ev) {
    const file = ev.target.files?.[0];
    ev.target.value = "";
    if (!file) return;
    const text = await file.text();
    const res = await this._service("import_recipes", { recipes: text }, true);
    this._toast(`📥 ${res.added.length} neu, ${res.skipped.length} übersprungen`);
    this._closeModal();
  }

  /* ------------------------------------------------------------ offers & budget */
  _renderOffers() {
    const stores = this._offersMode === "stores";
    const recipeCount = (this._data.offers || []).filter((o) => o.current && o.recipe_count).length;
    const seg = `<div class="seg somode" role="group" aria-label="Angebote anzeigen">
        <button class="${stores ? "" : "on"}" data-action="offers-mode" data-mode="recipes" aria-pressed="${!stores}">🍽️ <span class="wide-only">Für meine Rezepte</span><span class="narrow-only">Meine Rezepte</span> (${recipeCount})</button>
        <button class="${stores ? "on" : ""}" data-action="offers-mode" data-mode="stores" aria-pressed="${stores}">🏪 <span class="wide-only">Alle Angebote meiner Läden</span><span class="narrow-only">Meine Läden</span> (<span data-socount>${this._storeOfferCount()}</span>)</button>
      </div>`;
    return seg + (stores ? this._renderStoreOffers() : this._renderRecipeOffers());
  }

  _renderRecipeOffers() {
    const eco = this._data.economy || {};
    const week = eco.week || {};
    const next = eco.next_week || {};
    const budget = eco.budget;
    const meta = eco.offers_meta || {};
    const sources = eco.price_sources || {};
    const marktguru = eco.offers_source === "marktguru";
    // offers come from the chains directly (EDEKA, ALDI SÜD) and/or from marktguru (optional)
    const online = marktguru || Boolean(sources.edeka?.enabled) || Boolean(sources.aldi?.enabled);
    const when = this._offersWhen || "current";
    const offers = (this._data.offers || []).filter((o) => {
      if (when === "current" && !o.current) return false;
      if (when === "upcoming" && o.current) return false;
      if (this._offersStore && o.store !== this._offersStore) return false;
      if (this._offersMine !== false && !o.recipe_count) return false;
      return true;
    });
    const stores = [...new Set((this._data.offers || []).map((o) => o.store).filter(Boolean))].sort();
    const maxDay = Math.max(1, ...(week.days || []).map((d) => d.total || 0));
    const bars = (week.days || [])
      .map((d) => `<div style="height:${Math.round(((d.total || 0) / maxDay) * 100)}%" title="${shortDate(d.date)}: ${eur(d.total)}"><span>${shortDate(d.date).split(" ")[0]}</span></div>`)
      .join("");
    const ratio = budget ? (week.total || 0) / budget : 0;
    const budgetHtml = `<div class="card budgetcard">
        <div><div class="meta">Diese Woche (geschätzt)</div><div class="big">${eur(week.total || 0)}</div></div>
        <div>
          ${budget ? `<div class="meta">Budget ${eur(budget)} · ${week.remaining >= 0 ? `noch <b>${eur(week.remaining)}</b> frei` : `<b style="color:var(--ep-red)">${eur(-week.remaining)} drüber</b>`}</div>
          <div class="progress" style="height:10px;max-width:none;margin-top:6px"><div style="width:${Math.min(100, Math.round(ratio * 100))}%;background:${ratio > 1 ? "#c62828" : ratio > 0.85 ? "#ef6c00" : "#2e7d32"}"></div></div>` : `<div class="hint">Kein Wochenbudget festgelegt – einstellen unter ${this._settingsLink("planning", "⚙️ Budget & Planung")}.</div>`}
          <div class="meta" style="margin-top:6px">${week.savings ? `🏷️ ${eur(week.savings)} durch Angebote gespart · ` : ""}Nächste Woche bisher ≈ ${eur(next.total || 0)}</div>
        </div>
        <div class="bars" style="margin:6px 0 18px">${bars}</div>
      </div>`;
    const targets = this._data.offer_targets || [];
    const zips = targets.length
      ? targets.map((t) => `PLZ ${esc(t.zip_code)}${targets.length > 1 || (t.stores || []).length ? ` (${esc((t.stores || []).join(", "))})` : ""}`).join(" · ")
      : `PLZ ${esc(eco.zip_code || "–")}`;
    const rewe = sources.rewe;
    const edekaSource = sources.edeka;
    const aldiSource = sources.aldi;
    const aldiWeekly = eco.catalog?.sources?.aldi_weekly;
    // one line per active source
    const sourceLines =
      (marktguru
        ? `<div class="meta">Quelle: marktguru.de (inoffiziell) · ${zips} · ${meta.last_update ? `aktualisiert ${new Date(meta.last_update).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })}` : "noch nicht geladen"}${meta.status === "error" ? ` · ⚠️ ${esc((meta.errors || [])[0] || "Fehler")}` : ""}</div>`
        : "") +
      (edekaSource?.enabled
        ? `<div class="meta">🏷️ EDEKA direkt (edeka.de): ${esc(edekaSource.message || edekaSource.status)}</div>`
        : "") +
      (aldiSource?.enabled
        ? `<div class="meta">🏷️ ALDI SÜD direkt (experimentell): ${aldiWeekly ? `${esc(aldiWeekly)} Wochenangebote · ` : ""}${esc(aldiSource.message || aldiSource.status)}</div>`
        : "") +
      (rewe?.enabled
        ? `<div class="meta">🛒 REWE-Onlinepreise (experimentell): ${esc(rewe.message || rewe.status)}</div>`
        : "");
    const info = online
      ? `${sourceLines}${marktguru ? "" : `<div class="meta">Für Ketten ohne eigene Quelle (Lidl, REWE, Netto, Rossmann …) gibt es optional marktguru (inoffiziell, eigenes Risiko): ${this._settingsLink("offers", "⚙️ Angebote & Preisquellen")}</div>`}`
      : `<div class="card infobox"><b>Online-Angebote sind aus.</b> EDEKA- und ALDI-SÜD-Angebote kommen direkt von den Ketten, für andere Ketten gibt es marktguru (inoffiziell, eigenes Risiko). Einschalten: ${this._settingsLink("offers", "⚙️ Angebote & Preisquellen")} – gesucht wird bei deinen Läden aus dem Tab „🏪 Läden & Preise“. Angebote aus dem Prospekt kannst du jederzeit selbst eintragen – oder Jarvis sagen: „Bei Lidl gibt es Hähnchenbrust für 4,99 Euro bis Samstag“.</div>${sourceLines}`;
    const branchLabels = Object.fromEntries((this._data.branches || []).map((b) => [b.id, b]));
    const cards = offers
      .map((o) => {
        const img = safeUrl(o.image);
        const tagged = (o.branches || []).map((id) => branchLabels[id]).filter(Boolean);
        return `<div class="card offer">
          <div class="oimg" ${img ? `style="background-image:url('${img}')"` : ""}>${img ? "" : "🏷️"}</div>
          <div style="flex:1;min-width:0">
            <div class="ot">${esc(o.title)}</div>
            <span class="store">${esc(o.store || "?")}</span>${o.loyalty_note ? ` <span class="meta">(${esc(o.loyalty_note)})</span>` : o.loyalty ? ' <span class="meta">(mit App/Karte)</span>' : ""}
            ${tagged.length ? `<div class="branchtags">${tagged.map((b) => `<span class="bdg" title="Gilt für diesen Laden">${b.main ? "⭐" : "📍"} ${esc(b.label)}</span>`).join("")}</div>` : ""}
            <div><span class="pr">${eur(o.price)}</span>${o.old_price ? `<span class="old">${eur(o.old_price)}</span>` : ""}${o.discount ? `<span class="disc">−${o.discount}%</span>` : ""}</div>
            <div class="meta">${esc(o.description || "")}${o.valid_from || o.valid_to ? ` · ${o.valid_from ? shortDate(o.valid_from) : ""}–${o.valid_to ? shortDate(o.valid_to) : ""}` : ""}</div>
            ${o.recipes?.length ? `<div class="chips" style="margin-top:4px">${o.recipes.slice(0, 3).map((n) => `<button class="chip" data-action="open-recipe-name" data-name="${esc(n)}">${dishEmoji(n)} ${esc(n)}</button>`).join("")}${o.recipe_count > 3 ? `<span class="meta">+${o.recipe_count - 3}</span>` : ""}</div>` : ""}
            <div class="acts">
              <button class="btn small" data-action="offer-to-list" data-id="${esc(o.id)}">🛒 Merken</button>
              <button class="btn small" data-action="offer-recipes" data-id="${esc(o.id)}">🍳 Rezepte</button>
              ${o.source === "manual" ? `<button class="btn small danger" data-action="remove-offer" data-id="${esc(o.id)}">🗑</button>` : ""}
            </div>
          </div>
        </div>`;
      })
      .join("");
    return `${budgetHtml}
      <div class="row">
        <button class="chip ${when === "current" ? "active" : ""}" data-action="offers-when" data-when="current">Aktuell</button>
        <button class="chip ${when === "upcoming" ? "active" : ""}" data-action="offers-when" data-when="upcoming">Ab nächster Woche</button>
        <button class="chip ${when === "all" ? "active" : ""}" data-action="offers-when" data-when="all">Alle</button>
        <button class="chip ${this._offersMine !== false ? "active" : ""}" data-action="offers-mine">Nur passend zu meinen Rezepten</button>
        <span class="spacer"></span>
        ${online ? `<button class="btn" data-action="refresh-offers" ${this._refreshing.has("offers-tab") ? "disabled" : ""}>${this._refreshing.has("offers-tab") ? "⏳ Lade Angebote …" : "🔄 Aktualisieren"}</button>` : ""}
        <button class="btn" data-action="add-offer">＋ Angebot eintragen</button>
        <button class="btn ghost" data-action="go-tab" data-tab="stores" data-sec="prices">💶 Preise</button>
      </div>
      ${stores.length > 1 ? `<div class="row chips tagrow"><button class="chip ${this._offersStore ? "" : "active"}" data-action="offers-store" data-store="">Alle Märkte</button>${stores.map((st) => `<button class="chip ${st === this._offersStore ? "active" : ""}" data-action="offers-store" data-store="${esc(st)}">${esc(st)}</button>`).join("")}</div>` : ""}
      <div class="row">
        <input type="search" placeholder="🔍 Preis/Angebot suchen, z. B. „Butter“ (Aldi, Lidl, REWE …)" data-enter="live-search" data-focuskey="livesearch" style="flex:1;min-width:200px">
        <button class="btn" data-action="live-search">Suchen</button>
      </div>
      ${info}
      <div class="liveresults"></div>
      ${offers.length ? `<div class="offers" style="margin-top:12px">${cards}</div>` : `<div class="empty"><div class="big">🏷️</div>${online ? "Keine passenden Angebote im gewählten Zeitraum." : "Noch keine Angebote eingetragen."}</div>`}`;
  }

  async _liveSearch() {
    const input = this._content.querySelector('[data-focuskey="livesearch"]');
    const query = input?.value.trim();
    if (!query) return;
    const box = this._content.querySelector(".liveresults");
    box.innerHTML = `<div class="hint">⏳ Suche „${esc(query)}“ …</div>`;
    const res = await this._service("search_offers", { query }, true);
    const live = res?.live || [];
    const saved = res?.saved || [];
    const book = await this._prices();
    const price = book.find((p) => p.key && (p.key === query.toLowerCase() || p.name.toLowerCase() === query.toLowerCase()));
    const rows = [...live, ...saved.filter((s) => !live.some((l) => l.id === s.id))]
      .slice(0, 12)
      .map((o) => `<div class="pricerow"><span>${esc(o.title)} <span class="meta">${esc(o.description || "")}${o.valid_to ? ` · bis ${shortDate(o.valid_to)}` : ""}</span></span><span class="store">${esc(o.store)}</span><b>${eur(o.price)}</b></div>`)
      .join("");
    box.innerHTML = `<div class="card" style="padding:12px 14px;margin-top:10px">
        <h4 style="margin:0 0 6px">Ergebnisse für „${esc(query)}“</h4>
        ${price ? `<div class="meta">Normalpreis (${price.source === "user" ? "eigener Preis" : price.source === "offer_regular" ? "aus Prospekt gelernt" : "Richtwert"}): ${eur(price.price)} für ${price.amount} ${esc(price.unit)}${price.store ? ` (${esc(price.store)})` : ""}</div>` : ""}
        ${rows || `<div class="hint">${res?.error ? `Online-Suche fehlgeschlagen: ${esc(res.error)}` : this._data.economy?.offers_source === "marktguru" ? "Derzeit kein Angebot gefunden." : "Online-Suche ist aus – nur gespeicherte Angebote werden durchsucht."}</div>`}
      </div>`;
  }

  async _prices(force = false) {
    if (!this._priceList || force) {
      try {
        this._priceList = (await this._hass.callWS({ type: `${DOMAIN}/prices` })).prices;
      } catch (e) {
        this._priceList = [];
      }
    }
    return this._priceList;
  }

  _openAutoPlan(start, days) {
    const strategy = this._data.economy?.strategy || "balanced";
    const budget = this._data.economy?.budget;
    const body = `
      <div class="hint">${esc(this._dateLabel(start))} + ${days - 1} Tage · nur freie Plätze werden gefüllt.${budget ? ` Wochenbudget: ${eur(budget)}.` : ""}</div>
      <div class="strategy">${Object.entries(STRATEGY_LABELS).map(([k, [label, desc]]) => `<label><input type="radio" name="strategy" value="${k}" ${k === strategy ? "checked" : ""}><span><b>${label}</b><br><span class="meta">${desc}</span></span></label>`).join("")}</div>
      <div><h4>Mahlzeiten</h4><div class="chips">${this._data.meals.map((m) => `<label class="chip"><input type="checkbox" class="pm" value="${m.id}" ${m.id === this._data.default_meal ? "checked" : ""}> ${esc(m.label)}</label>`).join("")}</div></div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary go">✨ Planen</button>`;
    this._showModal("Woche automatisch planen", body, footer, (root) => {
      root.querySelector(".go").addEventListener("click", async () => {
        const meals = [...root.querySelectorAll(".pm:checked")].map((x) => x.value);
        const chosen = root.querySelector('input[name="strategy"]:checked')?.value;
        const res = await this._service("auto_plan", { start_date: start, days, meals: meals.length ? meals : [this._data.default_meal], strategy: chosen }, true);
        this._closeModal();
        const n = res?.planned?.length || 0;
        const total = res?.week?.total;
        this._toast(n ? `✨ ${n} Mahlzeiten eingeplant${total ? ` · Woche ≈ ${eur(total)}` : ""}` : "Keine freien Plätze oder passenden Rezepte");
      });
    });
  }

  _openOfferForm(prefill = {}) {
    // own branches first (an offer for one branch), then the chains
    const branches = (this._data.branches || []).filter((b) => b.selected).map((b) => b.label);
    const chains = ["Aldi Süd", "Aldi Nord", "Lidl", "REWE", "EDEKA", "Penny", "Netto", "Kaufland", "Norma", "Rossmann", "dm", "Müller", "Budni"];
    const stores = [...new Set([...branches, ...chains])];
    const body = `
      <div class="hint">Ein Angebot aus dem Prospekt eintragen – es wird bei Rezeptkosten, Planung und Einkaufsliste berücksichtigt.${prefill.store ? " Gilt für den gewählten Laden." : ""}</div>
      <label class="field">Produkt<input class="product" placeholder="z. B. Hähnchenbrustfilet" value="${esc(prefill.product || "")}"></label>
      <div class="grid2">
        <label class="field">Markt<input class="store" list="ep-stores" placeholder="z. B. Lidl" value="${esc(prefill.store || "")}"><datalist id="ep-stores">${stores.map((x) => `<option value="${esc(x)}">`).join("")}</datalist></label>
        <label class="field">Packung<input class="pack" placeholder="z. B. 1 kg, 500 g"></label>
        <label class="field">Preis (€)<input class="price" type="number" step="0.01" min="0" placeholder="4,99"></label>
        <label class="field">Normalpreis (€, optional)<input class="old" type="number" step="0.01" min="0"></label>
        <label class="field">Gültig ab<input class="from" type="date" value="${this._today()}"></label>
        <label class="field">Gültig bis<input class="to" type="date"></label>
      </div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">💾 Speichern</button>`;
    this._showModal("Angebot eintragen", body, footer, (root) => {
      root.querySelector(".product").focus();
      root.querySelector(".save").addEventListener("click", async () => {
        const v = (sel) => root.querySelector(sel).value.trim();
        if (!v(".product") || !v(".store") || !v(".price")) return this._toast("Bitte Produkt, Markt und Preis angeben.");
        const data = { product: v(".product"), store: v(".store"), price: Number(v(".price")) };
        if (v(".pack")) data.pack = v(".pack");
        if (v(".old")) data.old_price = Number(v(".old"));
        if (v(".from")) data.valid_from = v(".from");
        if (v(".to")) data.valid_to = v(".to");
        await this._service("add_offer", data, true);
        this._closeModal();
        this._toast("🏷️ Angebot gespeichert");
      });
    });
  }

  async _openPrices() {
    let list = await this._prices(true);
    let query = "";
    const sourceLabel = { user: "✏️ eigener Preis", offer_regular: "🏷️ aus Prospekt", default: "Richtwert" };
    const rows = () =>
      list
        .filter((p) => !query || p.name.toLowerCase().includes(query.toLowerCase()))
        .slice(0, 60)
        .map((p) => `<div class="pricerow"><span>${esc(p.name)} <span class="meta">${p.amount} ${esc(p.unit)} · ${sourceLabel[p.source] || p.source}${p.store ? ` · ${esc(p.store)}` : ""}</span></span><b>${eur(p.price)}</b><button class="btn small" data-edit="${esc(p.name)}">✏️</button></div>`)
        .join("");
    // with a main store its store book counts (README order): store prices before general ones
    const precedence = this._data.economy?.main_retailer
      ? "Eigene Preise haben Vorrang vor Richtwerten. Ein Ladenpreis (eigener oder aus dem Prospekt gelernter) gilt in seinem Laden vor dem allgemeinen Preis – beim Hauptladen also auch für Einkaufsliste und Rezeptkosten."
      : "Eigene Preise haben Vorrang; Normalpreise aus Prospekten werden automatisch gelernt.";
    const body = `
      <div class="hint">Richtwerte sind typische Discounter-Preise. ${precedence}</div>
      <input type="search" class="q" placeholder="Zutat suchen …">
      <div class="list">${rows()}</div>
      <div class="section editor" style="display:none">
        <h4 class="ename"></h4>
        <div class="grid2">
          <label class="field">Preis (€)<input class="eprice" type="number" step="0.01" min="0"></label>
          <label class="field">Packung<span style="display:flex;gap:6px"><input class="eamount" type="number" min="0" style="width:90px"><select class="eunit">${["g", "ml", "Stück", "Bund", "Pck.", "Dose", "Kopf"].map((u) => `<option>${u}</option>`).join("")}</select></span></label>
          <label class="field">Markt (optional)<input class="estore"></label>
        </div>
        <div><button class="btn primary esave">💾 Speichern</button> <button class="btn ereset">↩ Richtwert verwenden</button></div>
      </div>`;
    this._showModal("Allgemeine Richtwerte", body, "", (root) => {
      const listEl = root.querySelector(".list");
      const editor = root.querySelector(".editor");
      let editing = null;
      root.querySelector(".q").addEventListener("input", (ev) => {
        query = ev.target.value;
        listEl.innerHTML = rows();
      });
      listEl.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-edit]");
        if (!btn) return;
        editing = list.find((p) => p.name === btn.dataset.edit);
        if (!editing) return;
        editor.style.display = "";
        root.querySelector(".ename").textContent = editing.name;
        root.querySelector(".eprice").value = editing.price;
        root.querySelector(".eamount").value = editing.amount;
        root.querySelector(".eunit").value = editing.unit;
        root.querySelector(".estore").value = editing.store || "";
        editor.scrollIntoView({ block: "nearest" });
      });
      root.querySelector(".esave").addEventListener("click", async () => {
        if (!editing) return;
        const data = {
          ingredient: editing.name,
          price: Number(root.querySelector(".eprice").value),
          amount: Number(root.querySelector(".eamount").value) || 1,
          unit: root.querySelector(".eunit").value,
        };
        const store = root.querySelector(".estore").value.trim();
        if (store) data.store = store;
        await this._service("set_price", data, true);
        list = await this._prices(true);
        listEl.innerHTML = rows();
        editor.style.display = "none";
        this._toast(`💶 Preis für ${editing.name} gespeichert`);
      });
      root.querySelector(".ereset").addEventListener("click", async () => {
        if (!editing) return;
        await this._service("set_price", { ingredient: editing.name, remove: true }, true);
        list = await this._prices(true);
        listEl.innerHTML = rows();
        editor.style.display = "none";
      });
    });
  }

  /* ------------------------------------------------------------ stores & prices (1.3) */
  _zoneName(zone) {
    const known = [...(this._branchSearch?.zones || []), ...(this._branchSearch?.areas || [])].find((z) => z.zone === zone);
    if (known?.name) return known.name;
    const state = this._hass?.states?.[zone];
    if (state?.attributes?.friendly_name) return state.attributes.friendly_name;
    if (zone === "zone.home") return "Zuhause";
    return String(zone || "").replace(/^zone\./, "").replace(/_/g, " ");
  }

  _searchZoneList() {
    const zones = this._branchSearch?.zones;
    if (zones?.length) return zones;
    return Object.keys(this._hass?.states || {})
      .filter((id) => id.startsWith("zone.") && this._hass.states[id].attributes?.latitude != null)
      .map((id) => ({ zone: id, name: this._zoneName(id), default: id === "zone.home" || /arbeit|work/i.test(id + this._zoneName(id)) }));
  }

  _zoneSelection() {
    if (!this._searchZones) {
      const s = this._branchSearch;
      const list = this._searchZoneList();
      const last = s?.time ? (s.areas || []).map((a) => a.zone).filter((z) => list.some((x) => x.zone === z)) : [];
      this._searchZones = new Set(last.length ? last : list.filter((z) => z.default).map((z) => z.zone));
    }
    return this._searchZones;
  }

  _distanceBadges(near, route, max = 3) {
    const out = [];
    const isHome = (z) => z === "zone.home";
    const isWork = (z) => /arbeit|work/i.test(`${z} ${this._zoneName(z)}`);
    for (const [zone, m] of Object.entries(near || {}).sort((a, b) => a[1] - b[1]).slice(0, 2)) {
      const icon = isHome(zone) ? "🏠" : isWork(zone) ? "💼" : "📍";
      const where = isHome(zone) ? "von Zuhause" : `von ${this._zoneName(zone)}`;
      out.push(`<span class="bdg" title="Luftlinie">${icon} ${distText(m)} ${esc(where)}</span>`);
    }
    const routes = Object.entries(route || {}).sort((a, b) => a[1] - b[1]);
    if (routes.length) {
      const names = routes.map(([z]) => this._zoneName(z)).join(", ");
      const detail = routes.map(([z, m]) => `${this._zoneName(z)}: ${distText(m)} neben der Strecke`).join(" · ");
      out.push(`<span class="bdg" title="${esc(`Auf dem Weg von Zuhause (Luftlinie) – ${detail}`)}">💼 am Arbeitsweg (${esc(names)})</span>`);
    }
    return out.slice(0, max + 1);
  }

  _ensureStoresData() {
    if (this._branchSearch === undefined && !this._branchSearchLoading) {
      this._branchSearchLoading = true;
      this._hass
        .callWS({ type: `${DOMAIN}/find_branches`, cached_only: true })
        .then((res) => {
          this._branchSearch = res;
        })
        .catch((err) => {
          this._branchSearch = null;
          this._searchError = errText(err);
        })
        .finally(() => {
          this._branchSearchLoading = false;
          if (this._tab === "stores") this._renderContent();
          this._flushScroll();
        });
    }
    if ((!this._storePrices || this._storePricesStale) && !this._storePricesLoading) this._fetchStorePrices();
  }

  async _fetchStorePrices() {
    const seq = (this._priceSeq = (this._priceSeq || 0) + 1);
    this._storePricesLoading = true;
    this._storePricesStale = false;
    try {
      const query = this._priceQuery.trim();
      const res = await this._hass.callWS({ type: `${DOMAIN}/store_prices`, ...(query ? { query } : {}), limit: 400 });
      if (seq !== this._priceSeq) return;
      this._storePrices = res;
      this._priceError = null;
    } catch (err) {
      if (seq !== this._priceSeq) return;
      this._priceError = errText(err);
      this._storePrices = this._storePrices || { retailers: [], rows: [], total: 0 };
    } finally {
      if (seq === this._priceSeq) this._storePricesLoading = false;
    }
    if (this._tab === "stores") this._renderPriceMatrix();
    this._flushScroll();
  }

  _sec(key, title, body, meta = "", defOpen = true) {
    const open = this._secOpen[key] ?? defOpen;
    return `<details class="card sec" id="sec-${key}" data-sec="${key}" data-open="${open ? 1 : 0}" ${open ? "open" : ""}>
        <summary>${title}${meta ? `<span class="meta">${meta}</span>` : ""}</summary>
        <div class="secbody">${body}</div>
      </details>`;
  }

  _renderStores() {
    this._ensureStoresData();
    const branches = this._data.branches || [];
    const selected = branches.filter((b) => b.selected).length;
    return `<div class="stores">
      ${this._sec("mine", "⭐ Meine Läden", this._renderMyStores(), branches.length ? `${selected} aktiv${branches.length > selected ? ` · ${branches.length - selected} pausiert` : ""}` : "")}
      ${this._sec("near", "🔍 In der Nähe suchen", this._renderNearSearch(), "OpenStreetMap", !branches.length)}
      ${this._sec("manual", "＋ Laden manuell hinzufügen", this._renderManualForm(), "", false)}
      ${this._sec("prices", "💶 Preisliste je Laden", this._renderPriceSection())}
      ${this._sec("receipts", "🧾 Kassenzettel", `<div class="rbox">${this._receiptSectionHtml()}</div>`, this._receiptMeta())}
      ${this._sec("sources", "🔄 Preisquellen", this._renderSources(), "", true)}
    </div>`;
  }

  _renderMyStores() {
    const branches = this._orderedBranches();
    const explain = "Alles kommt in den Hauptladen – nur Angebote und deutlich günstigere Artikel in andere Läden.";
    if (!branches.length) {
      return `<div class="empty" style="padding:20px 8px">
          <div class="big">🏪</div><b>Noch keine Läden gespeichert.</b><br>
          <span class="hint">Wähle deinen <b>Hauptladen</b>: ${esc(explain)} Der erste Laden, den du speicherst, wird automatisch dein Hauptladen.</span>
          <div class="row" style="justify-content:center;margin:14px 0 0">
            <button class="btn primary" data-action="open-sec" data-sec="near">🔍 In der Nähe suchen</button>
            <button class="btn" data-action="open-sec" data-sec="manual">＋ Manuell hinzufügen</button>
          </div>
        </div>`;
    }
    const split = this._data.store_split || {};
    const main = branches.find((b) => b.main);
    let intro = main
      ? `<div class="hint">⭐ <b>Hauptladen ${esc(main.label)}:</b> ${esc(explain)} Ein anderer Laden lohnt sich ab ${eur(split.min_saving ?? 1)} oder ${esc(split.min_percent ?? 20)} % Ersparnis, Angebote ab ${eur(split.offer_min ?? 0.3)}.</div>`
      : `<div class="notice warn">Noch kein Hauptladen – tippe bei einem Laden auf „⭐ Als Hauptladen“.</div>`;
    if (split.mode === "off") intro += `<div class="notice">ℹ️ Die Aufteilung der Einkaufsliste nach Läden ist ausgeschaltet. Einschalten: ${this._settingsLink("stores", "⚙️ Läden & Einkauf")}</div>`;
    else if (split.mode === "main_only") intro += `<div class="notice">ℹ️ Modus „nur Hauptladen“: alles kommt in den Hauptladen, die anderen Läden dienen zum Preisvergleich.</div>`;
    const others = branches.filter((b) => !b.main);
    const cards = branches.map((b) => this._branchCard(b, others)).join("");
    return `${intro}<div class="branchgrid">${cards}</div>${this._renderStorePrefs()}`;
  }

  /** Readable name of an "immer hier" product key (from the backend, else the key). */
  _prefName(key) {
    const name = this._data.store_preference_names?.[key];
    return name || String(key).charAt(0).toUpperCase() + String(key).slice(1);
  }

  /** "Immer hier gekauft": the remembered store per product (also ones not on the list). */
  _renderStorePrefs() {
    const prefs = this._data.store_preferences || {};
    const keys = Object.keys(prefs);
    // without an active split (no main store / "aus") the preferences have no effect
    if (!keys.length || !this._data.store_split?.active) return "";
    const order = this._orderedBranches();
    const active = new Set(order.filter((b) => b.selected).map((b) => b.retailer));
    const rank = (retailer) => {
      const i = order.findIndex((b) => b.retailer === retailer);
      return i < 0 ? order.length : i;
    };
    const groups = new Map();
    for (const key of keys) {
      if (!groups.has(prefs[key])) groups.set(prefs[key], []);
      groups.get(prefs[key]).push({ key, name: this._prefName(key) });
    }
    const rows = [...groups.entries()]
      .sort((a, b) => rank(a[0]) - rank(b[0]) || this._retailerName(a[0]).localeCompare(this._retailerName(b[0]), "de"))
      .map(([retailer, items]) => {
        const store = this._retailerName(retailer);
        const chips = items
          .sort((a, b) => a.name.localeCompare(b.name, "de"))
          .map((p) => `<span class="prefchip">${esc(p.name)}<button class="icon" data-action="pref-forget" data-key="${esc(p.key)}" title="${esc(`${p.name} nicht mehr immer bei ${store} kaufen`)}" aria-label="${esc(`${p.name} nicht mehr immer bei ${store} kaufen`)}">✕</button></span>`)
          .join("");
        const off = active.has(retailer) ? "" : ' <span class="bdg warn" title="Kein aktiver Laden dieser Kette – der Artikel kommt in den Hauptladen">kein aktiver Laden</span>';
        return `<div class="prefrow">${retailerDot(retailer, store).replace('class="rdot"', 'class="rdot sm"')}<div class="prefitems"><b>${esc(store)}</b>${off}<div class="badges">${chips}</div></div></div>`;
      })
      .join("");
    const open = this._secOpen.prefs ?? true;
    return `<details class="prefbox" data-sec="prefs" data-open="${open ? 1 : 0}" ${open ? "open" : ""}>
        <summary>⭐ Immer hier gekauft <span class="meta">${keys.length} Artikel</span></summary>
        <div class="hint">Diese Artikel kommen auf jeder Einkaufsliste in den gemerkten Laden (gemerkt per Sprache oder mit ⇄ „Immer in diesem Laden kaufen“). ✕ = Laden wieder automatisch wählen.</div>
        ${rows}
      </details>`;
  }

  /** ✕ at an "immer hier" product: forget exactly this remembered product key.
   *  By key, not by name: the name would be parsed again ("bio milch" is "Milch") or find
   *  another list item ("Vollmilch"). Items of the product get the automatic store again,
   *  only a choice of another store stays (the backend decides, in one step). */
  async _forgetStorePref(el, key) {
    const retailer = this._data.store_preferences?.[key];
    if (!retailer) return;
    const name = this._prefName(key);
    el.disabled = true;
    try {
      await this._hass.callWS({ type: `${DOMAIN}/forget_store_preference`, key });
      this._toast(`✕ ${name}: nicht mehr immer bei ${this._retailerName(retailer)}`);
    } catch (err) {
      el.disabled = false;
      this._toast(errText(err));
    }
  }

  _branchCard(b, others) {
    const pos = others.indexOf(b);
    const badges = [];
    if (b.main) badges.push('<span class="bdg star">⭐ Hauptladen</span>');
    if (!b.selected) badges.push('<span class="bdg">⏸ pausiert</span>');
    if (this._retailerKind(b.retailer) === "drugstore") badges.push('<span class="bdg" title="Drogerie: Drogerie- und Haushaltsartikel kommen hierher">🧴 Drogerie</span>');
    badges.push(...this._distanceBadges(b.near, b.route));
    if (!b.postcode) badges.push('<span class="bdg warn" title="Ohne Postleitzahl werden für diesen Laden keine eigenen Angebote gesucht">PLZ fehlt</span>');
    else if (b.postcode_guessed) badges.push('<span class="bdg warn" title="Die PLZ stammt von einem Laden in der Nähe – bitte prüfen">PLZ geschätzt</span>');
    if (b.retailer_guessed) badges.push('<span class="bdg warn" title="Die Kette wurde aus Name oder PLZ erraten (z. B. Aldi Süd/Nord)">Kette bitte prüfen</span>');
    const address = [b.street, [b.postcode, b.city].filter(Boolean).join(" ")].filter(Boolean).join(", ");
    const markets = this._reweMarkets[b.id];
    const link = STORE_LINKS[b.retailer];
    let rewe = "";
    if (link) {
      const stored = b[link.field] || "";
      const value = this._reweInput[b.id] ?? stored;
      const label = link.title.replace(/^\S+ /, "");
      const list = markets?.markets?.length
        ? `<div class="markets">${markets.markets
            .map((m) => `<div class="market"><span><b>${esc(m.name || link.name)}</b><br><span class="meta">${esc([m.street, [m.postcode, m.city].filter(Boolean).join(" ")].filter(Boolean).join(", "))} · ID ${esc(m.id)}${m.distance_km != null ? ` · ${esc(String(m.distance_km).replace(".", ","))} km` : ""}${m.branch_id && m.branch_id !== b.id ? " · schon bei einem anderen Laden" : ""}</span></span>${m.id === stored ? '<span class="bdg ok">✓ gewählt</span>' : `<button class="btn small" data-action="rewe-pick" data-id="${esc(b.id)}" data-market="${esc(m.id)}">Übernehmen</button>`}</div>`)
            .join("")}</div>`
        : "";
      const off = b.retailer !== "rewe" && this._data.economy?.price_sources?.[link.source]?.enabled === false;
      rewe = `<div class="rewebox">
          <span>${link.title}</span>
          <input data-input="rewe-id" data-enter="rewe-save" data-id="${esc(b.id)}" data-focuskey="rewe-${esc(b.id)}" value="${esc(value)}" placeholder="${esc(link.placeholder)}" inputmode="${link.mode}" aria-label="${esc(label)}">
          <button class="btn small primary" data-action="rewe-save" data-id="${esc(b.id)}" title="${esc(label)} speichern" ${value.trim() !== stored ? "" : "hidden"}>💾 Speichern</button>
          <button class="btn small" data-action="rewe-search" data-id="${esc(b.id)}" ${markets?.loading ? "disabled" : ""}>${markets?.loading ? "⏳ Suche …" : link.search}</button>
        </div>
        ${off ? `<div class="hint">Wird genutzt, sobald du ${b.retailer === "edeka" ? "„EDEKA-Angebote“" : "„ALDI-SÜD-Preise“"} einschaltest: ${this._settingsLink("offers", "⚙️ Angebote & Preisquellen")}</div>` : ""}
        ${markets?.error ? `<div class="notice err">${esc(markets.error)}</div>` : ""}
        ${markets?.markets && !markets.markets.length ? `<div class="hint">${esc(link.none)}${link.list === "markets" ? ` ${esc(markets.zip || "")}` : ""}.</div>` : ""}
        ${list}`;
    }
    return `<div class="branch ${b.main ? "main" : ""} ${b.selected ? "" : "off"}">
        <div class="bhead">${retailerDot(b.retailer, b.retailer_name)}<div style="min-width:0"><div class="bname">${esc(b.label)}</div><div class="baddr">${esc(b.retailer_name || this._retailerName(b.retailer))}${address ? ` · ${esc(address)}` : " · ohne Adresse"}</div></div></div>
        <div class="badges">${badges.join("")}</div>
        ${rewe}
        <div class="bacts">
          ${b.main ? "" : `<button class="btn small" data-action="branch-main" data-id="${esc(b.id)}">⭐ Als Hauptladen</button>`}
          <label class="switch" title="Pausierte Läden werden beim Einkauf und bei Angeboten nicht genutzt"><input type="checkbox" data-change="branch-selected" data-id="${esc(b.id)}" ${b.selected ? "checked" : ""}> aktiv</label>
          <span class="icons">
            ${b.main ? "" : `<button class="icon" data-action="branch-move" data-id="${esc(b.id)}" data-delta="-1" title="Nach oben" aria-label="Nach oben" ${pos <= 0 ? "disabled" : ""}>▲</button><button class="icon" data-action="branch-move" data-id="${esc(b.id)}" data-delta="1" title="Nach unten" aria-label="Nach unten" ${pos === others.length - 1 ? "disabled" : ""}>▼</button>`}
            <button class="icon" data-action="branch-edit" data-id="${esc(b.id)}" title="Bearbeiten" aria-label="Bearbeiten">✏️</button>
            <button class="icon" data-action="branch-remove" data-id="${esc(b.id)}" title="Entfernen" aria-label="Entfernen">🗑</button>
          </span>
        </div>
      </div>`;
  }

  /** Show a saved branch (service response) at once; the next data update confirms it. */
  _applyBranch(branch) {
    const list = this._data?.branches;
    const i = branch?.id && list ? list.findIndex((b) => b.id === branch.id) : -1;
    if (i < 0) return false;
    list[i] = { ...list[i], ...branch };
    if (branch.main) for (const b of list) if (b.id !== branch.id) b.main = false;
    this._renderContent();
    return true;
  }

  async _moveBranch(id, delta) {
    const ordered = this._orderedBranches();
    const main = ordered.filter((b) => b.main);
    const others = ordered.filter((b) => !b.main);
    const i = others.findIndex((b) => b.id === id);
    const j = i + delta;
    if (i < 0 || j < 0 || j >= others.length) return;
    [others[i], others[j]] = [others[j], others[i]];
    try {
      const res = await this._hass.callWS({ type: `${DOMAIN}/reorder_branches`, ids: [...main, ...others].map((b) => b.id) });
      if (res?.branches) {
        this._data.branches = res.branches;
        this._renderContent();
      }
    } catch (err) {
      this._toast(errText(err));
    }
  }

  async _searchReweMarkets(id) {
    const b = this._branch(id);
    if (!b) return;
    const link = STORE_LINKS[b.retailer] || STORE_LINKS.rewe;
    const zip = b.postcode || null;
    this._reweMarkets[id] = { loading: true, zip };
    this._renderContent();
    try {
      // ALDI SÜD searches by coordinates only: the branch's (else the backend uses home)
      const msg = link.list === "stores" ? (b.lat != null && b.lon != null ? { lat: b.lat, lon: b.lon } : {}) : { zip };
      const res = await this._hass.callWS({ type: `${DOMAIN}/${link.ws}`, ...msg });
      this._reweMarkets[id] = { markets: res[link.list] || [], zip: res.zip_code || zip };
    } catch (err) {
      this._reweMarkets[id] = { error: errText(err), zip };
    }
    if (this._tab === "stores") this._renderContent();
  }

  _renderNearSearch() {
    const s = this._branchSearch;
    if (s === undefined) return `<div class="hint">⏳ Lade letzte Suche …</div>`;
    const zones = this._searchZoneList();
    const chosen = this._zoneSelection();
    const radius = this._searchRadius ?? (s?.time && s.radius_km ? s.radius_km : s?.defaults?.radius_km || 3);
    const route = this._searchRoute ?? (s?.time ? Boolean(s.route) : s?.defaults?.route ?? true);
    const radiusOptions = [...new Set([...RADIUS_CHOICES, radius])].sort((a, b) => a - b);
    const zoneChips = zones.length
      ? zones.map((z) => `<button class="chip ${chosen.has(z.zone) ? "active" : ""}" data-action="zone-toggle" data-zone="${esc(z.zone)}" aria-pressed="${chosen.has(z.zone)}">${z.zone === "zone.home" ? "🏠" : /arbeit|work/i.test(z.zone + z.name) ? "💼" : "📍"} ${esc(z.name)}</button>`).join("")
      : `<span class="hint">Keine Zonen mit Koordinaten gefunden – lege in Home Assistant Zonen an (Einstellungen → Bereiche &amp; Zonen).</span>`;
    const results = s?.results || [];
    const warnings = [...(s?.warnings || [])];
    const error = this._searchError || s?.error;
    // chain filter: around home, work and the commute there can be a hundred shops
    const chainOf = (r) => r.retailer || "?";
    const chains = new Map();
    for (const r of results) {
      const id = chainOf(r);
      const c = chains.get(id) || { id, name: r.retailer_name || this._retailerName(r.retailer) || "Unbekannt", count: 0 };
      c.count += 1;
      chains.set(id, c);
    }
    const picked = new Set([...this._searchChains].filter((id) => chains.has(id)));
    const shown = picked.size ? results.filter((r) => picked.has(chainOf(r))) : results;
    const chainChips =
      chains.size > 1
        ? `<div class="chainchips" role="group" aria-label="Nach Kette filtern">
            <button class="chip ${picked.size ? "" : "active"}" data-action="chain-toggle" data-chain="" aria-pressed="${!picked.size}">Alle · ${results.length}</button>
            ${[...chains.values()]
              .sort((a, b) => a.name.localeCompare(b.name, "de"))
              .map((c) => `<button class="chip ${picked.has(c.id) ? "active" : ""}" data-action="chain-toggle" data-chain="${esc(c.id)}" aria-pressed="${picked.has(c.id)}">${retailerDot(c.id === "?" ? "" : c.id, c.name).replace('class="rdot"', 'class="rdot xs"')} ${esc(c.name)} · ${c.count}</button>`)
              .join("")}
          </div>`
        : "";
    const list = results.length
      ? `${chainChips}<div class="osmlist">${shown
          .map((r) => {
            const addr = [r.street, [r.postcode, r.city].filter(Boolean).join(" ")].filter(Boolean).join(", ");
            const flags = [
              ...this._distanceBadges(r.near, r.route, 2),
              r.postcode_guessed ? '<span class="bdg warn">PLZ geschätzt</span>' : "",
              !r.postcode ? '<span class="bdg warn">PLZ fehlt</span>' : "",
              r.retailer_guessed ? '<span class="bdg warn">Kette bitte prüfen</span>' : "",
            ].join("");
            return `<div class="osm">${retailerDot(r.retailer, r.retailer_name)}
              <div class="info"><b>${esc(r.retailer_name || r.retailer)}</b> <span class="meta">${esc(r.name && r.name !== r.retailer_name ? r.name : "")}</span>
                <div class="baddr">${esc(addr || "ohne Adresse")}</div><div class="badges" style="margin-top:4px">${flags}</div></div>
              ${r.saved ? '<span class="bdg ok">✓ gespeichert</span>' : `<button class="btn small primary" data-action="osm-add" data-id="${esc(r.id)}">＋ Hinzufügen</button>`}
            </div>`;
          })
          .join("")}</div>`
      : s?.time
        ? `<div class="hint">In diesem Umkreis wurde kein bekannter Supermarkt gefunden. Probier einen größeren Radius.</div>`
        : "";
    const busy = this._searching;
    return `
      <div class="hint">Wo kaufst du ein? Wähle die Orte, um die herum gesucht wird.</div>
      <div class="zonechips">${zoneChips}</div>
      <div class="row" style="margin:0">
        <label class="switch"><input type="checkbox" data-change="search-route" ${route ? "checked" : ""}> 💼 Arbeitsweg einbeziehen</label>
        <label class="switch">Umkreis <select data-change="search-radius" aria-label="Umkreis">${radiusOptions.map((km) => `<option value="${km}" ${Number(km) === Number(radius) ? "selected" : ""}>${String(km).replace(".", ",")} km</option>`).join("")}</select></label>
        <span class="spacer"></span>
        <button class="btn primary" data-action="osm-search" ${busy || !chosen.size ? "disabled" : ""}>${busy ? "⏳ Suche läuft … (bis zu 3 Min.)" : "🔍 Suchen"}</button>
        ${s?.time && !busy ? `<button class="btn" data-action="osm-search" data-refresh="1" title="Neu bei OpenStreetMap abfragen">🔄 Neu suchen</button>` : ""}
      </div>
      <div class="hint">🔒 Die Koordinaten deiner Zonen werden – auf ca. 100 m gerundet – an overpass-api.de gesendet (ist der Server voll: an den Ersatzserver overpass.kumi.systems). Das passiert nur, wenn du auf „Suchen“ tippst.</div>
      ${error ? `<div class="notice err">⚠️ ${esc(error)}</div>` : ""}
      ${warnings.map((w) => `<div class="notice warn">${esc(w)}</div>`).join("")}
      ${s?.time ? `<div class="meta">Letzte Suche: ${esc(timeText(s.time))} · ${shown.length < results.length ? `${shown.length} von ${results.length}` : results.length} Läden${s.areas?.length ? ` um ${esc(s.areas.map((a) => a.name).join(", "))}` : ""}${s.cached ? " · gespeichert" : ""}</div>` : ""}
      ${list}
      <div class="meta">${esc(s?.attribution || "© OpenStreetMap-Mitwirkende (ODbL)")}</div>`;
  }

  async _findBranches(refresh) {
    const zones = [...this._zoneSelection()];
    if (!zones.length) return this._toast("Bitte mindestens eine Zone auswählen.");
    const s = this._branchSearch;
    const radius = this._searchRadius ?? (s?.time && s.radius_km ? s.radius_km : s?.defaults?.radius_km || 3);
    const route = this._searchRoute ?? (s?.time ? Boolean(s.route) : s?.defaults?.route ?? true);
    this._searching = true;
    this._searchError = null;
    this._renderContent();
    try {
      const res = await this._hass.callWS({ type: `${DOMAIN}/find_branches`, zones, radius_km: Number(radius), route, refresh: Boolean(refresh) });
      this._branchSearch = res;
      this._toast(res.count ? `🔍 ${res.count} Läden gefunden` : "Keine Läden gefunden");
    } catch (err) {
      this._searchError = errText(err);
    } finally {
      this._searching = false;
      if (this._tab === "stores") this._renderContent();
    }
  }

  async _refreshSearchFlags() {
    try {
      this._branchSearch = await this._hass.callWS({ type: `${DOMAIN}/find_branches`, cached_only: true });
    } catch (e) {
      /* keep the old list */
    }
    if (this._tab === "stores") this._renderContent();
  }

  async _addOsmBranch(id) {
    const r = (this._branchSearch?.results || []).find((x) => x.id === id);
    if (!r) return;
    let res;
    try {
      res = await this._callService("save_branch", { id });
    } catch (err) {
      // not in the last stored search any more: send chain and address along
      const data = { id, store: r.retailer };
      for (const key of ["name", "street", "postcode", "city", "lat", "lon"]) if (r[key] != null && r[key] !== "") data[key] = r[key];
      res = await this._service("save_branch", data, true);
    }
    const b = res?.branch;
    this._toast(b?.main ? `⭐ ${b.label} ist dein Hauptladen` : `🏪 ${b?.label || r.label} hinzugefügt`);
    this._refreshSearchFlags();
  }

  _renderManualForm() {
    const m = this._manual;
    const retailers = this._data.economy?.retailers || [];
    const field = (key, label, attrs = "") =>
      `<label class="field">${label}<input data-input="manual" data-field="${key}" data-focuskey="manual-${key}" data-enter="manual-save" value="${esc(m[key] || "")}" ${attrs}></label>`;
    return `
      <div class="hint">Für Läden, die die Suche nicht findet (oder ohne Zonen). Mit Postleitzahl werden auch Angebote für diesen Laden gesucht.</div>
      <div class="formgrid">
        <label class="field">Kette<select data-change="manual" data-field="store"><option value="">– bitte wählen –</option>${chainOptions(retailers, m.store)}</select></label>
        ${field("label", "Name (optional)", 'placeholder="z. B. Lidl am Bahnhof"')}
        ${field("street", "Straße (optional)", 'placeholder="Hauptstraße 5"')}
        ${field("postcode", "PLZ", 'inputmode="numeric" maxlength="5" placeholder="80331"')}
        ${field("city", "Ort (optional)", 'placeholder="München"')}
      </div>
      <div><button class="btn primary" data-action="manual-save">＋ Laden speichern</button></div>`;
  }

  async _saveManualBranch() {
    const m = this._manual;
    if (!m.store) return this._toast("Bitte die Kette auswählen.");
    const postcode = (m.postcode || "").trim();
    if (postcode && !/^\d{5}$/.test(postcode)) return this._toast("Die Postleitzahl hat 5 Ziffern.");
    const data = { store: m.store };
    for (const key of ["label", "street", "city"]) if ((m[key] || "").trim()) data[key] = m[key].trim();
    if (postcode) data.postcode = postcode;
    if (this._savingManual) return; // double tap
    this._savingManual = true;
    let res;
    try {
      res = await this._service("save_branch", data, true);
    } finally {
      this._savingManual = false;
    }
    this._manual = { store: "", label: "", street: "", postcode: "", city: "" };
    const b = res?.branch;
    this._toast(b?.main ? `⭐ ${b.label} ist dein Hauptladen` : `🏪 ${b?.label || "Laden"} gespeichert`);
    this._renderContent();
    if (this._branchSearch?.results?.length) this._refreshSearchFlags();
  }

  _openBranchEditor(id) {
    const b = this._branch(id);
    if (!b) return;
    const retailers = this._data.economy?.retailers || [];
    const body = `
      <div class="hint">${b.source === "osm" ? "Aus OpenStreetMap übernommen – du kannst alles anpassen." : "Manuell angelegter Laden."}</div>
      <label class="field">Name<input class="blabel" value="${esc(b.label)}" placeholder="${esc(`${b.retailer_name || ""} ${b.street || b.city || ""}`.trim())}"></label>
      <label class="field">Kette${b.retailer_guessed ? ' <span class="bdg warn">bitte prüfen</span>' : ""}<select class="bstore">${chainOptions(retailers, b.retailer)}</select></label>
      <div class="grid2">
        <label class="field">Straße<input class="bstreet" value="${esc(b.street || "")}"></label>
        <label class="field">PLZ${b.postcode_guessed ? ' <span class="bdg warn">geschätzt</span>' : ""}<input class="bpostcode" value="${esc(b.postcode || "")}" inputmode="numeric" maxlength="5"></label>
        <label class="field">Ort<input class="bcity" value="${esc(b.city || "")}"></label>
      </div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">💾 Speichern</button>`;
    this._showModal("Laden bearbeiten", body, footer, (root) => {
      root.querySelector(".blabel").focus();
      let saving = false;
      const save = async () => {
        if (saving) return;
        const v = (sel) => root.querySelector(sel).value.trim();
        const postcode = v(".bpostcode");
        if (postcode && !/^\d{5}$/.test(postcode)) return this._toast("Die Postleitzahl hat 5 Ziffern.");
        const data = { id, store: v(".bstore"), street: v(".bstreet"), postcode, city: v(".bcity") };
        if (v(".blabel") !== b.label) data.label = v(".blabel");
        saving = true;
        try {
          const res = await this._service("save_branch", data, true);
          this._closeModal();
          this._toast("💾 Laden gespeichert");
          this._applyBranch(res?.branch);
        } catch (e) {
          /* toast shown */
        } finally {
          saving = false;
        }
      };
      root.querySelector(".save").addEventListener("click", save);
      // Enter in a text field saves (like the price dialog; "Fertig"/"Los" on phone keyboards)
      root.querySelector(".mbody").addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" && ev.target.tagName === "INPUT") {
          ev.preventDefault();
          save();
        }
      });
    });
  }

  _renderPriceSection() {
    const kinds = [
      ["all", "Alles"],
      ["food", "🍽️ Lebensmittel"],
      ["nonfood", "🧴 Drogerie & Haushalt"],
    ]
      .map(([k, label]) => `<button class="${this._priceKind === k ? "on" : ""}" data-action="price-kind" data-kind="${k}" aria-pressed="${this._priceKind === k}">${label}</button>`)
      .join("");
    return `
      <div class="pmtools">
        <input type="search" placeholder="🔍 Artikel suchen, z. B. „Butter“" value="${esc(this._priceQuery)}" data-input="price-filter" data-focuskey="price-filter" aria-label="Preisliste filtern">
        <span class="seg" role="group" aria-label="Artikel">${kinds}</span>
        <button class="btn ghost" data-action="open-prices" title="Richtwerte und eigene allgemeine Preise">📋 Allgemeine Richtwerte</button>
      </div>
      <div class="hint">Tippe auf einen Preis, um ihn für diesen Laden zu ändern. <span class="bdg ok">grün</span> = am günstigsten. <span class="bdg warn">🏷️</span> = aktuelles Angebot (zählt nicht als Normalpreis). Ohne Ladenpreis gilt dein allgemeiner Preis bzw. der Richtwert. Preise vom 🧾 Kassenzettel sind eigene Preise des Ladens. Fehlt ein Artikel (z. B. Kaffee)? Such ihn oben und lege ihn an.</div>
      <div class="pmbox">${this._priceMatrixHtml()}</div>`;
  }

  _renderPriceMatrix() {
    const box = this._content.querySelector(".pmbox");
    if (box) box.innerHTML = this._priceMatrixHtml();
  }

  /** "🏷️ 1,19 € bis Sa" of the current offer of a price list cell (display only). */
  _cellOfferText(offer) {
    if (!offer || offer.price == null) return "";
    const until = validText(offer, this._today());
    return `🏷️ ${eur(offer.price)}${until ? ` ${until}` : ""}`;
  }

  _priceCellHtml(row, retailer, cell, best) {
    const offer = cell?.offer || row.offers?.[retailer] || null;
    const offerTitle = offer ? `Angebot: ${offer.title || row.name} ${eur(offer.price)}${offer.app_price != null ? ` (mit App ${eur(offer.app_price)})` : offer.loyalty ? " (mit App/Karte)" : ""}${packText(offer.pack_amount, offer.pack_unit) ? ` · ${packText(offer.pack_amount, offer.pack_unit)}` : ""}` : "";
    if (!cell) {
      if (offer) {
        // only an offer is known: never shown as a regular price
        return `<button class="cell offeronly" data-action="price-cell" data-key="${esc(row.key)}" data-store="${esc(retailer)}" title="${esc(`${offerTitle} – Normalpreis eintragen`)}"><span class="p">${esc(this._cellOfferText(offer))}</span><span class="s">kein Normalpreis bekannt</span></button>`;
      }
      // a drugstore column: food is rarely sold there
      const dim = this._retailerKind(retailer) === "drugstore" && !NONFOOD_AISLES.includes(row.category);
      return `<button class="cell none ${dim ? "dim" : ""}" data-action="price-cell" data-key="${esc(row.key)}" data-store="${esc(retailer)}" title="Preis eintragen"><span class="p">＋</span></button>`;
    }
    const pack = packText(cell.amount, cell.unit);
    const hint = [PRICE_SOURCE[cell.source] || cell.source, cell.source === "user" ? "" : dayText(cell.updated)].filter(Boolean).join(" ");
    const title = [cell.name && cell.name !== row.name ? cell.name : "", unitPriceText(cell.unit_price, cell.base), cell.stale ? "älter als ein halbes Jahr" : "", offerTitle].filter(Boolean).join(" · ");
    return `<button class="cell ${best ? "best" : ""} ${cell.stale ? "stale" : ""}" data-action="price-cell" data-key="${esc(row.key)}" data-store="${esc(retailer)}" title="${esc(title)}">
        <span class="p">${eur(cell.price)}${best ? " ✓" : ""}${cell.stale ? " ⏳" : ""}</span><span class="s">${esc(pack)}</span><span class="s">${esc(hint)}</span>${offer ? `<span class="o">${esc(this._cellOfferText(offer))}</span>` : ""}</button>`;
  }

  _baseCellHtml(row) {
    const general = row.general;
    const cell = general || row.default;
    if (!cell) return `<button class="cell none" data-action="price-cell" data-key="${esc(row.key)}"><span class="p">＋</span></button>`;
    // an own general price from 1.2 may carry a store label ("Preis bei Aldi")
    const label = general ? `✏️ eigener Preis${general.store ? ` (${general.store})` : ""}` : "Richtwert";
    return `<button class="cell" data-action="price-cell" data-key="${esc(row.key)}" title="Gilt in allen Läden ohne eigenen oder gelernten Ladenpreis">
        <span class="p">${eur(cell.price)}</span><span class="s">${esc(packText(cell.amount, cell.unit))}</span><span class="s">${esc(label)}</span></button>`;
  }

  _priceMatrixHtml() {
    const m = this._storePrices;
    if (!m) return `<div class="hint">⏳ Lade Preisliste …</div>`;
    if (this._priceError) return `<div class="notice err">${esc(this._priceError)}</div>`;
    const retailers = m.retailers || [];
    // rows of the chosen aisles (Lebensmittel / Drogerie & Haushalt)
    const kindRows = (m.rows || []).filter((r) => this._priceKind === "all" || (this._priceKind === "nonfood") === NONFOOD_AISLES.includes(r.category));
    const rows = kindRows.slice(0, this._priceLimit);
    // an article that is not in the list yet (e.g. "Kaffee") can be added under the typed name
    const query = this._priceQuery.trim();
    const q = fold(query);
    const listed = (m.rows || []).some((r) => r.key === q || fold(r.name) === q || (r.aliases || []).some((a) => fold(a) === q));
    const add = q && !listed ? `<button class="btn small" data-action="price-new">＋ „${esc(query)}“ als Artikel anlegen</button>` : "";
    if (!rows.length) return `<div class="hint">${query ? `Nichts gefunden für „${esc(query)}“.` : "Noch keine Preise."}</div>${add ? `<div class="row">${add}</div>` : ""}`;
    // phone: no Richtwert column, so the general price / estimate goes under the name
    const baseLine = (row) => {
      const cell = row.general || row.default;
      return cell ? `<span class="meta">${row.general ? "✏️ allgemein" : "Richtwert"} ${eur(cell.price)}${packText(cell.amount, cell.unit) ? ` / ${esc(packText(cell.amount, cell.unit))}` : ""}</span>` : "";
    };
    const name = (row, withBase = false) => `<td class="pname">${esc(row.name)}${row.category ? `<span class="meta">${CATEGORY_ICONS[row.category] || ""} ${esc(row.category)}</span>` : ""}${withBase ? baseLine(row) : ""}</td>`;
    const head = (r) => `${retailerDot(r.id, r.name).replace('class="rdot"', 'class="rdot sm"')}${esc(r.name)}${r.id === m.main_retailer ? " ⭐" : ""}${r.kind === "drugstore" ? ' <span title="Drogerie">🧴</span>' : ""}`;
    let table;
    if (this._narrowQuery?.matches && retailers.length) {
      const store = retailers.some((r) => r.id === this._priceStore) ? this._priceStore : m.main_retailer || retailers[0].id;
      const select = `<label class="switch">Laden <select data-change="price-store" aria-label="Laden">${retailers.map((r) => `<option value="${esc(r.id)}" ${r.id === store ? "selected" : ""}>${esc(r.name)}${r.id === m.main_retailer ? " ⭐" : ""}</option>`).join("")}</select></label>`;
      const body = rows
        .map((row) => {
          const best = row.cheapest ? row.stores[row.cheapest] : null;
          const bestCell = best
            ? `<div class="cell static best"><span class="p">${eur(best.price)}</span><span class="s">${esc(this._retailerName(row.cheapest))}</span><span class="s">${esc(packText(best.amount, best.unit))}</span></div>`
            : `<div class="cell static none"><span class="p">–</span></div>`;
          return `<tr>${name(row, true)}<td>${this._priceCellHtml(row, store, row.stores[store], row.cheapest === store)}</td><td>${bestCell}</td></tr>`;
        })
        .join("");
      table = `${select}<div class="pmwrap"><table class="pm"><thead><tr><th>Artikel</th><th>${head(retailers.find((r) => r.id === store))}</th><th>Günstigster</th></tr></thead><tbody>${body}</tbody></table></div>`;
    } else {
      const body = rows
        .map((row) => `<tr>${name(row)}<td>${this._baseCellHtml(row)}</td>${retailers.map((r) => `<td>${this._priceCellHtml(row, r.id, row.stores[r.id], row.cheapest === r.id)}</td>`).join("")}</tr>`)
        .join("");
      table = `<div class="pmwrap"><table class="pm"><thead><tr><th>Artikel</th><th>Richtwert</th>${retailers.map((r) => `<th class="${r.kind === "drugstore" ? "drug" : ""}">${head(r)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
    }
    const total = this._priceKind === "all" ? m.total ?? (m.rows || []).length : kindRows.length;
    const shown = Math.min(rows.length, total);
    const more = kindRows.length > this._priceLimit ? `<button class="btn small" data-action="price-more">Mehr anzeigen</button>` : "";
    const empty = !retailers.length ? `<div class="notice">Noch keine Läden – speichere oben deine Läden, dann siehst du hier ihre Preise nebeneinander.</div>` : "";
    const addRow = add ? `<div class="row" style="margin:0 0 6px"><span class="meta">Nicht dabei?</span>${add}</div>` : "";
    return `${empty}${addRow}${table}<div class="row" style="margin:6px 0 0"><span class="meta">${shown} von ${total} Artikeln${this._storePricesLoading ? " · ⏳" : ""}</span><span class="spacer"></span>${more}</div>`;
  }

  _openPriceCell(key, retailer, newName = null) {
    // newName: a new article (not in the list yet), its name and store are chosen here
    const draft = newName != null;
    const row = draft ? { key: "", name: newName, stores: {}, default: null, general: null } : (this._storePrices?.rows || []).find((r) => r.key === key);
    if (!row) return;
    const retailers = this._storePrices?.retailers || [];
    const main = this._storePrices?.main_retailer;
    if (draft) {
      // preset: the store shown on the phone, else the main store, else all stores
      const shown = this._narrowQuery?.matches && retailers.some((r) => r.id === this._priceStore) ? this._priceStore : null;
      retailer = shown || (retailers.some((r) => r.id === main) ? main : retailers[0]?.id) || null;
    }
    const cell = draft ? null : retailer ? row.stores?.[retailer] : row.general;
    const offer = !draft && retailer ? cell?.offer || row.offers?.[retailer] || null : null;
    const base = cell || row.default || { price: "", amount: 1, unit: "Stück" };
    const storeName = retailer ? this._retailerName(retailer) : "";
    const units = PRICE_UNITS.includes(base.unit) ? PRICE_UNITS : [base.unit, ...PRICE_UNITS];
    const history = (cell?.history || []).slice(-6).reverse();
    const num = (v) => (v == null || v === "" ? "" : String(v).replace(".", ","));
    const parse = (v) => Number(String(v).trim().replace(/\s*€$/, "").replace(",", "."));
    // own prices: typed ones and those taken from a receipt (1.4)
    const own = retailer ? ["user", "receipt"].includes(cell?.source) : Boolean(row.general);
    const info = cell
      ? `${PRICE_SOURCE[cell.source] || (retailer ? cell.source : "✏️ eigener Preis")}${cell.updated ? ` · ${dayText(cell.updated)}` : ""}${cell.stale ? " · ⏳ älter als ein halbes Jahr" : ""}${cell.name && cell.name !== row.name ? ` · „${cell.name}“` : ""}`
      : row.default
        ? `Noch kein eigener Preis – Richtwert ${eur(row.default.price)} für ${packText(row.default.amount, row.default.unit)}`
        : "Noch kein Preis";
    const head = draft
      ? `<label class="field">Artikel<input class="ename" autocomplete="off" placeholder="z. B. Kaffee" value="${esc(row.name)}"></label>
      <label class="field">Laden<select class="estore"><option value="">Alle Läden (allgemeiner Preis)</option>${retailers.map((r) => `<option value="${esc(r.id)}" ${r.id === retailer ? "selected" : ""}>${esc(r.name)}${r.id === main ? " ⭐" : ""}</option>`).join("")}</select></label>
      <div class="hint">Der Artikel steht danach in der Preisliste; auf der Einkaufsliste bekommt er diesen Preis.</div>`
      : `<div class="hint">${retailer ? `Preis bei <b>${esc(storeName)}</b>` : "Allgemeiner Preis – gilt in allen Läden ohne eigenen oder gelernten Ladenpreis"} · ${esc(info)}</div>`;
    const body = `
      ${head}
      <div class="grid2">
        <label class="field">Preis (€)<input class="eprice" inputmode="decimal" autocomplete="off" placeholder="1,99" value="${esc(num(base.price))}"></label>
        <label class="field">Packung<span style="display:flex;gap:6px"><input class="eamount" inputmode="decimal" autocomplete="off" style="width:100px" value="${esc(num(base.amount ?? 1))}"><select class="eunit">${units.map((u) => `<option ${u === base.unit ? "selected" : ""}>${esc(u)}</option>`).join("")}</select></span></label>
      </div>
      ${history.length > 1 ? `<div class="meta">Verlauf: ${history.map((h) => `${dayText(h.date)} ${eur(h.price)}${h.source === "receipt" ? " 🧾" : ""}`).join(" · ")}</div>` : ""}
      ${offer ? `<div class="notice warn">${esc(this._cellOfferText(offer))}${offer.title && offer.title !== row.name ? ` – ${esc(offer.title)}` : ""}: aktuelles Angebot, zählt nicht als Normalpreis.</div>` : ""}
      ${retailer && cell && !own ? `<div class="hint">Dieser Preis wurde automatisch gelernt. Ein eigener Preis hat Vorrang.</div>` : ""}`;
    const footer = `${own ? `<button class="btn reset">↩ Zurücksetzen</button>` : ""}<span class="spacer"></span><button class="btn" data-close>Abbrechen</button><button class="btn primary save">💾 Speichern</button>`;
    const title = draft ? "＋ Neuer Artikel" : `${row.name}${storeName ? ` · ${storeName}` : ""}`;
    this._showModal(title, body, footer, (root) => {
      const price = root.querySelector(".eprice");
      const nameField = root.querySelector(".ename");
      const first = nameField && !nameField.value.trim() ? nameField : price;
      first.focus();
      first.select?.();
      const done = async (data, message) => {
        try {
          await this._service("set_price", data, true);
          this._closeModal();
          this._toast(message);
          if (draft) {
            // show the new article in the list
            this._priceQuery = data.ingredient;
            const filter = this._content.querySelector('[data-input="price-filter"]');
            if (filter) filter.value = data.ingredient;
          }
          await this._fetchStorePrices();
        } catch (e) {
          /* toast shown */
        }
      };
      const save = () => {
        const name = draft ? nameField.value.trim() : row.name;
        if (!name) return this._toast("Bitte einen Artikel eingeben, z. B. Kaffee.");
        const value = parse(price.value);
        if (price.value.trim() === "" || !Number.isFinite(value) || value < 0) return this._toast("Bitte einen Preis eingeben, z. B. 1,99.");
        const store = draft ? root.querySelector(".estore").value || null : retailer;
        const where = store ? ` bei ${this._retailerName(store)}` : "";
        const amount = parse(root.querySelector(".eamount").value);
        const data = { ingredient: name, price: value, amount: Number.isFinite(amount) && amount > 0 ? amount : 1, unit: root.querySelector(".eunit").value };
        if (store) data.store = store;
        done(data, `💶 ${name}: ${eur(value)}${where} gespeichert`);
      };
      root.querySelector(".save").addEventListener("click", save);
      for (const field of [price, nameField]) field?.addEventListener("keydown", (ev) => ev.key === "Enter" && save());
      root.querySelector(".reset")?.addEventListener("click", () => {
        const data = { ingredient: row.name, remove: true };
        if (retailer) data.store = retailer;
        done(data, `↩ ${row.name}${storeName ? ` bei ${storeName}` : ""}: eigener Preis entfernt`);
      });
    });
  }

  _renderSources() {
    const eco = this._data.economy || {};
    const meta = eco.offers_meta || {};
    const online = eco.offers_source === "marktguru";
    const catalog = eco.catalog || {};
    const rewe = eco.price_sources?.rewe || {};
    const enable = (label) => `<div class="hint">Einschalten: ${this._settingsLink("offers", "⚙️ Angebote & Preisquellen")}${label ? ` ${esc(label)}` : ""}</div>`;
    const targets = (this._data.offer_targets || []).map((t) => `<span class="bdg">PLZ ${esc(t.zip_code)} · ${esc((t.stores || []).join(", "))}</span>`).join("");
    const chips = {
      ok: '<span class="bdg ok">✅ ok</span>',
      pending: '<span class="bdg">⏳ wartet</span>',
      error: '<span class="bdg bad">⚠️ Fehler</span>',
      blocked: '<span class="bdg bad">⛔ gesperrt</span>',
      off: '<span class="bdg">⏸ aus</span>',
    };
    const mgStatus = !online
      ? chips.off
      : meta.status === "blocked" || catalog.status === "blocked"
        ? '<span class="bdg bad">⛔ pausiert</span>'
        : meta.status === "error"
          ? chips.error
          : meta.last_update || catalog.updated
            ? '<span class="bdg ok">✅ aktiv</span>'
            : '<span class="bdg">⏳ noch nicht geladen</span>';
    const mgCount = catalog.sources?.marktguru;
    const mg = `<div class="section">
        <h4>🏷️ marktguru (inoffiziell) ${mgStatus}</h4>
        <div class="notice warn">⚠️ ${esc(MG_WARNING)}</div>
        <div class="meta">Optionale Ergänzung für Ketten ohne eigene Quelle (Lidl, REWE, Netto, Penny, Kaufland, Rossmann, dm …): etwa 2–3× pro Woche alle Angebote deiner Läden; aus den Prospekten werden auch Normalpreise je Laden gelernt.</div>
        ${online && (meta.last_update || catalog.updated) ? `<div>Zuletzt ${esc(timeText(catalog.updated || meta.last_update))}: <b>${esc(mgCount ?? meta.count ?? 0)}</b> Angebote${meta.learned ? ` · ${esc(meta.learned)} Normalpreise gelernt` : ""}</div>` : ""}
        ${online && ["error", "blocked"].includes(meta.status) && meta.errors?.length ? `<div class="notice err">${esc(meta.errors[0])}</div>` : ""}
        ${online ? `<div class="badges">${targets || '<span class="hint">Keine Postleitzahl – trage bei deinen Läden eine PLZ ein.</span>'}</div>` : ""}
        ${online ? `<div>${this._refreshButton("offers")}</div>` : enable("")}
      </div>`;
    const reweChip = chips[rewe.status || "off"] || "";
    const canRefresh = rewe.enabled && rewe.market_id && !rewe.blocked_until;
    const rw = `<div class="section">
        <h4>🛒 REWE-Onlinepreise <span class="bdg warn">experimentell</span> ${reweChip}</h4>
        <div class="meta">Normalpreise aus dem REWE-Onlineshop für deinen REWE-Markt (wöchentlich). REWE hat keine öffentliche Angebotsliste – REWE-Angebote gibt es nur über marktguru oder selbst eingetragen.</div>
        ${rewe.message ? `<div>${esc(rewe.message)}</div>` : ""}
        ${rewe.enabled ? `<div class="meta">${[rewe.prices ? `${rewe.prices} REWE-Preise gespeichert` : "", rewe.last_success ? `zuletzt erfolgreich ${timeText(rewe.last_success)}` : "", rewe.blocked_until ? `Pause bis ${timeText(rewe.blocked_until)}` : ""].filter(Boolean).map(esc).join(" · ")}</div>` : ""}
        ${canRefresh || this._refreshing.has("rewe") ? `<div>${this._refreshButton("rewe")} <span class="hint">dauert ein paar Minuten</span></div>` : rewe.enabled ? (rewe.blocked_until ? "" : `<div class="hint">Trage bei deinem REWE-Laden oben die Markt-ID ein (🔎 Markt suchen).</div>`) : enable("Dabei werden Suchbegriffe und deine Markt-ID an www.rewe.de gesendet.")}
      </div>`;
    // 1.4: ALDI SÜD prices (experimental) and the offers of the EDEKA market
    const aldi = eco.price_sources?.aldi || {};
    const hasAldi = (this._data.branches || []).some((b) => b.retailer === "aldi-sued");
    const aldiRefresh = aldi.enabled && hasAldi && !aldi.blocked_until;
    const al = `<div class="section">
        <h4>🛒 ALDI SÜD <span class="bdg warn">experimentell</span> ${chips[aldi.status || "off"] || ""}</h4>
        <div class="meta">Normalpreise von der ALDI-SÜD-Website (wöchentlich); Wochenangebote und gerade reduzierte Artikel werden Angebote.</div>
        ${aldi.message ? `<div>${esc(aldi.message)}</div>` : ""}
        ${aldi.enabled ? `<div class="meta">${[aldi.prices ? `${aldi.prices} ALDI-SÜD-Preise gespeichert` : "", catalog.sources?.aldi_weekly ? `${catalog.sources.aldi_weekly} Wochenangebote` : "", aldi.store_label || "", aldi.last_success ? `zuletzt erfolgreich ${timeText(aldi.last_success)}` : "", aldi.blocked_until ? `Pause bis ${timeText(aldi.blocked_until)}` : ""].filter(Boolean).map(esc).join(" · ")}</div>` : ""}
        ${aldiRefresh || this._refreshing.has("aldi") ? `<div>${this._refreshButton("aldi")} <span class="hint">dauert ein paar Minuten</span></div>` : aldi.enabled ? (hasAldi || aldi.blocked_until ? "" : `<div class="hint">Speichere oben eine ALDI-SÜD-Filiale.</div>`) : enable("Dabei werden Suchbegriffe und die Lage deiner ALDI-SÜD-Filiale an ALDI SÜD gesendet.")}
      </div>`;
    const edeka = eco.price_sources?.edeka || {};
    const hasEdeka = (this._data.branches || []).some((b) => b.retailer === "edeka");
    const edekaRefresh = edeka.enabled && edeka.market_id && !edeka.blocked_until;
    const ed = `<div class="section">
        <h4>🏷️ EDEKA-Angebote ${chips[edeka.status || "off"] || ""}</h4>
        <div class="meta">Die Prospekt-Angebote deines EDEKA-Markts direkt von edeka.de (täglich).</div>
        ${edeka.message ? `<div>${esc(edeka.message)}</div>` : ""}
        ${edeka.enabled ? `<div class="meta">${[catalog.sources?.edeka ? `${catalog.sources.edeka} Angebote` : "", edeka.prices ? `${edeka.prices} passend zu deinen Rezepten` : "", edeka.last_success ? `zuletzt erfolgreich ${timeText(edeka.last_success)}` : "", edeka.blocked_until ? `Pause bis ${timeText(edeka.blocked_until)}` : ""].filter(Boolean).map(esc).join(" · ")}</div>` : ""}
        ${edekaRefresh || this._refreshing.has("edeka") ? `<div>${this._refreshButton("edeka")}</div>` : edeka.enabled ? (edeka.blocked_until ? "" : `<div class="hint">${hasEdeka ? "Verknüpfe oben deinen EDEKA-Laden mit seinem Markt (🔎 EDEKA-Markt suchen)." : "Speichere oben deinen EDEKA-Markt."}</div>`) : enable("Dabei wird die Markt-ID deines EDEKA-Markts an www.edeka.de gesendet.")}
      </div>`;
    return `<div class="srcgrid">${rw}${al}${ed}${mg}</div>`;
  }

  /** Toast of an offers refresh (Angebote tab and Läden & Preise): during the cooldown the
   *  backend fetched nothing and only sends the last result with cooldown_until and a
   *  message – then that message, not a count of "loaded" offers. */
  _offersRefreshText(res) {
    if (res?.cooldown_until && res?.message) return `🏷️ ${res.message}`;
    if (res?.status !== "ok") return `Fehler: ${(res?.errors || []).join("; ") || res?.message || "unbekannt"}`;
    const all = res.catalog?.count;
    // without marktguru (only EDEKA / ALDI SÜD direct) the result has no count of its
    // own: the catalog's matched offers are the ones for the recipes
    const n = res.count ?? res.catalog?.matched;
    return `🏷️ ${n != null ? `${n} passende Angebote geladen` : "Angebote aktualisiert"}${res.learned ? `, ${res.learned} Normalpreise gelernt` : ""}${all != null ? ` · ${all} Angebote deiner Läden` : ""}`;
  }

  _refreshButton(source) {
    const busy = this._refreshing.has(source);
    const label = source === "offers" || source === "edeka" ? "🔄 Angebote aktualisieren" : "🔄 Preise aktualisieren";
    return `<button class="btn" data-action="refresh-source" data-source="${source}" ${busy ? "disabled" : ""}>${busy ? "⏳ Lädt …" : label}</button>`;
  }

  async _refreshSource(el, source) {
    if (this._refreshing.has(source)) return;
    // kept in a set so a data update while it runs (minutes for REWE) keeps the busy button
    this._refreshing.add(source);
    el.disabled = true;
    el.textContent = "⏳ Lädt …";
    try {
      const res = await this._service("refresh_prices", { source }, true);
      if (source === "rewe") this._toast(`🛒 REWE: ${res?.message || "fertig"}`);
      else if (source === "aldi") this._toast(`🛒 ALDI SÜD: ${res?.message || "fertig"}`);
      else if (source === "edeka") this._toast(`🏷️ EDEKA: ${res?.message || "fertig"}`);
      else this._toast(this._offersRefreshText(res));
    } finally {
      this._refreshing.delete(source);
      this._so.stale = true;
      if (this._tab === "stores") this._renderContent();
    }
  }

  /** A button that opens the settings view at a section (admins), else the way to the
   *  options of the integration. */
  _settingsLink(section, label) {
    if (this._isAdmin()) return `<button class="btn small" data-action="open-settings" data-sec="${esc(section)}">${esc(label)}</button>`;
    return `<i>${esc(label.replace(/^⚙️\s*/, ""))}</i> (Einstellungen – nur für Administratoren)`;
  }

  /* ------------------------------------------------------------ all offers of the saved stores (1.4) */
  /** Number shown in the mode switch: current offers of the shown stores (last answer),
   *  before the first answer the catalog's count. */
  _storeOfferCount() {
    const res = this._so.result;
    if (res?.stores?.length) {
      const picked = this._soPicked(res.stores);
      return res.stores.filter((st) => !picked.size || picked.has(st.branch_id)).reduce((n, st) => n + (st.count_current || 0), 0);
    }
    if (res) return res.total || 0;
    return this._data?.economy?.catalog?.count ?? 0;
  }

  /** The remembered store chips that still exist. */
  _soPicked(stores) {
    const known = new Set((stores || []).map((st) => st.branch_id));
    return new Set([...this._so.branches].filter((id) => known.has(id)));
  }

  _saveSoBranches() {
    this._setPref("offers_branches", JSON.stringify([...this._so.branches]));
  }

  _renderStoreOffers() {
    const so = this._so;
    if ((so.stale || !so.result) && !so.loading) this._fetchStoreOffers();
    const when = so.when;
    const kinds = OFFER_KINDS.map(([k, label]) => `<button class="${so.kind === k ? "on" : ""}" data-action="so-kind" data-kind="${k}" aria-pressed="${so.kind === k}">${label}</button>`).join("");
    const whens = [
      ["current", "Aktuell"],
      ["upcoming", "Ab nächster Woche"],
      ["all", "Alle"],
    ]
      .map(([k, label]) => `<button class="chip ${when === k ? "active" : ""}" data-action="so-when" data-when="${k}" aria-pressed="${when === k}">${label}</button>`)
      .join("");
    const busy = this._refreshing.has("offers-tab");
    return `
      <div class="sochips" role="group" aria-label="Läden">${this._soChipsHtml()}</div>
      <div class="sotools">
        ${whens}
        <span class="seg" role="group" aria-label="Art">${kinds}</span>
      </div>
      <div class="sotools">
        <input type="search" placeholder="🔍 In den Angeboten suchen, z. B. „Kaffee“" value="${esc(so.query)}" data-input="so-query" data-focuskey="so-query" aria-label="In den Angeboten suchen">
        <label class="switch">Sortieren <select data-change="so-sort" aria-label="Sortieren">${Object.entries(OFFER_SORTS).map(([k, v]) => `<option value="${k}" ${k === so.sort ? "selected" : ""}>${v}</option>`).join("")}</select></label>
        <button class="btn" data-action="refresh-offers" ${busy ? "disabled" : ""}>${busy ? "⏳ Lade Angebote …" : "🔄 Aktualisieren"}</button>
        <button class="btn" data-action="add-offer">＋ Angebot eintragen</button>
      </div>
      <div class="sobody">${this._soBodyHtml()}</div>`;
  }

  _soChipsHtml() {
    const res = this._so.result;
    const stores = res?.stores || [];
    if (!stores.length) return "";
    const picked = this._soPicked(stores);
    const when = this._so.when;
    const count = (st) => (when === "upcoming" ? st.count_upcoming : when === "all" ? st.count_current + st.count_upcoming : st.count_current) || 0;
    const total = stores.reduce((n, st) => n + count(st), 0);
    return `<button class="chip all ${picked.size ? "" : "active"}" data-action="so-store" data-branch="" aria-pressed="${!picked.size}">Alle meine Läden <span class="n">${total}</span></button>${stores
      .map((st) => {
        const on = picked.has(st.branch_id);
        const label = `${st.label}${st.main ? " ⭐" : ""}`;
        // "Aktuell" on a weekend: a store whose new week has not started yet shows when
        const later = when === "current" && !st.leaflet_only && !st.count_current && st.count_upcoming ? ` · 📅 ${st.count_upcoming}` : "";
        const title = `${this._soSourceText(st)}${later ? ` · ab nächster Woche ${st.count_upcoming} Angebot${st.count_upcoming === 1 ? "" : "e"}` : ""}`;
        return `<button class="chip ${on ? "active" : ""}" data-action="so-store" data-branch="${esc(st.branch_id)}" aria-pressed="${on}" title="${esc(title)}">${retailerDot(st.retailer, st.store).replace('class="rdot"', 'class="rdot xs"')}${esc(label)} <span class="n">${st.leaflet_only ? "📰" : `${count(st)}${later}`}</span></button>`;
      })
      .join("")}`;
  }

  _soSourceText(st) {
    const names = (st.sources || []).map((src) => OFFER_SOURCE_LABEL[src] || src);
    return names.length ? names.join(" + ") : "keine Angebotsquelle";
  }

  /** Why a store has no offers: which source (option) brings them. */
  _soHowTo(st) {
    const r = st.retailer;
    if (r === "edeka") return this._data.economy?.price_sources?.edeka?.enabled ? "EDEKA: bitte im Laden den EDEKA-Markt verknüpfen (🏪 Läden & Preise → „EDEKA-Markt suchen“)." : "EDEKA: „EDEKA-Angebote“ einschalten (kommt direkt von edeka.de).";
    if (r === "aldi-sued") return "ALDI SÜD: „ALDI-SÜD-Preise“ einschalten (Wochenangebote direkt von ALDI SÜD).";
    if (r === "rewe") return "REWE: keine öffentliche Angebotsliste – nur über marktguru (inoffiziell, eigenes Risiko).";
    return `${st.store}: über marktguru (inoffiziell, eigenes Risiko).`;
  }

  _soBodyHtml() {
    const so = this._so;
    const res = so.result;
    if (!res) return so.error ? `<div class="notice err">${esc(so.error)}</div>` : `<div class="hint">⏳ Lade Angebote …</div>`;
    const stores = res.stores || [];
    const picked = this._soPicked(stores);
    const shown = stores.filter((st) => !picked.size || picked.has(st.branch_id));
    const meta = res.meta || {};
    const today = this._today();
    // source line per store (EDEKA direkt / ALDI SÜD direkt / marktguru (inoffiziell))
    const status = { ok: "", pending: " · ⏳ noch nicht geladen", error: " · ⚠️ Fehler", blocked: " · ⛔ pausiert", off: " · ⏸ keine Quelle" };
    const lines = shown
      .map((st) => `<span>${retailerDot(st.retailer, st.store).replace('class="rdot"', 'class="rdot xs"')}${esc(st.label)}: ${esc(this._soSourceText(st))}${status[st.status] ?? ""}${st.error ? ` – ${esc(st.error)}` : ""}</span>`)
      .join("");
    const updated = meta.updated ? `<span>🕘 aktualisiert ${esc(timeText(meta.updated))}</span>` : "";
    let srcline = "";
    if (lines || updated) {
      // phones: folded (one line per store would push the offers down)
      srcline = this._narrowQuery?.matches
        ? `<details class="srcbox"><summary>ℹ️ Quellen der Angebote${meta.updated ? ` · ${esc(timeText(meta.updated))}` : ""}</summary><div class="srcline">${lines}</div></details>`
        : `<div class="srcline">${lines}${updated}</div>`;
    }
    const notes = [];
    if (so.error) notes.push(`<div class="notice err">${esc(so.error)}</div>`);
    if (meta.status === "blocked" && meta.errors?.length) notes.push(`<div class="notice err">⛔ ${esc(meta.errors[0])}</div>`);
    if (!stores.length && !(this._data.branches || []).length) {
      notes.push(`<div class="notice">🏪 Speichere zuerst deine Läden im Tab ${`<button class="btn small" data-action="go-tab" data-tab="stores" data-sec="mine">🏪 Läden & Preise</button>`} – dann siehst du hier alle Angebote dieser Läden.</div>`);
    }
    const off = shown.filter((st) => st.status === "off" && !st.leaflet_only);
    if (off.length) {
      notes.push(`<div class="notice warn"><b>Für ${off.length === 1 ? "diesen Laden" : "diese Läden"} ist keine Angebotsquelle eingeschaltet:</b><br>${[...new Set(off.map((st) => this._soHowTo(st)))].map(esc).join("<br>")}<br>${this._settingsLink("offers", "⚙️ Angebotsquellen einschalten")}</div>`);
    }
    const pending = shown.filter((st) => st.status === "pending");
    if (pending.length && !res.total) notes.push(`<div class="notice">⏳ Die Angebote von ${esc(pending.map((st) => st.label).join(", "))} sind noch nicht geladen – tippe auf „🔄 Aktualisieren“.</div>`);
    // leaflet-only stores (NORMA, EDEKA without market): page images + manual entry, for the
    // chosen time ("Aktuell" = the leaflet of this week)
    const when = so.when;
    const fits = (lf) => when === "all" || (when === "current") === !(lf.valid_from && lf.valid_from > today);
    const leafletStores = shown.filter((st) => st.leaflet_only && (st.leaflets || []).some(fits));
    const tiles = leafletStores.flatMap((st) => st.leaflets.filter(fits).map((lf, i) => this._leafletHtml(st, lf, today, i === 0))).join("");
    const onlyLeaflets = leafletStores.length && leafletStores.length === shown.length;
    // with other stores the tiles come after the offers; a note on top says where
    if (tiles && !onlyLeaflets) {
      notes.push(`<div class="lfnote hint">📰 ${leafletStores.map((st) => `${esc(st.label)}: nur Prospektbilder`).join(" · ")} <button class="btn small" data-action="so-store" data-branch="${esc(leafletStores[0].branch_id)}" data-only="1">📰 Prospekt ansehen</button></div>`);
    }
    const leaflets = tiles ? `<div class="leaflets">${tiles}</div>` : "";
    const cards = so.offers.map((o) => this._soCardHtml(o, today)).join("");
    let empty = "";
    if (!so.offers.length && !so.loading && !onlyLeaflets) {
      const filtered = so.query.trim() || so.kind !== "all" || so.when !== "all";
      const what = so.query.trim() ? `für „${esc(so.query.trim())}“` : "für diese Auswahl";
      // nothing now, but next week's leaflet is there (the store counts follow kind / query)
      const upcoming = so.when === "current" ? shown.reduce((n, st) => n + (st.count_upcoming || 0), 0) : 0;
      if (upcoming) {
        empty = `<div class="empty"><div class="big">📅</div>Gerade keine Angebote ${what} – ab nächster Woche ${upcoming === 1 ? "gibt es 1 Angebot" : `gibt es ${upcoming} Angebote`}.<div class="row" style="justify-content:center;margin:12px 0 0"><button class="btn primary" data-action="so-when" data-when="upcoming">📅 Ab nächster Woche zeigen</button></div></div>`;
      } else {
        empty = `<div class="empty"><div class="big">🏷️</div>${filtered && stores.some((st) => st.count_current || st.count_upcoming) ? `Keine Angebote ${what}.` : "Noch keine Angebote deiner Läden."}</div>`;
      }
    }
    const more = so.offers.length < (res.total || 0) ? `<div class="row" style="justify-content:center;margin-top:12px"><button class="btn" data-action="so-more" ${so.loading ? "disabled" : ""}>${so.loading ? "⏳ Lade …" : `Mehr laden (${so.offers.length} von ${res.total})`}</button></div>` : "";
    const count = res.total ? `<div class="meta" style="margin-bottom:8px">${res.total} Angebote${so.loading ? " · ⏳" : ""}</div>` : "";
    const list = `${count}${cards ? `<div class="soffers">${cards}</div>` : empty}${more}`;
    return onlyLeaflets ? `${srcline}${notes.join("")}${leaflets}${list}` : `${srcline}${notes.join("")}${list}${leaflets ? `<div style="margin-top:14px">${leaflets}</div>` : ""}`;
  }

  /** EDEKA with leaflet images only (marktguru): all single offers of the market come
   *  directly from edeka.de – the switch, or the market link that is still missing. */
  _edekaDirectHint(st) {
    if (st.retailer !== "edeka") return "";
    const b = this._branch(st.branch_id);
    if (!this._data.economy?.price_sources?.edeka?.enabled) {
      return `<div class="notice">💡 Alle Einzelangebote deines EDEKA-Markts kommen direkt von edeka.de, wenn du „EDEKA-Angebote“ einschaltest. ${this._settingsLink("offers", "⚙️ EDEKA-Angebote einschalten")}</div>`;
    }
    if (b && !b.edeka_market_id) {
      return `<div class="notice">💡 Alle Einzelangebote deines EDEKA-Markts kommen direkt von edeka.de, sobald der Laden mit seinem EDEKA-Markt verknüpft ist. <button class="btn small" data-action="so-edeka-search" data-id="${esc(b.id)}">🔎 EDEKA-Markt suchen</button></div>`;
    }
    return "";
  }

  _leafletHtml(st, lf, today, first = true) {
    const until = validText({ valid_from: lf.valid_from, valid_to: lf.valid_to }, today);
    const pages = (lf.pages || [])
      .slice(0, 4)
      .map((url, i) => (safeUrl(url) ? `<a href="${esc(httpLink(lf.url) || safeUrl(url))}" target="_blank" rel="noreferrer" aria-label="Prospektseite ${i + 1}"><img loading="lazy" src="${esc(safeUrl(url))}" alt=""></a>` : ""))
      .join("");
    const head = `📰 Prospekt ${esc(st.label)}${lf.page_count ? ` · ${lf.page_count} Seiten` : ""}${until ? ` · gültig ${esc(until)}` : ""}`;
    return `<div class="card leaflet">
        <div class="lfhead">${retailerDot(st.retailer, st.store).replace('class="rdot"', 'class="rdot sm"')}<span>${head}</span></div>
        ${pages ? `<div class="lfpages">${pages}</div>` : ""}
        <div class="hint">Für diesen Markt liefert marktguru nur Prospektbilder, keine einzelnen Angebote. Ein Angebot, das du nutzen willst, kannst du selbst eintragen.</div>
        ${first ? this._edekaDirectHint(st) : ""}
        <div class="lfacts">
          ${httpLink(lf.url) ? `<a class="btn small" href="${esc(httpLink(lf.url))}" target="_blank" rel="noreferrer">Prospekt öffnen ↗</a>` : ""}
          <button class="btn small" data-action="add-offer" data-store="${esc(st.label)}">＋ Angebot aus Prospekt eintragen</button>
        </div>
      </div>`;
  }

  _soCardHtml(o, today) {
    const img = safeUrl(o.image);
    const ref = o.old_price || o.regular_price;
    const pack = packText(o.pack_amount, o.pack_unit);
    const desc = [pack, o.description && o.description !== pack ? o.description : ""].filter(Boolean).join(" · ");
    const badges = [];
    if (o.app_price != null) badges.push(`<span class="bdg warn" title="Preis mit der App des Händlers">mit App ${eur(o.app_price)}</span>`);
    else if (o.loyalty && !/payback/i.test(o.loyalty_note || "")) badges.push(`<span class="bdg warn" title="${esc(o.loyalty_note || "nur mit App/Kundenkarte")}">mit App/Karte</span>`);
    if (/payback/i.test(`${o.loyalty_note || ""} ${o.highlight || ""}`)) badges.push('<span class="bdg">PAYBACK</span>');
    if (o.online_only) badges.push('<span class="bdg bad">nur online</span>');
    if (o.deposit) badges.push(`<span class="bdg">+${eur(o.deposit)} Pfand</span>`);
    const until = validText(o, today);
    if (until) badges.push(`<span class="bdg ${o.current ? "" : "ok"}">${esc(until)}</span>`);
    const unit = o.unit_price != null && o.base_unit && o.base_unit !== "Stück" ? unitPriceText(o.unit_price, o.base_unit) : "";
    const ids = o.branch_ids || [];
    const branch = ids.length === 1 ? this._branch(ids[0]) : null;
    const where = branch ? branch.label : ids.length > 1 ? `${o.store} (${ids.length} Läden)` : o.store;
    // one of the planning offers already (📌 would only add a second copy)
    const counts = (this._data.offers || []).some((x) => String(x.id) === String(o.id));
    return `<div class="card soffer ${o.current ? "" : "later"}">
        <div class="sotop">
          <div class="soimg">${img ? `<img loading="lazy" src="${esc(img)}" alt="">` : "🏷️"}</div>
          <div class="sot">${o.brand ? `<div class="brand">${esc(o.brand)}</div>` : ""}<div class="pname">${esc(o.product || o.title)}</div>${desc ? `<div class="pack">${esc(desc)}</div>` : ""}</div>
        </div>
        <div class="soprice"><span class="pr">${eur(o.price)}</span>${ref && ref > o.price ? `<span class="old" title="${o.old_price ? "Streichpreis" : "Normalpreis"}">${eur(ref)}</span>` : ""}${o.discount ? `<span class="disc">−${o.discount}%</span>` : ""}${unit ? `<span class="up">${esc(unit)}</span>` : ""}</div>
        <div class="someta"><span class="sostore">${retailerDot(o.retailer, o.store).replace('class="rdot"', 'class="rdot xs"')}${esc(where)}</span>${badges.join("")}</div>
        <div class="acts">
          <button class="btn small" data-action="so-add" data-id="${esc(o.id)}">➕ Auf die Einkaufsliste</button>
          ${counts ? `<button class="btn small" data-action="so-pin" data-id="${esc(o.id)}" title="Passt zu deinen Rezepten oder der Einkaufsliste – zählt schon für Planung, Budget und Einkaufsliste">✓ Zählt schon</button>` : `<button class="btn small" data-action="so-pin" data-id="${esc(o.id)}" title="Als eigenes Angebot merken – zählt dann für Planung, Budget und Einkaufsliste">📌 Merken</button>`}
        </div>
      </div>`;
  }

  async _fetchStoreOffers(append = false) {
    const so = this._so;
    const seq = ++so.seq;
    so.loading = true;
    so.stale = false;
    so.error = null;
    if (!append) this._renderStoreOfferParts();
    const ids = [...so.branches];
    const msg = { type: `${DOMAIN}/store_offers`, when: so.when, kind: so.kind, sort: so.sort, offset: append ? so.offers.length : 0, limit: OFFER_PAGE };
    if (ids.length) msg.branch_ids = ids;
    if (so.query.trim()) msg.query = so.query.trim();
    try {
      const res = await this._hass.callWS(msg);
      if (seq !== so.seq) return;
      // a remembered store that was removed: forget it and ask again
      const known = new Set((res.stores || []).map((st) => st.branch_id));
      const gone = ids.filter((id) => !known.has(id));
      if (gone.length && (res.stores || []).length) {
        gone.forEach((id) => so.branches.delete(id));
        this._saveSoBranches();
        so.loading = false;
        return this._fetchStoreOffers();
      }
      so.result = res;
      so.offers = append ? [...so.offers, ...(res.offers || []).filter((o) => !so.offers.some((x) => x.id === o.id))] : res.offers || [];
    } catch (err) {
      if (seq !== so.seq) return;
      so.error = errText(err);
    }
    so.loading = false;
    this._renderStoreOfferParts();
  }

  /** Update chips, results and the count of the mode switch (the search field keeps its
   *  focus and caret). */
  _renderStoreOfferParts() {
    if (this._tab !== "offers" || this._offersMode !== "stores") return;
    const chips = this._content.querySelector(".sochips");
    if (chips) chips.innerHTML = this._soChipsHtml();
    const body = this._content.querySelector(".sobody");
    if (body) body.innerHTML = this._soBodyHtml();
    const count = this._content.querySelector("[data-socount]");
    if (count) count.textContent = this._storeOfferCount();
  }

  _soOffer(id) {
    return this._so.offers.find((o) => String(o.id) === String(id));
  }

  async _soAdd(el, id) {
    const o = this._soOffer(id);
    if (!o) return;
    const data = { item: o.product || o.title, offer_id: o.id };
    const picked = this._soPicked(this._so.result?.stores);
    const ids = o.branch_ids || [];
    const branch = ids.find((b) => picked.has(b)) || ids[0];
    if (branch) data.store = branch;
    el.disabled = true;
    try {
      const res = await this._service("add_shopping_item", data, true);
      const item = res?.item || {};
      const cost = item.price;
      const price = cost != null ? ` für ${cost === o.price ? "" : "≈ "}${eur(cost)}` : "";
      const label = item.store_label || this._branch(branch)?.label || o.store;
      this._toast(`🛒 ${item.summary || data.item}${price}${label ? ` bei ${label}` : ""} auf die Einkaufsliste gesetzt`);
    } finally {
      el.disabled = false;
    }
  }

  async _soPin(el, id) {
    const o = this._soOffer(id);
    if (!o) return;
    const ids = o.branch_ids || [];
    const branch = ids.length === 1 ? this._branch(ids[0]) : null;
    const store = branch?.label || o.store;
    // the catalog offer itself is one of the planning offers (same id): a manual copy would
    // count it twice (offers list, Jarvis)
    if ((this._data.offers || []).some((x) => String(x.id) === String(o.id))) return this._toast("📌 Dieses Angebot zählt schon für Planung, Budget und Einkaufsliste.");
    const title = o.brand && !String(o.title || "").toLowerCase().includes(o.brand.toLowerCase()) ? `${o.brand} ${o.product || o.title}` : o.title || o.product;
    const known = (this._data.offers || []).some((x) => x.source === "manual" && fold(x.title) === fold(title) && x.price === o.price && (x.valid_to || "") === (o.valid_to || ""));
    if (known) return this._toast("📌 Dieses Angebot hast du schon gemerkt.");
    const data = { product: title, store, price: o.price };
    const ref = o.old_price || o.regular_price;
    if (ref && ref > o.price) data.old_price = ref;
    const pack = packText(o.pack_amount, o.pack_unit);
    if (pack) data.pack = pack;
    if (o.valid_from) data.valid_from = o.valid_from;
    if (o.valid_to) data.valid_to = o.valid_to;
    el.disabled = true;
    try {
      await this._service("add_offer", data, true);
      this._toast(`📌 ${title} gemerkt – zählt jetzt für Planung, Budget und Einkaufsliste`);
    } finally {
      el.disabled = false;
    }
  }

  /* ------------------------------------------------------------ settings view (⚙️, 1.4) */
  async _openSettings(section = null) {
    if (!this._isAdmin()) return this._toast("⚙️ Die Einstellungen können nur Administratoren ändern.");
    if (this._settings) return this._settingsGo(section);
    this._settings = { loading: true, data: null, values: null, original: null, errors: {}, saving: false, phase: "edit", message: null, section: section || "general", jump: section };
    this._renderSettings();
    try {
      const data = await this._hass.callWS({ type: `${DOMAIN}/get_settings` });
      if (!this._settings) return;
      Object.assign(this._settings, { loading: false, data, values: JSON.parse(JSON.stringify(data.values)), original: JSON.parse(JSON.stringify(data.values)) });
    } catch (err) {
      if (!this._settings) return;
      Object.assign(this._settings, { loading: false, message: errText(err) });
    }
    this._renderSettings();
    if (this._settings?.jump) this._settingsGo(this._settings.jump, false);
    this._settingsRoot.querySelector("[data-sclose]")?.focus();
  }

  _settingsField(key) {
    return this._settings?.data?.fields?.[key] || {};
  }

  /** Values that differ from the stored ones (numbers compared as numbers). */
  _settingsChanges() {
    const st = this._settings;
    if (!st?.values) return {};
    const changes = {};
    for (const [key, value] of Object.entries(st.values)) {
      const type = this._settingsField(key).type;
      const before = st.original[key];
      const same = type === "int" || type === "float" ? parseNum(value) === parseNum(before) || (String(value).trim() === "" && before == null) : JSON.stringify(value ?? null) === JSON.stringify(before ?? null);
      if (!same) changes[key] = value;
    }
    return changes;
  }

  _renderSettings() {
    const st = this._settings;
    const root = this._settingsRoot;
    if (!st) {
      root.innerHTML = "";
      return;
    }
    const scroll = root.querySelector(".sbody")?.scrollTop;
    const errCount = Object.keys(st.errors).length;
    const changes = Object.keys(this._settingsChanges()).length;
    const bySection = {};
    for (const key of Object.keys(st.errors)) {
      const sec = this._settingsField(key).section;
      bySection[sec] = (bySection[sec] || 0) + 1;
    }
    const nav = SETTINGS_SECTIONS.map(([id, label]) => `<button class="${st.section === id ? "on" : ""}" data-snav="${id}">${label}${bySection[id] ? `<span class="nerr">${bySection[id]}</span>` : ""}</button>`).join("");
    let body;
    if (st.loading) body = `<div class="loading">Lade Einstellungen …</div>`;
    else if (!st.data) body = `<div class="notice err">${esc(st.message || "Die Einstellungen konnten nicht geladen werden.")}</div>`;
    else body = SETTINGS_SECTIONS.map(([id, label]) => this._settingsSectionHtml(id, label)).join("");
    let banner = "";
    if (st.phase === "reloading") banner = `<div class="card sbanner notice">⏳ <span><b>Gespeichert – Essensplaner lädt neu …</b><br><span class="hint">Die Einstellungen werden übernommen; das dauert ein paar Sekunden.</span></span></div>`;
    else if (st.phase === "failed") banner = `<div class="card sbanner notice err">⚠️ <span><b>Gespeichert, aber der Essensplaner antwortet noch nicht.</b><br>${esc(st.message || "")} <button class="btn small" data-sreload>Seite neu laden</button></span></div>`;
    const state = st.saving
      ? "⏳ Speichere …"
      : st.phase === "reloading"
        ? "Gespeichert – Essensplaner lädt neu …"
        : errCount
          ? `${errCount} ${errCount === 1 ? "Feld" : "Felder"} bitte prüfen`
          : changes
            ? `${changes} ungespeicherte Änderung${changes === 1 ? "" : "en"}`
            : "Keine Änderungen";
    const busy = st.saving || st.phase === "reloading";
    root.innerHTML = `
      <div class="sview" role="dialog" aria-modal="true" aria-label="Einstellungen">
        <div class="spage">
          <div class="shead"><h2>⚙️ Einstellungen</h2><button class="icon" data-sclose title="Schließen" aria-label="Schließen">✕</button></div>
          <div class="smain">
            <nav class="snav" aria-label="Bereiche">${nav}</nav>
            <div class="sbody">${banner}${body}</div>
          </div>
          <div class="sfoot">
            <span class="sstate ${errCount ? "err" : ""}" aria-live="polite">${esc(state)}</span>
            <button class="btn" data-sclose ${busy ? "disabled" : ""}>${changes ? "Abbrechen" : "Schließen"}</button>
            <button class="btn primary" data-ssave ${busy || !st.data || !changes ? "disabled" : ""}>💾 Speichern</button>
          </div>
        </div>
      </div>`;
    const sbody = root.querySelector(".sbody");
    if (scroll != null) sbody.scrollTop = scroll;
    const view = root.querySelector(".sview");
    view.addEventListener("click", (ev) => {
      if (ev.target === view || ev.target.closest("[data-sclose]")) return this._closeSettings();
      if (ev.target.closest("[data-ssave]")) return this._saveSettings();
      if (ev.target.closest("[data-sreload]")) return location.reload();
      if (ev.target.closest("[data-saitest]")) return this._settingsAiTest();
      const jump = ev.target.closest("[data-sjump]");
      if (jump) return this._settingsGo(jump.dataset.sjump);
      const navBtn = ev.target.closest("[data-snav]");
      if (navBtn) return this._settingsGo(navBtn.dataset.snav);
      const go = ev.target.closest("[data-sgo]");
      if (go) {
        this._closeSettings(true);
        this._goTab(go.dataset.sgo, go.dataset.sec);
      }
    });
    view.addEventListener("input", (ev) => this._onSettingsInput(ev));
    view.addEventListener("change", (ev) => this._onSettingsInput(ev));
    sbody.addEventListener("scroll", () => this._settingsSpy(), { passive: true });
  }

  /** Highlight the section shown at the top of the scroll area. */
  _settingsSpy() {
    const st = this._settings;
    const body = this._settingsRoot.querySelector(".sbody");
    if (!st || !body) return;
    if (this._settingsJumping) {
      // a jump from the navigation is still scrolling (long jumps take longer than the
      // first timer): the clicked section stays chosen until the scrolling stops
      clearTimeout(this._settingsJumpTimer);
      this._settingsJumpTimer = setTimeout(() => (this._settingsJumping = false), 150);
      return;
    }
    let current = SETTINGS_SECTIONS[0][0];
    for (const [id] of SETTINGS_SECTIONS) {
      const sec = body.querySelector(`[data-ssec="${id}"]`);
      if (sec && sec.offsetTop - body.offsetTop <= body.scrollTop + 40) current = id;
    }
    if (body.scrollTop + body.clientHeight >= body.scrollHeight - 4) {
      // scrolled to the end: the last sections never reach the top – a section picked in
      // the navigation stays chosen while it is in view, else the last one is
      const order = SETTINGS_SECTIONS.map(([id]) => id);
      const picked = this._settingsPicked;
      const sec = picked && body.querySelector(`[data-ssec="${picked}"]`);
      const inView = sec && sec.offsetTop - body.offsetTop < body.scrollTop + body.clientHeight;
      current = inView && order.indexOf(picked) >= order.indexOf(current) ? picked : order[order.length - 1];
    } else this._settingsPicked = null;
    if (current !== st.section) {
      st.section = current;
      this._settingsRoot.querySelectorAll("[data-snav]").forEach((b) => b.classList.toggle("on", b.dataset.snav === current));
    }
  }

  _settingsGo(section, smooth = true) {
    const st = this._settings;
    if (!st || !section) return;
    st.section = section;
    this._settingsPicked = section;
    this._settingsRoot.querySelectorAll("[data-snav]").forEach((b) => b.classList.toggle("on", b.dataset.snav === section));
    const body = this._settingsRoot.querySelector(".sbody");
    const sec = body?.querySelector(`[data-ssec="${section}"]`);
    if (!sec) return;
    this._settingsJumping = true;
    body.scrollTo({ top: sec.offsetTop - body.offsetTop - 4, behavior: smooth ? "smooth" : "auto" });
    clearTimeout(this._settingsJumpTimer);
    this._settingsJumpTimer = setTimeout(() => (this._settingsJumping = false), smooth ? 600 : 50);
  }

  _settingsSectionHtml(id, label) {
    const st = this._settings;
    const d = st.data;
    const f = (key, extra) => this._settingsFieldHtml(key, extra);
    let inner = "";
    if (id === "general") {
      const times = ["fruehstueck", "mittagessen", "snack", "abendessen"].map((m) => f(`time_${m}`)).join("");
      inner = `${f("default_servings")}${f("default_meal")}${f("enabled_meals")}
        <div class="sfield"><div class="flabel">Uhrzeiten</div><div class="fhelp">Für den Kalender und „Nächste Mahlzeit“.</div><div class="sgrid">${times}</div></div>
        ${f("pantry_staples")}${f("excluded")}${f("auto_mark_cooked")}${f("shopping_sync_entity")}${f("register_intents")}${f("show_panel")}`;
    } else if (id === "planning") {
      inner = `${f("weekly_budget")}${f("plan_strategy")}${f("season_aware")}${f("occasions_in_budget")}${f("drinks_alcohol")}`;
    } else if (id === "offers") {
      inner = `<div class="hint">Angebote und Preise kommen direkt von den Ketten, wo es eine öffentliche Quelle gibt (EDEKA, ALDI SÜD, REWE-Preise). marktguru ist eine optionale Ergänzung auf eigenes Risiko. Alle Quellen sind aus, bis du sie einschaltest.</div>
        ${f("offers_source")}${f("all_leaflets")}${f("zip_code")}${f("offer_stores")}${f("offers_watchlist")}${f("edeka_offers")}${f("aldi_online_prices")}${f("rewe_online_prices")}
        <div class="hint">Filialen verknüpfen (EDEKA-Markt, ALDI-SÜD-Filiale, REWE-Markt-ID): <button class="btn small" data-sgo="stores" data-sec="mine">🏪 Läden & Preise</button></div>`;
    } else if (id === "stores") {
      inner = `${f("store_split_mode")}
        <div class="sfield"><div class="flabel">Schwellen</div><div class="fhelp">Wann ein Artikel in einen anderen Laden als den Hauptladen kommt (nur echte Ladenpreise, keine Richtwerte; unter 0,20 € Ersparnis wird nie verschoben).</div><div class="sgrid">${f("store_split_min_saving")}${f("store_split_min_percent")}${f("store_split_offer_min")}${f("store_split_trip_min")}</div></div>
        ${f("branch_zones")}${f("branch_radius_km")}${f("branch_route")}${f("branch_route_radius_m")}
        <div class="hint">${d.branches ? `${d.branches} Läden gespeichert${d.main_branch ? ` · Hauptladen: ${esc(d.main_branch)}` : ""}` : "Noch keine Läden gespeichert"} – <button class="btn small" data-sgo="stores" data-sec="mine">🏪 Läden & Preise</button></div>`;
    } else if (id === "receipts") {
      inner = `${f("receipt_ai_task_entity")}<div class="hint">Kassenzettel erfasst du im Tab „🏪 Läden & Preise“ oder über „🧾 Kassenzettel“ in der Einkaufsliste.</div>`;
    } else if (id === "ai") {
      inner = `<div class="hint">Optional – der Essensplaner funktioniert komplett ohne KI. Die KI läuft über Home Assistant, hier werden keine Schlüssel gespeichert: richte dort z. B. <b>Anthropic</b> (Claude), <b>OpenAI</b>, <b>Google Gemini</b> oder <b>Ollama</b> (lokal oder mit Cloud-Modellen) ein – sie bringen eine KI-Aufgabe und/oder einen Gesprächsagenten mit.</div>
        ${f("ai_entity")}
        <div class="sfield"><div class="aitestrow"><button class="btn" data-saitest ${st.aiTest?.running ? "disabled" : ""}>🔌 Verbindung testen</button><div class="aitest" data-aitest aria-live="polite">${this._aiTestHtml()}</div></div></div>
        ${f("ai_features")}
        <div class="hint">📷 Kassenzettel-Fotos brauchen eine <b>KI-Aufgabe</b>, die Bilder lesen kann – ein Gesprächsagent bekommt keine Bilder. Eine eigene KI-Aufgabe dafür wählst du unter <button class="btn small" data-sjump="receipts">🧾 Kassenzettel</button></div>
        <div class="hint">🔒 Die KI bekommt nur Rezeptnamen, Tags und Zutaten, Kettennamen, Angebotspreise, Monat und Gästezahl – keine Adressen, Postleitzahlen, Notizen oder Kassenzettel-Texte. Antworten werden gegen deine Rezepte geprüft und nie ungefragt übernommen; während einer Anfrage sind die Essensplaner-Sprachbefehle für die KI gesperrt (keine Schleifen).</div>`;
    }
    return `<section class="card ssec" data-ssec="${id}" aria-label="${esc(label)}"><h3>${label}</h3>${inner}</section>`;
  }

  _settingsFieldHtml(key) {
    const st = this._settings;
    const d = st.data;
    const field = d.fields?.[key];
    if (!field) return "";
    const [label, help, unit] = SETTING_INFO[key] || [key, ""];
    const value = st.values[key];
    const error = st.errors[key];
    const id = `s-${key}`;
    const warnings = (d.warnings || []).filter((w) => w.key === key && key !== "offers_source").map((w) => `<div class="notice warn">${esc(w.message)}</div>`).join("");
    const errHtml = error ? `<div class="ferr" id="${id}-err">⚠️ ${esc(error)}</div>` : "";
    const aria = `data-skey="${esc(key)}" id="${id}" ${error ? `aria-invalid="true" aria-describedby="${id}-err"` : ""}`;
    const range = field.min != null && field.max != null ? `${num(field.min)}–${num(field.max)}${unit ? ` ${unit}` : ""}` : "";
    const wrap = (control, opts = {}) => `<div class="sfield ${error ? "invalid" : ""}" data-field="${esc(key)}">${opts.noLabel ? "" : `<label class="flabel" for="${id}">${esc(label)}${opts.badge || ""}</label>`}${control}${help && !opts.noHelp ? `<div class="fhelp">${esc(help)}${range && opts.range !== false ? ` (${esc(range)})` : ""}</div>` : range ? `<div class="fhelp">${esc(range)}</div>` : ""}${opts.after || ""}${warnings}${errHtml}</div>`;
    const choice = (list) => list || [];
    switch (field.type) {
      case "int":
      case "float":
        return wrap(`<div class="fin"><input ${aria} inputmode="decimal" autocomplete="off" value="${esc(num(value))}">${unit ? `<span class="unit">${esc(unit)}</span>` : ""}</div>`);
      case "bool":
        return `<div class="sfield ${error ? "invalid" : ""}" data-field="${esc(key)}"><label class="switch"><input type="checkbox" ${aria} ${value ? "checked" : ""}> ${esc(label)}${["rewe_online_prices", "aldi_online_prices"].includes(key) ? ' <span class="bdg warn">experimentell</span>' : ""}</label>${help ? `<div class="fhelp">${esc(help)}</div>` : ""}${warnings}${errHtml}</div>`;
      case "time":
        return `<div class="sfield ${error ? "invalid" : ""}" data-field="${esc(key)}"><label class="flabel" for="${id}">${esc(label)}</label><input type="time" ${aria} value="${esc(value || "")}">${errHtml}</div>`;
      case "text":
      case "textarea": {
        if (key === "zip_code") {
          const postcodes = d.branch_postcodes || [];
          const extra = postcodes.length ? `<div class="fhelp">Postleitzahlen deiner Läden: ${esc(postcodes.join(", "))}</div>` : "";
          return wrap(`<input ${aria} class="" inputmode="numeric" maxlength="5" autocomplete="postal-code" placeholder="z. B. 80331" value="${esc(value || "")}" style="width:140px">`, { after: extra });
        }
        if (field.type === "textarea") return wrap(`<textarea ${aria} rows="2">${esc(value || "")}</textarea>`, { range: false });
        return wrap(`<input ${aria} class="wide" autocomplete="off" value="${esc(value || "")}">`, { range: false });
      }
      case "select": {
        if (key === "offers_source") {
          const on = value === "marktguru";
          return `<div class="sfield ${error ? "invalid" : ""}" data-field="${esc(key)}"><label class="switch"><input type="checkbox" ${aria} ${on ? "checked" : ""}> ${esc(label)}</label><div class="notice warn">⚠️ ${esc(MG_WARNING)}</div><div class="fhelp">${esc(help)}</div>${errHtml}</div>`;
        }
        if (key === "plan_strategy") {
          const opts = choice(d.choices?.[SELECT_CHOICES[key]])
            .map((c) => {
              const [title, desc] = STRATEGY_LABELS[c.value] || [c.label, ""];
              return `<label><input type="radio" name="s-strategy" data-skey="${esc(key)}" value="${esc(c.value)}" ${c.value === value ? "checked" : ""}><span><b>${esc(title)}</b>${desc ? `<br><span class="meta">${esc(desc)}</span>` : ""}</span></label>`;
            })
            .join("");
          return wrap(`<div class="choice" role="radiogroup" aria-label="${esc(label)}">${opts}</div>`, { noLabel: false });
        }
        if (key === "store_split_mode") {
          const desc = { off: "Eine Liste wie bisher, ohne Läden.", main_only: "Alles kommt in den Hauptladen; die anderen Läden dienen zum Preisvergleich.", main_exceptions: "Alles in den Hauptladen, nur Angebote und deutlich günstigere Artikel in andere Läden; Drogerieartikel in deine Drogerie." };
          const opts = choice(d.choices?.[SELECT_CHOICES[key]])
            .map((c) => `<label><input type="radio" name="s-split" data-skey="${esc(key)}" value="${esc(c.value)}" ${c.value === value ? "checked" : ""}><span><b>${esc(c.label)}</b><br><span class="meta">${esc(desc[c.value] || "")}</span></span></label>`)
            .join("");
          return wrap(`<div class="choice" role="radiogroup" aria-label="${esc(label)}">${opts}</div>`);
        }
        const list = d.choices?.[SELECT_CHOICES[key]];
        return wrap(`<select ${aria}>${choice(list).map((c) => `<option value="${esc(c.value)}" ${c.value === value ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select>`);
      }
      case "multi": {
        const selected = new Set(value || []);
        const chip = (c) => `<label class="chip pick2"><input type="checkbox" data-skey="${esc(key)}" value="${esc(c.value)}" ${selected.has(c.value) ? "checked" : ""}>${c.kind ? retailerDot(c.value, c.label).replace('class="rdot"', 'class="rdot xs"') : ""}${esc(c.label)}</label>`;
        const all = choice(d.choices?.[MULTI_CHOICES[key]]);
        if (key === "offer_stores") {
          const food = all.filter((c) => c.kind !== "drugstore");
          const drug = all.filter((c) => c.kind === "drugstore");
          return wrap(`<div class="meta">Supermärkte</div><div class="chips">${food.map(chip).join("")}</div><div class="meta">Drogerien</div><div class="chips">${drug.map(chip).join("")}</div>`);
        }
        return wrap(`<div class="chips" role="group" aria-label="${esc(label)}">${all.map(chip).join("")}</div>`);
      }
      case "entity": {
        const spec = ENTITY_CHOICES[key] || { list: "", none: "– keine –", empty: "" };
        const list = choice(d.choices?.[spec.list]);
        const option = (c) => `<option value="${esc(c.value)}" ${c.value === value ? "selected" : ""}>${esc(c.label)}${c.label !== c.value ? ` (${esc(c.value)})` : ""}${c.missing ? " – nicht gefunden" : c.available === false ? " – nicht erreichbar" : ""}</option>`;
        let opts = list.map(option).join("");
        if (spec.groups) {
          // AI Tasks and conversation agents in their own groups (a missing value last)
          const kinds = Object.keys(spec.groups);
          opts = kinds.map((k) => list.filter((c) => c.kind === k && !c.missing)).map((items, i) => (items.length ? `<optgroup label="${esc(spec.groups[kinds[i]])}">${items.map(option).join("")}</optgroup>` : "")).join("") + list.filter((c) => c.missing || !kinds.includes(c.kind)).map(option).join("");
        }
        const empty = !list.length && spec.empty ? `<div class="fhelp">${esc(spec.empty)}</div>` : "";
        return wrap(`<select ${aria} class="wide"><option value="">${esc(this._settingsNone(key, spec))}</option>${opts}</select>`, { after: empty });
      }
      case "entities": {
        const selected = new Set(value || []);
        const zones = choice(d.choices?.zones);
        const chips = zones.map((c) => `<label class="chip pick2"><input type="checkbox" data-skey="${esc(key)}" value="${esc(c.value)}" ${selected.has(c.value) ? "checked" : ""}>${c.value === "zone.home" ? "🏠" : /arbeit|work/i.test(c.value + c.label) ? "💼" : "📍"} ${esc(c.label)}${c.missing ? " (nicht gefunden)" : ""}</label>`).join("");
        return wrap(zones.length ? `<div class="chips" role="group" aria-label="${esc(label)}">${chips}</div>` : `<div class="hint">Keine Zonen gefunden – lege in Home Assistant Zonen an (Einstellungen → Bereiche &amp; Zonen).</div>`);
      }
      default:
        return "";
    }
  }

  /** The "none" entry of an entity picker; the receipt picker names the AI it falls back to. */
  _settingsNone(key, spec) {
    const st = this._settings;
    if (key === "receipt_ai_task_entity") {
      const general = st?.values?.ai_entity;
      if (general && String(general).startsWith("ai_task.")) {
        const c = (st.data?.choices?.ai_entities || []).find((x) => x.value === general);
        return `– wie 🤖 KI: ${c?.label || general} –`;
      }
    }
    return spec.none;
  }

  /** The result of "Verbindung testen" (running, ok with seconds, or the German error). */
  _aiTestHtml() {
    const t = this._settings?.aiTest;
    if (!t) return "";
    if (t.running) return `<span class="meta">⏳ Teste … (eine lokale KI braucht bis zu einer Minute)</span>`;
    if (t.ok) {
      const c = (this._settings.data?.choices?.ai_entities || []).find((x) => x.value === t.entity);
      return `<span class="bdg ok">✅ Verbunden</span> <span class="meta">${esc(c?.label || t.entity || "")} (${esc(AI_KIND_LABELS[t.mode] || t.mode || "")}) hat in ${esc(num(t.seconds ?? 0))} s mit JSON geantwortet.</span>`;
    }
    return `<div class="notice ${t.code === "ai_busy" ? "warn" : "err"}">⚠️ ${esc(t.error || "Die KI hat nicht geantwortet.")}</div>`;
  }

  _settingsAiTestRender() {
    const root = this._settingsRoot;
    const box = root?.querySelector("[data-aitest]");
    if (box) box.innerHTML = this._aiTestHtml();
    const btn = root?.querySelector("[data-saitest]");
    if (btn) btn.disabled = Boolean(this._settings?.aiTest?.running);
  }

  /** "Verbindung testen": a tiny request to the AI chosen in the form (also before saving). */
  async _settingsAiTest() {
    const st = this._settings;
    if (!st?.data || st.aiTest?.running) return;
    const entity = st.values?.ai_entity || null;
    st.aiTest = { running: true, entity };
    this._settingsAiTestRender();
    let res;
    try {
      res = await this._hass.callWS({ type: `${DOMAIN}/ai_test`, ...(entity ? { entity_id: entity } : {}) });
    } catch (err) {
      res = { ok: false, error: errText(err) };
    }
    if (this._settings !== st) return;
    st.aiTest = { ...res, entity: res?.entity || entity, running: false };
    this._settingsAiTestRender();
  }

  _onSettingsInput(ev) {
    const st = this._settings;
    const t = ev.target;
    const key = t.dataset?.skey;
    if (!st?.values || !key) return;
    const field = this._settingsField(key);
    // text inputs: "input" while typing; checkboxes / selects / radios: "change"
    if (ev.type === "input" && ["checkbox", "radio"].includes(t.type)) return;
    if (ev.type === "change" && !["checkbox", "radio", "select-one", "time"].includes(t.type) && t.tagName !== "SELECT") return;
    let value;
    if (field.type === "multi" || field.type === "entities") {
      const boxes = [...this._settingsRoot.querySelectorAll(`input[type=checkbox][data-skey="${CSS.escape(key)}"]`)];
      value = boxes.filter((b) => b.checked).map((b) => b.value);
    } else if (key === "offers_source") value = t.checked ? "marktguru" : "off";
    else if (field.type === "bool") value = t.checked;
    else if (field.type === "entity") value = t.value || null;
    else value = t.value;
    st.values[key] = value;
    if (key === "ai_entity") {
      // another AI: the last test result is not about it; the receipt picker's "none"
      // names the AI it falls back to
      if (!st.aiTest?.running) st.aiTest = null;
      this._settingsAiTestRender();
      const none = this._settingsRoot.querySelector('select[data-skey="receipt_ai_task_entity"] option[value=""]');
      if (none) none.textContent = this._settingsNone("receipt_ai_task_entity", ENTITY_CHOICES.receipt_ai_task_entity);
    }
    const hadError = key in st.errors || (key === "offers_source" && "zip_code" in st.errors);
    delete st.errors[key];
    if (key === "offers_source") delete st.errors.zip_code;
    if (key === "enabled_meals" && !value.length) st.errors[key] = "Bitte mindestens eine Mahlzeit auswählen.";
    if (hadError || key === "enabled_meals") {
      const sec = this._settingsRoot.querySelector(`.sfield[data-field="${CSS.escape(key)}"]`);
      sec?.classList.toggle("invalid", key in st.errors);
      sec?.querySelector(".ferr")?.remove();
      if (key in st.errors && sec) sec.insertAdjacentHTML("beforeend", `<div class="ferr">⚠️ ${esc(st.errors[key])}</div>`);
      if (key === "offers_source") {
        const zip = this._settingsRoot.querySelector('.sfield[data-field="zip_code"]');
        zip?.classList.remove("invalid");
        zip?.querySelector(".ferr")?.remove();
      }
    }
    this._settingsFooter();
  }

  /** Footer text and the save button without re-rendering the fields (focus, caret). */
  _settingsFooter() {
    const st = this._settings;
    const root = this._settingsRoot;
    const changes = Object.keys(this._settingsChanges()).length;
    const errCount = Object.keys(st.errors).length;
    const state = root.querySelector(".sstate");
    if (state) {
      state.textContent = errCount ? `${errCount} ${errCount === 1 ? "Feld" : "Felder"} bitte prüfen` : changes ? `${changes} ungespeicherte Änderung${changes === 1 ? "" : "en"}` : "Keine Änderungen";
      state.classList.toggle("err", Boolean(errCount));
    }
    const save = root.querySelector("[data-ssave]");
    if (save) save.disabled = !changes || st.saving || st.phase === "reloading";
    const close = root.querySelector(".sfoot [data-sclose]");
    if (close) close.textContent = changes ? "Abbrechen" : "Schließen";
  }

  _closeSettings(force = false) {
    const st = this._settings;
    if (!st) return;
    if (st.saving || st.phase === "reloading") return;
    if (!force && Object.keys(this._settingsChanges()).length && !confirm("Ungespeicherte Änderungen verwerfen?")) return;
    this._settings = null;
    this._renderSettings();
  }

  async _saveSettings() {
    const st = this._settings;
    if (!st?.data || st.saving) return;
    const changes = this._settingsChanges();
    if (!Object.keys(changes).length) return this._closeSettings(true);
    if (st.errors.enabled_meals) return this._settingsFocusError();
    st.saving = true;
    this._renderSettings();
    let res;
    try {
      res = await this._hass.callWS({ type: `${DOMAIN}/save_settings`, values: changes });
    } catch (err) {
      st.saving = false;
      this._renderSettings();
      return this._toast(errText(err));
    }
    st.saving = false;
    if (!res?.saved) {
      st.errors = { ...(res?.errors || {}) };
      this._renderSettings();
      return this._settingsFocusError();
    }
    st.errors = {};
    if (!res.reload) {
      this._settings = null;
      this._renderSettings();
      return this._toast("⚙️ Einstellungen gespeichert");
    }
    st.phase = "reloading";
    st.original = JSON.parse(JSON.stringify(st.values));
    this._renderSettings();
    this._settingsRoot.querySelector(".sbody").scrollTop = 0;
    await this._reloadAfterSettings();
  }

  _settingsFocusError() {
    const st = this._settings;
    const first = Object.keys(st?.data?.fields || {}).find((k) => k in st.errors) || Object.keys(st.errors)[0];
    if (!first) return;
    const sec = this._settingsField(first).section;
    if (sec) {
      st.section = sec;
      this._settingsRoot.querySelectorAll("[data-snav]").forEach((b) => b.classList.toggle("on", b.dataset.snav === sec));
    }
    const field = this._settingsRoot.querySelector(`.sfield[data-field="${CSS.escape(first)}"]`);
    this._settingsJumping = true;
    field?.scrollIntoView({ block: "center", behavior: "auto" });
    clearTimeout(this._settingsJumpTimer);
    this._settingsJumpTimer = setTimeout(() => (this._settingsJumping = false), 50);
    const input = field?.querySelector("input, select, textarea");
    if (input) {
      input.focus({ preventScroll: true });
      if (input.select && input.type !== "checkbox" && input.type !== "radio") input.select();
    }
  }

  /** The integration reloads with the new options: its websocket commands answer
   *  "not_loaded" for a moment – subscribe again and load the data with retries. */
  async _reloadAfterSettings() {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    // the panel was removed meanwhile (Home Assistant left the page, e.g. the panel was
    // switched off): stop – connectedCallback loads everything again if it comes back
    const gone = () => {
      if (this.isConnected) return false;
      if (this._settings?.phase === "reloading") {
        this._settings = null;
        this._renderSettings();
      }
      this._reloadOnConnect = true;
      return true;
    };
    await sleep(SETTINGS_RELOAD_DELAYS[0]);
    let ok = false;
    let last = null;
    for (const delay of SETTINGS_RELOAD_DELAYS.slice(1)) {
      if (gone()) return;
      try {
        await this._hass.callWS({ type: `${DOMAIN}/data` });
        ok = true;
        break;
      } catch (err) {
        last = err;
        await sleep(delay);
      }
    }
    if (gone()) return;
    const st = this._settings;
    if (!ok) {
      if (st) {
        st.phase = "failed";
        st.message = errText(last);
        this._renderSettings();
      }
      return;
    }
    if (this._unsub) {
      const unsub = this._unsub;
      this._unsub = null;
      try {
        const fn = await unsub;
        if (typeof fn === "function") await fn();
      } catch (e) {
        /* already gone */
      }
    }
    await this._subscribe();
    if (gone()) return;
    this._forgetLoaded();
    await this._load();
    if (this._settings === st) {
      this._settings = null;
      this._renderSettings();
    }
    this._toast("⚙️ Einstellungen gespeichert – der Essensplaner wurde neu geladen");
  }

  /** Everything may have changed (sources, stores, meals …): the next _load fetches it all. */
  _forgetLoaded() {
    this._dataJson = null;
    this._costs = {};
    this._priceList = null;
    this._storePricesStale = true;
    this._receiptsStale = true;
    this._so.stale = true;
    this._branchSearch = undefined;
  }

  /* ------------------------------------------------------------ receipts (Kassenzettel, 1.4) */
  _receiptMeta() {
    const r = this._data.economy?.receipts;
    if (!r?.total_receipts) return "";
    return `${r.total_receipts} gespeichert${r.receipt_prices ? ` · ${r.receipt_prices} Preise` : ""}`;
  }

  _aiState() {
    const r = this._data.economy?.receipts || {};
    return { entity: r.ai_entity || null, available: Boolean(r.ai_entity && r.ai_available) };
  }

  _receiptSectionHtml() {
    if (!this._isAdmin()) return `<div class="hint">🧾 Kassenzettel erfassen und ihre Preise übernehmen können nur Administratoren.</div>`;
    // after an error (e.g. a backend not restarted after the update) only the next data
    // change asks again – never in a loop
    const need = (this._receipts === null && !this._receiptsError) || this._receiptsStale;
    if (need && !this._receiptsLoading) this._fetchReceipts();
    const ai = this._aiState();
    const intro = `<div class="hint">Fotografiere einen Kassenzettel oder füge seinen Text ein: nach deiner Prüfung werden seine Preise die eigenen Preise des Ladens (mit Datum, 🧾 in der Preisliste).${ai.entity ? (ai.available ? ` Fotos liest die KI-Aufgabe ${esc(ai.entity)}.` : ` Die KI-Aufgabe ${esc(ai.entity)} ist gerade nicht erreichbar – Text einfügen geht immer.`) : " Für Fotos braucht es eine KI-Aufgabe – ohne sie fügst du den Text ein (Handy: „Text aus Foto kopieren“)."}</div>`;
    const actions = `<div class="row" style="margin:0"><button class="btn primary" data-action="receipt-new">🧾 Kassenzettel erfassen</button>${ai.entity ? "" : this._settingsLink("receipts", "⚙️ KI-Aufgabe wählen")}</div>`;
    let list = "";
    if (this._receiptsError) list = `<div class="notice err">${esc(this._receiptsError)}</div>`;
    else if (!this._receipts) list = `<div class="hint">⏳ Lade Kassenzettel …</div>`;
    else if (!this._receipts.receipts?.length) list = `<div class="hint">Noch keine Kassenzettel gespeichert.</div>`;
    else {
      const limit = this._receiptLimit || 10;
      const loaded = this._receipts.receipts;
      // the backend keeps up to 200 receipts; older ones are fetched with "Mehr anzeigen"
      const count = Math.max(this._receipts.count || 0, loaded.length);
      const items = loaded.slice(0, limit);
      list = `<div class="rlist">${items
        .map((r) => {
          const pdf = isPdfReceipt(r);
          const thumb = pdf ? `<span class="rthumb" title="PDF">📄</span>` : r.image_url ? `<span class="rthumb"><img loading="lazy" src="${esc(r.image_url)}" alt=""></span>` : `<span class="rthumb">🧾</span>`;
          const total = r.total ?? r.sum;
          return `<div class="rrow">
            <button class="icon" data-action="receipt-show" data-id="${esc(r.id)}" title="Ansehen" aria-label="Kassenzettel ansehen" style="width:auto;height:auto;border-radius:8px;padding:0">${thumb}</button>
            <div class="rinfo"><b>${esc(r.store_label || r.retailer_name || "")}</b><div class="meta">${esc(dayText(r.date))}${r.date ? esc(String(r.date).slice(0, 4)) : ""} · ${esc(this._receiptCountText(r))}${pdf ? " · 📄 PDF" : r.source === "photo" ? " · 📷 Foto" : ""}</div></div>
            <div class="rsum"><b>${eur(total)}</b></div>
            <button class="icon" data-action="receipt-delete" data-id="${esc(r.id)}" title="Löschen" aria-label="Kassenzettel löschen">🗑</button>
          </div>`;
        })
        .join("")}</div>${count > items.length ? `<div class="row" style="margin:6px 0 0;align-items:center"><span class="meta">${items.length} von ${count}</span><button class="btn small" data-action="receipts-more" ${this._receiptsLoading ? "disabled" : ""}>${this._receiptsLoading ? "⏳ Lade …" : "Mehr anzeigen"}</button></div>` : ""}`;
    }
    return `${intro}${actions}${list}`;
  }

  _renderReceiptSection() {
    const box = this._content.querySelector(".rbox");
    if (box) box.innerHTML = this._receiptSectionHtml();
  }

  async _fetchReceipts() {
    this._receiptsLoading = true;
    this._receiptsStale = false;
    try {
      this._receipts = await this._hass.callWS({ type: `${DOMAIN}/receipts`, limit: this._receiptFetchLimit || RECEIPT_FETCH_STEP });
      this._receiptsError = null;
    } catch (err) {
      this._receiptsError = errText(err);
    } finally {
      this._receiptsLoading = false;
    }
    if (this._tab === "stores") this._renderReceiptSection();
  }

  /** Big phone photos are made smaller (JPEG, at most 2400 px) before the upload. */
  async _shrinkImage(file) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size <= 8 * 1024 * 1024 || typeof createImageBitmap !== "function") return file;
    try {
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 2400 / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.88));
      return blob ? new File([blob], "kassenzettel.jpg", { type: "image/jpeg" }) : file;
    } catch (e) {
      return file;
    }
  }

  /** POST the photo / PDF with the user's token (HA's fetchWithAuth when there). */
  async _uploadReceiptFile(file) {
    const form = new FormData();
    form.append("file", file, file.name || "kassenzettel.jpg");
    const init = { method: "POST", body: form };
    let resp;
    if (typeof this._hass.fetchWithAuth === "function") resp = await this._hass.fetchWithAuth(RECEIPT_UPLOAD_URL, init);
    else {
      const token = this._hass.auth?.data?.access_token;
      resp = await fetch(RECEIPT_UPLOAD_URL, { ...init, headers: token ? { Authorization: `Bearer ${token}` } : {} });
    }
    let json = {};
    try {
      json = await resp.json();
    } catch (e) {
      /* not JSON */
    }
    if (!resp.ok) throw new Error(json.message || (resp.status === 401 || resp.status === 403 ? "Nur Administratoren können Kassenzettel hochladen." : `Hochladen fehlgeschlagen (HTTP ${resp.status}).`));
    return json;
  }

  /** Options "Meine Läden" / "Andere Kette"; with a placeholder nothing is preselected
   *  (a receipt whose store was not recognized must not go to the first store). */
  _branchChoices(selectedBranch, selectedRetailer, placeholder = "") {
    const branches = this._orderedBranches().filter((b) => b.retailer);
    const retailers = this._data.economy?.retailers || [];
    const opts = branches.map((b) => `<option value="b:${esc(b.id)}" ${b.id === selectedBranch ? "selected" : ""}>${esc(b.label)}${b.main ? " ⭐" : ""}</option>`).join("");
    const chains = retailers.map((r) => `<option value="r:${esc(r.id)}" ${!selectedBranch && r.id === selectedRetailer ? "selected" : ""}>${esc(r.name)}</option>`).join("");
    const none = placeholder ? `<option value="" disabled selected>${esc(placeholder)}</option>` : "";
    return `${none}${opts ? `<optgroup label="Meine Läden">${opts}</optgroup>` : ""}<optgroup label="Andere Kette">${chains}</optgroup>`;
  }

  /** The capture dialog: photo / PDF (read by the AI Task) or pasted text, then review. */
  _openReceipt() {
    if (!this._isAdmin()) return this._toast("🧾 Kassenzettel können nur Administratoren speichern.");
    this._receipt = { step: "input", upload: null, text: "", busy: null, error: null, proposal: null, store: "" };
    this._renderReceiptInput();
  }

  _renderReceiptInput() {
    const st = this._receipt;
    if (!st) return;
    const ai = this._aiState();
    const touch = window.matchMedia?.("(pointer: coarse)")?.matches;
    const up = st.upload;
    const preview = up ? (String(up.content_type || "").includes("pdf") ? `<div class="notice">📄 PDF hochgeladen (${Math.round((up.size || 0) / 1024)} KB)</div>` : up.url ? `<img class="rpreview" src="${esc(up.url)}" alt="Kassenzettel">` : `<div class="notice">📷 Foto hochgeladen</div>`) : "";
    const aiPart = up
      ? ai.available
        ? `<div class="row" style="margin:0"><button class="btn primary rai" ${st.busy ? "disabled" : ""}>${st.busy === "ai" ? "⏳ KI liest den Kassenzettel … (bis zu ein paar Minuten)" : "🤖 Mit KI auslesen"}</button></div>`
        : `<div class="notice warn">${ai.entity ? `Die KI-Aufgabe ${esc(ai.entity)} ist gerade nicht erreichbar.` : "Für Fotos braucht es eine KI-Aufgabe (⚙️ Einstellungen → Kassenzettel)."} Füge unten den Text ein – das Foto wird mit dem Kassenzettel gespeichert.</div>`
      : "";
    const body = `
      <div class="hint">Die geprüften Preise werden die eigenen Preise des Ladens. Der KI-Aufgabe wird nur das Bild geschickt; eingefügter Text wird lokal gelesen.</div>
      <label class="field">Laden (optional – wird sonst erkannt)<select class="rstore"><option value="">Automatisch erkennen</option>${this._branchChoices(st.store.startsWith("b:") ? st.store.slice(2) : null, st.store.startsWith("r:") ? st.store.slice(2) : null)}</select></label>
      <div class="section">
        <h4>📷 Foto oder PDF</h4>
        <div class="rpick">
          ${touch ? `<button class="btn ${up ? "" : "primary"} rcam" ${st.busy ? "disabled" : ""}>📷 Foto aufnehmen</button>` : ""}
          <button class="btn ${touch || up ? "" : "primary"} rfile" ${st.busy ? "disabled" : ""}>${st.busy === "upload" ? "⏳ Lade hoch …" : "📁 Foto oder PDF wählen"}</button>
          <input type="file" accept="image/*" capture="environment" class="rcamin" hidden>
          <input type="file" accept="image/*,application/pdf" class="rfilein" hidden>
        </div>
        ${preview}${aiPart}
      </div>
      <div class="section">
        <h4>📋 Text einfügen</h4>
        <div class="hint">Tipp: Mit der Handy-Funktion „Text aus Foto kopieren“ (iPhone: Livetext, Android: Google Lens) den Kassenzettel abfotografieren, den Text kopieren und hier einfügen.</div>
        <textarea class="rtext" placeholder="Lidl&#10;Milbona H-Milch 1,5%   0,99 A&#10;…&#10;zu zahlen   8,87" aria-label="Text des Kassenzettels">${esc(st.text)}</textarea>
        <div><button class="btn ${up && ai.available ? "" : "primary"} rparse" ${st.busy ? "disabled" : ""}>${st.busy === "text" ? "⏳ Lese …" : "📄 Text auslesen"}</button></div>
      </div>
      ${st.error ? `<div class="notice err">${esc(st.error)}</div>` : ""}`;
    this._showModal("🧾 Kassenzettel erfassen", body, `<button class="btn" data-close>Abbrechen</button>`, (root) => {
      root.querySelector(".modal").style.width = "min(760px, 100%)";
      const camIn = root.querySelector(".rcamin");
      const fileIn = root.querySelector(".rfilein");
      root.querySelector(".rcam")?.addEventListener("click", () => camIn.click());
      root.querySelector(".rfile").addEventListener("click", () => fileIn.click());
      const onFile = (ev) => {
        const file = ev.target.files?.[0];
        ev.target.value = "";
        if (file) this._receiptUpload(file);
      };
      camIn.addEventListener("change", onFile);
      fileIn.addEventListener("change", onFile);
      const text = root.querySelector(".rtext");
      text.addEventListener("input", () => (st.text = text.value));
      root.querySelector(".rstore").addEventListener("change", (ev) => (st.store = ev.target.value));
      root.querySelector(".rparse").addEventListener("click", () => this._receiptParse("text"));
      root.querySelector(".rai")?.addEventListener("click", () => this._receiptParse("ai"));
    }, {
      // a pasted text or an upload is not lost by a tap beside the dialog
      sticky: () => Boolean(st.text.trim() || st.upload || st.busy),
      guard: () => this._receipt !== st || st.busy !== "ai" || confirm("Die KI liest den Kassenzettel noch. Trotzdem abbrechen?"),
    });
  }

  async _receiptUpload(file) {
    const st = this._receipt;
    if (!st) return;
    if (!/^(image\/|application\/pdf)/.test(file.type || "") && !/\.(jpe?g|png|webp|pdf)$/i.test(file.name || "")) {
      st.error = "Bitte ein Foto (JPG, PNG, WebP) oder eine PDF-Datei wählen.";
      return this._renderReceiptInput();
    }
    st.busy = "upload";
    st.error = null;
    this._renderReceiptInput();
    try {
      const small = await this._shrinkImage(file);
      if (small.size > RECEIPT_MAX_BYTES) throw new Error("Die Datei ist zu groß (höchstens 10 MB).");
      st.upload = await this._uploadReceiptFile(small);
    } catch (err) {
      st.error = errText(err);
    } finally {
      st.busy = null;
    }
    if (this._receipt === st) this._renderReceiptInput();
  }

  _receiptBranch(st) {
    const v = st.store || "";
    return v.startsWith("b:") ? v.slice(2) : v.startsWith("r:") ? v.slice(2) : null;
  }

  async _receiptParse(how) {
    const st = this._receipt;
    if (!st || st.busy) return;
    const msg = { type: `${DOMAIN}/receipt_parse` };
    if (how === "text") {
      if (!st.text.trim()) {
        st.error = "Bitte zuerst den Text des Kassenzettels einfügen.";
        return this._renderReceiptInput();
      }
      msg.text = st.text;
    } else {
      if (!st.upload?.upload_id) return;
      msg.upload_id = st.upload.upload_id;
      msg.ai = true;
    }
    const branch = this._receiptBranch(st);
    if (branch) msg.branch = branch;
    st.busy = how;
    st.error = null;
    this._renderReceiptInput();
    try {
      const proposal = await this._hass.callWS(msg);
      if (this._receipt !== st) return;
      st.proposal = proposal;
      st.step = "review";
      st.busy = null;
      // the photo goes with the receipt also when its text was pasted
      if (how === "text" && st.upload?.upload_id && !proposal.upload_id) proposal.upload_id = st.upload.upload_id;
      await this._renderReceiptReview();
    } catch (err) {
      st.busy = null;
      st.error = errText(err);
      if (this._receipt === st) this._renderReceiptInput();
    }
  }

  /** Article names for the article field of the review (estimates, own and store prices). */
  async _articleNames() {
    const names = new Set();
    for (const p of await this._prices()) if (p.name) names.add(p.name);
    for (const r of this._storePrices?.rows || []) if (r.name) names.add(r.name);
    return [...names].sort((a, b) => a.localeCompare(b, "de"));
  }

  async _renderReceiptReview() {
    const st = this._receipt;
    const p = st?.proposal;
    if (!p) return;
    const names = await this._articleNames();
    if (this._receipt !== st) return;
    const items = p.items || [];
    for (const it of items) {
      it._article ??= it.product || "";
      it._ignored ??= Boolean(it.ignored) || it.status === "ignored";
      it._regular ??= Boolean(it.regular);
    }
    const unitOptions = (unit) => (PRICE_UNITS.includes(unit) || !unit ? PRICE_UNITS : [unit, ...PRICE_UNITS]).map((u) => `<option ${u === (unit || "Stück") ? "selected" : ""}>${esc(u)}</option>`).join("");
    const rows = items
      .map((it, i) => {
        const current = it.current ? `bisher ${eur(it.current.price)}${packText(it.current.amount, it.current.unit) ? ` / ${packText(it.current.amount, it.current.unit)}` : ""}` : "";
        const sub = [it.status === "unknown" && it.suggestion ? `Vorschlag: ${it.suggestion}` : "", current, it.kind && it.kind !== "article" ? { deposit: "Pfand", discount: "Rabatt", storno: "Storno" }[it.kind] || "" : ""].filter(Boolean).join(" · ");
        return `<div class="rline ${it._ignored ? "ignored" : ""}" data-i="${i}">
          <div class="src">${esc(it.line || it.name || "")}</div>
          <div class="art">
            <input list="ep-articles" class="rart" value="${esc(it._article)}" placeholder="${esc(it.suggestion || "Artikel wählen …")}" aria-label="Erkannter Artikel" ${it._ignored ? "disabled" : ""}>
            <label class="ign"><input type="checkbox" class="rign" ${it._ignored ? "checked" : ""}> ignorieren</label>
            ${sub ? `<span class="meta">${esc(sub)}</span>` : ""}${it.warning ? `<span class="rwarn" ${it.offer && !this._receiptOffer(it) ? "hidden" : ""}>⚠️ ${esc(it.warning)}</span>` : ""}${it.offer ? `<label class="ign rregl" title="Kein Angebot: der Preis wird als Normalpreis des Ladens gespeichert" ${this._receiptAtOffer(it) ? "" : "hidden"}><input type="checkbox" class="rreg" ${it._regular ? "checked" : ""}> trotzdem als Normalpreis</label>` : ""}
          </div>
          <div class="packin" ${it.weight ? 'title="Gewogen: gespeichert wird der Preis je kg"' : ""}><input class="ramount" inputmode="decimal" value="${esc(num(it.amount))}" aria-label="Menge / Packung" placeholder="Menge" ${it.weight ? "disabled" : ""}><select class="runit" aria-label="Einheit" ${it.weight ? "disabled" : ""}>${unitOptions(it.unit)}</select></div>
          <div><input class="rprice" inputmode="decimal" value="${esc(num(it.price))}" aria-label="Zeilensumme (Preis der Zeile auf dem Kassenzettel)"></div>
          <div class="rown meta" aria-live="polite">${esc(this._receiptOwnText(it))}</div>
        </div>`;
      })
      .join("");
    const warn = (p.warnings || []).map((w) => `<div class="notice warn">${esc(w)}</div>`).join("");
    const unknownStore = !p.branch_id && !p.retailer;
    const body = `
      <div class="rhead">
        <label class="field">Laden<select class="rbranch">${this._branchChoices(p.branch_id, p.retailer, unknownStore ? "– bitte Laden wählen –" : "")}</select><span class="rneed" hidden>Bitte den Laden wählen – seine Preise werden gespeichert.</span></label>
        <label class="field">Datum<input type="date" class="rdate" value="${esc(p.date || this._today())}" max="${esc(this._today())}"></label>
      </div>
      ${warn}
      <div class="rtable">
        <div class="rline headrow"><span>Zeile</span><span>Erkannter Artikel</span><span>Menge / Packung</span><span>Zeilensumme</span></div>
        ${rows || '<div class="hint" style="padding:10px">Keine Zeilen erkannt.</div>'}
      </div>
      <datalist id="ep-articles">${names.map((n) => `<option value="${esc(n)}">`).join("")}</datalist>
      <div class="rtotal"><label class="switch">Summe laut Kassenzettel <input class="rtot" inputmode="decimal" style="width:100px" value="${esc(num(p.total))}" aria-label="Summe laut Kassenzettel"> €</label><span class="rcheck"></span></div>
      <div class="hint">Der Preis einer Zeile ist ihre Summe auf dem Kassenzettel; gespeichert wird der Normalpreis einer Packung (bei „2 x 0,49“ also 0,49 €, ein Rabatt der Zeile zählt nicht) bzw. bei gewogenen Artikeln der Preis je kg – siehe „→ gespeichert“. Ohne Artikel oder mit „ignorieren“ wird eine Zeile nicht als Preis übernommen (z. B. Pfand, Rabatte, Tüten). Zugeordnete Namen merkt sich der Essensplaner für den nächsten Kassenzettel.</div>`;
    const footer = `<button class="btn rback">← Zurück</button><span class="spacer"></span><button class="btn" data-close>Abbrechen</button><button class="btn primary rsave">💾 Preise übernehmen</button>`;
    // the review (maybe minutes of AI Task work and the articles chosen) is not dropped by a
    // tap beside the dialog, and closing it asks first
    const guard = () => this._receipt !== st || st.busy === "save" || confirm("Prüfung verwerfen? Der ausgelesene Kassenzettel und deine Änderungen gehen verloren.");
    this._showModal(`🧾 Prüfen – ${p.branch_label || p.retailer_name || "Kassenzettel"}`, body, footer, (root) => {
      root.querySelector(".modal").style.width = "min(980px, 100%)";
      const update = () => this._receiptTotals(root);
      const own = (line, it) => {
        const out = line.querySelector(".rown");
        if (out) out.textContent = this._receiptOwnText(it);
        // the offer warning only while the line still is at the offer price (and not
        // marked "trotzdem als Normalpreis"), the mark only while it is at that price
        const warn = line.querySelector(".rwarn");
        if (warn && it.offer) warn.hidden = !this._receiptOffer(it);
        const regular = line.querySelector(".rregl");
        if (regular) regular.hidden = !this._receiptAtOffer(it);
      };
      root.querySelector(".rtable").addEventListener("input", (ev) => {
        const line = ev.target.closest(".rline[data-i]");
        if (!line) return;
        const it = items[Number(line.dataset.i)];
        if (ev.target.classList.contains("rart")) it._article = ev.target.value;
        if (ev.target.classList.contains("ramount")) it._amount = ev.target.value;
        if (ev.target.classList.contains("rprice")) it._price = ev.target.value;
        own(line, it);
        update();
      });
      root.querySelector(".rtable").addEventListener("change", (ev) => {
        const line = ev.target.closest(".rline[data-i]");
        if (!line) return;
        const it = items[Number(line.dataset.i)];
        if (ev.target.classList.contains("runit")) it._unit = ev.target.value;
        if (ev.target.classList.contains("rreg")) it._regular = ev.target.checked;
        if (ev.target.classList.contains("rign")) {
          it._ignored = ev.target.checked;
          line.classList.toggle("ignored", it._ignored);
          line.querySelector(".rart").disabled = it._ignored;
        }
        own(line, it);
        update();
      });
      root.querySelector(".rtot").addEventListener("input", update);
      root.querySelector(".rbranch").addEventListener("change", update);
      root.querySelector(".rback").addEventListener("click", () => {
        st.step = "input";
        this._renderReceiptInput();
      });
      root.querySelector(".rsave").addEventListener("click", () => this._receiptSave(root));
      update();
    }, { sticky: true, guard });
  }

  _receiptLineValues(it) {
    const price = it._price != null ? parseNum(it._price) : it.price;
    const amount = it._amount != null ? parseNum(it._amount) : it.amount;
    return { price, amount, unit: it._unit || it.unit || "Stück" };
  }

  /** What saving a line stores (like receipts.own_price in the backend): the regular price
   *  of one piece – line total plus the line's discount, divided by the quantity – or, for
   *  a weighed article, the price per kg (its pack fields do not count). */
  _receiptOwnPrice(it) {
    const v = this._receiptLineValues(it);
    const discount = Number(it.discount) || 0;
    const qty = Number(it.quantity) || 1;
    const price = v.price + discount;
    if (!Number.isFinite(price) || price <= 0 || qty <= 0) return null;
    const weight = Number(it.weight) || 0;
    if (weight > 0) {
      let perKg = Math.round((price / weight) * 100) / 100;
      const given = Number(it.unit_price);
      if (given && Math.abs(given - perKg) <= 0.05) perKg = Math.round(given * 100) / 100;
      return { price: perKg, weight, discount, qty: 1 };
    }
    const amount = Number.isFinite(v.amount) && v.amount > 0 ? v.amount : null;
    return { price: Math.round((price / qty) * 100) / 100, amount, unit: v.unit, discount, qty };
  }

  /** The leaflet offer the backend found for the line (receipts.receipt_offer), while the
   *  line keeps its article and is still at the offer price – to the cent, computed like
   *  the backend does when saving (line total plus discount, divided by the quantity). */
  _receiptAtOffer(it) {
    const offer = it.offer;
    if (!offer || it._ignored || it.weight) return null;
    if (String(it._article || "").trim() !== (it.product || "")) return null;
    const v = this._receiptLineValues(it);
    const each = (v.price + (Number(it.discount) || 0)) / (Number(it.quantity) || 1);
    const price = Number(offer.price);
    return Number.isFinite(each) && each > 0 && Number.isFinite(price) && Math.abs(each - price) <= RECEIPT_OFFER_TOLERANCE + 1e-6 ? offer : null;
  }

  /** The offer while saving the line only adds the price history (status "offer", the
   *  store's regular price stays) – not when the user marked it "trotzdem als Normalpreis". */
  _receiptOffer(it) {
    return it._regular ? null : this._receiptAtOffer(it);
  }

  _receiptOwnText(it) {
    if (it._ignored || !String(it._article || "").trim()) return "";
    const o = this._receiptOwnPrice(it);
    if (!o) return "";
    const offer = this._receiptOffer(it);
    if (offer) return `→ nur im Preisverlauf (Angebot${offer.valid_to ? ` bis ${dayText(offer.valid_to)}` : ""})`;
    const why = [o.discount > 0 ? `Normalpreis vor Rabatt −${eur(o.discount)}` : "", o.qty !== 1 ? `Zeilensumme ÷ ${num(o.qty)}` : ""].filter(Boolean);
    if (o.weight) return `→ gespeichert: ${eur(o.price)}/kg (gewogen ${num(o.weight)} kg${why.length ? `, ${why.join(", ")}` : ""})`;
    const pack = o.amount ? packText(o.amount, o.unit) : "";
    return `→ gespeichert: ${eur(o.price)}${pack ? ` / ${pack}` : " je Packung (Größe wird ergänzt)"}${why.length ? ` (${why.join(", ")})` : ""}`;
  }

  _receiptTotals(root) {
    const items = this._receipt?.proposal?.items || [];
    let sum = 0;
    let bad = 0;
    let n = 0;
    for (const it of items) {
      const v = this._receiptLineValues(it);
      if (!Number.isFinite(v.price)) bad += 1;
      else sum += v.price;
      if (!it._ignored && String(it._article || "").trim() && Number.isFinite(v.price)) n += 1;
    }
    sum = Math.round(sum * 100) / 100;
    const total = parseNum(root.querySelector(".rtot")?.value);
    const check = root.querySelector(".rcheck");
    if (check) {
      const ok = Number.isFinite(total) && Math.abs(total - sum) < 0.015;
      check.innerHTML = `Summe der Zeilen <b>${eur(sum)}</b> ${Number.isFinite(total) ? (ok ? '<span class="bdg ok">✓ stimmt</span>' : `<span class="bdg warn">⚠️ ${eur(Math.abs(total - sum))} Unterschied – bitte Zeilen prüfen</span>`) : ""}${bad ? ` <span class="bdg bad">${bad} Preis${bad > 1 ? "e" : ""} ungültig</span>` : ""}`;
    }
    const branch = root.querySelector(".rbranch");
    const noStore = Boolean(branch) && !branch.value;
    branch?.classList.toggle("invalid", noStore);
    branch?.setAttribute("aria-invalid", noStore ? "true" : "false");
    const need = root.querySelector(".rneed");
    if (need) need.hidden = !noStore;
    const save = root.querySelector(".rsave");
    if (save) {
      save.textContent = noStore ? "💾 Erst den Laden wählen" : `💾 ${n} Preis${n === 1 ? "" : "e"} übernehmen`;
      save.disabled = Boolean(bad) || !items.length || noStore;
    }
    return { sum, n, bad, noStore };
  }

  async _receiptSave(root) {
    const st = this._receipt;
    const p = st?.proposal;
    if (!p || st.busy) return;
    const { bad, noStore } = this._receiptTotals(root);
    if (bad) return this._toast("Bitte die Preise prüfen (z. B. 1,99).");
    const choice = root.querySelector(".rbranch").value;
    if (noStore || !choice) {
      root.querySelector(".rbranch").focus();
      return this._toast("Bitte zuerst den Laden wählen.");
    }
    const receipt = {
      date: root.querySelector(".rdate").value || p.date || this._today(),
      source: p.source,
      items: (p.items || []).map((it) => {
        const v = this._receiptLineValues(it);
        const article = String(it._article || "").trim();
        const changed = article !== (it.product || "");
        // regular ("trotzdem als Normalpreis"): the backend does not check the line for an offer
        const item = { line: it.line, name: it.name, price: v.price, quantity: it.quantity, weight: it.weight, unit_price: it.unit_price, discount: it.discount, ignored: Boolean(it._ignored), regular: Boolean(it._regular) };
        if (!it._ignored && article) {
          item.key = changed ? article : it.key || article;
          item.product = changed ? null : it.product;
        }
        if (Number.isFinite(v.amount) && v.amount > 0) {
          item.amount = v.amount;
          item.unit = v.unit;
        }
        return item;
      }),
    };
    if (choice.startsWith("b:")) receipt.branch_id = choice.slice(2);
    else if (choice.startsWith("r:")) receipt.store = choice.slice(2);
    const total = parseNum(root.querySelector(".rtot").value);
    if (Number.isFinite(total)) receipt.total = total;
    if (p.upload_id) receipt.upload_id = p.upload_id;
    if (p.id) receipt.id = p.id;
    st.busy = "save";
    const btn = root.querySelector(".rsave");
    btn.disabled = true;
    btn.textContent = "⏳ Speichere …";
    try {
      const res = await this._hass.callWS({ type: `${DOMAIN}/receipt_save`, receipt });
      const label = res?.receipt?.store_label || this._branch(receipt.branch_id)?.label || this._retailerName(receipt.store) || "den Laden";
      this._receipt = null;
      this._closeModal();
      const kept = res?.kept ? ` · ${res.kept} neuere eigene Preise behalten` : "";
      const offers = res?.offer ? ` · ${res.offer} Angebotspreis${res.offer === 1 ? "" : "e"} nur im Preisverlauf` : "";
      this._toast(`🧾 ${res?.saved ?? 0} Preis${res?.saved === 1 ? "" : "e"} für ${label} übernommen${kept}${offers}`);
      this._receiptsStale = true;
      this._storePricesStale = true;
      if (this._tab === "stores") {
        this._renderReceiptSection();
        this._fetchStorePrices();
      }
    } catch (err) {
      st.busy = null;
      btn.disabled = false;
      this._receiptTotals(root);
      this._toast(errText(err));
    }
  }

  /** "3 Preise übernommen · 1 Angebotspreis nur im Preisverlauf" of a stored receipt (the
   *  backend's prices count only the saved lines). */
  _receiptCountText(r) {
    const offers = (r.items || []).filter((it) => it.status === "offer").length;
    return `${r.prices || 0} Preis${r.prices === 1 ? "" : "e"} übernommen${offers ? ` · ${offers} Angebotspreis${offers === 1 ? "" : "e"} nur im Preisverlauf` : ""}`;
  }

  _receiptById(id) {
    return (this._receipts?.receipts || []).find((r) => r.id === id);
  }

  _showReceipt(id) {
    const r = this._receiptById(id);
    if (!r) return;
    const icon = { saved: "✓", kept: "↺", offer: "🏷️", ignored: "–", unknown: "?", skipped: "–" };
    const title = { saved: "als Preis übernommen", kept: "neuerer eigener Preis behalten", offer: "Angebotspreis – nur im Preisverlauf", ignored: "ignoriert", unknown: "ohne Artikel", skipped: "ohne Preis" };
    const rows = (r.items || [])
      .map((it) => `<div class="pricerow"><span>${esc(it.product || it.name)}${it.product && it.name !== it.product ? ` <span class="meta">${esc(it.name)}</span>` : ""}</span><span class="meta" title="${esc(title[it.status] || "")}">${icon[it.status] || ""}</span><b>${eur(it.price)}</b></div>`)
      .join("");
    const hasOffer = (r.items || []).some((it) => it.status === "offer");
    const file = !r.image_url
      ? ""
      : isPdfReceipt(r)
        ? `<a class="btn" href="${esc(r.image_url)}" target="_blank" rel="noreferrer">📄 PDF öffnen ↗</a>`
        : `<a href="${esc(r.image_url)}" target="_blank" rel="noreferrer"><img class="rpreview" src="${esc(r.image_url)}" alt="Kassenzettel"></a>`;
    const body = `
      ${file}
      <div class="meta">${esc(dayText(r.date))}${esc(String(r.date || "").slice(0, 4))} · Summe ${eur(r.total ?? r.sum)} · ${esc(this._receiptCountText(r))}</div>
      <div>${rows}</div>
      <div class="hint">✓ = als Preis übernommen · ↺ = ein neuerer eigener Preis bleibt${hasOffer ? " · 🏷️ = Angebotspreis, nur im Preisverlauf" : ""} · – = ignoriert</div>`;
    const footer = `<button class="btn danger rdel">🗑 Löschen</button><span class="spacer"></span><button class="btn" data-close>Schließen</button>`;
    this._showModal(`🧾 ${r.store_label || r.retailer_name}`, body, footer, (root) => {
      root.querySelector(".rdel").addEventListener("click", () => this._deleteReceipt(id));
    });
  }

  _deleteReceipt(id) {
    const r = this._receiptById(id);
    if (!r) return;
    const body = `<div>Kassenzettel von <b>${esc(r.store_label || r.retailer_name)}</b> vom ${esc(dayText(r.date))} löschen?</div>${r.prices ? `<div class="hint">Die ${r.prices} Preise daraus kannst du behalten (sie bleiben eigene Preise des Ladens) oder mit entfernen.</div>` : ""}`;
    const footer = `<button class="btn" data-close>Abbrechen</button>${r.prices ? `<button class="btn danger rdelall">🗑 Mit Preisen löschen</button>` : ""}<button class="btn primary rdelone">🗑 ${r.prices ? "Preise behalten" : "Löschen"}</button>`;
    this._showModal("Kassenzettel löschen", body, footer, (root) => {
      const run = async (removePrices) => {
        try {
          const res = await this._hass.callWS({ type: `${DOMAIN}/receipt_delete`, receipt_id: id, remove_prices: removePrices });
          this._closeModal();
          this._toast(`🗑 Kassenzettel gelöscht${res?.prices_removed ? ` · ${res.prices_removed} Preise entfernt` : ""}`);
          if (this._receipts) this._receipts.receipts = this._receipts.receipts.filter((x) => x.id !== id);
          this._receiptsStale = true;
          if (removePrices) this._storePricesStale = true;
          if (this._tab === "stores") {
            this._renderReceiptSection();
            if (removePrices) this._fetchStorePrices();
          }
        } catch (err) {
          this._toast(errText(err));
        }
      };
      root.querySelector(".rdelone").addEventListener("click", () => run(false));
      root.querySelector(".rdelall")?.addEventListener("click", () => run(true));
    });
  }

  /* ------------------------------------------------------------ store picker (shopping list) */
  async _openStorePicker(uid) {
    const item = (this._data.shopping || []).find((i) => i.uid === uid);
    if (!item) return;
    const branches = this._orderedBranches().filter((b) => b.selected);
    const prices = {};
    for (const a of item.alternatives || []) prices[a.branch_id] = { price: a.price, offer: a.offer, real: a.real };
    // whether the item's own price is the store's or an estimate only compare_prices tells
    if (item.branch_id) prices[item.branch_id] = { price: item.price, offer: item.offer };
    // true: the store's own price (or an offer), false: an estimate (Richtwert), null: unknown
    const realOf = (x) => (!x ? null : x.offer ? true : x.real == null ? null : Boolean(x.real));
    // food at a drugstore only with its own price or an offer (like compare_prices)
    const drugFood = (b) => this._retailerKind(b.retailer) === "drugstore" && !NONFOOD_AISLES.includes(item.category);
    let compare = null;
    // "immer hier kaufen" is stored per product and retailer (also while a manual choice wins)
    const prefs = this._data.store_preferences || {};
    const remembered = (item.key && prefs[item.key]) || (item.store_reason === "preferred" ? item.retailer : null) || null;
    const rememberedBranch = remembered ? branches.find((b) => b.retailer === remembered) : null;
    let selected = "auto";
    if (item.store_override && branches.some((b) => b.id === item.store_override)) selected = item.store_override;
    else if (item.store_reason === "preferred" && item.branch_id) selected = item.branch_id;
    const alwaysFor = (store) => Boolean(remembered) && (store === "auto" || this._branch(store)?.retailer === remembered);
    let always = alwaysFor(selected);
    const initial = `${selected}|${always}`;
    const known = [
      ...(item.alternatives || []),
      ...(item.branch_id ? [{ branch_id: item.branch_id, retailer: item.retailer, label: item.store_label, price: item.price, offer: item.offer }] : []),
    ];
    // only the first branch per chain is priced: another branch of the chain (e.g. Lidl on the
    // way to work) has the chain's prices – offers only where they apply (they are per postcode)
    const offerAt = (offer, b) => {
      const saved = offer && (this._data.offers || []).find((o) => o.id === offer.id);
      return !offer || Boolean(saved && (!Array.isArray(saved.branches) || saved.branches.includes(b.id)));
    };
    const chainPrice = (b) => {
      const same = (x) => x.retailer === b.retailer && x.branch_id !== b.id && x.price != null && offerAt(x.offer, b);
      const a = known.find(same);
      const c = compare?.results?.find((r) => same(r) && (!a || r.branch_id === a.branch_id)) || null;
      if (!a && !c) return null;
      const from = a?.label || c?.label || this._branch((a || c).branch_id)?.label || "";
      return { c, price: a?.price ?? c.price, offer: a?.offer || c?.offer || null, real: c ? realOf(c) : realOf(a), from };
    };
    const rowsHtml = () => {
      const entries = branches.map((b) => {
        const c = compare?.results?.find((r) => r.branch_id === b.id);
        const p = prices[b.id];
        let e = !p && !c ? { b, c: null, price: null, offer: null, real: null, ...chainPrice(b) } : { b, c, price: p?.price ?? c?.price ?? null, offer: p?.offer || c?.offer || null, real: c ? realOf(c) : realOf(p) ?? realOf(compare?.results?.find((r) => r.retailer === b.retailer)) };
        // no estimate of food at a drugstore (compare_prices leaves it out as well)
        if (e.price != null && e.real !== true && drugFood(b)) e = { b, c: null, price: null, offer: null, real: null, dropped: true };
        return e;
      });
      // "günstigster" only among the stores' own prices – never because of an estimate; a
      // price not known as own or estimate yet (compare still loading) holds it back
      const priced = entries.filter((e) => e.price != null && e.real !== false);
      const min = priced.length ? Math.min(...priced.map((e) => e.price)) : null;
      const unique = priced.filter((e) => e.price === min).length < priced.length;
      const auto = `<button class="pick ${selected === "auto" ? "sel" : ""}" data-store="auto"><span style="font-size:22px">🤖</span>
          <span class="pi"><b>Automatisch</b><div class="sub">Hauptladen – außer ein anderer Laden hat ein Angebot oder ist deutlich günstiger</div></span></button>`;
      return (
        auto +
        entries
          .map(({ b, c, price, offer, real, from, dropped }) => {
            const tags = [
              b.id === item.branch_id ? '<span class="bdg">aktuell</span>' : "",
              b.main ? '<span class="bdg star">⭐</span>' : "",
              rememberedBranch && b.id === rememberedBranch.id ? '<span class="bdg" title="Für diesen Artikel gemerkt">immer hier</span>' : "",
              unique && real === true && price === min ? '<span class="bdg ok">günstigster</span>' : "",
            ].join(" ");
            const estimate = price != null && real === false;
            const sub = [offer ? `🏷️ Angebot${offer.valid_to ? ` bis ${shortDate(offer.valid_to)}` : ""}` : estimate ? "Richtwert, kein Preis des Ladens" : c ? PRICE_SOURCE[c.source] || "" : "", c?.pack ? c.pack : "", c?.unit_price && c.base !== "Stück" ? unitPriceText(c.unit_price, c.base) : "", from !== undefined && !estimate ? `Preis der Kette${from ? ` (wie ${from})` : ""}` : ""].filter(Boolean).join(" · ");
            const pp = price == null ? '<span class="meta">–</span>' : estimate ? `<span class="meta" title="Richtwert – kein Preis des Ladens">≈ ${eur(price)}</span>` : `<b>${eur(price)}</b>`;
            return `<button class="pick ${selected === b.id ? "sel" : ""}" data-store="${esc(b.id)}">${retailerDot(b.retailer, b.retailer_name)}
              <span class="pi"><b>${esc(b.label)}</b> ${tags}<div class="sub">${esc(sub || (compare || dropped ? "kein Preis bekannt" : ""))}</div></span>
              <span class="pp">${pp}</span></button>`;
          })
          .join("")
      );
    };
    const alwaysHtml = () =>
      selected === "auto"
        ? remembered
          ? `<label class="switch"><input type="checkbox" class="always" ${always ? "checked" : ""}> Gemerkten Laden (${esc(this._retailerName(remembered))}) für diesen Artikel vergessen</label>`
          : ""
        : `<label class="switch"><input type="checkbox" class="always" ${always ? "checked" : ""}> Immer in diesem Laden kaufen</label>`;
    const body = `
      <div class="hint">Preise für die benötigte Menge (ganze Packungen).</div>
      <div class="picklist" style="max-height:none">${rowsHtml()}</div>
      <div class="alwaysbox">${alwaysHtml()}</div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">✓ Übernehmen</button>`;
    this._showModal(`Wo kaufen? – ${item.summary}`, body, footer, (root) => {
      const list = root.querySelector(".picklist");
      const box = root.querySelector(".alwaysbox");
      const refresh = () => {
        list.innerHTML = rowsHtml();
        box.innerHTML = alwaysHtml();
      };
      list.addEventListener("click", (ev) => {
        const pick = ev.target.closest("[data-store]");
        if (!pick) return;
        if (selected !== pick.dataset.store) always = alwaysFor(pick.dataset.store);
        selected = pick.dataset.store;
        refresh();
      });
      box.addEventListener("change", (ev) => {
        if (ev.target.classList.contains("always")) always = ev.target.checked;
      });
      let saving = false;
      root.querySelector(".save").addEventListener("click", async () => {
        if (`${selected}|${always}` === initial) return this._closeModal();
        if (saving) return;
        saving = true;
        try {
          const b = this._branch(selected);
          // unticked "immer hier" for the remembered store: forget it first, then pick the store
          if (selected !== "auto" && !always && remembered && b?.retailer === remembered) {
            await this._service("set_shopping_store", { item: uid, store: "auto", always: true }, true);
          }
          const data = { item: uid, store: selected };
          if (always) data.always = true;
          await this._service("set_shopping_store", data, true);
          this._closeModal();
          this._toast(selected === "auto" ? `🤖 ${item.summary}: Laden wird automatisch gewählt` : `⇄ ${item.summary} → ${b?.label || "Laden"}${always ? " (immer)" : ""}`);
        } catch (e) {
          /* toast shown */
        } finally {
          saving = false;
        }
      });
      this._hass
        .callWS({ type: `${DOMAIN}/compare_prices`, item: item.summary })
        .then((res) => {
          compare = res;
          if (this._modal?.root === root) refresh();
        })
        .catch(() => {});
    });
  }

  /* ------------------------------------------------------------ cooking mode */
  async _acquireWakeLock() {
    try {
      if ("wakeLock" in navigator && !this._wakeLock) {
        this._wakeLock = await navigator.wakeLock.request("screen");
        this._wakeLock.addEventListener?.("release", () => (this._wakeLock = null));
      }
    } catch (e) {
      /* not supported / not allowed */
    }
  }

  _releaseWakeLock() {
    try {
      this._wakeLock?.release();
    } catch (e) {
      /* ignore */
    }
    this._wakeLock = null;
  }

  async _openCooking(id, servings, ctx) {
    const base = this._recipe(id);
    if (!base) return;
    const res = await this._service("get_recipe", { recipe: id, servings: servings || base.servings }, true);
    const r = res?.recipe || base;
    this._cook = { r, step: 0, checked: new Set(), timers: [], ctx, ingOpen: false, nextTimerId: 1 };
    this._cookRoot.innerHTML = `<div class="cook"></div>`;
    const root = this._cookRoot.firstElementChild;
    root.addEventListener("click", (ev) => this._cookClick(ev));
    root.addEventListener("change", (ev) => {
      const box = ev.target.closest("[data-ing]");
      if (!box) return;
      const i = Number(box.dataset.ing);
      if (box.checked) this._cook.checked.add(i);
      else this._cook.checked.delete(i);
      box.closest("label").classList.toggle("done", box.checked);
    });
    let touchX = null;
    root.addEventListener("touchstart", (ev) => (touchX = ev.touches[0].clientX), { passive: true });
    root.addEventListener("touchend", (ev) => {
      if (touchX == null || !ev.target.closest(".cook-step")) return;
      const dx = ev.changedTouches[0].clientX - touchX;
      touchX = null;
      if (Math.abs(dx) > 60) this._cookGo(dx < 0 ? 1 : -1);
    });
    this._cookInterval = setInterval(() => this._tickTimers(), 1000);
    this._acquireWakeLock();
    this._renderCooking();
  }

  _cookSteps() {
    const steps = this._cook.r.steps || [];
    return steps.length ? steps : ["Für dieses Rezept sind keine Schritte hinterlegt. Guten Appetit! 😋"];
  }

  _renderCooking() {
    const cook = this._cook;
    if (!cook) return;
    const { r, step } = cook;
    const steps = this._cookSteps();
    const text = steps[step];
    const suggestions = findTimers(text);
    const last = step === steps.length - 1;
    const root = this._cookRoot.firstElementChild;
    root.innerHTML = `
      <div class="cook-head">
        <button class="icon" data-cook="close" title="Kochmodus beenden">✕</button>
        <div class="t">👩‍🍳 ${esc(r.name)}</div>
        <span class="meta">👥 ${r.servings}</span>
        <button class="btn small cook-ing-toggle" data-cook="ing">🧾 Zutaten</button>
      </div>
      <div class="cook-main">
        <aside class="card cook-ing ${cook.ingOpen ? "open" : ""}">
          <h4>Zutaten <span class="meta">(${(r.ingredient_lines || []).length})</span></h4>
          ${(r.ingredient_lines || []).map((l, i) => `<label class="${cook.checked.has(i) ? "done" : ""}"><input type="checkbox" data-ing="${i}" ${cook.checked.has(i) ? "checked" : ""}><span>${esc(l)}</span></label>`).join("") || '<div class="hint">Keine Zutaten hinterlegt.</div>'}
        </aside>
        <section class="cook-step">
          <div class="n">Schritt ${step + 1} von ${steps.length}</div>
          <div class="txt">${esc(text)}</div>
          ${suggestions.length ? `<div class="tsugg">${suggestions.map((t) => `<button class="btn big" data-timer="${t.seconds}" data-label="${esc(t.label)}">⏱ ${esc(t.label)} – Timer starten</button>`).join("")}</div>` : ""}
        </section>
      </div>
      <div class="cook-timers"></div>
      <div class="cook-foot">
        <button class="btn big" data-cook="prev" ${step === 0 ? "disabled" : ""}>◀ Zurück</button>
        <div class="dots">${steps.map((_, i) => `<button class="${i === step ? "on" : i < step ? "past" : ""}" data-goto="${i}" title="Schritt ${i + 1}"></button>`).join("")}</div>
        ${last ? `<button class="btn big primary" data-cook="finish">✅ Fertig</button>` : `<button class="btn big primary" data-cook="next">Weiter ▶</button>`}
      </div>`;
    this._renderTimers();
  }

  _renderTimers() {
    const box = this._cookRoot.querySelector(".cook-timers");
    if (!box || !this._cook) return;
    box.innerHTML = this._cook.timers
      .map((t) => {
        const left = (t.end - Date.now()) / 1000;
        return `<div class="timer ${t.done ? "done" : ""}" data-timer-id="${t.id}"><span>⏱ ${esc(t.label)}</span><b>${t.done ? "Fertig!" : formatClock(left)}</b><button class="icon" data-cancel="${t.id}" title="Timer beenden">✕</button></div>`;
      })
      .join("");
  }

  _tickTimers() {
    if (!this._cook) return;
    let changed = false;
    for (const t of this._cook.timers) {
      if (!t.done && t.end <= Date.now()) {
        t.done = true;
        changed = true;
        beep();
        this._toast(`⏰ Timer „${t.label}“ ist abgelaufen!`);
      }
    }
    if (changed) return this._renderTimers();
    this._cookRoot.querySelectorAll("[data-timer-id]").forEach((el) => {
      const t = this._cook.timers.find((x) => String(x.id) === el.dataset.timerId);
      if (t && !t.done) el.querySelector("b").textContent = formatClock((t.end - Date.now()) / 1000);
    });
  }

  _cookGo(delta) {
    if (!this._cook) return;
    const steps = this._cookSteps();
    const next = Math.max(0, Math.min(steps.length - 1, this._cook.step + delta));
    if (next !== this._cook.step) {
      this._cook.step = next;
      this._renderCooking();
    }
  }

  async _cookClick(ev) {
    const t = ev.target.closest("button");
    if (!t || !this._cook) return;
    if (t.dataset.goto != null) {
      this._cook.step = Number(t.dataset.goto);
      return this._renderCooking();
    }
    if (t.dataset.timer) {
      this._cook.timers.push({ id: this._cook.nextTimerId++, label: t.dataset.label, end: Date.now() + Number(t.dataset.timer) * 1000, done: false });
      return this._renderTimers();
    }
    if (t.dataset.cancel) {
      this._cook.timers = this._cook.timers.filter((x) => String(x.id) !== t.dataset.cancel);
      return this._renderTimers();
    }
    switch (t.dataset.cook) {
      case "close":
        this._closeCooking();
        break;
      case "prev":
        this._cookGo(-1);
        break;
      case "next":
        this._cookGo(1);
        break;
      case "ing":
        this._cook.ingOpen = !this._cook.ingOpen;
        this._cookRoot.querySelector(".cook-ing").classList.toggle("open", this._cook.ingOpen);
        break;
      case "finish": {
        const { r, ctx } = this._cook;
        try {
          await this._service("mark_cooked", ctx ? { date: ctx.date, meal: ctx.meal } : { recipe: r.id });
        } catch (e) {
          /* toast already shown */
        }
        this._closeCooking(true);
        this._toast(`Guten Appetit! 😋 ${r.name} ist als gekocht vermerkt.`);
        break;
      }
      default:
        break;
    }
  }

  _closeCooking(force = false) {
    if (!this._cook) return;
    const running = this._cook.timers.some((t) => !t.done);
    if (!force && running && !confirm("Es laufen noch Timer. Kochmodus trotzdem beenden?")) return;
    clearInterval(this._cookInterval);
    this._releaseWakeLock();
    this._cookRoot.innerHTML = "";
    this._cook = null;
  }
}

if (!customElements.get("essensplaner-panel")) {
  customElements.define("essensplaner-panel", EssensplanerPanel);
}
