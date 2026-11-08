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
  product: "📦 Artikel",
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

/* 1.5: product database ("📦 Artikel"), "Produkt wechseln", leaflets of all branches */
const PRODUCT_SORTS = { price: "Preis", unit_price: "Grundpreis", saving: "Ersparnis", name: "Name", recent: "Zuletzt gesehen" };
const PRODUCT_ONLY = [
  ["favorites", "⭐ Favoriten"],
  ["offers", "🏷️ Angebote"],
  ["bought", "🧾 Gekauft"],
  ["manual", "✍️ Eigene"],
  ["unsorted", "❓ Unsortiert"],
];
const PRODUCT_PAGE = 60;
// 1.5.1: kinds and aisles a product can be sorted into ("🗂️ Einordnung", AI sorting)
const PRODUCT_KIND_LABELS = { food: "🍽️ Lebensmittel", drinks: "🥤 Getränk", drugstore: "🧴 Drogerie", household: "🧽 Haushalt", nonfood: "📦 Non-Food (kein Lebensmittel)" };
const CHECKED_LABELS = { rule: "nach Regeln eingeordnet", ai: "🤖 von der KI geprüft", user: "✋ von dir eingeordnet" };
const DAY_SHORT = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
/** "So 03:15" of an ISO time (local). */
const weekdayTime = (iso) => {
  const d = new Date(iso || "");
  return Number.isNaN(d.getTime()) ? "" : `${DAY_SHORT[d.getDay()]} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
const PRODUCT_REASON = {
  manual: "von dir gewählt",
  favorite: "⭐ Lieblingsprodukt",
  picked: "schon mal gewählt",
  bought: "🧾 schon gekauft",
  offer: "",
  cheapest: "💶 günstigstes",
};
const LEAFLET_WHEN = [
  ["current", "Diese Woche"],
  ["upcoming", "Nächste Woche"],
  ["all", "Alle"],
];
const OFFERS_MODES = ["recipes", "stores", "leaflets"];
/** A page of a leaflet ("{page}" counted from page_base). */
const leafletPage = (template, index, base) => (template ? String(template).replace("{page}", String((Number(base) || 0) + index)) : "");

/* 1.5: occasions ("🎉 Anlass"), drinks ("🍷 Passt dazu"), season */
const OCC_COURSES = ["starter", "main", "side", "dessert", "snack", "drink", "extra"];
const DISH_COURSES = new Set(["starter", "main", "side", "dessert", "snack"]);
const COURSE_ADD = { starter: "＋ Vorspeise", main: "＋ Gericht", side: "＋ Beilage", dessert: "＋ Dessert", snack: "＋ Snack", drink: "＋ Getränk", extra: "＋ Zubehör" };
// recipe tags of drinks (occasions.DRINK_TAGS, folded): a drink gets no "🍷 Passt dazu"
const DRINK_TAGS = new Set(["getraenk", "getraenke", "drink", "drinks", "cocktail", "cocktails", "mocktail", "mocktails", "bowle", "punsch", "heissgetraenk"]);
const DRINK_EMOJI = { wine: "🍷", sparkling: "🥂", beer: "🍺", mixed: "🍹", soft: "🥤", juice: "🧃", hot: "☕", water: "💧" };
// the fields of an occasion item a suggestion carries (occasions._ITEM_FIELDS without uid
// and servings: the occasion's servings count)
const OCC_ITEM_FIELDS = ["recipe_id", "product_id", "title", "name", "quantity", "unit", "alcohol", "note", "ai", "auto", "drink", "hint", "reason"];
const AI_WAIT = "bis zu 3 Minuten"; // 1.5.1: menus and the auto plan wait up to 180 s
// a recipe counts as "in season" (🍂 badge, filter) from this score of season.recipe_season
const SEASON_BADGE = 0.25;
const drinkEmoji = (d) => DRINK_EMOJI[d?.kind] || (d?.alcohol ? "🍷" : "🥤");
const isDrinkRecipe = (r) => (r?.kind ? r.kind === "drink" : (r?.tags || []).some((t) => DRINK_TAGS.has(fold(t))));

/* 1.5.1: recipe kinds (kinds.py) and leftovers ("🍲 Reste") */
const KIND_FILTERS = [
  ["meal", "🍽️ Mahlzeiten", ["meal"]],
  ["snack", "🥪 Snacks", ["snack"]],
  ["dessert", "🍰 Desserts", ["dessert"]],
  ["drink", "🥤 Getränke", ["drink"]],
  ["parts", "🧈 Beilagen & Bestandteile", ["side", "component"]],
  ["breakfast", "☕ Frühstück", ["breakfast"]],
];
const KIND_LABELS = { meal: "🍽️ Mahlzeit", breakfast: "☕ Frühstück", snack: "🥪 Snack", dessert: "🍰 Dessert", drink: "🥤 Getränk", side: "🥔 Beilage", component: "🧈 Bestandteil" };
// kinds that fill a meal slot on their own; the others come "Dazu" (extras of a meal)
const SLOT_KINDS = new Set(["meal", "breakfast", "snack"]);
const SLOT_KIND = { fruehstueck: "breakfast", snack: "snack" };
const MEAL_NAMES = { fruehstueck: "Frühstück", mittagessen: "Mittagessen", snack: "Snack", abendessen: "Abendessen" };
const recipeKind = (r) => r?.kind || (isDrinkRecipe(r) ? "drink" : "meal");
/** "🍲 Reste von Dienstag (Lasagne)" for leftovers, else the entry's title. */
const entryTitle = (entry, iso) => {
  const lo = entry?.leftover_of;
  if (!lo?.date) return entry?.title || "";
  const when = lo.date === iso ? `vom ${MEAL_NAMES[lo.meal] || lo.meal}` : `von ${WEEKDAYS[weekdayIndex(fromIso(lo.date))]}`;
  return `🍲 Reste ${when}${entry.title ? ` (${entry.title})` : ""}`;
};
/** "≈ 23 €" in the week plan (cents from below 10 €). */
const euShort = (v) => (Number(v) >= 10 ? `${Math.round(Number(v))} €` : eur(v));
const qtyText = (x) => (x?.quantity ? `${num(Math.round(Number(x.quantity) * 100) / 100)} ${x.unit || ""}`.trim() : "");
const alcBadge = (alcohol, kids = false) => `<span class="alcb ${alcohol ? "" : "free"}">${alcohol ? "mit Alkohol" : kids ? "alkoholfrei · für Kinder" : "alkoholfrei"}</span>`;
/** An occasion item from a suggestion of occasion_suggest (dishes, drinks, extras, AI –
 *  1.5.1: with the AI's servings). */
const occItem = (s, course) => {
  const raw = { course: s.course || course };
  for (const k of OCC_ITEM_FIELDS) if (s[k] != null && s[k] !== "") raw[k] = s[k];
  if (s.ai && s.servings_ai) raw.servings = s.servings_ai;
  return raw;
};
/** 1.5.1: the steps of the amount steppers (l and kg in halves, g in 50, ml in 250, else 1). */
const amtStep = (unit) => (unit === "l" || unit === "kg" ? 0.5 : unit === "g" ? 50 : unit === "ml" ? 250 : 1);
const OCC_UNITS = ["l", "ml", "kg", "g", "Stück", "Pck.", "Tüte", "Flasche", "Dose", "Kiste", "Glas", "Bund"];
/** An occasion item from a drink of drinks_suggest (like occasions.drink_item). */
const drinkItem = (d) => {
  const item = { course: "drink", title: d.title, alcohol: Boolean(d.alcohol) };
  if (d.name && d.name !== d.title) item.name = d.name;
  if (d.recipe_id) item.recipe_id = d.recipe_id;
  else if (d.quantity) {
    item.quantity = d.quantity;
    item.unit = d.unit || "l";
  }
  if (d.id) {
    item.drink = d.id;
    item.auto = "drink";
  }
  if (d.hint) item.hint = d.hint;
  if (d.ai) item.ai = true;
  return item;
};

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
  edeka_offers: ["EDEKA-Angebote", "Einmal am Tag die Prospekt-Angebote deines EDEKA-Markts von www.edeka.de (nur die Markt-ID wird gesendet). Inoffizielle Schnittstelle; lehnt EDEKA ab, wird 7 Tage pausiert. Braucht eine EDEKA-Filiale mit Markt-ID. Die Nutzungsbedingungen von edeka.de untersagen das automatische Auslesen ohne Zustimmung – Nutzung auf eigenes Risiko, nur privat."],
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
  ai_features: ["KI nutzen für", "Ohne Haken arbeitet die Funktion nur nach Regeln. Mit Haken gibt es die Knöpfe „🤖 KI-Menü“ im Anlass, „🤖 KI-Vorschläge“ bei den Getränken, „🤖 mit KI“ beim automatischen Planen sowie „🤖 Artikel sortieren“ und „🤖 Rezepte sortieren“ – die KI wird nur gefragt, wenn du sie drückst; nur das Sortieren prüft zusätzlich jeden Sonntag gegen 3 Uhr, was neu dazugekommen ist."],
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
  .progress { height: 6px; border-radius: 999px; background: var(--ep-divider); overflow: hidden; min-width: 90px; flex: 0 1 120px; }
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
  .chip.kind { background: transparent; border: 1px solid var(--ep-divider); cursor: default; }
  .kindrow { margin-bottom: 0; }
  .meal.leftover .t { font-style: italic; }
  .picklist.dazu { max-height: 190px; }
  .pick.part.sel::after { content: "✓"; margin-left: 6px; color: var(--ep-primary); font-weight: 600; }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr 90px; gap: 10px; }
  @media (max-width: 600px) { .grid3 { grid-template-columns: 1fr 1fr; } }
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
  /* 1.5: pictures with placeholders, "📦 Artikel", "Produkt wechseln", leaflets */
  .imgph { display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; line-height: 1; }
  .products { max-width: 1440px; margin: 0 auto; }
  .prfilter .chip { display: inline-flex; align-items: center; gap: 5px; font-size: 13px; padding: 7px 12px; min-height: 38px; }
  .prfilter .chip .n, .prcats .chip .n { font-size: 11px; opacity: .8; }
  .prfilter .seg { margin-left: auto; }
  .prcats { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: thin; padding-bottom: 4px; margin-bottom: 10px; }
  .prcats:empty { display: none; }
  .prcats .chip { flex: none; display: inline-flex; align-items: center; gap: 4px; font-size: 13px; padding: 6px 11px; min-height: 36px; }
  .prcount { margin-bottom: 8px; }
  .praisort { margin: 2px 0 8px; }
  .praisort:empty { display: none; }
  .prcard { position: relative; }
  .prcard .sotop { cursor: pointer; padding-right: 46px; border-radius: var(--ep-radius) var(--ep-radius) 0 0; }
  .prcard .sotop:hover .pname { text-decoration: underline; }
  .prcard .sotop:focus-visible { outline: 2px solid var(--ep-primary); outline-offset: -2px; }
  .soffer .soimg .imgph { font-size: 30px; }
  .sofav { position: absolute; top: 4px; right: 4px; width: 40px; height: 40px; font-size: 21px; color: var(--ep-secondary-text); }
  .sofav.on { color: #f4b400; }
  /* shopping list: picture and product */
  .ithumb { flex: none; width: 40px; height: 40px; padding: 0; border-radius: 9px; border: 1px solid var(--ep-divider); background: #fff; color: #212121; display: inline-flex; align-items: center; justify-content: center; overflow: hidden; font-size: 21px; font-family: inherit; cursor: pointer; }
  .ithumb:has(.imgph) { background: var(--ep-accent-bg); color: var(--primary-text-color); }
  span.ithumb { cursor: default; }
  .ithumb img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .ithumb:hover { border-color: var(--ep-primary); }
  .item.done .ithumb { opacity: .5; }
  .pline { font-size: 12.5px; color: var(--ep-secondary-text); overflow-wrap: anywhere; line-height: 1.35; }
  .pline[data-swap] { cursor: pointer; }
  .pline[data-swap]:hover { color: var(--primary-text-color); text-decoration: underline; }
  .pline b { color: var(--primary-text-color); font-weight: 600; font-size: 11.5px; text-transform: uppercase; letter-spacing: .03em; }
  .pline .pwhy { white-space: nowrap; }
  /* suggestions and product rows: picture, store chip */
  .sthumb { flex: none; width: 40px; height: 40px; border-radius: 8px; border: 1px solid var(--ep-divider); background: #fff; color: #212121; display: inline-flex; align-items: center; justify-content: center; overflow: hidden; font-size: 20px; }
  .sthumb:has(.imgph) { background: var(--ep-accent-bg); color: var(--primary-text-color); }
  .sthumb img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .schip { display: inline-flex; align-items: center; gap: 4px; font-weight: 500; color: var(--primary-text-color); vertical-align: middle; }
  .schip.est { font-weight: 400; color: var(--ep-secondary-text); }
  .swaprow .pi b { font-weight: 600; }
  .pbrand { font-size: 11.5px; text-transform: uppercase; letter-spacing: .03em; color: var(--ep-secondary-text); }
  .swaprow .pp .meta, .pick .pp .meta { display: block; font-size: 11.5px; }
  .favbox:empty { display: none; }
  /* product details and form */
  .prhero { display: flex; gap: 14px; align-items: flex-start; }
  .prbig { width: 128px; height: 128px; flex: none; border-radius: 12px; background: #fff; color: #212121; border: 1px solid var(--ep-divider); overflow: hidden; display: flex; align-items: center; justify-content: center; font-size: 52px; }
  .prbig:has(.imgph) { background: var(--ep-accent-bg); }
  .prbig img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .prinfo { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .prinfo .brand { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--ep-secondary-text); }
  .prinfo .pname { font-size: 18px; font-weight: 600; line-height: 1.25; overflow-wrap: anywhere; }
  .prprice { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 8px; }
  .prprice .pr { font-size: 24px; font-weight: 700; color: var(--ep-red); }
  .prprice .old { text-decoration: line-through; color: var(--ep-secondary-text); }
  .prprice .disc { background: #c62828; color: #fff; font-size: 11px; font-weight: 700; border-radius: 6px; padding: 1px 6px; }
  .prprice .up { font-size: 12.5px; color: var(--ep-secondary-text); }
  .favkeys { display: flex; flex-wrap: wrap; gap: 6px; }
  .favkeys .chip { font-size: 13.5px; padding: 7px 12px; min-height: 40px; display: inline-flex; align-items: center; gap: 4px; }
  .spark { width: 100%; max-width: 460px; height: auto; display: block; }
  .spark .ln { fill: none; stroke: var(--ep-primary); stroke-width: 2; stroke-linejoin: round; }
  .spark circle.r { fill: var(--ep-primary); }
  .spark circle.o { fill: #ef6c00; }
  .sparklegend { display: flex; flex-wrap: wrap; gap: 4px 14px; }
  .sparklegend .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; background: var(--ep-primary); vertical-align: 0; }
  .sparklegend .dot.o { background: #ef6c00; margin-left: 6px; }
  .pfhead { display: flex; gap: 12px; align-items: flex-start; }
  .pfhead .prbig { width: 96px; height: 96px; font-size: 40px; }
  .pfmain { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
  .pfmain input, .modal .grid2 input, .modal .grid2 select { width: 100%; min-width: 0; }
  .modal .ferr { font-size: 13px; color: var(--ep-red); font-weight: 500; }
  /* leaflets */
  .lftools .chip { font-size: 13px; padding: 6px 12px; min-height: 36px; }
  .lftiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
  .lfstore { display: inline-flex; align-items: center; gap: 5px; min-width: 0; }
  .lfname { font-size: 13px; overflow-wrap: anywhere; }
  .lftile.link .lfcover { aspect-ratio: auto; height: 96px; flex-direction: row; gap: 10px; font-size: 34px; }
  .lftile.link .lfcover .rdot { width: 44px; height: 44px; border-radius: 12px; font-size: 16px; }
  .lflinks { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; margin-top: 14px; }
  .lflinks .btn { gap: 5px; }
  .lftile { position: relative; display: flex; flex-direction: column; min-width: 0; padding: 0; text-align: left; border: var(--ha-card-border-width, 0) solid var(--ep-divider); background: var(--ep-card); color: var(--primary-text-color); font: inherit; border-radius: var(--ep-radius); box-shadow: var(--ep-shadow); overflow: hidden; cursor: pointer; text-decoration: none; transition: box-shadow .15s, transform .15s; }
  .lftile:hover { box-shadow: 0 6px 18px rgba(0,0,0,.18); transform: translateY(-1px); }
  .lfcover { aspect-ratio: 3 / 4; background: var(--ep-accent-bg); display: flex; flex-direction: column; gap: 6px; align-items: center; justify-content: center; font-size: 40px; overflow: hidden; }
  .lfcover img { width: 100%; height: 100%; object-fit: cover; object-position: top; display: block; }
  .lfcover .meta { font-size: 13px; }
  .lfinfo { padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .lfinfo b { font-size: 14px; overflow-wrap: anywhere; min-width: 0; }
  .lftile .lfnext { position: absolute; top: 8px; left: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.2); background: color-mix(in srgb, #2e7d32 22%, var(--ep-card)); }
  .lftile .lfext { position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,.55); color: #fff; border-radius: 999px; padding: 1px 8px; font-size: 13px; }
  .lfoverlay { position: fixed; inset: 0; z-index: 10; background: #121212; color: #fff; display: flex; flex-direction: column; animation: fade .12s ease-out; }
  .lfvhead { display: flex; align-items: center; gap: 6px; padding: 6px 8px 6px 14px; padding-top: calc(6px + env(safe-area-inset-top)); background: #000; min-width: 0; }
  .lfvtitle { flex: 1; min-width: 0; display: flex; gap: 8px; align-items: center; }
  .lfvtitle span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .lfvpos { font-variant-numeric: tabular-nums; font-size: 14px; white-space: nowrap; padding: 0 4px; }
  .lfvhead .icon { color: #fff; width: 44px; height: 44px; flex: none; }
  .lfvhead .icon:hover, .lfvhead .icon[aria-pressed="true"] { background: rgba(255,255,255,.18); }
  .lfvhead .btn { background: rgba(255,255,255,.12); color: #fff; border-color: rgba(255,255,255,.35); flex: none; min-height: 40px; }
  .lfvpages { flex: 1; min-height: 0; display: flex; overflow-x: auto; overflow-y: hidden; scroll-snap-type: x mandatory; scrollbar-width: none; overscroll-behavior: contain; outline: none; touch-action: manipulation; }
  .lfvpages::-webkit-scrollbar { display: none; }
  .lfpage { flex: 0 0 100%; width: 100%; height: 100%; scroll-snap-align: center; scroll-snap-stop: always; display: flex; align-items: center; justify-content: center; overflow: hidden; padding: 8px; }
  .lfpage img { max-width: 100%; max-height: 100%; object-fit: contain; background: #fff; box-shadow: 0 4px 18px rgba(0,0,0,.5); user-select: none; -webkit-user-drag: none; cursor: zoom-in; }
  .lfpage img:not([src]) { width: 60%; height: 80%; background: #222; box-shadow: none; }
  .lfpage .imgph { font-size: 56px; color: #aaa; }
  .lfpage.zoom { overflow: auto; align-items: flex-start; justify-content: flex-start; }
  .lfpage.zoom img { max-width: none; max-height: none; width: 200%; height: auto; cursor: zoom-out; }
  .lfvpages.zooming { overflow-x: hidden; scroll-snap-type: none; }
  .lfnav { position: absolute; top: 50%; transform: translateY(-50%); width: 48px; height: 72px; border: none; border-radius: 12px; background: rgba(0,0,0,.5); color: #fff; font-size: 36px; line-height: 1; cursor: pointer; z-index: 1; }
  .lfnav:hover { background: rgba(0,0,0,.75); }
  .lfnav.prev { left: 8px; }
  .lfnav.next { right: 8px; }
  .lfvfoot { display: flex; gap: 12px; align-items: center; padding: 4px 14px; padding-bottom: calc(4px + env(safe-area-inset-bottom)); background: #000; min-width: 0; }
  .lfvfoot .lfslider { flex: 1 1 auto; min-width: 0; min-height: 40px; accent-color: #fff; background: transparent; border: none; padding: 0; }
  .lfvfoot .meta { color: #bbb; flex: 0 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 45%; }
  @media (max-width: 600px) {
    .ithumb { width: 40px; height: 40px; font-size: 19px; }
    .prfilter { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: thin; padding-bottom: 4px; }
    .prfilter > * { flex: none; }
    .prfilter .seg { margin-left: 0; }
    .somode button { padding-left: 6px; padding-right: 6px; font-size: 13px; }
    .lftiles { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .prbig { width: 96px; height: 96px; font-size: 40px; }
    .lfvfoot .meta { display: none; }
    .lfvtitle .rdot { display: none; }
  }
  @media (pointer: coarse) {
    .lfnav { display: none; }
    .prcats .chip, .prfilter .chip, .lftools .chip { min-height: 40px; }
  }
  /* 1.5: occasions in the week plan and their editor, season, drinks */
  .occ { width: 100%; text-align: left; border: none; cursor: pointer; font: inherit; color: inherit; display: flex; gap: 9px; align-items: center; padding: 8px 9px; border-radius: 9px; background: color-mix(in srgb, #8e24aa 13%, var(--ep-card)); border-left: 4px solid #8e24aa; transition: box-shadow .15s; }
  .occ:hover { box-shadow: 0 2px 8px rgba(0,0,0,.12); }
  .occ .oemoji { width: 38px; height: 38px; flex: none; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 22px; background: var(--ep-card); }
  .occ .otxt { min-width: 0; }
  .occ .t { font-weight: 600; line-height: 1.2; font-size: 14px; overflow-wrap: anywhere; }
  .occ .s { font-size: 11.5px; color: color-mix(in srgb, var(--ep-secondary-text) 70%, var(--primary-text-color, #212121)); margin-top: 2px; }
  .seasonrow { display: flex; gap: 12px; align-items: center; padding: 10px 14px; margin: -4px 0 16px; }
  .seasonrow .semoji { font-size: 26px; flex: none; line-height: 1; }
  .seasonrow .stxt { flex: 1; min-width: 0; font-size: 14px; line-height: 1.55; overflow-wrap: anywhere; }
  .seasonrow .bdg { vertical-align: 1px; }
  .seasonrow .btn { flex: none; }
  .recipe .sbadge { position: absolute; top: 8px; left: 8px; max-width: calc(100% - 56px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: rgba(0,0,0,.6); color: #fff; border-radius: 999px; font-size: 12px; padding: 2px 9px; }
  .suglist { display: flex; flex-direction: column; gap: 6px; }
  .suglist:empty { display: none; }
  .sg { display: flex; gap: 10px; align-items: center; width: 100%; text-align: left; border: 1px solid var(--ep-divider); background: var(--ep-card); color: inherit; font: inherit; border-radius: 10px; padding: 6px 10px; cursor: pointer; min-height: 48px; }
  .sg:hover, .sg.sel { border-color: var(--ep-primary); background: var(--ep-accent-bg); }
  .sg .sgt { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .sg .why, .ocrow .why, .prow .why { font-size: 12px; color: var(--ep-secondary-text); overflow-wrap: anywhere; line-height: 1.35; }
  .sg .pp { text-align: right; white-space: nowrap; flex: none; display: flex; flex-direction: column; align-items: flex-end; gap: 1px; }
  .alcb { display: inline-block; font-size: 10.5px; font-weight: 500; line-height: 1.6; border-radius: 999px; padding: 0 7px; white-space: nowrap; vertical-align: 1px; background: color-mix(in srgb, #8e24aa 14%, transparent); color: color-mix(in srgb, #8e24aa 45%, var(--primary-text-color, #212121)); }
  .alcb.free { background: color-mix(in srgb, #2e7d32 14%, transparent); color: color-mix(in srgb, #2e7d32 45%, var(--primary-text-color, #212121)); }
  /* the occasion editor (full screen on phones) */
  .modal.occmodal { width: min(900px, 100%); }
  @media (max-width: 600px) {
    .overlay.full { padding: 0; }
    .overlay.full .modal { width: 100%; height: 100%; max-height: 100%; border-radius: 0; }
    .overlay.full .modal .mhead { padding-top: calc(12px + env(safe-area-inset-top)); }
    .overlay.full .modal .mfoot { padding-bottom: calc(12px + env(safe-area-inset-bottom)); }
  }
  .ochead { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px 12px; align-items: end; }
  .ochead .oname { grid-column: span 2; }
  .ochead .field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ep-secondary-text); min-width: 0; }
  .ochead input:not([type=checkbox]), .ochead select { width: 100%; min-width: 0; color: var(--primary-text-color); font-size: 15px; }
  .ochead .switch { color: var(--primary-text-color); }
  .stepper2 { display: flex; align-items: center; gap: 4px; }
  .stepper2 input { flex: 1; min-width: 0; text-align: center; }
  .stepper2 .icon { flex: none; border: 1px solid var(--ep-divider); width: 40px; height: 40px; }
  .stepper2 .icon[disabled] { opacity: .35; pointer-events: none; }
  .ocsum { display: flex; flex-wrap: wrap; gap: 4px 14px; align-items: baseline; padding: 10px 12px; border-radius: 12px; background: var(--ep-accent-bg); }
  .ocsum .big { font-size: 20px; font-weight: 700; color: var(--ep-green); }
  .ocmore { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; }
  .ocstate { font-size: 12.5px; color: var(--ep-secondary-text); margin-left: auto; }
  .occourses { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
  .ocsec { border: 1px solid var(--ep-divider); border-radius: 12px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
  .ocsec > h4 { margin: 0; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .ocsec > h4 .meta { font-weight: 400; margin-left: auto; }
  .ocsec.wide { grid-column: 1 / -1; }
  .ocitems { display: flex; flex-wrap: wrap; gap: 6px; }
  .occhip { display: inline-flex; align-items: center; max-width: 100%; min-width: 0; border-radius: 999px; background: var(--ep-accent-bg); font-size: 13.5px; }
  .occhip .on { border: none; background: none; color: inherit; font: inherit; padding: 4px 2px 4px 4px; text-align: left; overflow-wrap: anywhere; min-height: 40px; min-width: 0; display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .occhip button.on { cursor: pointer; }
  .occhip button.on:hover > span:not(.othumb):not(.meta):not(.alcb) { text-decoration: underline; }
  .occhip .meta { font-size: 12px; white-space: nowrap; }
  .occhip .icon { width: 36px; height: 36px; font-size: 13px; flex: none; }
  .occhip.ai { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ep-primary) 50%, transparent); }
  .occhip.missing { opacity: .6; }
  .othumb { width: 30px; height: 30px; border-radius: 50%; background: var(--ep-card) center/cover no-repeat; flex: none; display: inline-flex; align-items: center; justify-content: center; font-size: 16px; }
  .chip.ocplus { border: 1px dashed var(--ep-divider); background: transparent; font-size: 13px; padding: 6px 11px; min-height: 36px; }
  .ocadd { border-top: 1px dashed var(--ep-divider); padding-top: 8px; display: flex; flex-direction: column; gap: 8px; }
  .ocadd .addq { display: flex; gap: 6px; align-items: center; }
  .ocadd .addq input { flex: 1; min-width: 0; }
  .extras { display: flex; flex-direction: column; }
  .extras label { display: flex; gap: 10px; align-items: center; padding: 4px 2px; min-height: 40px; border-top: 1px solid var(--ep-divider); cursor: pointer; font-size: 14px; }
  .extras label:first-child { border-top: none; }
  .extras label input { width: 20px; height: 20px; accent-color: var(--ep-primary); flex: none; margin: 0; }
  .extras label > span:not(.meta) { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .extras label .meta { white-space: nowrap; }
  .extras label.missing > span:not(.meta) { color: var(--ep-secondary-text); }
  /* 1.5.1: amounts of the items (servings, packs, quantity + unit) and the AI's reasons */
  .extras .exrow { border-top: 1px solid var(--ep-divider); display: flex; flex-wrap: wrap; align-items: center; column-gap: 8px; }
  .extras .exrow:first-child { border-top: none; }
  .extras .exrow label { border-top: none; flex: 1 1 180px; }
  .extras .exrow .ocr2 { padding: 0 0 6px 30px; }
  .extras label .why, .occhip .why { display: block; font-size: 11.5px; color: var(--ep-secondary-text); line-height: 1.3; overflow-wrap: anywhere; }
  .occhip { flex-direction: column; align-items: stretch; border-radius: 14px; }
  .occhip.sel { box-shadow: inset 0 0 0 2px var(--ep-primary); }
  .occhip .ocr1 { display: flex; align-items: center; min-width: 0; }
  .occhip .ocr1 .on { flex: 1; }
  .occhip .ocr2 { display: flex; align-items: center; gap: 4px; padding: 0 6px 6px 8px; flex-wrap: wrap; }
  .occhip > .why { padding: 0 10px 6px; }
  .ocamt { display: inline-flex; align-items: center; gap: 3px; }
  .ocamt .u { font-size: 12px; color: var(--ep-secondary-text); padding: 0 2px; }
  .ocamt input { width: 62px; text-align: center; padding: 4px 2px; height: 32px; box-sizing: border-box; }
  .ocamt select { height: 32px; padding: 2px 4px; width: auto; max-width: 84px; box-sizing: border-box; }
  .occhip .ocamt .icon, .exrow .ocamt .icon, .occhip .prodbtn, .exrow .prodbtn { width: 32px; height: 32px; border: 1px solid var(--ep-divider); border-radius: 8px; background: var(--ep-card); font-size: 15px; }
  .prodbtn.on { border-color: var(--ep-primary); }
  .ocprod .suglist { max-height: 340px; overflow-y: auto; }
  .ocprod .suglist > * { flex: none; }
  .ocmenu { border: 1px solid var(--ep-primary); border-radius: 12px; padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; background: color-mix(in srgb, var(--ep-primary) 5%, var(--ep-card)); }
  .ocmenu h4 { margin: 0; }
  .ocmenu .mcs { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 0 18px; }
  .ocmenu .mc { display: flex; flex-direction: column; min-width: 0; }
  .ocmenu .mc > b { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: var(--ep-secondary-text); margin-top: 4px; }
  .ocrow { display: flex; gap: 8px; align-items: center; padding: 4px 0; min-width: 0; border-top: 1px solid var(--ep-divider); }
  .mc > b + .ocrow { border-top: none; }
  .ocrow .oi { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .ocrow .meta { white-space: nowrap; }
  .ocrow .btn { flex: none; }
  .spin { display: inline-block; animation: spin 1.2s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  details.ocnotes > summary { cursor: pointer; min-height: 40px; display: flex; align-items: center; font-weight: 500; }
  details.ocnotes textarea { min-height: 70px; }
  .tplgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 8px; }
  .tplgrid button { border: 1px solid var(--ep-divider); background: var(--ep-card); color: inherit; font: inherit; font-size: 13.5px; border-radius: 12px; padding: 8px 6px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 3px; text-align: center; min-height: 78px; overflow-wrap: anywhere; }
  .tplgrid button .e { font-size: 26px; line-height: 1.1; }
  .tplgrid button .meta { font-size: 11.5px; }
  .tplgrid button.on { border-color: var(--ep-primary); background: var(--ep-accent-bg); box-shadow: inset 0 0 0 1px var(--ep-primary); }
  /* drinks ("🍷 Passt dazu", meal entry) */
  .dchips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  .dchips .chip { font-size: 13px; padding: 6px 12px; min-height: 36px; display: inline-flex; align-items: center; gap: 5px; }
  .dchips .chip.alc { background: color-mix(in srgb, #8e24aa 12%, transparent); }
  .dchips .chip.on { box-shadow: inset 0 0 0 2px var(--ep-primary); }
  .dchip-x { display: inline-flex; align-items: center; gap: 2px; border-radius: 999px; background: var(--ep-accent-bg); padding-left: 11px; font-size: 13.5px; }
  .dchip-x .icon { width: 34px; height: 34px; font-size: 13px; }
  .dinfo { font-size: 13.5px; line-height: 1.45; display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; border-radius: 10px; background: var(--ep-accent-bg); }
  .dinfo .row { margin: 0; }
  /* auto plan results */
  .plist { display: flex; flex-direction: column; border: 1px solid var(--ep-divider); border-radius: 10px; overflow: hidden; }
  .prow { display: flex; gap: 12px; padding: 8px 12px; border-top: 1px solid var(--ep-divider); align-items: flex-start; }
  .prow:first-child { border-top: none; }
  .prow .pd { flex: none; width: 84px; font-weight: 600; font-size: 13.5px; }
  .prow .pd .meta { font-weight: 400; }
  .prow .pi { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .prow .pa { flex: none; display: flex; gap: 4px; align-items: center; }
  .prow.busy { opacity: 0.6; }
  label.switch.aiswitch { align-items: flex-start; padding: 8px 10px; border: 1px solid var(--ep-divider); border-radius: 10px; line-height: 1.4; }
  label.switch.aiswitch input { margin-top: 1px; flex: none; }
  /* season view */
  .seasonhead { display: flex; align-items: center; gap: 8px; justify-content: center; font-size: 16px; }
  .seasonhead b { min-width: 0; text-align: center; }
  .prodchips { display: flex; flex-wrap: wrap; gap: 6px; }
  .prodchips .bdg { font-size: 13px; padding: 4px 11px; }
  .srecipes { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 6px; }
  @media (max-width: 600px) {
    .seasonrow { flex-wrap: wrap; padding: 10px 12px; }
    .seasonrow .btn { margin-left: auto; }
    .occourses { grid-template-columns: 1fr; }
    .ochead { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .ochead .oname { grid-column: 1 / -1; }
    .tplgrid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .prow .pd { width: 70px; }
  }
  @media (pointer: coarse) {
    .dchips .chip, .chip.ocplus { min-height: 40px; }
    .occhip .icon, .dchip-x .icon { width: 40px; height: 40px; }
    .occhip .ocamt .icon, .exrow .ocamt .icon, .occhip .prodbtn, .exrow .prodbtn { width: 40px; height: 40px; }
    .ocamt input, .ocamt select { height: 40px; }
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
    .pick { min-height: 44px; }
    .starbtn { min-width: 40px; min-height: 40px; }
  }
  /* 1.5.1: compact phone layout – desktop keeps its layout (the wrappers are "contents") */
  .tab .ts { display: none; }
  .tab .ti { line-height: 1; }
  .addchips { display: none; }
  .weekacts, .shopacts, .offchips, .offacts { display: contents; }
  .srclines { display: flex; flex-direction: column; gap: 2px; margin: 0 0 4px; }
  .bars { margin: 6px 0 18px; }
  .budgetcard .bsave { grid-column: 2; }
  .recipe { position: relative; }
  .recipe .img { overflow: hidden; }
  .recipe .img > img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
  /* a small picture is shown whole on a neutral background instead of blown up */
  .recipe .img > img.lowres { object-fit: scale-down; padding: 6px; }
  .recipe .img:has(> img.lowres) { background: color-mix(in srgb, var(--ep-secondary-text) 12%, var(--ep-card)); }
  .recipe .img .sbadge { z-index: 1; }
  .soffer .sostore .sn { min-width: 0; }
  @media (max-width: 600px) {
    main { padding: 10px; }
    .meta, .hint { font-size: 13px; }
    button.chip { font-size: 13px; padding: 4px 12px; }
    .row { gap: 6px; margin-bottom: 10px; }
    /* tabs: icon over a short label – all six fit, nothing is cut off */
    .tabs { padding: 0 2px; gap: 0; }
    .tab { flex: 1 1 0; min-width: 0; flex-direction: column; gap: 2px; padding: 7px 2px 5px; font-size: 12px; letter-spacing: 0; position: relative; }
    .tab .ti { font-size: 19px; }
    .tab .tl { display: none; }
    .tab .ts { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
    .tab .count { position: absolute; top: 2px; left: calc(50% + 7px); font-size: 10px; line-height: 15px; padding: 0 5px; }
    /* week plan: compact hero, filled meals as cards, empty meals as one row of chips */
    .hero { flex-wrap: nowrap; align-items: flex-start; gap: 12px; padding: 12px; min-height: 0; margin-bottom: 10px; }
    .hero > div:not(.bigemoji):not(.side) { flex: 1; min-width: 0; }
    .hero .bigemoji { font-size: 34px; width: 40px; flex: none; text-align: center; margin-top: 2px; }
    .hero .kicker { font-size: 11.5px; letter-spacing: .05em; }
    .hero .htitle { font-size: 18px; margin: 2px 0 4px; overflow-wrap: anywhere; }
    .hero .hmeta { font-size: 13.5px; }
    .hero .hactions { margin-top: 8px; gap: 6px; }
    .hero:not(.img) .hactions { margin-left: -52px; }
    .hero .hactions .btn { padding: 6px 12px; }
    .seasonrow { margin: 0 0 10px; gap: 10px; }
    .seasonrow .semoji { font-size: 22px; }
    .seasonrow .stxt { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.45; }
    .weekacts { display: flex; gap: 6px; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; width: 100%; padding-bottom: 2px; }
    .weekacts::-webkit-scrollbar { display: none; }
    .weekacts .btn { flex: none; }
    .weekacts .primary { order: -1; }
    .week { grid-template-columns: 1fr; gap: 8px; }
    .day { padding: 10px 12px; gap: 6px; }
    .slot.vacant { display: none; }
    .slot .label { margin: 0 0 3px; }
    .meal, .occ { padding: 6px 8px; gap: 8px; }
    .meal .thumb, .occ .oemoji { width: 34px; height: 34px; font-size: 20px; }
    .meal .t, .occ .t { font-size: 14.5px; }
    .meal .s, .occ .s { font-size: 12.5px; }
    .addchips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip.addchip { min-height: 40px; display: inline-flex; align-items: center; padding: 4px 12px; font-size: 13px; background: transparent; color: var(--primary-text-color); border: 1px dashed color-mix(in srgb, var(--meal-color) 60%, var(--ep-divider)); }
    .chip.addchip.over { border-style: solid; background: var(--ep-accent-bg); }
    .dndtip { display: none; }
    /* recipes: a list with a thumbnail */
    .recfind input[type=search] { flex: 1 1 100% !important; }
    .recfind select { flex: 1 1 0; min-width: 0; }
    .recacts, .kindrow { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
    .recacts::-webkit-scrollbar { display: none; }
    .recacts > * { flex: none; }
    .recacts .spacer { display: none; }
    .recipes { grid-template-columns: 1fr; gap: 8px; }
    .recipe { flex-direction: row; align-items: flex-start; }
    .recipe:hover { transform: none; }
    .recipe .img { width: 72px; height: 72px; flex: none; margin: 10px 0 10px 10px; border-radius: 10px; font-size: 36px; }
    .recipe .img > img.lowres { padding: 3px; }
    .recipe .sbadge { top: auto; left: 3px; bottom: 3px; max-width: none; padding: 0 4px; font-size: 12px; line-height: 1.5; }
    .recipe .sbadge .sbt { display: none; }
    .recipe .fav { top: 2px; right: 2px; width: 40px; height: 40px; background: none; color: var(--ep-secondary-text); font-size: 19px; }
    .recipe .fav.on { color: #f4b400; }
    .recipe .body { padding: 9px 40px 10px 12px; gap: 4px; min-width: 0; }
    .recipe .name { font-size: 15px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .recipe .chips { flex-wrap: nowrap; overflow: hidden; }
    .recipe .chips .chip { flex: none; font-size: 12px; padding: 1px 8px; }
    .recipe .chips .chip:nth-child(n+4) { display: none; }
    /* shopping list: the add field and the view switch, the other actions as a chip row */
    .shopstat { padding: 10px 12px; gap: 10px; margin-bottom: 10px; }
    .shopstat .num { font-size: 22px; }
    .shopstat .sdone { white-space: nowrap; }
    .shopstat .spct { display: none; }
    .shoptools { flex-direction: column; align-items: stretch; flex-wrap: nowrap; }
    .shopacts, .offchips, .offacts, .weekacts { max-width: 100%; min-width: 0; }
    .shoptools .seg { align-self: flex-start; }
    .shopacts { display: flex; gap: 6px; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
    .shopacts::-webkit-scrollbar { display: none; }
    .shopacts .btn { flex: none; font-size: 13.5px; }
    .shopacts .spacer { display: none; }
    .storehead { padding: 10px 12px 8px; }
    .group h3 { padding: 8px 12px 6px; }
    .aisle { padding: 6px 12px 2px; }
    .item { gap: 8px; padding: 4px 2px 4px 12px; }
    .item .sum { font-size: 15px; line-height: 1.25; }
    .item .icon { width: 34px; }
    .item .price { font-size: 13px; }
    .pline, .item .desc { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12.5px; }
    .item .desc .lomore { display: none; }
    /* articles and offers of the stores: compact rows (picture, text, price; ⭐ ➕ on the right) */
    .soffers { grid-template-columns: 1fr; gap: 8px; }
    .soffer { display: grid; grid-template-columns: minmax(0, 1fr) 40px; column-gap: 6px; padding: 8px 6px 8px 10px; position: relative; }
    .soffer .sotop, .prcard .sotop { grid-column: 1; grid-row: 1; padding: 0; gap: 10px; }
    .soffer .soimg { width: 56px; height: 56px; font-size: 26px; border-radius: 9px; }
    .soffer .soimg .imgph { font-size: 26px; }
    .soffer .brand { font-size: 11px; }
    .soffer .pname { font-size: 14.5px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .soffer .pack { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .soffer .soprice, .soffer .someta { grid-column: 1; padding: 2px 0 0 66px; }
    .soffer .soprice { grid-row: 2; }
    .soffer .pr { font-size: 17px; }
    .soffer .someta { grid-row: 3; flex-wrap: nowrap; overflow: hidden; }
    .soffer .someta > .bdg { flex: none; }
    .soffer .sostore { flex: 0 1 auto; min-width: 0; overflow: hidden; }
    .soffer .sostore .sn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .soffer .acts { grid-column: 2; grid-row: 1 / span 3; flex-direction: column; flex-wrap: nowrap; justify-content: flex-start; padding: 0; margin: 0; gap: 4px; }
    .prcard .acts { justify-content: flex-end; padding-top: 44px; }
    .soffer .acts .btn { flex: none; width: 40px; height: 40px; min-height: 40px; padding: 0; justify-content: center; font-size: 16px; }
    .soffer .albl { display: none; }
    .sofav { top: 6px; right: 6px; }
    /* offers for the recipes: compact budget, scrollable chip rows, folded sources */
    .budgetcard { padding: 10px 12px; gap: 4px 12px; margin-bottom: 10px; }
    .budgetcard .big { font-size: 22px; }
    .budgetcard .bsave { grid-column: 1 / -1; }
    .bars { height: 30px; margin: 4px 0 16px; }
    .offrow { flex-direction: column; align-items: stretch; flex-wrap: nowrap; }
    .offrow > .spacer { display: none; }
    .offchips, .offacts { display: flex; gap: 6px; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
    .offchips::-webkit-scrollbar, .offacts::-webkit-scrollbar { display: none; }
    .offchips > *, .offacts > * { flex: none; }
    .offacts .btn { font-size: 13.5px; }
    .offers { grid-template-columns: minmax(0, 1fr); gap: 8px; }
    .offer { padding: 10px; gap: 10px; min-width: 0; }
    .offer .oimg { width: 56px; height: 56px; font-size: 26px; }
    .offer .chips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
    .offer .chips::-webkit-scrollbar { display: none; }
    .offer .chips > * { flex: none; }
    .sowhen { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
    .sowhen > * { flex: none; }
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
    this._kind = this._pref("kind", "");
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
    // 1.5: "📦 Artikel" tab (the product database, loaded page by page)
    let prStores = [];
    try {
      prStores = JSON.parse(this._pref("products_stores", "[]")) || [];
    } catch (e) {
      prStores = [];
    }
    this._pr = {
      query: "",
      stores: new Set(Array.isArray(prStores) ? prStores : []), // "b:<branch id>" | "r:<retailer>"
      category: "",
      only: "",
      kind: this._pref("products_kind", "all"),
      sort: this._pref("products_sort", "price"),
      result: null,
      products: [],
      loading: false,
      error: null,
      stale: true,
      seq: 0,
    };
    // 1.5: "📰 Prospekte" (Angebote tab)
    this._lf = { when: "current", result: null, loading: false, error: null, stale: true, seq: 0 };
    this._lfView = null; // the open leaflet viewer
    this._badImages = new Set(); // image URLs that failed: shown as placeholder at once
    // 1.5: the open occasion editor, "🍂 Saison" filter of the recipes, "🍷 Passt dazu"
    this._occ = null;
    this._seasonOnly = false;
    this._drinkCache = {};
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
      // 1.5: the product database follows offers, prices, receipts, ⭐ and the list (picks)
      const productsStale = !changes.size || [...changes].some((c) => ["products", "offers", "branches", "price_sources", "prices", "receipts", "shopping", ""].includes(c));
      if (productsStale) this._pr.stale = true;
      if (offersStale) this._lf.stale = true;
      if (changes.has("receipts") || changes.has("prices")) this._receiptsStale = true;
      if (json === this._dataJson && this._data) {
        if (offersStale && this._tab === "offers" && this._offersMode === "stores" && !this._so.loading) this._fetchStoreOffers();
        if (offersStale && this._tab === "offers" && this._offersMode === "leaflets" && !this._lf.loading) this._fetchLeaflets();
        if (productsStale && this._tab === "products" && !this._pr.loading) this._fetchProducts(false, true);
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
      this._drinkCache = {}; // drinks follow offers and the options
      // an open occasion editor shows a change made elsewhere (voice, calendar)
      const occ = this._occ;
      const fresh = occ && !occ.saving && this._occView(occ.id);
      if (fresh && fresh.updated !== occ.view.updated) {
        occ.view = fresh;
        this._occRender(occ);
      }
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

  /** Index of a meal slot by time (leftovers come after their cooking meal). */
  _mealRank(id) {
    const i = this._data.all_meals.findIndex((m) => m.id === id);
    return i < 0 ? 9 : i;
  }

  /** The entries that are the leftovers of a planned meal: [{date, meal, entry}] (1.5.1). */
  _leftoversOf(iso, meal) {
    const found = [];
    const max = this._data.leftover_max_days || 7;
    for (let i = 0; i <= max; i++) {
      const day = toIso(addDays(fromIso(iso), i));
      for (const [m, e] of Object.entries(this._data.plan[day] || {})) {
        if (e.leftover_of?.date === iso && e.leftover_of?.meal === meal) found.push({ date: day, meal: m, entry: e });
      }
    }
    return found;
  }

  /** Planned meals of the previous 3 days (and earlier the same day) whose leftovers fit
   * this slot: [{date, meal, entry}], newest first. */
  _leftoverSources(iso, meal) {
    const found = [];
    for (let i = 0; i <= 3; i++) {
      const day = toIso(addDays(fromIso(iso), -i));
      for (const [m, e] of Object.entries(this._data.plan[day] || {})) {
        if (e.leftover_of || !(e.recipe_id || e.title)) continue;
        if (i === 0 && this._mealRank(m) >= this._mealRank(meal)) continue;
        found.push({ date: day, meal: m, entry: e });
      }
    }
    return found.sort((a, b) => b.date.localeCompare(a.date) || this._mealRank(b.meal) - this._mealRank(a.meal));
  }

  /** "🍲 Die Reste am Mittwoch werden jetzt dort frisch gekocht." after a move / delete. */
  _unlinkedToast(views) {
    if (!views?.length) return;
    const list = views.map((v) => `${this._dateLabel(v.date)} (${v.dish || v.title})`).join(", ");
    this._toast(`🍲 ${list}: keine Reste mehr – wird jetzt dort frisch gekocht.`);
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
          <button class="tab" data-tab="plan"><span class="ti">🗓️</span><span class="tl">Wochenplan</span><span class="ts">Plan</span></button>
          <button class="tab" data-tab="recipes"><span class="ti">📖</span><span class="tl">Rezepte</span><span class="ts">Rezepte</span><span class="count" data-count="recipes"></span></button>
          <button class="tab" data-tab="shopping"><span class="ti">🛒</span><span class="tl">Einkaufsliste</span><span class="ts">Einkauf</span><span class="count" data-count="shopping"></span></button>
          <button class="tab" data-tab="products"><span class="ti">📦</span><span class="tl">Artikel</span><span class="ts">Artikel</span></button>
          <button class="tab" data-tab="offers"><span class="ti">💶</span><span class="tl">Angebote<span class="long"> & Budget</span></span><span class="ts">Angebote</span><span class="count" data-count="offers"></span></button>
          <button class="tab" data-tab="stores"><span class="ti">🏪</span><span class="tl">Läden<span class="long"> & Preise</span></span><span class="ts">Läden</span></button>
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
    // 1.5: a product / leaflet image that cannot be loaded becomes its placeholder (emoji)
    this.shadowRoot.addEventListener("error", (ev) => this._brokenImage(ev.target), true);
    // 1.5.1: a picture smaller than its box is shown whole (contain), not blown up
    this.shadowRoot.addEventListener("load", (ev) => this._imageLoaded(ev.target), true);
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
      if (ev.key === "Enter" && ev.target.dataset.input === "pr-query") {
        ev.preventDefault();
        clearTimeout(this._prTimer);
        this._fetchProducts();
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
      const res = await this._service("move_meal", { from_date: src.date, from_meal: src.meal, to_date: to.date, to_meal: to.meal }, true);
      this._unlinkedToast(res?.leftovers_unlinked);
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
    else if (this._tab === "products") this._content.innerHTML = this._renderProducts();
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
        `<div class="mini"><b>${esc(relativeDay(iso, today).split(",")[0])}</b><span>${main ? esc(entryTitle(main[1], iso)) : '<span class="meta">noch frei</span>'}</span></div>`
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
          <div class="htitle">${esc(entryTitle(up.entry, up.date))}</div>
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
      const emptyIds = [];
      const slots = slotIds
        .map((mealId) => {
          const entry = meals[mealId];
          const color = this._mealColor(mealId);
          let inner;
          if (entry) {
            planned += 1;
            const recipe = this._recipe(entry.recipe_id);
            const drinks = entry.drinks?.length ? `🥤 ${entry.drinks[0].title}${entry.drinks.length > 1 ? ` +${entry.drinks.length - 1}` : ""}` : "";
            // 1.5.1: extras ("＋ Kräuterbutter") and leftovers cooked here ("🍲 +2 für Mi")
            const extras = entry.extras?.length ? `＋ ${entry.extras.map((x) => x.title).join(", ")}` : "";
            const lefts = entry.leftover_of ? [] : this._leftoversOf(iso, mealId);
            const leftText = lefts.length ? `🍲 +${lefts.reduce((n, l) => n + (Number(l.entry.servings) || 0), 0) || lefts.length} für ${lefts.map((l) => WEEKDAYS[weekdayIndex(fromIso(l.date))].slice(0, 2)).join(", ")}` : "";
            const sub = [entry.servings ? `👥 ${entry.servings}` : "", recipe?.total_time && !entry.leftover_of ? `⏱ ${recipe.total_time} min` : "", entry.note || "", extras, leftText, drinks].filter(Boolean).join(" · ");
            const mc = weekCosts?.[iso]?.[mealId];
            const costHtml = mc?.cost != null && !mc.leftover ? `<span class="cost">≈ ${eur(mc.cost)}</span>${mc.on_offer?.length ? `<span class="tagoffer" title="Im Angebot: ${esc(mc.on_offer.join(", "))}">🏷️ ${mc.on_offer.length}</span>` : ""}` : "";
            const thumb = recipe?.image && safeUrl(recipe.image)
              ? `<span class="thumb" ${bg(recipe.image)}></span>`
              : `<span class="thumb">${entry.cooked ? "✅" : recipe ? dishEmoji(recipe.name) : "📝"}</span>`;
            inner = `<button class="meal ${recipe ? "" : "free"} ${entry.cooked ? "cooked" : ""} ${entry.leftover_of ? "leftover" : ""}" draggable="true" data-drag-date="${iso}" data-drag-meal="${mealId}" data-action="open-entry" data-date="${iso}" data-meal="${mealId}" title="Klicken zum Bearbeiten, ziehen zum Verschieben">
                ${thumb}<span><div class="t">${esc(entryTitle(entry, iso))}</div>${sub || costHtml ? `<div class="s">${esc(sub)} ${costHtml}</div>` : ""}</span>
              </button>`;
          } else {
            emptyIds.push(mealId);
            inner = `<button class="add" data-action="add-entry" data-date="${iso}" data-meal="${mealId}">＋ <span>hinzufügen</span></button>`;
          }
          return `<div class="slot ${entry ? "" : "vacant"}" style="--meal-color:${color}" data-drop-date="${iso}" data-drop-meal="${mealId}"><div class="label"><i></i>${esc(this._mealLabel(mealId))}</div>${inner}</div>`;
        })
        .join("");
      // 1.5.1: phones show the empty slots as one row of small chips ("＋ Frühstück ＋ Snack")
      const addChips = emptyIds.length
        ? `<div class="addchips">${emptyIds.map((mealId) => `<button class="chip addchip" style="--meal-color:${this._mealColor(mealId)}" data-action="add-entry" data-date="${iso}" data-meal="${mealId}" data-drop-date="${iso}" data-drop-meal="${mealId}" aria-label="${esc(this._mealLabel(mealId))} am ${esc(WEEKDAYS[i])} planen">＋ ${esc(this._mealLabel(mealId))}</button>`).join("")}</div>`
        : "";
      const cls = iso === today ? "today" : iso < today ? "past" : "";
      // 1.5: occasions of the day ("🎬 Filmabend · 20:00 · 👥 4 · ≈ 23 €")
      const occasions = this._occasionsOn(iso).map((o) => this._occCardHtml(o)).join("");
      days += `<div class="card day ${cls}">
          <div class="dayhead"><span class="wd">${WEEKDAYS[i]}</span><span class="dt">${day.getDate()}. ${MONTHS[day.getMonth()]}</span>${iso === today ? '<span class="badge">Heute</span>' : ""}</div>
          ${occasions}${slots}${addChips}
        </div>`;
    }
    const capacity = 7 * this._data.meals.length;
    const pct = capacity ? Math.min(100, Math.round((planned / capacity) * 100)) : 0;
    return `
      ${this._renderHero()}
      ${this._renderSeasonRow()}
      <div class="row">
        <button class="icon" data-action="week" data-delta="-7" title="Vorherige Woche">◀</button>
        <div class="weeklabel">${esc(label)}</div>
        <button class="icon" data-action="week" data-delta="7" title="Nächste Woche">▶</button>
        <button class="btn small" data-action="week" data-delta="0">Heute</button>
        <div class="progress" title="${planned} von ${capacity} Mahlzeiten geplant"><div style="width:${pct}%"></div></div>
        <span class="meta">${planned}/${capacity} geplant</span>
        ${this._budgetPill(start)}
        <span class="spacer"></span>
        <div class="weekacts">
          <button class="btn" data-action="copy-week" title="Plan der Vorwoche in diese Woche übernehmen">⧉ Letzte Woche übernehmen</button>
          <button class="btn" data-action="occasion-new" title="Filmabend, Grillabend, Weihnachtsessen … mit Gängen, Getränken und Zubehör">🎉 Anlass planen</button>
          <button class="btn" data-action="auto-plan">✨ Automatisch planen</button>
          <button class="btn primary" data-action="shopping-from-week">🛒 Einkaufsliste</button>
        </div>
      </div>
      <div class="week">${days}</div>
      <p class="hint dndtip" style="text-align:center;margin-top:14px">Tipp: Mahlzeiten mit der Maus auf einen anderen Tag ziehen – belegte Plätze werden getauscht.</p>`;
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
      if (this._seasonOnly && !this._seasonOf(r.id)) return false;
      if (this._kind) {
        const filter = KIND_FILTERS.find((f) => f[0] === this._kind);
        if (filter && !filter[2].includes(recipeKind(r))) return false;
      }
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
        const season = this._seasonOf(r.id);
        // 1.5.1: a picture (not a background): small pictures are not blown up (lowres, see
        // _imageLoaded()); phones show the card as a row with a thumbnail
        return `<div class="card recipe" data-action="open-recipe" data-id="${esc(r.id)}">
            <div class="img">${safeUrl(r.image) ? this._img(r.image, dishEmoji(r.name)) : dishEmoji(r.name)}
              ${season ? `<span class="sbadge" title="${esc(season.hints.join(" · "))}">🍂<span class="sbt"> ${esc((season.items || [])[0] || "Saison")}</span></span>` : ""}
            </div>
            <button class="icon fav ${r.favorite ? "on" : ""}" data-action="toggle-fav" data-id="${esc(r.id)}" title="Favorit" aria-label="Favorit" aria-pressed="${Boolean(r.favorite)}">${r.favorite ? "★" : "☆"}</button>
            <div class="body">
              <div class="name">${esc(r.name)}</div>
              ${r.rating ? `<div class="stars">${stars(r.rating)}</div>` : ""}
              ${meta ? `<div class="meta">${meta}</div>` : ""}
              <div class="chips"><span class="chip kind k-${recipeKind(r)}" title="Art${r.kind_source === "user" ? " (selbst gewählt)" : r.kind_source === "ai" ? " (von der KI geprüft)" : ""}">${KIND_LABELS[recipeKind(r)] || ""}${r.kind_source === "ai" ? " 🤖" : ""}</span>${(r.tags || []).slice(0, 3).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
            </div>
          </div>`;
      })
      .join("");
    return `
      <div class="row recfind">
        <input type="search" placeholder="🔍 Rezepte oder Zutaten suchen …" value="${esc(this._search)}" data-input="search" data-focuskey="search" style="flex:1;min-width:200px">
        <select data-change="sort" title="Sortierung">${Object.entries(SORTS).map(([k, v]) => `<option value="${k}" ${k === this._sort ? "selected" : ""}>${v}</option>`).join("")}</select>
        <button class="btn ${this._favOnly ? "primary" : ""}" data-action="fav-only">★ Favoriten</button>
        <button class="btn ${this._seasonOnly ? "primary" : ""}" data-action="season-only" aria-pressed="${this._seasonOnly}" title="Rezepte mit Zutaten der Saison und zur Zeit des Jahres">🍂 Saison</button>
      </div>
      <div class="row recacts">
        <button class="btn primary" data-action="new-recipe">＋ Neues Rezept</button>
        <button class="btn" data-action="import">🌐 Von URL importieren</button>
        <button class="btn" data-action="cook-with">🧊 Was kann ich kochen?</button>
        ${this._aiSortButton("recipes")}
        <span class="spacer"></span>
        <button class="btn ghost" data-action="backup">💾 Sichern & Teilen</button>
      </div>
      ${this._aiOn("recipes") ? `<div class="praisort">${this._aiSortLine("recipes")}</div>` : ""}
      <div class="row chips tagrow kindrow" role="group" aria-label="Art">
        <button class="chip ${this._kind ? "" : "active"}" data-action="kind" data-kind="" aria-pressed="${!this._kind}">Alle Arten</button>
        ${KIND_FILTERS.map(([id, label, kinds]) => {
          const n = this._data.recipes.filter((r) => kinds.includes(recipeKind(r))).length;
          return n ? `<button class="chip ${this._kind === id ? "active" : ""}" data-action="kind" data-kind="${id}" aria-pressed="${this._kind === id}">${label} (${n})</button>` : "";
        }).join("")}
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
        .filter((p) => p && !p.startsWith("≈ ") && !p.startsWith("🏷️ ") && !(byStore && p.startsWith("🏪 ")) && !(item.product && p.startsWith("📦 ")));
      return parts.filter((p) => !(item.status !== "completed" && p === item.category)).join(" · ");
    };
    // 1.5.1: "↪ 200 g übrig – z. B. für Chili" – phones show only "↪ 200 g übrig"
    const descHtml = (text) =>
      text
        .split(" · ")
        .map((part) => {
          const cut = part.startsWith("↪") ? part.indexOf(" – ") : -1;
          return cut > 0 ? `${esc(part.slice(0, cut))}<span class="lomore">${esc(part.slice(cut))}</span>` : esc(part);
        })
        .join(" · ");
    // 1.5: picture in front (the product's or the aisle's emoji), brand and product below
    // the name; both open "Produkt wechseln"
    const thumbOf = (item, isOpen) => {
      const p = item.product || null;
      const pic = this._img(p?.image || item.chosen?.offer?.image, CATEGORY_ICONS[item.category || "Sonstiges"] || "🛒");
      return isOpen
        ? `<button class="ithumb" data-action="swap-product" data-uid="${esc(item.uid)}" title="Produkt wählen" aria-label="Produkt wählen: ${esc(item.summary)}">${pic}</button>`
        : `<span class="ithumb">${pic}</span>`;
    };
    const productLine = (item, isOpen) => {
      const p = item.product;
      if (!p) return "";
      const full = p.name || p.title || "";
      const name = full && fold(item.summary).includes(fold(full)) ? "" : full;
      const pack = packText(p.pack_amount, p.pack_unit);
      const why = isOpen ? PRODUCT_REASON[item.product_reason] : "";
      const parts = [`${p.brand ? `<b>${esc(p.brand)}</b>${name ? " " : ""}` : ""}${esc(name)}`, pack && !fold(full).includes(fold(pack)) ? esc(pack) : "", why ? `<span class="pwhy">${esc(why)}</span>` : ""].filter(Boolean);
      const inner = parts.join(" · ");
      return `<div class="pline" ${isOpen ? `data-swap="${esc(item.uid)}" title="Produkt wechseln"` : ""}>${inner}</div>`;
    };
    const renderItem = (item) => {
      const isOpen = item.status !== "completed";
      const reason = byStore && isOpen ? REASON_CHIP[item.store_reason] : null;
      const saving = byStore && isOpen && item.saving > 0 ? `<span class="sv">spart ${eur(item.saving)}</span>` : "";
      const offer = item.offer ? `<span class="o">🏷️ ${byStore ? "Angebot" : esc(item.offer.store || "Angebot")}</span>` : "";
      return `
      <div class="item ${isOpen ? "" : "done"}">
        <label class="chk"><input type="checkbox" data-change="toggle-item" data-uid="${esc(item.uid)}" ${isOpen ? "" : "checked"} aria-label="${esc(item.summary)} erledigt"></label>
        ${thumbOf(item, isOpen)}
        <div class="txt"><div class="sum">${esc(item.summary)}${reason && item.store_reason !== "offer" ? `<span class="reason ${reason[1]}" title="${esc(reason[2])}">${reason[0]}</span>` : ""}</div>${productLine(item, isOpen)}${describe(item) ? `<div class="desc" title="${esc(describe(item))}">${descHtml(describe(item))}</div>` : ""}</div>
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
      ${total ? `<div class="card shopstat"><span class="num">${open.length}</span><span class="meta sdone">offen<br>${done.length} erledigt</span><div class="progress"><div style="width:${pct}%"></div></div><span class="meta spct">${pct}%</span>${priced.length ? `<span class="meta" style="text-align:right"><b style="font-size:16px;color:var(--primary-text-color)">≈ ${eur(sum)}</b><br>${offersUsed ? `🏷️ ${offersUsed} im Angebot · ` : ""}ganze Packungen</span>` : ""}</div>` : ""}
      ${hint}
      <div class="row addrow">
        <div class="addwrap">
          <input placeholder="${window.innerWidth < 600 ? "Artikel, z. B. „2 Liter Milch“" : "Artikel hinzufügen, z. B. „2 Liter Milch“"}" aria-label="Artikel hinzufügen" data-enter="add-item" data-focuskey="additem" data-input="additem" value="${esc(this._addText)}" autocomplete="off" autocapitalize="sentences" enterkeyhint="done" role="combobox" aria-autocomplete="list" aria-expanded="${this._suggest.open ? "true" : "false"}">
          <div class="suggest" role="listbox" ${this._suggest.open ? "" : "hidden"}>${this._suggest.open ? this._suggestHtml() : ""}</div>
        </div>
        <button class="btn primary" data-action="add-item">Hinzufügen</button>
      </div>
      <div class="row shoptools">
        ${split ? `<div class="seg" role="group" aria-label="Sortierung"><button class="${byStore ? "on" : ""}" data-action="shop-mode" data-mode="store">🏪 Nach Laden</button><button class="${byStore ? "" : "on"}" data-action="shop-mode" data-mode="aisle">🧺 Nach Abteilung</button></div>` : ""}
        <div class="shopacts" role="group" aria-label="Aktionen">
          <button class="btn" data-action="shopping-next-week">🗓️ Aus Plan<span class="wide-only"> (7 Tage) erstellen</span></button>
          ${open.length ? `<button class="btn" data-action="share-list">📤 Teilen<span class="wide-only"> / Kopieren</span></button>` : ""}
          ${split && open.length ? `<button class="btn" data-action="assign-stores" title="Alle offenen Artikel neu auf die Läden verteilen">🔄 Läden neu zuordnen</button>` : ""}
          ${this._isAdmin() ? `<button class="btn" data-action="receipt-new" title="Kassenzettel fotografieren oder Text einfügen – seine Preise werden die Preise des Ladens">🧾 Kassenzettel</button>` : ""}
          <span class="spacer"></span>
          ${done.length ? `<button class="btn ghost" data-action="clear-done">🧹 Erledigte entfernen (${done.length})</button>` : ""}
          ${total ? `<button class="btn danger" data-action="clear-all">🗑 Liste leeren</button>` : ""}
        </div>
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

  /** 1.5: the search covers every saved store – online sources of each chain with a branch. */
  _expectLive() {
    const eco = this._data?.economy || {};
    const chains = new Set((this._data?.branches || []).filter((b) => b.selected).map((b) => b.retailer));
    if (eco.main_retailer) chains.add(eco.main_retailer);
    return (
      eco.offers_source === "marktguru" ||
      (eco.price_sources?.rewe?.enabled && chains.has("rewe")) ||
      (eco.price_sources?.aldi?.enabled && chains.has("aldi-sued"))
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
      const local = await this._hass.callWS({ type: `${DOMAIN}/article_search`, query, live: false, scope: "all" });
      if (seq !== this._suggestSeq) return;
      localDone = true;
      this._setSuggestResults(local, query, live);
      if (!live) return;
      const online = await this._hass.callWS({ type: `${DOMAIN}/article_search`, query, live: true, scope: "all" });
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
    const ident = (r) => r && `${r.title}|${r.pack}|${r.source}|${r.offer?.id || ""}|${r.product_id || ""}|${r.branch_id || ""}`;
    const current = ident(s.results[s.index]);
    s.results = res?.results || [];
    s.store = res?.store || null;
    s.scope = res?.scope || "main";
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
    let head = "";
    if (store) head = `<div class="shint top">${retailerDot(store.retailer, store.retailer_name).replace('class="rdot"', 'class="rdot sm"')}<span>Artikel bei <b>${esc(store.label)}</b>${store.main ? " (Hauptladen)" : ""}</span></div>`;
    else if (s.scope === "all" && s.results.length) head = `<div class="shint top"><span>🔎 Aus allen deinen Läden – günstigste zuerst</span></div>`;
    const rows = s.results
      .map((r, i) => {
        const shop = SHOP_PROVIDERS[r.provider];
        const offer = r.offer && !shop;
        const sourceHint =
          r.source === "live"
            ? shop
              ? shop
              : "🏷️ Prospekt (online)"
            : r.source === "product" && offer
              ? ""
              : ARTICLE_SOURCE[r.source] || "";
        const until = offer && r.offer?.valid_to ? `${sourceHint ? " " : "🏷️ "}bis ${shortDate(r.offer.valid_to)}` : "";
        const where = r.retailer
          ? `<span class="schip">${retailerDot(r.retailer, this._retailerName(r.retailer)).replace('class="rdot"', 'class="rdot xs"')}${esc(r.store_label || this._retailerName(r.retailer))}</span>`
          : '<span class="schip est">Allgemein</span>';
        const sub = [sourceHint + until, r.count > 1 ? `${r.count}× gekauft` : ""].filter(Boolean).join(" · ");
        const ph = r.source === "default" ? "≈" : r.source === "product" ? "📦" : offer ? "🏷️" : "🛒";
        return `<button class="sugg ${i === s.index ? "sel" : ""}" data-sugg="${i}" role="option" aria-selected="${i === s.index}" tabindex="-1">
          <span class="sthumb">${this._img(r.image, ph)}</span>
          <span class="st"><div class="t">${esc(r.title)}${r.pack ? ` <span class="meta">${esc(r.pack)}</span>` : ""}${offer ? ' <span class="tagoffer">🏷️ Angebot</span>' : ""}</div><div class="sub">${where}${sub ? ` ${esc(sub)}` : ""}</div></span>
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
    // 1.5: a product of the database (also a shop hit of REWE / ALDI SÜD online): the item
    // is that product, bought at its chain for its offer or regular price (the backend
    // decides the branch like for a picked offer)
    const productId = r.product_id && (r.source === "product" || (r.source === "live" && SHOP_PROVIDERS[r.provider])) ? r.product_id : null;
    if (productId) data.product_id = productId;
    else {
      // A hit of the main store is no store choice: the item stays in the automatic
      // assignment ("Hauptladen + Ausnahmen") and still moves to a better offer elsewhere.
      // Only a hit of another store (or of a retailer without branches) names it.
      const searched = s.store?.branch_id || (s.scope === "all" ? this._data?.main_branch || null : null);
      let store = null;
      if (r.branch_id) store = r.branch_id !== searched ? r.branch_id : null;
      else if (!this._splitActive()) store = r.retailer || null;
      if (store) data.store = store;
      if (STORE_PRICE_HITS.has(r.source)) {
        if (r.price != null) data.price = r.price;
        if (r.pack) data.pack = r.pack;
      }
      // saved offers (a live leaflet offer has the id it is saved under by the offer refresh)
      const leaflet = r.source === "offer" || (r.source === "live" && !SHOP_PROVIDERS[r.provider]);
      if (leaflet && r.offer?.id) data.offer_id = r.offer.id;
    }
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
    const label = item.store_label || r.store_label || (r.retailer ? this._retailerName(r.retailer) : "");
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
    // 1.5: the leaflet viewer turns pages with the arrow keys
    // (not while the page slider has the focus: it moves itself)
    const inSlider = ev.composedPath?.()[0]?.classList?.contains("lfslider");
    if (this._lfView && !inSlider && this._modal?.root === this._lfView.root && (ev.key === "ArrowRight" || ev.key === "ArrowLeft")) {
      ev.preventDefault();
      this._lfView.go(this._lfView.index + (ev.key === "ArrowRight" ? 1 : -1));
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
    } else if (kind === "pr-query") {
      this._pr.query = t.value;
      clearTimeout(this._prTimer);
      this._prTimer = setTimeout(() => this._fetchProducts(), 350);
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
      } else if (kind === "pr-sort") {
        this._pr.sort = t.value;
        this._setPref("products_sort", t.value);
        this._fetchProducts();
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
    // 1.5: the product line of a shopping item (its picture is the button for the same)
    const swap = ev.target.closest("[data-swap]");
    if (swap && this._content.contains(swap)) {
      ev.stopPropagation();
      this._openProductSwap(swap.dataset.swap).catch(() => {});
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
      /* 1.5: occasions, season */
      case "occasion-open":
        this._openOccasion(d.id);
        break;
      case "occasion-new":
        this._openOccasionNew({ date: d.date || null });
        break;
      case "season-open":
        this._openSeason();
        break;
      case "season-only":
        this._seasonOnly = !this._seasonOnly;
        this._renderContent();
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
      case "kind":
        this._kind = d.kind || "";
        this._setPref("kind", this._kind);
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
          this._lf.stale = true;
          if (this._tab === "offers") this._renderContent();
        }
        break;
      }
      case "add-offer":
        this._openOfferForm({ store: d.store || "" });
        break;
      case "offers-mode":
        this._offersMode = OFFERS_MODES.includes(d.mode) ? d.mode : "recipes";
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
      /* 1.5: "📦 Artikel" */
      case "pr-store": {
        const pr = this._pr;
        if (!d.store) pr.stores.clear();
        else if (pr.stores.has(d.store)) pr.stores.delete(d.store);
        else pr.stores.add(d.store);
        if (pr.stores.size && pr.stores.size === (pr.result?.stores || []).length) pr.stores.clear();
        this._setPref("products_stores", JSON.stringify([...pr.stores]));
        pr.category = "";
        this._fetchProducts();
        break;
      }
      case "pr-cat":
        this._pr.category = this._pr.category === d.cat ? "" : d.cat || "";
        this._fetchProducts();
        break;
      case "pr-only":
        this._pr.only = this._pr.only === d.only ? "" : d.only || "";
        this._fetchProducts();
        break;
      case "pr-kind":
        this._pr.kind = d.kind;
        this._setPref("products_kind", d.kind);
        this._pr.category = "";
        this._fetchProducts();
        break;
      case "pr-more":
        if (!this._pr.loading) await this._fetchProducts(true);
        break;
      case "pr-reset":
        Object.assign(this._pr, { query: "", category: "", only: "" });
        this._pr.stores.clear();
        this._setPref("products_stores", "[]");
        this._renderContent();
        this._fetchProducts();
        break;
      case "pr-open":
        await this._openProduct(d.id);
        break;
      case "pr-add":
        await this._productToList(el, this._prCard(d.id) || { id: d.id, title: d.title });
        break;
      case "pr-fav":
        await this._productFavorite(el, d.id, d.key || null, d.on !== "1");
        break;
      case "pr-new":
        this._openProductForm({});
        break;
      case "ai-sort":
        await this._aiSort(d.target, el);
        break;
      case "swap-product":
        await this._openProductSwap(d.uid);
        break;
      /* 1.5: "📰 Prospekte" */
      case "lf-when":
        this._lf.when = d.when;
        this._renderLeafletParts();
        break;
      case "lf-open":
        this._openLeaflet(d.id, Number(d.page) || 0);
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
      <div class="overlay ${opts.full ? "full" : ""}">
        <div class="modal ${opts.cls || ""}" role="dialog" aria-label="${esc(title)}">
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
    this._lfView = null;
    // a closed receipt dialog stays closed when its upload / reading finishes
    this._receipt = null;
    // … and so does a closed occasion editor
    this._occ = null;
  }

  _mealOptions(selected) {
    return this._data.all_meals.map((m) => `<option value="${m.id}" ${m.id === selected ? "selected" : ""}>${esc(m.label)}</option>`).join("");
  }

  /** Plan a slot. opts (1.5.1, from the auto plan's result): back() instead of closing,
   *  saved(entry) after planning (the caller shows its dialog again). */
  _openPicker(date, meal, current, autoSuggest = false, opts = {}) {
    const servings = current?.servings || this._data.default_servings;
    let selected = current?.recipe_id || null;
    let query = "";
    // 1.5.1: meals first (those of this slot's kind at the top); sides, sauces, drinks and
    // desserts come "Dazu" – as extras of the slot's meal, never as a meal of their own
    const wanted = SLOT_KIND[meal] || "meal";
    let extras = (current?.extras || []).map((x) => ({ recipe_id: x.recipe_id || null, title: x.title }));
    const matches = (r, q) => !q || fold(r.name).includes(q) || (r.tags || []).some((t) => fold(t).includes(q));
    const byFav = (a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0) || a.name.localeCompare(b.name, "de");
    const listHtml = () => {
      const q = fold(query).trim();
      const items = this._data.recipes
        .filter((r) => (SLOT_KINDS.has(recipeKind(r)) || r.id === selected) && matches(r, q))
        .sort((a, b) => (recipeKind(a) === wanted ? 0 : 1) - (recipeKind(b) === wanted ? 0 : 1) || byFav(a, b))
        .slice(0, 80);
      if (!items.length) return `<div class="pick" style="cursor:default">Kein Rezept gefunden – wird als Freitext eingetragen.</div>`;
      return items
        .map((r) => {
          const season = this._seasonOf(r.id);
          const kind = recipeKind(r);
          return `<button class="pick ${r.id === selected ? "sel" : ""}" data-pick="${esc(r.id)}">${dishEmoji(r.name)} ${esc(r.name)}${r.favorite ? ' <span class="stars"><span class="on">★</span></span>' : ""}${season ? ` <span title="${esc(season.hints.join(" · "))}">🍂</span>` : ""}<span class="m">${kind !== wanted ? `${esc(KIND_LABELS[kind] || "")} · ` : ""}${r.total_time ? r.total_time + " min" : ""}</span></button>`;
        })
        .join("");
    };
    const dazuHtml = () => {
      const q = fold(query).trim();
      const on = new Set(extras.map((x) => x.recipe_id).filter(Boolean));
      const items = this._data.recipes
        .filter((r) => !SLOT_KINDS.has(recipeKind(r)) && r.id !== selected && (on.has(r.id) || matches(r, q)))
        .sort((a, b) => (on.has(b.id) ? 1 : 0) - (on.has(a.id) ? 1 : 0) || byFav(a, b))
        .slice(0, 60);
      const free = extras.filter((x) => !x.recipe_id).map((x) => `<button class="pick part sel" data-xfree="${esc(x.title)}">📝 ${esc(x.title)}<span class="m">Freitext</span></button>`).join("");
      return (
        free +
          items.map((r) => `<button class="pick part ${on.has(r.id) ? "sel" : ""}" data-extra="${esc(r.id)}" aria-pressed="${on.has(r.id)}">${dishEmoji(r.name)} ${esc(r.name)}<span class="m">${esc(KIND_LABELS[recipeKind(r)] || "")}</span></button>`).join("") ||
        '<div class="pick" style="cursor:default">Keine Beilagen, Saucen oder Getränke gefunden.</div>'
      );
    };
    const dazuInfo = () => (extras.length ? `Dazu: ${extras.map((x) => esc(x.title)).join(", ")}` : "Bestandteile wie Saucen, Dips oder Getränke werden zu der Mahlzeit dazugeplant – nie als eigene Mahlzeit.");
    // leftovers of the last days for an empty slot ("🍲 Reste von Dienstag (Lasagne)")
    const sources = current ? [] : this._leftoverSources(date, meal);
    const leftHtml = sources.length
      ? `<div class="section"><h4>🍲 Reste essen</h4><div class="suglist leftlist">${sources
          .slice(0, 6)
          .map((x) => `<button class="sg" data-left="${x.date}|${x.meal}"><span class="sthumb">🍲</span><span class="sgt"><b>${esc(entryTitle({ title: x.entry.title, leftover_of: { date: x.date, meal: x.meal } }, date))}</b><div class="why">${esc(this._dateLabel(x.date))} · ${esc(this._mealLabel(x.meal))} – wird dort für alle mitgekocht</div></span></button>`)
          .join("")}</div></div>`
      : "";
    const body = `
      <div class="hint" style="display:flex;align-items:center;gap:6px"><i style="width:9px;height:9px;border-radius:50%;background:${this._mealColor(meal)};display:inline-block"></i>${esc(this._dateLabel(date))} · ${esc(this._mealLabel(meal))}</div>
      ${leftHtml}
      <input type="search" placeholder="Rezept suchen oder Freitext („Pizza bestellen“) …" class="q" value="${esc(current && !current.recipe_id ? current.title : "")}">
      <div class="row" style="margin:0"><button class="btn small psuggest">💡 Vorschläge</button><span class="hint">nach Favoriten, Saison, Angeboten und Abwechslung</span></div>
      <div class="suggestions suglist"></div>
      <div class="picklist main">${listHtml()}</div>
      <h4 style="margin:4px 0 0">➕ Dazu <span class="hint" style="font-weight:normal">Beilagen, Saucen & Dips, Getränke, Desserts</span></h4>
      <div class="hint dazuinfo">${dazuInfo()}</div>
      <div class="picklist dazu">${dazuHtml()}</div>
      <div class="grid2">
        <label class="field">Portionen<input type="number" min="1" max="50" class="servings" value="${servings}"></label>
        <label class="field">Notiz<input class="note" value="${esc(current?.note || "")}" placeholder="optional"></label>
      </div>`;
    const footer = `${opts.back ? '<button class="btn" data-close>← Zurück</button>' : '<button class="btn" data-close>Abbrechen</button>'}<button class="btn primary save">📅 Einplanen</button>`;
    const modalOpts = opts.back
      ? {
          guard: () => {
            opts.back();
            return false;
          },
        }
      : {};
    this._showModal(current ? "Mahlzeit ändern" : "Mahlzeit planen", body, footer, (root) => {
      const q = root.querySelector(".q");
      const list = root.querySelector(".picklist.main");
      const dazu = root.querySelector(".picklist.dazu");
      const renderDazu = () => {
        dazu.innerHTML = dazuHtml();
        root.querySelector(".dazuinfo").innerHTML = dazuInfo();
      };
      q.focus();
      q.addEventListener("input", () => {
        query = q.value;
        selected = null;
        list.innerHTML = listHtml();
        renderDazu();
      });
      q.addEventListener("keydown", (ev) => ev.key === "Enter" && root.querySelector(".save").click());
      list.addEventListener("click", (ev) => {
        const pick = ev.target.closest("[data-pick]");
        if (!pick) return;
        selected = pick.dataset.pick;
        list.innerHTML = listHtml();
        renderDazu();
      });
      list.addEventListener("dblclick", (ev) => {
        if (ev.target.closest("[data-pick]")) root.querySelector(".save").click();
      });
      dazu.addEventListener("click", (ev) => {
        const pick = ev.target.closest("[data-extra]");
        const free = ev.target.closest("[data-xfree]");
        if (pick) {
          const id = pick.dataset.extra;
          const r = this._recipe(id);
          extras = extras.some((x) => x.recipe_id === id) ? extras.filter((x) => x.recipe_id !== id) : [...extras, { recipe_id: id, title: r?.name || id }];
        } else if (free) {
          extras = extras.filter((x) => x.recipe_id || x.title !== free.dataset.xfree);
        } else return;
        renderDazu();
      });
      root.querySelector(".leftlist")?.addEventListener("click", async (ev) => {
        const left = ev.target.closest("[data-left]");
        if (!left) return;
        const [fromDate, fromMeal] = left.dataset.left.split("|");
        const res = await this._service("plan_leftover", { date, meal, from_date: fromDate, from_meal: fromMeal, servings: Number(root.querySelector(".servings").value) || undefined }, true);
        this._toast(`🍲 ${res?.entry?.title || "Reste"}: ${this._dateLabel(date)}, ${this._mealLabel(meal)}`);
        if (opts.saved) return opts.saved(res?.entry);
        this._closeModal();
      });
      // 1.5: with the reasons ("⭐ Favorit · 🍂 Saison: Kürbis · 🏷️ Angebot: Hack")
      const suggest = async () => {
        const box = root.querySelector(".suggestions");
        box.innerHTML = '<span class="hint">⏳ Suche Vorschläge …</span>';
        const res = await this._service("suggest_recipes", { count: 4, meal, date }, true);
        box.innerHTML =
          (res?.recipes || [])
            .map((r) => {
              const why = (r.reasons || []).join(" · ");
              return `<button class="sg" data-sugg="${esc(r.id)}"><span class="sthumb">${dishEmoji(r.name)}</span><span class="sgt"><b>${esc(r.name)}</b>${why ? `<div class="why">${esc(why)}</div>` : ""}</span>${r.cost ? `<span class="pp"><span class="meta">≈ ${eur(r.cost)}</span></span>` : ""}</button>`;
            })
            .join("") || '<span class="hint">Keine passenden Rezepte</span>';
      };
      // (not ".suggest": that is the article dropdown of the shopping list)
      root.querySelector(".psuggest").addEventListener("click", suggest);
      if (autoSuggest) suggest();
      root.querySelector(".suggestions").addEventListener("click", (ev) => {
        const chip = ev.target.closest("[data-sugg]");
        if (!chip) return;
        selected = chip.dataset.sugg;
        query = "";
        q.value = "";
        root.querySelectorAll(".suggestions [data-sugg]").forEach((x) => x.classList.toggle("sel", x === chip));
        list.innerHTML = listHtml();
        renderDazu();
        list.querySelector(".sel")?.scrollIntoView({ block: "nearest" });
      });
      root.querySelector(".save").addEventListener("click", async () => {
        const data = { date, meal, servings: Number(root.querySelector(".servings").value) || undefined };
        const note = root.querySelector(".note").value.trim();
        if (note) data.note = note;
        if (selected) data.recipe = selected;
        else if (q.value.trim()) data.title = q.value.trim();
        else if (extras.length && current) data[current.recipe_id ? "recipe" : "title"] = current.recipe_id || current.title;
        else if (extras.length) return this._toast("Bitte zuerst eine Mahlzeit wählen – Beilagen, Saucen und Getränke werden zu ihr dazugeplant.");
        else return this._toast("Bitte ein Rezept auswählen oder einen Text eingeben.");
        if (extras.length || current?.extras?.length) data.extras = extras.map((x) => (x.recipe_id ? { recipe_id: x.recipe_id } : { title: x.title }));
        if (opts.saved) {
          const res = await this._service("plan_meal", data, true);
          return opts.saved(res?.entry);
        }
        await this._service("plan_meal", data);
        this._closeModal();
      });
    }, modalOpts);
  }

  _openEntry(date, meal) {
    const entry = (this._data.plan[date] || {})[meal];
    if (!entry) return;
    const recipe = this._recipe(entry.recipe_id);
    const lo = entry.leftover_of;
    const lefts = lo ? [] : this._leftoversOf(date, meal);
    // cooked here: its own servings and those of its leftovers
    const cookServings = lefts.length ? (Number(entry.servings) || this._data.default_servings) + lefts.reduce((n, l) => n + (Number(l.entry.servings) || 0), 0) : entry.servings;
    // 1.5.1: "🍲 Für einen weiteren Tag mitkochen" (default: the next day, the same meal)
    const next = toIso(addDays(fromIso(date), 1));
    const leftoverSec = lo
      ? `<div class="section"><h4>🍲 Reste</h4><div>Gekocht wird am ${esc(this._dateLabel(lo.date))} (${esc(this._mealLabel(lo.meal))}) für alle Portionen – hier kommt nichts auf die Einkaufsliste, die Reste kosten nichts.</div><div><button class="btn small fresh">🍳 Doch frisch kochen</button></div></div>`
      : `<div class="section leftsec"><h4>🍲 Für einen weiteren Tag mitkochen</h4>
          ${lefts.length ? `<div>Mitgekocht für: ${lefts.map((l) => `${esc(this._dateLabel(l.date))}, ${esc(this._mealLabel(l.meal))}${l.entry.servings ? ` (👥 ${l.entry.servings})` : ""}`).join(" · ")}</div>` : ""}
          <div class="hint">Hier wird für beide Mahlzeiten gekocht und eingekauft – praktisch, wenn sonst angebrochene Packungen übrig bleiben.</div>
          <div class="grid3">
            <label class="field">Reste am<input type="date" class="ldate" value="${next}"></label>
            <label class="field">Mahlzeit<select class="lmeal">${this._mealOptions(meal)}</select></label>
            <label class="field">Portionen<input type="number" min="1" max="50" class="lserv" value="${entry.servings || this._data.default_servings}"></label>
          </div>
          <div class="hint lwarn"></div>
          <div><button class="btn small leftover">🍲 Mitkochen</button></div>
        </div>`;
    const extras = entry.extras || [];
    const extrasSec = `<div class="section"><h4>➕ Dazu</h4><div class="xchips">${extras.length ? extras.map((x, n) => `<span class="dchip-x">${x.recipe_id ? dishEmoji(x.title) : "📝"} ${esc(x.title)}<button class="icon" data-xx="${n}" aria-label="${esc(x.title)} entfernen" title="Entfernen">✕</button></span>`).join("") : '<span class="hint">Beilagen, Saucen & Dips, Getränke oder ein Dessert zur Mahlzeit – kommen mit auf die Einkaufsliste.</span>'}</div><div><button class="btn small xadd">＋ Dazu planen</button></div></div>`;
    const body = `
      <div class="hint" style="display:flex;align-items:center;gap:6px"><i style="width:9px;height:9px;border-radius:50%;background:${this._mealColor(meal)};display:inline-block"></i>${esc(this._dateLabel(date))} · ${esc(this._mealLabel(meal))}</div>
      <div class="heroimg" ${recipe ? bg(recipe.image) : ""}>${recipe && safeUrl(recipe.image) ? "" : lo ? "🍲" : recipe ? dishEmoji(recipe.name) : "📝"}</div>
      <div class="meta" style="font-size:14px">${[entry.servings ? `👥 ${entry.servings} Portionen` : "", recipe?.total_time && !lo ? `⏱ ${recipe.total_time} min` : "", entry.cooked ? "✅ gekocht" : ""].filter(Boolean).join(" · ")}</div>
      ${entry.note ? `<div>📝 ${esc(entry.note)}</div>` : ""}
      ${!recipe && !lo ? `<div class="hint">Freitext ohne Rezept – Zutaten landen nicht auf der Einkaufsliste.</div>` : ""}
      ${leftoverSec}
      ${extrasSec}
      ${recipe && isDrinkRecipe(recipe) ? "" : `<div class="section drinksec"><h4>🥤 Getränke dazu</h4><div class="dchips"></div><div class="dadd"></div></div>`}
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
      ${entry.cooked ? "" : `<button class="btn cooked">✅ ${lo ? "Gegessen" : "Gekocht"}</button>`}
      ${recipe ? `<button class="btn showr">📖 Rezept</button><button class="btn primary cookbtn">👩‍🍳 Kochmodus</button>` : ""}`;
    // the same dish with other extras (plan_meal keeps cooked, drinks and the leftovers link)
    const planSame = (extrasList) => {
      const data = { date, meal, extras: extrasList.map((x) => (x.recipe_id ? { recipe_id: x.recipe_id } : { title: x.title })) };
      if (entry.servings) data.servings = entry.servings;
      if (entry.recipe_id) data.recipe = entry.recipe_id;
      else data.title = entry.title;
      if (entry.note) data.note = entry.note;
      return this._service("plan_meal", data, true);
    };
    this._showModal(entryTitle(entry, date), body, footer, (root) => {
      this._entryDrinks(root, date, meal, entry);
      root.querySelector(".remove").addEventListener("click", async () => {
        const res = await this._service("remove_meal", { date, meal }, true);
        this._unlinkedToast((res?.removed || []).flatMap((v) => v.leftovers_unlinked || []));
        this._closeModal();
      });
      root.querySelector(".change").addEventListener("click", () => this._openPicker(date, meal, entry));
      root.querySelector(".cooked")?.addEventListener("click", async () => {
        await this._service("mark_cooked", { date, meal });
        this._closeModal();
      });
      root.querySelector(".showr")?.addEventListener("click", () => this._openRecipe(recipe.id, cookServings, { date, meal }));
      root.querySelector(".cookbtn")?.addEventListener("click", () => {
        this._closeModal();
        this._openCooking(recipe.id, cookServings, { date, meal });
      });
      root.querySelector(".xadd").addEventListener("click", () => this._openPicker(date, meal, entry));
      root.querySelector(".xchips").addEventListener("click", async (ev) => {
        const x = ev.target.closest("[data-xx]");
        if (!x) return;
        await planSame(extras.filter((_, n) => n !== Number(x.dataset.xx)));
        this._closeModal();
      });
      root.querySelector(".fresh")?.addEventListener("click", async () => {
        // leftovers become a normal meal of this day (its drinks and extras stay)
        const data = { date, meal, servings: entry.servings || undefined };
        if (entry.recipe_id) data.recipe = entry.recipe_id;
        else data.title = entry.title;
        if (entry.note) data.note = entry.note;
        if (entry.drinks?.length) data.drinks = entry.drinks;
        if (extras.length) data.extras = extras.map((x) => (x.recipe_id ? { recipe_id: x.recipe_id } : { title: x.title }));
        await this._service("remove_meal", { date, meal });
        await this._service("plan_meal", data);
        this._toast(`🍳 ${entry.title}: wird am ${this._dateLabel(date)} frisch gekocht`);
        this._closeModal();
      });
      const lwarn = () => {
        const box = root.querySelector(".lwarn");
        if (!box) return;
        const d = root.querySelector(".ldate").value;
        const m = root.querySelector(".lmeal").value;
        const there = (this._data.plan[d] || {})[m];
        const ok = d && (d > date || (d === date && this._mealRank(m) > this._mealRank(meal)));
        box.textContent = !ok ? "Die Reste gibt es nach dem Kochen – bitte einen späteren Tag oder eine spätere Mahlzeit wählen." : there && !(there.leftover_of?.date === date && there.leftover_of?.meal === meal) ? `Dort steht schon „${entryTitle(there, d)}“ – wird durch die Reste ersetzt.` : "";
      };
      root.querySelector(".ldate")?.addEventListener("change", lwarn);
      root.querySelector(".lmeal")?.addEventListener("change", lwarn);
      lwarn();
      root.querySelector(".leftover")?.addEventListener("click", async () => {
        const toDate = root.querySelector(".ldate").value;
        const toMeal = root.querySelector(".lmeal").value;
        if (!toDate) return;
        const res = await this._service("plan_leftover", { date: toDate, meal: toMeal, from_date: date, from_meal: meal, servings: Number(root.querySelector(".lserv").value) || undefined }, true);
        this._toast(`🍲 ${entry.title}: Reste am ${this._dateLabel(toDate)}, ${this._mealLabel(toMeal)}${res?.entry?.replaced ? ` (statt ${res.entry.replaced})` : ""}`);
        this._closeModal();
      });
      root.querySelector(".move").addEventListener("click", async () => {
        const toDate = root.querySelector(".mdate").value;
        const toMeal = root.querySelector(".mmeal").value;
        if (!toDate || (toDate === date && toMeal === meal)) return;
        const res = await this._service("move_meal", { from_date: date, from_meal: meal, to_date: toDate, to_meal: toMeal }, true);
        this._toast(`↪ ${entry.title}: ${this._dateLabel(toDate)}, ${this._mealLabel(toMeal)}`);
        this._unlinkedToast(res?.leftovers_unlinked);
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
      const season = this._data.recipe_season?.[id];
      const body = `
        <div class="heroimg" ${bg(r.image)}>${safeUrl(r.image) ? "" : dishEmoji(r.name)}</div>
        <div class="row" style="margin:0;justify-content:space-between">
          <span class="stepper">👥 <button class="icon minus" title="Weniger">−</button><input type="number" class="servings" min="1" max="50" value="${servings}"><button class="icon plus" title="Mehr">＋</button> Portionen</span>
          <span class="rating">${stars(current.rating, true)}</span>
        </div>
        <div class="meta">${[r.prep_time ? `Vorbereitung ${r.prep_time} min` : "", r.cook_time ? `Kochen ${r.cook_time} min` : "", r.total_time ? `Gesamt ${r.total_time} min` : "", current.cooked_count ? `🍳 ${current.cooked_count}× gekocht${current.last_cooked ? `, zuletzt ${this._dateLabel(current.last_cooked)}` : ""}` : ""].filter(Boolean).join(" · ")}</div>
        <div class="chips">${(r.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        ${season?.hints?.length ? `<div class="meta">${esc(season.hints.join(" · "))}</div>` : ""}${season?.out?.length ? `<div class="meta">⏳ Gerade nicht in Saison: ${esc(season.out.join(", "))}</div>` : ""}
        ${r.cost ? `<div class="section"><div class="costbox"><span class="big">≈ ${eur(r.cost.total)}</span><span class="meta">${eur(r.cost.per_serving)} pro Portion${r.cost.savings ? ` · 🏷️ ${eur(r.cost.savings)} gespart` : ""} · Schätzung</span></div>${r.cost.on_offer?.length ? `<div class="meta">🏷️ Im Angebot: ${r.cost.on_offer.map((o) => `${esc(o.ingredient)} (${esc(o.store)} ${eur(o.price)}${o.valid_to ? ` bis ${shortDate(o.valid_to)}` : ""})`).join(", ")}</div>` : ""}${r.cost.unknown?.length ? `<div class="hint">Ohne Preis: ${esc(r.cost.unknown.join(", "))}</div>` : ""}</div>` : ""}
        ${isDrinkRecipe(r) ? "" : `<div class="section drinkbox"><h4>🍷 Passt dazu</h4><div class="dchips"><span class="hint">⏳ Suche passende Getränke …</span></div><div class="dinfo" hidden></div></div>`}
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
        ${ctx?.occasion ? `<button class="btn back" title="Zurück zum Anlass">← Anlass</button>` : ""}
        <button class="btn danger delete" title="Löschen">🗑</button>
        <button class="btn share" title="Rezept teilen">📤</button>
        <button class="btn fav">${current.favorite ? "★ Favorit" : "☆ Favorit"}</button>
        <button class="btn edit">✏️ Bearbeiten</button>
        <button class="btn primary cookbtn">👩‍🍳 Kochmodus</button>`;
      this._showModal(r.name, body, footer, (root) => {
        this._fillDrinks(root, r, ctx);
        root.querySelector(".back")?.addEventListener("click", () => this._openOccasion(ctx.occasion));
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
          const res = await this._service("plan_meal", { date, meal, recipe: id, servings }, true);
          // 1.5.1: a side, sauce, drink or dessert joins the meal planned there
          this._toast(res?.entry?.added_as_extra ? `➕ ${r.name} zu ${res.entry.title}: ${this._dateLabel(date)}, ${this._mealLabel(meal)}` : `📅 ${r.name}: ${this._dateLabel(date)}, ${this._mealLabel(meal)}`);
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
      <label class="field">Art<select class="kind">
        <option value="auto">Automatisch${r.kind && r.kind_source !== "user" ? ` (jetzt: ${esc(KIND_LABELS[r.kind] || r.kind)}${r.kind_source === "ai" ? " – von der KI geprüft" : ""})` : ""}</option>
        ${Object.entries(KIND_LABELS).map(([k, label]) => `<option value="${k}" ${r.kind_source === "user" && r.kind === k ? "selected" : ""}>${esc(label)}</option>`).join("")}
      </select></label>
      <div class="hint">Nur Mahlzeiten, Frühstück und Snacks werden allein eingeplant. Getränke, Beilagen, Bestandteile (Saucen, Dips, Kräuterbutter) und Desserts kommen zu einer Mahlzeit dazu.</div>
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
        // 1.5.1: the kind (the rules decide with "Automatisch")
        const kind = v(".kind");
        if (kind !== "auto") data.kind = kind;
        else if (r.kind_source === "user") data.kind = "auto";
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
    const mode = OFFERS_MODES.includes(this._offersMode) ? this._offersMode : "recipes";
    const recipeCount = (this._data.offers || []).filter((o) => o.current && o.recipe_count).length;
    const button = (m, html) => `<button class="${mode === m ? "on" : ""}" data-action="offers-mode" data-mode="${m}" aria-pressed="${mode === m}">${html}</button>`;
    const seg = `<div class="seg somode" role="group" aria-label="Angebote anzeigen">
        ${button("recipes", `🍽️ <span class="wide-only">Für meine Rezepte</span><span class="narrow-only">Rezepte</span> (${recipeCount})`)}
        ${button("stores", `🏪 <span class="wide-only">Alle Angebote meiner Läden</span><span class="narrow-only">Läden</span> (<span data-socount>${this._storeOfferCount()}</span>)`)}
        ${button("leaflets", `📰 Prospekte<span data-lfcount>${this._lfCount()}</span>`)}
      </div>`;
    if (mode === "leaflets") return seg + this._renderLeaflets();
    return seg + (mode === "stores" ? this._renderStoreOffers() : this._renderRecipeOffers());
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
    // 1.5.1: no empty chart (nothing planned or priced this week)
    const anyDay = (week.days || []).some((d) => (d.total || 0) > 0);
    const bars = (week.days || [])
      .map((d) => `<div style="height:${Math.round(((d.total || 0) / maxDay) * 100)}%" title="${shortDate(d.date)}: ${eur(d.total)}"><span>${shortDate(d.date).split(" ")[0]}</span></div>`)
      .join("");
    const ratio = budget ? (week.total || 0) / budget : 0;
    const budgetHtml = `<div class="card budgetcard">
        <div><div class="meta">Diese Woche (geschätzt)</div><div class="big">${eur(week.total || 0)}</div></div>
        <div>
          ${budget ? `<div class="meta">Budget ${eur(budget)} · ${week.remaining >= 0 ? `noch <b>${eur(week.remaining)}</b> frei` : `<b style="color:var(--ep-red)">${eur(-week.remaining)} drüber</b>`}</div>
          <div class="progress" style="height:10px;max-width:none;margin-top:6px"><div style="width:${Math.min(100, Math.round(ratio * 100))}%;background:${ratio > 1 ? "#c62828" : ratio > 0.85 ? "#ef6c00" : "#2e7d32"}"></div></div>` : `<div class="hint">Kein Wochenbudget festgelegt – einstellen unter ${this._settingsLink("planning", "⚙️ Budget & Planung")}.</div>`}
        </div>
        <div class="meta bsave">${week.savings ? `🏷️ ${eur(week.savings)} durch Angebote gespart · ` : ""}Nächste Woche bisher ≈ ${eur(next.total || 0)}</div>
        ${anyDay ? `<div class="bars">${bars}</div>` : ""}
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
    const sourceText = `${sourceLines}${online && !marktguru ? `<div class="meta">Für Ketten ohne eigene Quelle (Lidl, REWE, Netto, Rossmann …) gibt es optional marktguru (inoffiziell, eigenes Risiko): ${this._settingsLink("offers", "⚙️ Angebote & Preisquellen")}</div>` : ""}`;
    // 1.5.1: phones fold the sources (several lines would push the offers down)
    const sourceBox = !sourceText
      ? ""
      : this._narrowQuery?.matches
        ? `<details class="srcbox offsrc"><summary>ℹ️ Quellen${meta.last_update ? ` · ${esc(new Date(meta.last_update).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }))}` : ""}</summary><div class="srclines">${sourceText}</div></details>`
        : `<div class="srclines">${sourceText}</div>`;
    const info = online
      ? sourceBox
      : `<div class="card infobox"><b>Online-Angebote sind aus.</b> EDEKA- und ALDI-SÜD-Angebote kommen direkt von den Ketten, für andere Ketten gibt es marktguru (inoffiziell, eigenes Risiko). Einschalten: ${this._settingsLink("offers", "⚙️ Angebote & Preisquellen")} – gesucht wird bei deinen Läden aus dem Tab „🏪 Läden & Preise“. Angebote aus dem Prospekt kannst du jederzeit selbst eintragen – oder Jarvis sagen: „Bei Lidl gibt es Hähnchenbrust für 4,99 Euro bis Samstag“.</div>${sourceBox}`;
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
      <div class="row offrow">
        <div class="offchips" role="group" aria-label="Filter">
          <button class="chip ${when === "current" ? "active" : ""}" data-action="offers-when" data-when="current">Aktuell</button>
          <button class="chip ${when === "upcoming" ? "active" : ""}" data-action="offers-when" data-when="upcoming">Ab nächster Woche</button>
          <button class="chip ${when === "all" ? "active" : ""}" data-action="offers-when" data-when="all">Alle</button>
          <button class="chip ${this._offersMine !== false ? "active" : ""}" data-action="offers-mine">Nur passend zu meinen Rezepten</button>
        </div>
        <span class="spacer"></span>
        <div class="offacts">
          ${online ? `<button class="btn" data-action="refresh-offers" ${this._refreshing.has("offers-tab") ? "disabled" : ""}>${this._refreshing.has("offers-tab") ? "⏳ Lade Angebote …" : "🔄 Aktualisieren"}</button>` : ""}
          <button class="btn" data-action="add-offer">＋ Angebot<span class="wide-only"> eintragen</span></button>
          <button class="btn ghost" data-action="go-tab" data-tab="stores" data-sec="prices">💶 Preise</button>
        </div>
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
    // 1.5: "🤖 mit KI" – the AI plans from the rules' best candidates (feature "season")
    const ai = this._aiOn("season");
    // 1.5.1: the result stays open – each row "🔄 Neu vorschlagen" / "✏️ Ändern"
    const st = { busy: false, res: null, usedAi: false, strategy, shown: {}, rowBusy: null };
    const key = (p) => `${p.date}|${p.meal}`;
    const body = `
      <div class="hint">${esc(this._dateLabel(start))} + ${days - 1} Tage · nur freie Plätze werden gefüllt.${budget ? ` Wochenbudget: ${eur(budget)}.` : ""}</div>
      <div class="strategy">${Object.entries(STRATEGY_LABELS).map(([k, [label, desc]]) => `<label><input type="radio" name="strategy" value="${k}" ${k === strategy ? "checked" : ""}><span><b>${label}</b><br><span class="meta">${desc}</span></span></label>`).join("")}</div>
      <div><h4>Mahlzeiten</h4><div class="chips">${this._data.meals.map((m) => `<label class="chip"><input type="checkbox" class="pm" value="${m.id}" ${m.id === this._data.default_meal ? "checked" : ""}> ${esc(m.label)}</label>`).join("")}</div></div>
      ${ai ? `<label class="switch aiswitch"><input type="checkbox" class="pai"><span>🤖 <b>mit KI</b> (${esc(this._aiName())}) – plant die Tage aus den besten Vorschlägen der Regeln nach Saison, Angeboten, Kosten und Abwechslung. Dauert ${AI_WAIT}.${this._aiOffline("season") ? `<br><span class="meta">⚠️ ${esc(this._aiName())} ist gerade nicht erreichbar – dann wird nach Regeln geplant.</span>` : ""}</span></label>` : ""}
      <div class="ferr" hidden></div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary go">✨ Planen</button>`;
    const rowHtml = (p) => {
      const k = key(p);
      const busy = st.rowBusy === k;
      const why = (p.reasons || []).length ? p.reasons.join(" · ") : p.manual ? "✏️ selbst gewählt" : "";
      return `<div class="prow ${busy ? "busy" : ""}" data-k="${esc(k)}"><span class="pd">${esc(shortDate(p.date))}<br><span class="meta">${esc(this._mealLabel(p.meal))}</span></span><span class="pi"><b>${esc(p.title)}</b>${p.cost != null ? ` <span class="meta">≈ ${eur(p.cost)}</span>` : ""}${why ? `<div class="why">${esc(why)}</div>` : ""}</span><span class="pa"><button class="btn small" data-replan="${esc(k)}" ${st.rowBusy ? "disabled" : ""} title="Neu vorschlagen – ein anderes passendes Rezept" aria-label="${esc(p.title)}: neu vorschlagen">${busy ? '<span class="spin">⏳</span>' : "🔄"}<span class="wide-only"> Neu vorschlagen</span></button><button class="btn small" data-change="${esc(k)}" ${st.rowBusy ? "disabled" : ""} title="Selbst aussuchen" aria-label="${esc(p.title)}: ändern">✏️<span class="wide-only"> Ändern</span></button></span></div>`;
    };
    const result = () => {
      const res = st.res;
      const planned = res?.planned || [];
      const total = res?.week?.total;
      const aiNote = st.usedAi && res?.ai
        ? res.ai.ok
          ? `<div class="notice">🤖 ${esc(this._aiName())} hat die Woche aus deinen Rezepten geplant – geprüft gegen Mahlzeiten, Abwechslung und Ausschlüsse.${res.ai.notes ? `<br><span class="meta">„${esc(res.ai.notes)}“</span>` : ""}</div>`
          : `<div class="notice warn">🤖 ${esc(res.ai.error || "Die KI hat nicht geantwortet.")} Es wurde nach Regeln geplant.</div>`
        : "";
      return `<div class="costbox"><span class="big">✨ ${planned.length} ${planned.length === 1 ? "Mahlzeit" : "Mahlzeiten"} eingeplant</span>${total != null ? `<span class="meta weektotal">Woche ≈ ${eur(total)}</span>` : ""}</div>
        ${aiNote}
        ${planned.length ? `<div class="plist">${planned.map(rowHtml).join("")}</div><div class="hint">🔄 schlägt für den Tag ein anderes Rezept vor (Saison, Angebote, Budget, Abwechslung), ✏️ zum Selbst-Aussuchen.</div>` : '<div class="hint">Keine freien Plätze oder passenden Rezepte.</div>'}`;
    };
    const find = (k) => (st.res?.planned || []).findIndex((p) => key(p) === k);
    const showResult = () => {
      this._showModal("Woche automatisch planen", result(), `<button class="btn primary" data-close>✓ Fertig</button>`, (root) => mountResult(root), {
        sticky: () => Boolean(st.rowBusy),
      });
    };
    const rerender = (root) => {
      if (this._modal?.root !== root) return;
      root.querySelector(".mbody").innerHTML = result();
    };
    const replan = async (root, k) => {
      const n = find(k);
      if (n < 0 || st.rowBusy) return;
      const p = st.res.planned[n];
      const shown = (st.shown[k] = st.shown[k] || new Set());
      if (p.recipe_id) shown.add(p.recipe_id);
      st.rowBusy = k;
      rerender(root);
      try {
        const res = await this._service("replan_meal", { date: p.date, meal: p.meal, strategy: st.strategy, exclude: [...shown] }, true);
        if (res?.found && res.entry) {
          st.res.planned[n] = res.entry;
          if (res.entry.recipe_id) shown.add(res.entry.recipe_id);
          if (res.week) st.res.week = res.week;
        } else this._toast("Kein anderes passendes Rezept gefunden – ✏️ zum Selbst-Aussuchen.");
      } catch (e) {
        /* toast shown by _service */
      } finally {
        st.rowBusy = null;
        rerender(root);
      }
    };
    const change = (k) => {
      const n = find(k);
      if (n < 0) return;
      const p = st.res.planned[n];
      const current = (this._data.plan[p.date] || {})[p.meal] || p;
      this._openPicker(p.date, p.meal, current, false, {
        back: () => showResult(),
        saved: async (entry) => {
          if (entry) st.res.planned[n] = { ...entry, reasons: [], manual: true, cost: null };
          // the week's total and the new dish's cost (the plan's costs of that week)
          try {
            const day = fromIso(p.date);
            const monday = toIso(addDays(day, -weekdayIndex(day)));
            const costs = await this._service("get_costs", { start_date: monday, days: 7 }, true);
            if (costs?.total != null && st.res.week) st.res.week = { ...st.res.week, total: costs.total };
            const meal = (costs?.days || []).find((d) => d.date === p.date)?.meals?.find((m) => m.meal === p.meal);
            if (meal && st.res.planned[n]) st.res.planned[n].cost = meal.cost;
          } catch (e) {
            /* the total stays */
          }
          showResult();
        },
      });
    };
    const mountResult = (root) => {
      root.querySelector(".mbody").addEventListener("click", (ev) => {
        const re = ev.target.closest("[data-replan]");
        if (re) return replan(root, re.dataset.replan);
        const ch = ev.target.closest("[data-change]");
        if (ch && !st.rowBusy) change(ch.dataset.change);
      });
    };
    this._showModal("Woche automatisch planen", body, footer, (root) => {
      const go = root.querySelector(".go");
      go.addEventListener("click", async () => {
        if (st.busy) return;
        const meals = [...root.querySelectorAll(".pm:checked")].map((x) => x.value);
        const chosen = root.querySelector('input[name="strategy"]:checked')?.value;
        const withAi = Boolean(root.querySelector(".pai")?.checked);
        st.busy = withAi ? "ai" : "rules";
        go.disabled = true;
        go.innerHTML = withAi ? `<span class="spin">⏳</span> ${esc(this._aiName())} plant … (${AI_WAIT})` : "⏳ Plane …";
        root.querySelectorAll(".mbody input").forEach((x) => (x.disabled = true));
        let res;
        try {
          res = await this._service("auto_plan", { start_date: start, days, meals: meals.length ? meals : [this._data.default_meal], strategy: chosen, ...(withAi ? { ai: true } : {}) }, true);
        } catch (e) {
          st.busy = false;
          if (this._modal?.root !== root) return;
          go.disabled = false;
          go.textContent = "✨ Planen";
          root.querySelectorAll(".mbody input").forEach((x) => (x.disabled = false));
          return;
        }
        st.busy = false;
        const n = res?.planned?.length || 0;
        if (this._modal?.root !== root) {
          // closed meanwhile: the result as a toast
          this._toast(n ? `✨ ${n} Mahlzeiten eingeplant` : "Keine freien Plätze oder passenden Rezepte");
          return;
        }
        Object.assign(st, { res, usedAi: withAi, strategy: chosen || strategy });
        root.querySelector(".mbody").innerHTML = result();
        root.querySelector(".mfoot").innerHTML = `<button class="btn primary" data-close>✓ Fertig</button>`;
        mountResult(root);
      });
    }, {
      sticky: () => Boolean(st.busy || st.rowBusy),
      guard: () => st.busy !== "ai" || confirm(`${this._aiName()} plant noch. Trotzdem schließen? (Die Planung läuft weiter.)`),
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
      <div class="sotools sowhen">
        ${whens}
        <span class="seg" role="group" aria-label="Art">${kinds}</span>
      </div>
      <div class="sotools">
        <input type="search" placeholder="🔍 In den Angeboten suchen, z. B. „Kaffee“" value="${esc(so.query)}" data-input="so-query" data-focuskey="so-query" aria-label="In den Angeboten suchen">
        <label class="switch"><span class="wide-only">Sortieren</span> <select data-change="so-sort" aria-label="Sortieren">${Object.entries(OFFER_SORTS).map(([k, v]) => `<option value="${k}" ${k === so.sort ? "selected" : ""}>${v}</option>`).join("")}</select></label>
        <button class="btn" data-action="refresh-offers" ${busy ? "disabled" : ""}>${busy ? "⏳ Lade Angebote …" : "🔄 Aktualisieren"}</button>
        <button class="btn" data-action="add-offer">＋ Angebot<span class="wide-only"> eintragen</span></button>
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
    // 1.5.1: like the leaflets tab – on Sunday the leaflets from Monday are this week's
    const week = weekdayIndex(fromIso(today)) === 6 ? toIso(addDays(fromIso(today), 1)) : today;
    const fits = (lf) => when === "all" || (when === "current") === !(lf.valid_from && lf.valid_from > week);
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

  /** An offer card of the store offers; 1.5: also a product of the database (opts.product:
   *  ⭐, tap opens the details, its price source, "➕" puts the product on the list). */
  _soCardHtml(o, today, opts = {}) {
    const product = Boolean(opts.product);
    const ref = o.old_price || (product ? null : o.regular_price);
    const pack = packText(o.pack_amount, o.pack_unit);
    const desc = [pack, o.description && o.description !== pack ? o.description : ""].filter(Boolean).join(" · ");
    const badges = [];
    if (o.app_price != null) badges.push(`<span class="bdg warn" title="Preis mit der App des Händlers">mit App ${eur(o.app_price)}</span>`);
    else if (o.loyalty && !/payback/i.test(o.loyalty_note || "")) badges.push(`<span class="bdg warn" title="${esc(o.loyalty_note || "nur mit App/Kundenkarte")}">mit App/Karte</span>`);
    if (/payback/i.test(`${o.loyalty_note || ""} ${o.highlight || ""}`)) badges.push('<span class="bdg">PAYBACK</span>');
    if (o.online_only) badges.push('<span class="bdg bad">nur online</span>');
    if (o.deposit) badges.push(`<span class="bdg">+${eur(o.deposit)} Pfand</span>`);
    const until = validText(o, today);
    if (until) badges.push(`<span class="bdg ${o.current ? "" : "ok"}">${product ? "🏷️ " : ""}${esc(until)}</span>`);
    if (product) {
      if (!o.on_offer && o.regular_source && PRICE_SOURCE[o.regular_source]) badges.push(`<span class="bdg" title="Woher der Normalpreis stammt">${esc(PRICE_SOURCE[o.regular_source])}</span>`);
      if (o.stale && o.price != null) badges.push(`<span class="bdg warn" title="Preis länger nicht bestätigt">Stand ${esc(dayText(o.regular_seen || o.last_seen))}</span>`);
      if (o.bought) badges.push('<span class="bdg ok" title="Schon gekauft (Kassenzettel / abgehakt)">🧾 gekauft</span>');
      if (o.manual) badges.push('<span class="bdg" title="Eigener Artikel">✍️ eigener</span>');
      if (o.unsorted) badges.push('<span class="bdg warn" title="Die Regeln wissen nicht, was das ist – „🤖 Artikel sortieren“ oder selbst einordnen">❓ unsortiert</span>');
      else if (o.checked === "ai" && o.ai_fix) badges.push('<span class="bdg" title="Von der KI neu eingeordnet">🤖 einsortiert</span>');
    }
    const unit = o.unit_price != null && o.base_unit && o.base_unit !== "Stück" ? unitPriceText(o.unit_price, o.base_unit) : "";
    const ids = o.branch_ids || [];
    const branch = ids.length === 1 ? this._branch(ids[0]) : null;
    const where = branch ? branch.label : ids.length > 1 ? `${o.store} (${ids.length} Läden)` : o.store;
    const img = this._img(o.image, product ? CATEGORY_ICONS[o.category] || "📦" : "🏷️");
    const price = o.price != null ? `<span class="pr">${eur(o.price)}</span>` : '<span class="meta">kein Preis</span>';
    const fav = product
      ? `<button class="icon sofav ${o.favorite ? "on" : ""}" data-action="pr-fav" data-id="${esc(o.id)}" data-on="${o.favorite ? "1" : "0"}" aria-pressed="${o.favorite}" title="${o.favorite ? "Lieblingsprodukt – tippen zum Entfernen" : "Als Lieblingsprodukt merken (wird beim Einkauf bevorzugt)"}" aria-label="Lieblingsprodukt">${o.favorite ? "⭐" : "☆"}</button>`
      : "";
    const top = `<div class="soimg">${img}</div>
          <div class="sot">${o.brand ? `<div class="brand">${esc(o.brand)}</div>` : ""}<div class="pname">${esc(o.product || o.title)}</div>${desc ? `<div class="pack">${esc(desc)}</div>` : ""}</div>`;
    let acts;
    if (product) {
      acts = `<button class="btn small" data-action="pr-add" data-id="${esc(o.id)}" aria-label="Auf die Einkaufsliste" title="Auf die Einkaufsliste">➕<span class="albl"> Auf die Einkaufsliste</span></button>`;
    } else {
      // one of the planning offers already (📌 would only add a second copy)
      const counts = (this._data.offers || []).some((x) => String(x.id) === String(o.id));
      acts = `<button class="btn small" data-action="so-add" data-id="${esc(o.id)}" aria-label="Auf die Einkaufsliste" title="Auf die Einkaufsliste">➕<span class="albl"> Auf die Einkaufsliste</span></button>
          ${counts ? `<button class="btn small" data-action="so-pin" data-id="${esc(o.id)}" aria-label="Zählt schon" title="Passt zu deinen Rezepten oder der Einkaufsliste – zählt schon für Planung, Budget und Einkaufsliste">✓<span class="albl"> Zählt schon</span></button>` : `<button class="btn small" data-action="so-pin" data-id="${esc(o.id)}" aria-label="Merken" title="Als eigenes Angebot merken – zählt dann für Planung, Budget und Einkaufsliste">📌<span class="albl"> Merken</span></button>`}`;
    }
    return `<div class="card soffer ${o.current ? "" : "later"} ${product ? "prcard" : ""}">
        ${product ? `<div class="sotop" data-action="pr-open" data-enter="pr-open" data-id="${esc(o.id)}" role="button" tabindex="0" aria-label="${esc(o.title || o.product)} – Details">${top}</div>${fav}` : `<div class="sotop">${top}</div>`}
        <div class="soprice">${price}${ref && o.price != null && ref > o.price ? `<span class="old" title="${product || !o.old_price ? "Normalpreis" : "Streichpreis"}">${eur(ref)}</span>` : ""}${o.discount ? `<span class="disc">−${o.discount}%</span>` : ""}${unit ? `<span class="up">${esc(unit)}</span>` : ""}</div>
        <div class="someta"><span class="sostore">${retailerDot(o.retailer, o.store).replace('class="rdot"', 'class="rdot xs"')}<span class="sn">${esc(where)}</span></span>${badges.join("")}</div>
        <div class="acts">${acts}</div>
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

  /* ------------------------------------------------------------ images (1.5) */
  /** An image with its placeholder (emoji): no URL, a URL that failed before, or one that
   *  fails now (_brokenImage) shows the emoji instead. */
  _img(url, ph = "🛒", alt = "") {
    const src = safeUrl(url);
    if (!src || this._badImages.has(src)) return `<span class="imgph" aria-hidden="true">${esc(ph)}</span>`;
    return `<img loading="lazy" decoding="async" src="${esc(src)}" alt="${esc(alt)}" data-ph="${esc(ph)}">`;
  }

  _imageLoaded(img) {
    if (img?.tagName !== "IMG" || !img.naturalWidth) return;
    const box = img.parentElement;
    if (!box) return;
    const small = img.naturalWidth < box.clientWidth * 0.9 || img.naturalHeight < box.clientHeight * 0.9;
    img.classList.toggle("lowres", small);
  }

  _brokenImage(img) {
    if (img?.tagName !== "IMG" || img.dataset?.ph === undefined) return;
    const src = img.getAttribute("src");
    if (src) this._badImages.add(src);
    const span = document.createElement("span");
    span.className = "imgph";
    span.setAttribute("aria-hidden", "true");
    span.textContent = img.dataset.ph || "🛒";
    img.replaceWith(span);
  }

  /* ------------------------------------------------------------ 📦 Artikel (1.5) */
  _prStoreKey(st) {
    return st.branch_id ? `b:${st.branch_id}` : `r:${st.retailer}`;
  }

  _prPicked(stores) {
    const known = new Set((stores || []).map((st) => this._prStoreKey(st)));
    return new Set([...this._pr.stores].filter((key) => known.has(key)));
  }

  _prCard(id) {
    return this._pr.products.find((p) => p.id === id);
  }

  _renderProducts() {
    const pr = this._pr;
    if ((pr.stale || !pr.result) && !pr.loading) this._fetchProducts(false, Boolean(pr.result));
    const sorts = Object.entries(PRODUCT_SORTS)
      .map(([k, v]) => `<option value="${k}" ${k === pr.sort ? "selected" : ""}>${v}</option>`)
      .join("");
    return `<div class="products">
      <div class="prchips sochips" role="group" aria-label="Läden">${this._prChipsHtml()}</div>
      <div class="sotools">
        <input type="search" placeholder="🔍 Artikel oder Marke suchen, z. B. „Butter“" value="${esc(pr.query)}" data-input="pr-query" data-focuskey="pr-query" aria-label="Artikel suchen">
        <label class="switch">Sortieren <select data-change="pr-sort" aria-label="Sortieren">${sorts}</select></label>
        <button class="btn" data-action="pr-new" title="Einen Artikel mit Preis und Bild selbst eintragen">＋ Eigener Artikel</button>
        ${this._aiSortButton("products")}
      </div>
      <div class="praisort">${this._aiSortLine("products")}</div>
      <div class="sotools prfilter" role="group" aria-label="Filter">${this._prFilterHtml()}</div>
      <div class="prcats" role="group" aria-label="Kategorien">${this._prCatsHtml()}</div>
      <div class="prbody">${this._prBodyHtml()}</div>
    </div>`;
  }

  _prChipsHtml() {
    const stores = this._pr.result?.stores || [];
    if (!stores.length) return "";
    const picked = this._prPicked(stores);
    const perChain = new Map(stores.map((st) => [st.retailer, st.count || 0]));
    const total = [...perChain.values()].reduce((a, b) => a + b, 0);
    return `<button class="chip all ${picked.size ? "" : "active"}" data-action="pr-store" data-store="" aria-pressed="${!picked.size}">Alle Läden <span class="n">${total}</span></button>${stores
      .map((st) => {
        const key = this._prStoreKey(st);
        const on = picked.has(key);
        return `<button class="chip ${on ? "active" : ""}" data-action="pr-store" data-store="${esc(key)}" aria-pressed="${on}" title="${esc(st.store)}">${retailerDot(st.retailer, st.store).replace('class="rdot"', 'class="rdot xs"')}${esc(st.label)}${st.main ? " ⭐" : ""} <span class="n">${st.count || 0}</span></button>`;
      })
      .join("")}`;
  }

  _prFilterHtml() {
    const pr = this._pr;
    const kinds = OFFER_KINDS.map(([k, label]) => `<button class="${pr.kind === k ? "on" : ""}" data-action="pr-kind" data-kind="${k}" aria-pressed="${pr.kind === k}">${label}</button>`).join("");
    const counts = pr.result?.counts || this._data?.products || {};
    const n = { favorites: counts.favorites, offers: counts.offers, bought: counts.bought, manual: counts.manual, unsorted: counts.unsorted };
    const only = PRODUCT_ONLY.filter(([k]) => k !== "unsorted" || counts.unsorted || pr.only === k).map(
      ([k, label]) => `<button class="chip ${pr.only === k ? "active" : ""}" data-action="pr-only" data-only="${k}" aria-pressed="${pr.only === k}">${label}${n[k] != null ? ` <span class="n">${n[k]}</span>` : ""}</button>`
    ).join("");
    return `${only}<span class="seg" role="group" aria-label="Art">${kinds}</span>`;
  }

  _prCatsHtml() {
    const pr = this._pr;
    const cats = pr.result?.categories || [];
    if (cats.length < 2 && !pr.category) return "";
    return `<button class="chip ${pr.category ? "" : "active"}" data-action="pr-cat" data-cat="" aria-pressed="${!pr.category}">Alle Abteilungen</button>${cats
      .map((c) => {
        const on = c.name === pr.category;
        return `<button class="chip ${on ? "active" : ""}" data-action="pr-cat" data-cat="${esc(c.name)}" aria-pressed="${on}">${CATEGORY_ICONS[c.name] || "🛒"} ${esc(c.name)} <span class="n">${c.count}</span></button>`;
      })
      .join("")}`;
  }

  _prBodyHtml() {
    const pr = this._pr;
    const res = pr.result;
    if (!res) return pr.error ? `<div class="notice err">${esc(pr.error)}</div>` : `<div class="hint">⏳ Lade Artikel …</div>`;
    const counts = res.counts || this._data?.products || {};
    const notes = pr.error ? `<div class="notice err">${esc(pr.error)}</div>` : "";
    if (!counts.products) {
      return `${notes}<div class="empty"><div class="big">📦</div><b>Noch keine Artikel gespeichert.</b><br><span class="hint">Die Artikel-Datenbank füllt sich von selbst – ohne zusätzliche Abfragen: aus den Angeboten deiner Läden, den Onlinepreisen von REWE und ALDI SÜD, deinen Kassenzetteln und Artikeln, die du auf die Einkaufsliste setzt. Eigene Artikel (mit Preis und Bild) trägst du selbst ein.</span><div class="row" style="justify-content:center;margin:12px 0 0"><button class="btn primary" data-action="pr-new">＋ Eigener Artikel</button></div></div>`;
    }
    const today = this._today();
    const cards = pr.products.map((p) => this._soCardHtml(p, today, { product: true })).join("");
    const filtered = Boolean(pr.query.trim() || pr.category || pr.only || pr.stores.size || pr.kind !== "all");
    let empty = "";
    if (!pr.products.length && !pr.loading) {
      const what = pr.query.trim() ? `für „${esc(pr.query.trim())}“` : "für diese Auswahl";
      empty = `<div class="empty"><div class="big">🔎</div>Keine Artikel ${what}.${filtered ? `<div class="row" style="justify-content:center;margin:12px 0 0"><button class="btn" data-action="pr-reset">Filter zurücksetzen</button></div>` : ""}</div>`;
    }
    const more =
      pr.products.length < (res.total || 0)
        ? `<div class="row" style="justify-content:center;margin-top:12px"><button class="btn" data-action="pr-more" ${pr.loading ? "disabled" : ""}>${pr.loading ? "⏳ Lade …" : `Mehr laden (${pr.products.length} von ${res.total})`}</button></div>`
        : "";
    const count = `<div class="meta prcount">${res.total} ${res.total === 1 ? "Artikel" : "Artikel"}${pr.loading ? " · ⏳" : ""} · gespeichert aus Angeboten, Onlinepreisen, Kassenzetteln und deinen eigenen</div>`;
    return `${notes}${count}${cards ? `<div class="soffers">${cards}</div>` : empty}${more}`;
  }

  /** append: the next page; quiet: a change elsewhere – the shown pages again, no spinner. */
  async _fetchProducts(append = false, quiet = false) {
    const pr = this._pr;
    const seq = ++pr.seq;
    pr.loading = true;
    pr.stale = false;
    pr.error = null;
    if (!append && !quiet) this._renderProductParts();
    const limit = quiet && !append ? Math.min(100, Math.max(PRODUCT_PAGE, pr.products.length)) : PRODUCT_PAGE;
    const msg = { type: `${DOMAIN}/products`, kind: pr.kind, sort: pr.sort, offset: append ? pr.products.length : 0, limit };
    const branches = [...pr.stores].filter((k) => k.startsWith("b:")).map((k) => k.slice(2));
    const retailers = [...pr.stores].filter((k) => k.startsWith("r:")).map((k) => k.slice(2));
    if (branches.length) msg.branch_ids = branches;
    if (retailers.length) msg.retailers = retailers;
    if (pr.query.trim()) msg.query = pr.query.trim();
    if (pr.category) msg.category = pr.category;
    if (pr.only) msg.only = pr.only;
    try {
      const res = await this._hass.callWS(msg);
      if (seq !== pr.seq) return;
      // a remembered store that was removed: forget it and ask again
      const known = new Set((res.stores || []).map((st) => this._prStoreKey(st)));
      const gone = [...pr.stores].filter((k) => !known.has(k));
      if (gone.length && (res.stores || []).length) {
        gone.forEach((k) => pr.stores.delete(k));
        this._setPref("products_stores", JSON.stringify([...pr.stores]));
        pr.loading = false;
        return this._fetchProducts(append, quiet);
      }
      pr.result = res;
      pr.products = append ? [...pr.products, ...(res.products || []).filter((p) => !pr.products.some((x) => x.id === p.id))] : res.products || [];
    } catch (err) {
      if (seq !== pr.seq) return;
      pr.error = errText(err);
    }
    pr.loading = false;
    this._renderProductParts();
  }

  /** Chips, filters and cards (the search field keeps its focus and caret). */
  _renderProductParts() {
    if (this._tab !== "products") return;
    const part = (sel, html) => {
      const el = this._content.querySelector(sel);
      if (el) el.innerHTML = html;
    };
    part(".prchips", this._prChipsHtml());
    part(".praisort", this._aiSortLine("products"));
    part(".prfilter", this._prFilterHtml());
    part(".prcats", this._prCatsHtml());
    part(".prbody", this._prBodyHtml());
  }

  /** ➕: the product on the shopping list (its chain, its offer or regular price). */
  async _productToList(el, p) {
    if (!p?.id) return;
    if (el) el.disabled = true;
    try {
      const res = await this._service("add_shopping_item", { item: p.title || p.product || "", product_id: p.id }, true);
      const item = res?.item || {};
      const cost = item.price;
      const label = item.store_label || p.store || "";
      this._toast(`🛒 ${item.summary || p.title}${cost != null ? ` für ${eur(cost)}` : ""}${label ? ` bei ${label}` : ""} auf die Einkaufsliste gesetzt`);
      return item;
    } finally {
      if (el) el.disabled = false;
    }
  }

  /** ⭐ a product for an ingredient (key; default its first) or take the ⭐ away. */
  async _productFavorite(el, pid, key, on, title = "") {
    if (el) el.disabled = true;
    try {
      const msg = { type: `${DOMAIN}/product_favorite`, product_id: pid, favorite: on };
      if (key) msg.key = key;
      const res = await this._hass.callWS(msg);
      // show it at once (the change event reloads the list as well); a ⭐ moves from the
      // product that had it for this ingredient
      const favorites = res?.favorites || {};
      for (const p of this._pr.products) {
        p.favorite_keys = Object.keys(favorites).filter((k) => favorites[k] === p.id);
        p.favorite = p.favorite_keys.length > 0;
      }
      this._renderProductParts();
      const name = title || this._prCard(pid)?.title || "Artikel";
      this._toast(on ? `⭐ ${name} ist jetzt dein Lieblingsprodukt – wird beim Einkauf bevorzugt` : `☆ ${name} ist kein Lieblingsprodukt mehr`);
      return res;
    } catch (err) {
      this._toast(errText(err));
      throw err;
    } finally {
      if (el) el.disabled = false;
    }
  }

  /** Price history as a small line chart (offer prices orange). */
  _sparkline(history) {
    const pts = (history || []).filter((h) => h && h.price != null && h.date).sort((a, b) => String(a.date).localeCompare(String(b.date)));
    if (pts.length < 2) {
      return `<div class="hint">${pts.length ? `Bisher ein Preis: ${eur(pts[0].price)} am ${esc(dayText(pts[0].date))}${pts[0].kind === "offer" ? " (Angebot)" : ""}.` : "Noch kein Preisverlauf."} Er entsteht, wenn der Artikel in Angeboten, Onlinepreisen oder auf Kassenzetteln wieder auftaucht.</div>`;
    }
    const W = 320;
    const H = 96;
    const P = 10;
    const prices = pts.map((p) => Number(p.price));
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    // evenly spaced in their order (a regular and an offer price can share a day)
    const x = (i) => Math.round((P + (i / (pts.length - 1)) * (W - 2 * P)) * 10) / 10;
    const y = (p) => Math.round((max === min ? H / 2 : P + ((max - Number(p.price)) / (max - min)) * (H - 2 * P)) * 10) / 10;
    const line = pts.map((p, i) => `${x(i)},${y(p)}`).join(" ");
    const dots = pts
      .map((p, i) => `<circle class="${p.kind === "offer" ? "o" : "r"}" cx="${x(i)}" cy="${y(p)}" r="4"><title>${esc(dayText(p.date))}: ${esc(eur(p.price))}${p.kind === "offer" ? " (Angebot)" : ""}</title></circle>`)
      .join("");
    const label = `Preisverlauf von ${eur(min)} bis ${eur(max)}`;
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}"><polyline class="ln" points="${line}"></polyline>${dots}</svg>
      <div class="meta sparklegend"><span>${esc(dayText(pts[0].date))} – ${esc(dayText(pts[pts.length - 1].date))}</span><span>günstigster ${eur(min)} · teuerster ${eur(max)}</span><span><i class="dot r"></i> Normalpreis <i class="dot o"></i> Angebot</span></div>`;
  }

  async _openProduct(pid) {
    let detail;
    try {
      detail = await this._hass.callWS({ type: `${DOMAIN}/product_detail`, product_id: pid });
    } catch (err) {
      this._toast(errText(err));
      return;
    }
    const today = this._today();
    const body = () => {
      const p = detail.product;
      const pack = packText(p.pack_amount, p.pack_unit);
      const unit = p.unit_price != null && p.base_unit && p.base_unit !== "Stück" ? unitPriceText(p.unit_price, p.base_unit) : "";
      const until = validText(p, today);
      const regular = p.regular_price != null ? `Normalpreis ${eur(p.regular_price)}${p.regular_source && PRICE_SOURCE[p.regular_source] ? ` · ${PRICE_SOURCE[p.regular_source]}` : ""}${p.regular_seen ? ` · Stand ${dayText(p.regular_seen)}` : ""}` : "";
      const favs = new Set(detail.favorite_for || []);
      const keys = detail.keys || [];
      const favHtml = keys.length
        ? `<div class="favkeys">${keys
            .map((k) => {
              const on = favs.has(k.key);
              return `<button class="chip ${on ? "active" : ""}" data-fav="${esc(k.key)}" data-on="${on ? "1" : "0"}" aria-pressed="${on}">${on ? "⭐" : "☆"} ${esc(k.name)}</button>`;
            })
            .join("")}</div><div class="hint">Ein Lieblingsprodukt wird beim Erstellen der Einkaufsliste für diese Zutat genommen – und der Laden richtet sich danach.</div>`
        : `<div class="favkeys"><button class="chip" data-fav="" data-on="0" aria-pressed="false">☆ Als Lieblingsprodukt merken</button></div><div class="hint">Noch keiner Zutat zugeordnet – gemerkt wird er für „${esc(p.product || p.title)}“.</div>`;
      const twins = (detail.twins || [])
        .map((t) => `<button class="pick" data-twin="${esc(t.id)}">${retailerDot(t.retailer, t.store)}<span class="pi"><b>${esc(t.store)}</b><div class="sub">${esc([packText(t.pack_amount, t.pack_unit), t.on_offer ? `🏷️ Angebot ${validText(t, today)}` : ""].filter(Boolean).join(" · "))}</div></span><span class="pp">${t.price != null ? `<b>${eur(t.price)}</b>` : '<span class="meta">–</span>'}</span></button>`)
        .join("");
      const picks = (detail.picks || []).map((k) => `${k.kind === "bought" ? "🧾 gekauft" : "👆 gewählt"}: ${k.count}× (zuletzt ${dayText(k.last)})`);
      return `<div class="prhero">
          <div class="prbig">${this._img(p.image, CATEGORY_ICONS[p.category] || "📦")}</div>
          <div class="prinfo">
            ${p.brand ? `<div class="brand">${esc(p.brand)}</div>` : ""}
            <div class="pname">${esc(p.product || p.title)}</div>
            <div class="meta">${esc([pack, p.category].filter(Boolean).join(" · "))}</div>
            <div class="prprice">${p.price != null ? `<span class="pr">${eur(p.price)}</span>` : '<span class="meta">kein Preis</span>'}${p.old_price && p.price != null && p.old_price > p.price ? `<span class="old">${eur(p.old_price)}</span>` : ""}${p.discount ? `<span class="disc">−${p.discount}%</span>` : ""}${unit ? `<span class="up">${esc(unit)}</span>` : ""}</div>
            <div class="badges"><span class="bdg">${retailerDot(p.retailer, p.store).replace('class="rdot"', 'class="rdot xs"')} ${esc(p.store)}</span>${until ? `<span class="bdg ${p.current ? "warn" : "ok"}">🏷️ Angebot ${esc(until)}</span>` : ""}${p.stale && p.price != null ? '<span class="bdg warn">Preis länger nicht bestätigt</span>' : ""}${p.manual ? '<span class="bdg">✍️ eigener Artikel</span>' : ""}</div>
            ${regular && (p.on_offer || p.stale) ? `<div class="meta">${esc(regular)}</div>` : regular ? `<div class="meta">${esc(regular.replace(/^Normalpreis [^·]*· ?/, "") || "")}</div>` : ""}
          </div>
        </div>
        <div class="section"><h4>⭐ Lieblingsprodukt für …</h4>${favHtml}</div>
        <div class="section"><h4>📈 Preisverlauf</h4>${this._sparkline(detail.history)}</div>
        ${this._prSortHtml(p, detail)}
        ${twins ? `<div class="section"><h4>🔁 Auch bei …</h4><div class="hint">Der gleiche Markenartikel bei deinen anderen Läden.</div><div class="picklist" style="max-height:none">${twins}</div></div>` : ""}
        ${picks.length ? `<div class="meta">${esc(picks.join(" · "))}</div>` : ""}`;
    };
    const p0 = detail.product;
    const footer = `${p0.manual ? `<button class="btn danger" data-pdel>🗑 Löschen</button><button class="btn" data-pedit>✏️ Bearbeiten</button>` : ""}<button class="btn" data-precipe title="Fertiggericht: ein Rezept mit diesem Artikel als Zutat">🍕 Als Rezept speichern</button><button class="btn primary" data-padd>➕ Auf die Einkaufsliste</button>`;
    this._showModal(`📦 Artikel bei ${p0.store || this._retailerName(p0.retailer)}`, `<div class="prdetail">${body()}</div>`, footer, (root) => {
      const box = root.querySelector(".prdetail");
      const reload = async () => {
        try {
          detail = await this._hass.callWS({ type: `${DOMAIN}/product_detail`, product_id: detail.product.id });
          if (this._modal?.root === root) box.innerHTML = body();
        } catch (err) {
          /* the product is gone: keep what is shown */
        }
      };
      box.addEventListener("click", async (ev) => {
        const sortBtn = ev.target.closest("[data-psort]");
        if (sortBtn) {
          const keysText = box.querySelector("[data-pkeys]")?.value || "";
          sortBtn.disabled = true;
          try {
            await this._hass.callWS({
              type: `${DOMAIN}/product_classify`,
              product_id: detail.product.id,
              category: box.querySelector("[data-pcat]")?.value || null,
              kind: box.querySelector("[data-pkind]")?.value || null,
              keys: keysText.split(",").map((k) => k.trim()).filter(Boolean),
            });
            this._toast(`✋ ${detail.product.title} eingeordnet – die KI ändert das nicht mehr`);
            this._pr.stale = true;
            await reload();
          } catch (err) {
            this._toast(errText(err));
            sortBtn.disabled = false;
          }
          return;
        }
        const fav = ev.target.closest("[data-fav]");
        if (fav) {
          try {
            await this._productFavorite(fav, detail.product.id, fav.dataset.fav, fav.dataset.on !== "1", detail.product.title);
            await reload();
          } catch (e) {
            /* toast shown */
          }
          return;
        }
        const twin = ev.target.closest("[data-twin]");
        if (twin) this._openProduct(twin.dataset.twin);
      });
      root.querySelector("[data-padd]").addEventListener("click", async (ev) => {
        try {
          await this._productToList(ev.currentTarget, detail.product);
          this._closeModal();
        } catch (e) {
          /* toast shown */
        }
      });
      root.querySelector("[data-precipe]").addEventListener("click", async (ev) => {
        const btn = ev.currentTarget;
        btn.disabled = true;
        try {
          const res = await this._hass.callWS({ type: `${DOMAIN}/product_to_recipe`, product_id: detail.product.id });
          this._toast(`🍕 Rezept „${res?.recipe?.name || detail.product.title}“ gespeichert – zu finden unter 📖 Rezepte`);
          this._closeModal();
        } catch (err) {
          this._toast(errText(err));
        } finally {
          btn.disabled = false;
        }
      });
      root.querySelector("[data-pedit]")?.addEventListener("click", () => {
        const key = (detail.keys || [])[0];
        this._openProductForm({ ...detail.product, ingredient: key ? key.name : "", favorite: (detail.favorite_for || []).length > 0 });
      });
      root.querySelector("[data-pdel]")?.addEventListener("click", async (ev) => {
        if (!confirm(`„${detail.product.title}“ aus deinen Artikeln löschen? Auch sein ⭐ und was beim Einkauf gelernt wurde, sind dann weg.`)) return;
        const btn = ev.currentTarget;
        btn.disabled = true;
        try {
          await this._hass.callWS({ type: `${DOMAIN}/product_delete`, product_id: detail.product.id });
          this._toast(`🗑 ${detail.product.title} gelöscht`);
          this._closeModal();
          this._pr.products = this._pr.products.filter((x) => x.id !== detail.product.id);
          this._fetchProducts(false, true);
        } catch (err) {
          this._toast(errText(err));
          btn.disabled = false;
        }
      });
    });
  }

  /** 1.5.1: who sorted the product and "✋ So einordnen" (aisle, kind, ingredients). */
  _prSortHtml(p, detail) {
    const by = p.checked ? CHECKED_LABELS[p.checked] || p.checked : "❓ noch nicht eingeordnet – die Regeln wissen nicht, was das ist";
    const fix = p.checked === "ai" && p.ai_fix?.before ? p.ai_fix.before : null;
    const before = fix ? ` · vorher: ${[fix.category, PRODUCT_KIND_LABELS[fix.kind] || (fix.kind === "unknown" ? "unbekannt" : fix.kind)].filter(Boolean).join(", ")}` : "";
    const kind = p.unsorted ? "" : p.kind;
    const cats = CATEGORY_ORDER.map((c) => `<option value="${esc(c)}" ${c === p.category ? "selected" : ""}>${CATEGORY_ICONS[c] || ""} ${esc(c)}</option>`).join("");
    const kinds = `${kind ? "" : '<option value="" selected>– bitte wählen –</option>'}${Object.entries(PRODUCT_KIND_LABELS)
      .map(([k, label]) => `<option value="${k}" ${k === kind ? "selected" : ""}>${esc(label)}</option>`)
      .join("")}`;
    const keys = (detail.keys || []).map((k) => k.name).join(", ");
    return `<div class="section"><h4>🗂️ Einordnung</h4>
      <div class="meta">${esc(by)}${p.checked_at && p.checked !== "rule" ? ` (${esc(dayText(p.checked_at))})` : ""}${esc(before)}</div>
      <div class="grid2">
        <label class="field">Abteilung<select data-pcat>${cats}</select></label>
        <label class="field">Art<select data-pkind>${kinds}</select></label>
      </div>
      <label class="field">Zutat(en) – kommagetrennt, leer = keine<input data-pkeys value="${esc(keys)}" placeholder="z. B. Butter"></label>
      <div class="row"><button class="btn small" data-psort>✋ So einordnen</button><span class="hint">Was du hier einstellst, ändert die KI nie.</span></div>
    </div>`;
  }

  /** "＋ Eigener Artikel" (prefill.id: change that own product). */
  _openProductForm(prefill = {}) {
    const editing = Boolean(prefill.id);
    const retailers = this._data.economy?.retailers || [];
    const mine = [...new Set((this._data.branches || []).filter((b) => b.selected).map((b) => b.retailer))].filter(Boolean);
    const selected = prefill.retailer || this._data.economy?.main_retailer || mine[0] || "";
    const option = (r) => `<option value="${esc(r.id)}" ${r.id === selected ? "selected" : ""}>${esc(r.name)}</option>`;
    const own = retailers.filter((r) => mine.includes(r.id));
    const others = retailers.filter((r) => !mine.includes(r.id));
    const stores = own.length ? `<optgroup label="Meine Läden">${own.map(option).join("")}</optgroup><optgroup label="Weitere Ketten">${others.map(option).join("")}</optgroup>` : chainOptions(retailers, selected);
    const cats = CATEGORY_ORDER.map((c) => `<option value="${esc(c)}" ${c === (prefill.manual ? prefill.category : "") ? "selected" : ""}>${CATEGORY_ICONS[c] || ""} ${esc(c)}</option>`).join("");
    const price = prefill.regular_source === "user" || prefill.manual ? num(prefill.regular_price) : "";
    const body = `
      <div class="hint">Ein Artikel mit deinem Preis – er erscheint bei „📦 Artikel“, in der Suche „Artikel hinzufügen“ und kann dein Lieblingsprodukt werden. Bilder nur als Link (https://…).</div>
      <div class="pfhead"><div class="prbig pfprev">${this._img(prefill.image, CATEGORY_ICONS[prefill.category] || "📦")}</div>
        <div class="pfmain">
          <label class="field">Name *<input class="pf-name" placeholder="z. B. Hafer Drink Barista" value="${esc(prefill.product || prefill.name || "")}" autocomplete="off"></label>
          <label class="field">Marke<input class="pf-brand" placeholder="z. B. Vemondo" value="${esc(prefill.brand || "")}" autocomplete="off"></label>
        </div></div>
      <div class="grid2">
        <label class="field">Laden *<select class="pf-store">${stores}</select></label>
        <label class="field">Packung<input class="pf-pack" placeholder="z. B. 1 l, 500 g, 6 Stück" value="${esc(prefill.pack || packText(prefill.pack_amount, prefill.pack_unit) || "")}"></label>
        <label class="field">Preis (€)<input class="pf-price" inputmode="decimal" placeholder="z. B. 1,29" value="${esc(price)}"></label>
        <label class="field">Zutat (für Rezepte & Einkaufsliste)<input class="pf-ing" placeholder="z. B. Haferdrink" value="${esc(prefill.ingredient || "")}" autocomplete="off"></label>
        <label class="field">Abteilung<select class="pf-cat"><option value="">automatisch</option>${cats}</select></label>
        <label class="field">Bild (Link)<input class="pf-image" type="url" inputmode="url" placeholder="https://…" value="${esc(prefill.image || "")}"></label>
      </div>
      <label class="switch"><input type="checkbox" class="pf-fav" ${prefill.favorite ? "checked" : ""}> ⭐ Lieblingsprodukt für diese Zutat</label>
      <div class="ferr pf-err" role="alert" hidden></div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">💾 Speichern</button>`;
    this._showModal(editing ? "Eigenen Artikel bearbeiten" : "＋ Eigener Artikel", body, footer, (root) => {
      const $ = (sel) => root.querySelector(sel);
      const err = $(".pf-err");
      $(".pf-name").focus();
      $(".pf-image").addEventListener("input", (ev) => {
        $(".pfprev").innerHTML = this._img(ev.target.value.trim(), "📦");
      });
      // a hint about a field goes away as soon as it is changed
      root.querySelector(".mbody").addEventListener("input", () => {
        err.hidden = true;
      });
      let saving = false;
      $(".save").addEventListener("click", async () => {
        if (saving) return;
        const v = (sel) => $(sel).value.trim();
        const product = { store: v(".pf-store"), name: v(".pf-name") };
        if (!product.name) {
          err.hidden = false;
          err.textContent = "Bitte einen Namen angeben.";
          $(".pf-name").focus();
          return;
        }
        if (editing) product.id = prefill.id;
        product.brand = v(".pf-brand");
        if (v(".pf-pack")) product.pack = v(".pf-pack");
        if (v(".pf-price")) {
          const n = parseNum(v(".pf-price"));
          if (!Number.isFinite(n) || n < 0) {
            err.hidden = false;
            err.textContent = "Bitte einen Preis wie 1,29 eingeben.";
            $(".pf-price").focus();
            return;
          }
          product.price = n;
        }
        if (v(".pf-ing")) product.ingredient = v(".pf-ing");
        if (v(".pf-cat")) product.category = v(".pf-cat");
        product.image = v(".pf-image");
        if ($(".pf-fav").checked) product.favorite = true;
        else if (prefill.favorite) product.favorite = false;
        saving = true;
        err.hidden = true;
        try {
          const res = await this._hass.callWS({ type: `${DOMAIN}/product_save`, product });
          this._closeModal();
          this._toast(`📦 ${res?.product?.title || product.name} gespeichert`);
          this._pr.stale = true;
          if (this._tab === "products") this._fetchProducts(false, true);
        } catch (e) {
          err.hidden = false;
          err.textContent = errText(e);
        } finally {
          saving = false;
        }
      });
    });
  }

  /** "Produkt wechseln": the products for the item's ingredient at every saved chain,
   *  cheapest for the needed amount first; "⭐ immer dieses" makes it the favourite. */
  async _openProductSwap(uid) {
    const item = (this._data.shopping || []).find((i) => i.uid === uid);
    if (!item) return;
    let res = null;
    let error = null;
    let selected = item.product_reason === "manual" && item.product?.id ? item.product.id : "";
    let initial = selected;
    let favorite = false;
    const today = this._today();
    const amountText = () => {
      const a = res?.amounts || {};
      const parts = Object.entries(a).map(([unit, n]) => packText(n, unit) || `${num(n)} ${unit}`);
      return parts.join(" + ");
    };
    const listHtml = () => {
      if (error) return `<div class="notice err">${esc(error)}</div>`;
      if (!res) return `<div class="hint">⏳ Suche passende Artikel …</div>`;
      const alts = res.alternatives || [];
      const auto = `<button class="pick ${selected === "" ? "sel" : ""}" data-pid=""><span class="sthumb">🤖</span><span class="pi"><b>Automatisch</b><div class="sub">⭐ Lieblingsprodukt, sonst ein schon gekaufter oder der günstigste passende Artikel im Laden</div></span></button>`;
      if (!alts.length) {
        return `${auto}<div class="empty" style="padding:20px 8px"><div class="big">📦</div>Für „${esc(res.name || item.summary)}“ kenne ich noch keine Artikel.<br><span class="hint">Sie kommen aus Angeboten, Onlinepreisen und Kassenzetteln – oder du trägst einen eigenen ein.</span><div class="row" style="justify-content:center;margin:12px 0 0"><button class="btn" data-pnew>＋ Eigener Artikel</button></div></div>`;
      }
      const priced = alts.filter((a) => a.cost != null);
      const min = priced.length ? Math.min(...priced.map((a) => a.cost)) : null;
      const unique = priced.filter((a) => a.cost === min).length === 1 && priced.length > 1;
      const rows = alts
        .map((a) => {
          const tags = [
            a.id === res.current ? '<span class="bdg">aktuell</span>' : "",
            a.id === res.favorite ? '<span class="bdg star">⭐</span>' : "",
            unique && a.cost === min ? '<span class="bdg ok">günstigster</span>' : "",
            a.on_offer ? `<span class="bdg warn">🏷️ ${esc(validText(a, today) || "Angebot")}</span>` : "",
          ].join(" ");
          const unit = a.unit_price != null && a.base_unit && a.base_unit !== "Stück" ? unitPriceText(a.unit_price, a.base_unit) : "";
          const sub = [a.pack || packText(a.pack_amount, a.pack_unit), unit].filter(Boolean).join(" · ");
          const cost = a.cost != null ? `<b>${eur(a.cost)}</b>${a.packs > 1 ? `<span class="meta">${a.packs} × ${eur(a.price)}</span>` : ""}` : '<span class="meta">kein Preis</span>';
          return `<button class="pick swaprow ${selected === a.id ? "sel" : ""}" data-pid="${esc(a.id)}"><span class="sthumb">${this._img(a.image, CATEGORY_ICONS[a.category] || "📦")}</span>
            <span class="pi">${a.brand ? `<span class="pbrand">${esc(a.brand)}</span> ` : ""}<b>${esc(a.product || a.title)}</b> ${tags}<div class="sub"><span class="schip">${retailerDot(a.retailer, a.store).replace('class="rdot"', 'class="rdot xs"')}${esc(a.store)}</span>${esc(sub ? ` · ${sub}` : "")}</div></span>
            <span class="pp">${cost}</span></button>`;
        })
        .join("");
      return auto + rows;
    };
    const favHtml = () => {
      if (!selected) return "";
      if (res?.favorite === selected) return `<div class="hint">⭐ Das ist schon dein Lieblingsprodukt für ${esc(res.name || "diese Zutat")}.</div>`;
      return `<label class="switch"><input type="checkbox" class="favchk" ${favorite ? "checked" : ""}> ⭐ Immer dieses (Lieblingsprodukt für ${esc(res?.name || item.name || item.summary)})</label>`;
    };
    const hintHtml = () => {
      const amount = res ? amountText() : "";
      return `<div class="hint">${amount ? `Kosten für die benötigte Menge (${esc(amount)}), ganze Packungen` : "Preise je Packung"} – aus allen deinen Läden, günstigste zuerst.</div>`;
    };
    const body = `<div class="swaphint">${hintHtml()}</div><div class="picklist swaplist" style="max-height:none">${listHtml()}</div><div class="favbox">${favHtml()}</div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">✓ Übernehmen</button>`;
    this._showModal(`Produkt wählen – ${item.summary}`, body, footer, (root) => {
      const list = root.querySelector(".swaplist");
      const box = root.querySelector(".favbox");
      const refresh = () => {
        list.innerHTML = listHtml();
        box.innerHTML = favHtml();
        root.querySelector(".swaphint").innerHTML = hintHtml();
      };
      list.addEventListener("click", (ev) => {
        if (ev.target.closest("[data-pnew]")) {
          this._openProductForm({ retailer: item.retailer || "", ingredient: res?.name || item.name || "" });
          return;
        }
        const pick = ev.target.closest("[data-pid]");
        if (!pick) return;
        if (selected !== pick.dataset.pid) favorite = false;
        selected = pick.dataset.pid;
        refresh();
      });
      box.addEventListener("change", (ev) => {
        if (ev.target.classList.contains("favchk")) favorite = ev.target.checked;
      });
      let saving = false;
      root.querySelector(".save").addEventListener("click", async () => {
        if (selected === initial && !favorite) return this._closeModal();
        if (saving) return;
        saving = true;
        try {
          const remember = selected ? (favorite ? "favorite" : "pick") : "none";
          const out = await this._hass.callWS({ type: `${DOMAIN}/shopping_set_product`, uid, product_id: selected || null, remember });
          this._closeModal();
          const p = out?.item?.product;
          const where = out?.item?.store_label ? ` bei ${out.item.store_label}` : "";
          const price = out?.item?.price != null ? ` (≈ ${eur(out.item.price)})` : "";
          this._toast(selected ? `📦 ${item.summary}: ${p?.title || "Produkt"}${where}${price}${favorite ? " – ⭐ ab jetzt immer" : ""}` : `🤖 ${item.summary}: Produkt wird automatisch gewählt`);
        } catch (err) {
          this._toast(errText(err));
        } finally {
          saving = false;
        }
      });
      this._hass
        .callWS({ type: `${DOMAIN}/product_alternatives`, uid, limit: 30 })
        .then((r) => {
          res = r;
          if (!initial && item.product_reason === "manual" && r.current) initial = selected = r.current;
        })
        .catch((err) => {
          error = errText(err);
        })
        .finally(() => {
          if (this._modal?.root === root) refresh();
        });
    });
  }

  /* ------------------------------------------------------------ 📰 Prospekte (1.5) */
  _lfCount() {
    const res = this._lf.result;
    return res && res.meta?.marktguru !== false ? ` (${(res.leaflets || []).filter((l) => l.current).length})` : "";
  }

  _renderLeaflets() {
    const lf = this._lf;
    if ((lf.stale || !lf.result) && !lf.loading) this._fetchLeaflets();
    return `<div class="sotools lftools">${this._lfToolsHtml()}</div><div class="lfbody">${this._lfBodyHtml()}</div>`;
  }

  _lfToolsHtml() {
    const lf = this._lf;
    const busy = this._refreshing.has("offers-tab");
    const mg = this._lf.result?.meta?.marktguru;
    return `${LEAFLET_WHEN.map(([k, label]) => `<button class="chip ${lf.when === k ? "active" : ""}" data-action="lf-when" data-when="${k}" aria-pressed="${lf.when === k}">${label}</button>`).join("")}<span class="spacer"></span>${mg ? `<button class="btn" data-action="refresh-offers" ${busy ? "disabled" : ""}>${busy ? "⏳ Lade …" : "🔄 Aktualisieren"}</button>` : ""}`;
  }

  async _fetchLeaflets() {
    const lf = this._lf;
    const seq = ++lf.seq;
    lf.loading = true;
    lf.stale = false;
    lf.error = null;
    try {
      const res = await this._hass.callWS({ type: `${DOMAIN}/leaflets`, when: "all" });
      if (seq !== lf.seq) return;
      lf.result = res;
    } catch (err) {
      if (seq !== lf.seq) return;
      lf.error = errText(err);
    }
    lf.loading = false;
    this._renderLeafletParts();
  }

  _renderLeafletParts() {
    if (this._tab !== "offers" || this._offersMode !== "leaflets") return;
    const tools = this._content.querySelector(".lftools");
    if (tools) tools.innerHTML = this._lfToolsHtml();
    const body = this._content.querySelector(".lfbody");
    if (body) body.innerHTML = this._lfBodyHtml();
    const count = this._content.querySelector("[data-lfcount]");
    if (count) count.textContent = this._lfCount();
  }

  _lfTileHtml(l, today) {
    const until = validText(l, today);
    const named = l.name && fold(l.name) !== fold(l.store) ? l.name : "";
    const labels = (l.labels || []).join(" · ");
    const meta = [l.page_count ? `${l.page_count} Seiten` : "", labels].filter(Boolean).join(" · ");
    const inner = `<span class="lfcover">${this._img(l.cover, "📰")}</span>${l.current ? "" : '<span class="bdg ok lfnext">📅 nächste Woche</span>'}
      <span class="lfinfo"><span class="lfstore">${retailerDot(l.retailer, l.store).replace('class="rdot"', 'class="rdot xs"')}<b>${esc(l.store)}</b></span>${named ? `<span class="lfname">${esc(named)}</span>` : ""}${until ? `<span class="meta">${l.current ? "gültig " : ""}${esc(until)}</span>` : ""}${meta ? `<span class="meta">${esc(meta)}</span>` : ""}</span>`;
    if (l.page_url_template) return `<button class="lftile" data-action="lf-open" data-id="${esc(l.id)}" aria-label="Prospekt ${esc(l.store)}${named ? ` ${esc(named)}` : ""} öffnen">${inner}</button>`;
    const url = httpLink(l.url);
    return url ? `<a class="lftile" href="${esc(url)}" target="_blank" rel="noreferrer" title="Im Browser öffnen">${inner}<span class="lfext">↗</span></a>` : `<div class="lftile">${inner}</div>`;
  }

  /** A chain without leaflet pictures here: its own leaflet page (no request). */
  _lfLinkTileHtml(link, note) {
    const url = httpLink(link.url);
    if (!url) return "";
    return `<a class="lftile link" href="${esc(url)}" target="_blank" rel="noreferrer"><span class="lfcover">${retailerDot(link.retailer, link.store)}<span>📰</span></span><span class="lfext">↗</span>
      <span class="lfinfo"><span class="lfstore"><b>Prospekt bei ${esc(link.store)}</b></span>${note ? `<span class="meta">${esc(note)}</span>` : ""}${(link.labels || []).length ? `<span class="meta">${esc(link.labels.join(" · "))}</span>` : ""}</span></a>`;
  }

  _lfBodyHtml() {
    const lf = this._lf;
    const res = lf.result;
    if (!res) return lf.error ? `<div class="notice err">${esc(lf.error)}</div>` : `<div class="hint">⏳ Lade Prospekte …</div>`;
    const meta = res.meta || {};
    const today = this._today();
    const fits = (l) => lf.when === "all" || (lf.when === "current") === Boolean(l.current);
    const leaflets = (res.leaflets || []).filter(fits);
    const notes = [];
    if (lf.error) notes.push(`<div class="notice err">${esc(lf.error)}</div>`);
    if (!(res.branches || []).length && !(this._data.branches || []).length) {
      notes.push(`<div class="notice">🏪 Speichere zuerst deine Läden im Tab <button class="btn small" data-action="go-tab" data-tab="stores" data-sec="mine">🏪 Läden & Preise</button> – dann siehst du hier die Prospekte dieser Läden.</div>`);
    }
    if (!meta.marktguru) {
      notes.push(`<div class="notice">📰 Prospekte zum Blättern kommen über marktguru (inoffiziell – ${esc(MG_WARNING)}) ${this._settingsLink("offers", "⚙️ Angebote & Preisquellen")}<br>Ohne marktguru: die Prospektseiten deiner Ketten – sie öffnen im Browser, der Essensplaner fragt dafür nichts ab.</div>`);
    } else if (meta.all_leaflets === false) {
      notes.push(`<div class="hint" style="margin-bottom:10px">ℹ️ Nur Prospekte der Läden ohne Einzelangebote. Alle Filialen: „Prospekte aller Filialen“ einschalten – ${this._settingsLink("offers", "⚙️ Angebote")}</div>`);
    }
    if ((meta.errors || []).length) notes.push(`<div class="notice warn">⚠️ ${esc(meta.errors[0])}</div>`);
    // in the order of the saved branches; chains of leaflets without a branch last
    const order = [];
    for (const b of res.branches || []) if (!order.includes(b.retailer)) order.push(b.retailer);
    for (const l of res.leaflets || []) if (l.retailer && !order.includes(l.retailer)) order.push(l.retailer);
    const rank = (r) => (order.includes(r) ? order.indexOf(r) : 999);
    const tiles = [...leaflets].sort((a, b) => rank(a.retailer) - rank(b.retailer) || Number(b.current) - Number(a.current)).map((l) => this._lfTileHtml(l, today));
    // chains with a leaflet page of their own but no leaflet shown here: a link tile
    const none = meta.marktguru ? (lf.when === "upcoming" ? "noch kein Prospekt für nächste Woche" : "kein Prospekt über marktguru") : "";
    const linkTiles = (res.links || []).filter((k) => !leaflets.some((l) => l.retailer === k.retailer)).map((k) => this._lfLinkTileHtml(k, none));
    const grid = [...tiles, ...linkTiles].join("");
    // the chains' own pages for the chains shown with leaflet pictures
    const pages = (res.links || []).filter((k) => leaflets.some((l) => l.retailer === k.retailer) && httpLink(k.url));
    const chainLinks = pages.length
      ? `<div class="lflinks"><span class="meta">Auf den Seiten der Ketten:</span>${pages.map((k) => `<a class="btn small" href="${esc(httpLink(k.url))}" target="_blank" rel="noreferrer">${retailerDot(k.retailer, k.store).replace('class="rdot"', 'class="rdot xs"')}${esc(k.store)} ↗</a>`).join("")}</div>`
      : "";
    const empty = !grid ? `<div class="empty"><div class="big">📰</div>${lf.when === "upcoming" ? "Noch keine Prospekte für nächste Woche – sie kommen meist ab Sonntag." : "Keine Prospekte gefunden."}</div>` : "";
    const updated = meta.updated ? `<div class="meta" style="margin-top:10px">🕘 Prospekte aktualisiert ${esc(timeText(meta.updated))}</div>` : "";
    return `${notes.join("")}${grid ? `<div class="lftiles">${grid}</div>` : empty}${chainLinks}${updated}`;
  }

  /** Full-screen leaflet viewer: swipe / ‹ › through the pages (scroll snap), pages load
   *  near the shown one, double tap or 🔍 zooms (bigger image), "Öffnen ↗" on marktguru. */
  _openLeaflet(id, start = 0) {
    const l = (this._lf.result?.leaflets || []).find((x) => x.id === id);
    if (!l) return;
    if (!l.page_url_template) {
      const url = httpLink(l.url);
      if (url) window.open(url, "_blank", "noopener");
      return;
    }
    const count = Math.max(1, Number(l.page_count) || (l.pages || []).length || 1);
    const pages = Array.from(
      { length: count },
      (_, i) => `<div class="lfpage" data-page="${i}"><img alt="Seite ${i + 1}" data-ph="📄" data-src="${esc(safeUrl(leafletPage(l.page_url_template, i, l.page_base)))}" data-zoom="${esc(safeUrl(leafletPage(l.zoom_url_template, i, l.page_base)))}" draggable="false"></div>`
    ).join("");
    const url = httpLink(l.url);
    const valid = validText(l, this._today());
    this._modalRoot.innerHTML = `
      <div class="lfoverlay" role="dialog" aria-label="Prospekt ${esc(l.store)} ${esc(l.name || "")}">
        <div class="lfvhead">
          <div class="lfvtitle">${retailerDot(l.retailer, l.store).replace('class="rdot"', 'class="rdot sm"')}<span><b>${esc(l.name || l.store)}</b>${valid ? ` · ${esc(valid)}` : ""}</span></div>
          <span class="lfvpos" aria-live="polite">1 / ${count}</span>
          <button class="icon" data-lfzoom title="Vergrößern (Doppeltippen)" aria-label="Vergrößern" aria-pressed="false">🔍</button>
          ${url ? `<a class="btn small" href="${esc(url)}" target="_blank" rel="noreferrer" title="Prospekt im Browser öffnen">Öffnen ↗</a>` : ""}
          <button class="icon" data-close title="Schließen" aria-label="Schließen">✕</button>
        </div>
        <div class="lfvpages" tabindex="0" aria-label="Seiten">${pages}</div>
        <button class="lfnav prev" data-lfnav="-1" aria-label="Vorige Seite">‹</button>
        <button class="lfnav next" data-lfnav="1" aria-label="Nächste Seite">›</button>
        <div class="lfvfoot"><input type="range" class="lfslider" min="1" max="${count}" value="1" aria-label="Seite"><span class="meta">${esc((l.labels || []).join(" · "))}</span></div>
      </div>`;
    const root = this._modalRoot.querySelector(".lfoverlay");
    const scroller = root.querySelector(".lfvpages");
    const pos = root.querySelector(".lfvpos");
    const slider = root.querySelector(".lfslider");
    const zoomBtn = root.querySelector("[data-lfzoom]");
    const view = { id, count, index: -1, zoom: false, root };
    this._modal = { root, guard: null };
    this._lfView = view;
    const load = (i) => {
      const img = scroller.children[i]?.querySelector("img[data-src]");
      if (img && !img.getAttribute("src")) img.setAttribute("src", img.dataset.src);
    };
    const setZoom = (on) => {
      const page = scroller.children[view.index];
      view.zoom = on;
      zoomBtn.setAttribute("aria-pressed", String(on));
      scroller.classList.toggle("zooming", on);
      for (const el of scroller.querySelectorAll(".lfpage.zoom")) if (el !== page || !on) el.classList.remove("zoom");
      if (!page) return;
      const img = page.querySelector("img");
      if (on) {
        page.classList.add("zoom");
        if (img?.dataset.zoom && img.getAttribute("src") !== img.dataset.zoom) img.setAttribute("src", img.dataset.zoom);
      }
    };
    const update = () => {
      const width = scroller.clientWidth || 1;
      const i = Math.max(0, Math.min(count - 1, Math.round(scroller.scrollLeft / width)));
      if (i === view.index) return;
      if (view.zoom) setZoom(false);
      view.index = i;
      pos.textContent = `${i + 1} / ${count}`;
      slider.value = String(i + 1);
      for (let k = i - 1; k <= i + 2; k++) if (k >= 0 && k < count) load(k);
    };
    view.go = (i, smooth = true) => {
      const target = Math.max(0, Math.min(count - 1, i));
      if (view.zoom) setZoom(false);
      scroller.scrollTo({ left: target * scroller.clientWidth, behavior: smooth ? "smooth" : "auto" });
      // a smooth scroll ends with a scroll event; an instant one may not move at all
      if (!smooth) update();
    };
    let frame = 0;
    scroller.addEventListener("scroll", () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    });
    let lastTap = 0;
    scroller.addEventListener("click", (ev) => {
      if (!ev.target.closest(".lfpage")) return;
      const now = Date.now();
      if (now - lastTap < 350) {
        lastTap = 0;
        setZoom(!view.zoom);
      } else lastTap = now;
    });
    root.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-close]")) return this._requestCloseModal();
      const nav = ev.target.closest("[data-lfnav]");
      if (nav) return view.go(view.index + Number(nav.dataset.lfnav));
      if (ev.target.closest("[data-lfzoom]")) setZoom(!view.zoom);
    });
    slider.addEventListener("input", () => view.go(Number(slider.value) - 1, false));
    // the start page (instant), pages around it load
    requestAnimationFrame(() => {
      view.go(start, false);
      update();
      scroller.focus({ preventScroll: true });
    });
  }

  /* ------------------------------------------------------------ occasions, drinks, season (1.5) */
  _occasionsOn(iso) {
    return (this._data.occasions || []).filter((o) => o.date === iso);
  }

  _occView(id) {
    return (this._data.occasions || []).find((o) => o.id === id) || null;
  }

  _occTemplate(id) {
    return (this._data.occasion_meta?.templates || []).find((t) => t.id === id) || null;
  }

  _courseInfo(id) {
    return (this._data.occasion_meta?.courses || []).find((c) => c.id === id) || { id, label: id, emoji: "" };
  }

  /** An AI feature is switched on with an AI (its button shows). */
  _aiOn(feature) {
    return Boolean(this._data?.ai?.enabled?.[feature]);
  }

  _aiName() {
    return this._data?.ai?.label || "Die KI";
  }

  /** Switched on, but the AI is not reachable right now. */
  _aiOffline(feature) {
    return this._aiOn(feature) && !this._data?.ai?.ready?.[feature];
  }

  /** 1.5.1: "🤖 Artikel sortieren" / "🤖 Rezepte sortieren" (only with the feature on). */
  _aiSortButton(target) {
    if (!this._aiOn(target)) return "";
    const sort = this._data?.ai?.sort || {};
    const busy = (this._aiSorting || new Set()).has(target) || sort.running?.target === target;
    const label = target === "products" ? "Artikel sortieren" : "Rezepte sortieren";
    const title = this._aiOffline(target) ? `${this._aiName()} ist gerade nicht erreichbar` : target === "products" ? `${this._aiName()} prüft Abteilung, Art und Zutat der Artikel, die nur nach Regeln eingeordnet sind – deine Einordnungen bleiben` : `${this._aiName()} prüft, ob Rezepte Mahlzeit, Snack, Getränk … sind – deine Wahl bleibt`;
    return `<button class="btn" data-action="ai-sort" data-target="${target}" ${busy ? "disabled" : ""} title="${esc(title)}">${busy ? `<span class="spin">⏳</span> sortiert …` : `🤖 ${label}`}</button>`;
  }

  /** "🤖 Zuletzt sortiert: 09.11., 23 geändert · nächste Kontrolle So 03:15". */
  _aiSortLine(target, named = false) {
    const sort = this._data?.ai?.sort;
    const info = sort?.[target];
    if (!sort || !info) return "";
    const what = named ? `${target === "products" ? "Artikel" : "Rezepte"}: ` : "";
    if (!info.enabled) return named ? `${what}aus` : "";
    const run = sort.running;
    if (run && run.target === target) return `<span class="meta">🤖 ${what}${esc(this._aiName())} sortiert … (Anfrage ${run.request} von höchstens ${run.requests})</span>`;
    const parts = [];
    const res = info.result || {};
    if (info.last_run) {
      const counts = [`${res.changed || 0} geändert`];
      if (res.removed) counts.push(`${res.removed} Non-Food entfernt`);
      if (res.remaining) counts.push(`${res.remaining} noch offen`);
      parts.push(`Zuletzt sortiert: ${esc(timeText(info.last_run))}, ${counts.join(", ")}`);
    } else {
      parts.push(target === "products" ? "Noch nicht von der KI sortiert" : "Noch nicht von der KI geprüft");
    }
    if (target === "recipes" && info.pending) parts.push(`${info.pending} nach Regeln`);
    if (sort.next_run) parts.push(`nächste Kontrolle ${esc(weekdayTime(sort.next_run))}`);
    const warn = info.last_ok === false && (res.errors || []).length ? `<br><span class="bdg warn">⚠️ ${esc(res.errors[0])}</span> <span class="meta">Es bleibt bei den Regeln.</span>` : "";
    return `<span class="meta">🤖 ${what}${parts.join(" · ")}</span>${warn}`;
  }

  /** Start the AI sorting (target products | recipes) and show what it did. */
  async _aiSort(target, el) {
    this._aiSorting = this._aiSorting || new Set();
    if (this._aiSorting.has(target)) return;
    this._aiSorting.add(target);
    if (el) {
      el.disabled = true;
      el.innerHTML = `<span class="spin">⏳</span> sortiert …`;
    }
    this._toast(`🤖 ${this._aiName()} sortiert die ${target === "products" ? "Artikel" : "Rezepte"} – das kann ein paar Minuten dauern.`);
    try {
      const res = await this._hass.callWS({ type: `${DOMAIN}/ai_sort`, target });
      const part = res?.[target] || res || {};
      if (part.ok === false && !part.checked) {
        this._toast(`🤖 ${(part.errors || res?.errors || [])[0] || "Die KI hat nicht geantwortet."} Es bleibt bei den Regeln.`);
      } else {
        const bits = [`${part.checked || 0} geprüft`, `${part.changed || 0} geändert`];
        if (part.removed) bits.push(`${part.removed} Non-Food entfernt`);
        if (part.remaining) bits.push(`${part.remaining} noch offen – einfach noch mal drücken`);
        this._toast(`🤖 ${target === "products" ? "Artikel" : "Rezepte"} sortiert: ${bits.join(", ")}`);
      }
    } catch (err) {
      this._toast(errText(err));
    } finally {
      this._aiSorting.delete(target);
      if (target === "products") {
        this._pr.stale = true;
        if (this._tab === "products") this._renderContent();
      } else if (this._tab === "recipes") this._renderContent();
    }
  }

  /** A recipe's season (🍂 badge) – or null. */
  _seasonOf(id) {
    const s = this._data?.recipe_season?.[id];
    return s && s.score >= SEASON_BADGE && (s.items?.length || s.hints?.length) ? s : null;
  }

  _occCardHtml(o) {
    const who = `👥 ${o.guests}${o.children ? `+${o.children}` : ""}`;
    const meta = [o.time || "ganztägig", who].join(" · ");
    const tip = [o.summary, `${o.guests} Gäste${o.children ? `, ${o.children} Kinder` : ""}`].filter(Boolean).join(" – ");
    const cost = o.cost?.total ? ` · <span class="cost">≈ ${euShort(o.cost.total)}</span>` : "";
    return `<button class="occ" data-action="occasion-open" data-id="${esc(o.id)}" title="${esc(tip)}">
        <span class="oemoji" aria-hidden="true">${esc(o.emoji || "🎉")}</span>
        <span class="otxt"><div class="t">${esc(o.title)}</div><div class="s">${esc(meta)}${cost}</div></span>
      </button>`;
  }

  /** "Jetzt Saison: Kürbis, Grünkohl … 🏮 Martinstag" below the hero. */
  _renderSeasonRow() {
    const s = this._data.season;
    const produce = s?.produce || [];
    if (!produce.length && !(s?.windows || []).length) return "";
    const names = produce
      .slice(0, 7)
      .map((p) => `${esc(p.label)}${p.new ? '<span title="neu in der Saison">✨</span>' : ""}`)
      .join(", ");
    const windows = (s.windows || []).map((w) => `<span class="bdg">${esc(w.emoji)} ${esc(w.label)}</span>`).join(" ");
    const soon = (s.upcoming || []).slice(0, 2).map((w) => `${esc(w.emoji)} ${esc(w.label)} ab ${esc(dayText(w.start))}`).join(", ");
    return `<div class="card seasonrow">
        <span class="semoji" aria-hidden="true">${esc(s.season?.emoji || "🍂")}</span>
        <div class="stxt"><b>Jetzt Saison:</b> ${names || "–"}${produce.length > 7 ? " …" : ""} ${windows}${soon ? ` <span class="meta">· bald: ${soon}</span>` : ""}</div>
        <button class="btn small" data-action="season-open">🍂 <span class="wide-only">Saisonkalender</span><span class="narrow-only">Kalender</span></button>
      </div>`;
  }

  /** The season of a month: produce, times of the year, fitting recipes (ws season). */
  _openSeason() {
    const today = this._today();
    let year = Number(today.slice(0, 4));
    let month = Number(today.slice(5, 7));
    let seq = 0;
    const current = () => year === Number(today.slice(0, 4)) && month === Number(today.slice(5, 7));
    const html = (v) => {
      const produce = v.produce || [];
      const chip = (p) => `<span class="bdg ${p.strict ? "ok" : ""}" title="${p.new ? "neu in der Saison" : p.ending ? "bald vorbei" : ""}">${esc(p.label)}${p.new ? " ✨" : p.ending ? " ⏳" : ""}</span>`;
      const windows = (v.windows || []).map((w) => `<span class="bdg"><b>${esc(w.emoji)} ${esc(w.label)}</b></span>`).join("");
      const upcoming = (v.upcoming || []).map((w) => `<span class="bdg">${esc(w.emoji)} ${esc(w.label)} ab ${esc(dayText(w.start))}</span>`).join("");
      const recipes = (v.recipes || [])
        .map((r) => `<button class="sg" data-season-recipe="${esc(r.id)}"><span class="sthumb">${r.image && safeUrl(r.image) ? this._img(r.image, dishEmoji(r.name)) : dishEmoji(r.name)}</span><span class="sgt"><b>${esc(r.name)}</b><div class="why">${esc((r.hints || []).join(" · "))}</div></span></button>`)
        .join("");
      const out = (v.out_of_season || []).map((r) => `${esc(r.name)} <span class="meta">(${esc((r.items || []).join(", "))})</span>`).join(" · ");
      return `
        <div class="seasonhead"><button class="icon" data-smonth="-1" aria-label="Vorheriger Monat" title="Vorheriger Monat">‹</button><b>${esc(v.season?.emoji || "")} ${esc(v.season?.label || "")} · ${esc(v.month_name || "")} ${esc(String(v.date || "").slice(0, 4))}</b><button class="icon" data-smonth="1" aria-label="Nächster Monat" title="Nächster Monat">›</button></div>
        ${v.season_aware === false ? `<div class="notice warn">„Saison berücksichtigen“ ist aus: Vorschläge achten nur mit der Planungsart „🍂 Saisonal“ auf die Saison. <button class="btn small" data-season-settings>⚙️ Budget & Planung</button></div>` : ""}
        ${windows || upcoming ? `<div><h4>Zeit des Jahres</h4><div class="prodchips">${windows}${upcoming}</div></div>` : ""}
        <div><h4>Obst, Gemüse & Co. der Saison</h4>${produce.length ? `<div class="prodchips">${produce.map(chip).join("")}</div><div class="hint" style="margin-top:6px">✨ neu in der Saison · ⏳ bald vorbei · grün: typisch für diese Zeit</div>` : '<div class="hint">Nichts Besonderes.</div>'}</div>
        <div><h4>Passt aus deinen Rezepten</h4>${recipes ? `<div class="srecipes">${recipes}</div>` : '<div class="hint">Keine deiner Rezepte passt besonders – frag Jarvis „Was hat gerade Saison?“ oder importiere ein Saisonrezept.</div>'}</div>
        ${out ? `<details class="srcbox"><summary>Gerade nicht in Saison (${(v.out_of_season || []).length})</summary><div style="line-height:1.6">${out}</div></details>` : ""}`;
    };
    this._showModal("🍂 Saisonkalender", '<div class="loading">Lade …</div>', `<button class="btn primary" data-close>Schließen</button>`, (root) => {
      const body = root.querySelector(".mbody");
      const load = async () => {
        const my = ++seq;
        const msg = { type: `${DOMAIN}/season`, limit: 12 };
        if (!current()) msg.date = `${year}-${pad2(month)}-15`;
        try {
          const v = await this._hass.callWS(msg);
          if (my !== seq || this._modal?.root !== root) return;
          body.innerHTML = html(v);
        } catch (err) {
          if (my === seq && this._modal?.root === root) body.innerHTML = `<div class="notice err">${esc(errText(err))}</div>`;
        }
      };
      root.addEventListener("click", (ev) => {
        const step = ev.target.closest("[data-smonth]");
        if (step) {
          month += Number(step.dataset.smonth);
          if (month < 1) [month, year] = [12, year - 1];
          if (month > 12) [month, year] = [1, year + 1];
          load();
          return;
        }
        const r = ev.target.closest("[data-season-recipe]");
        if (r) return this._openRecipe(r.dataset.seasonRecipe);
        if (ev.target.closest("[data-season-settings]")) {
          this._closeModal();
          this._openSettings("planning");
        }
      });
      load();
    });
  }

  /** "🎉 Anlass planen": template, date, time, guests – then the editor. */
  _openOccasionNew(prefill = {}) {
    const templates = this._data.occasion_meta?.templates || [];
    let tpl = prefill.template || templates[0]?.id || "anlass";
    const info = (id) => templates.find((t) => t.id === id) || { title: "Anlass", emoji: "🎉", time: "" };
    // default: the next Saturday of the shown week (from today on)
    const todayDate = fromIso(this._today());
    const from = this._weekStart && this._weekStart > todayDate ? this._weekStart : todayDate;
    const date = prefill.date || toIso(addDays(from, (5 - weekdayIndex(from) + 7) % 7));
    let timeEdited = false;
    const body = `
      <div class="hint">Ein Anlass hat eigene Gänge (Vorspeise, Hauptgang, Beilagen, Dessert, Snacks), Getränke und Zubehör – mit Kosten und eigener Einkaufsliste. Er steht im Wochenplan und im Kalender.</div>
      <div class="tplgrid" role="radiogroup" aria-label="Vorlage">${templates
        .map((t) => `<button type="button" role="radio" aria-checked="${t.id === tpl}" class="${t.id === tpl ? "on" : ""}" data-tpl="${esc(t.id)}"><span class="e" aria-hidden="true">${esc(t.emoji)}</span><b>${esc(t.title)}</b><span class="meta">${t.time ? `${esc(t.time)} Uhr` : ""}</span></button>`)
        .join("")}</div>
      <label class="field">Name (optional)<input class="otitle" maxlength="80" placeholder="${esc(info(tpl).title)}"></label>
      <div class="grid2">
        <label class="field">Datum<input type="date" class="odate" value="${esc(date)}"></label>
        <label class="field">Uhrzeit<input type="time" class="otime" value="${esc(info(tpl).time || "")}"></label>
        <label class="field">Gäste (Erwachsene)<input type="number" inputmode="numeric" class="oguests" min="1" max="200" value="${esc(prefill.guests || this._data.default_servings || 2)}"></label>
        <label class="field">Kinder<input type="number" inputmode="numeric" class="ochildren" min="0" max="100" value="0"></label>
      </div>
      <label class="switch"><input type="checkbox" class="ofill" checked> ✨ Gerichte, Getränke und Zubehör gleich vorschlagen</label>
      <div class="ferr" hidden></div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary osave">🎉 Anlegen</button>`;
    this._showModal("🎉 Anlass planen", body, footer, (root) => {
      const grid = root.querySelector(".tplgrid");
      const title = root.querySelector(".otitle");
      const time = root.querySelector(".otime");
      time.addEventListener("input", () => (timeEdited = true));
      grid.addEventListener("click", (ev) => {
        const b = ev.target.closest("[data-tpl]");
        if (!b) return;
        tpl = b.dataset.tpl;
        grid.querySelectorAll("[data-tpl]").forEach((x) => {
          x.classList.toggle("on", x === b);
          x.setAttribute("aria-checked", String(x === b));
        });
        title.placeholder = info(tpl).title;
        if (!timeEdited) time.value = info(tpl).time || "";
      });
      const save = root.querySelector(".osave");
      save.addEventListener("click", async () => {
        const err = root.querySelector(".ferr");
        const occasion = {
          template: tpl,
          date: root.querySelector(".odate").value || this._today(),
          guests: Math.max(1, Number(root.querySelector(".oguests").value) || 1),
          children: Math.max(0, Number(root.querySelector(".ochildren").value) || 0),
          auto_fill: root.querySelector(".ofill").checked,
        };
        if (title.value.trim()) occasion.title = title.value.trim();
        if (time.value) occasion.time = time.value;
        save.disabled = true;
        save.textContent = occasion.auto_fill ? "⏳ Stelle zusammen …" : "⏳ Lege an …";
        err.hidden = true;
        try {
          const res = await this._hass.callWS({ type: `${DOMAIN}/occasion_save`, occasion });
          if (this._modal?.root !== root) return;
          this._toast(`🎉 ${res.occasion.label}: ${this._dateLabel(res.occasion.date)}`);
          this._openOccasion(res.occasion.id, res.occasion);
        } catch (e) {
          err.hidden = false;
          err.textContent = errText(e);
          save.disabled = false;
          save.textContent = "🎉 Anlegen";
        }
      });
    }, { sticky: true });
  }

  /** The occasion editor (full screen on phones). Every change is saved at once. */
  _openOccasion(id, view = null) {
    view = view || this._occView(id);
    if (!view) return this._toast("Diesen Anlass gibt es nicht mehr.");
    const st = { id, view, saving: 0, saved: false, error: null, add: null, menu: null, drinks: null, extras: null, extraCourses: new Set(), queue: Promise.resolve(), draft: {}, applying: false };
    this._occ = st;
    const footer = `<button class="btn danger" data-oc="delete" aria-label="Anlass löschen" title="Anlass löschen">🗑<span class="wide-only"> Löschen</span></button><span class="spacer"></span><button class="btn" data-oc="shop" title="Einkaufsliste für den Anlass">🛒 Einkaufsliste<span class="wide-only"> für den Anlass</span></button><button class="btn primary" data-close>✓ Fertig</button>`;
    this._showModal(view.label || view.title, this._occBodyHtml(st), footer, (root) => {
      st.root = root;
      root.addEventListener("click", (ev) => {
        const step = ev.target.closest("[data-ostep]");
        if (step) return this._occStep(st, step.dataset.ostep, Number(step.dataset.delta));
        const el = ev.target.closest("[data-oc]");
        if (!el || el.matches("input[type=checkbox]")) return;
        this._occAction(st, el.dataset.oc, el).catch(() => {});
      });
      root.addEventListener("change", (ev) => this._occChange(st, ev.target));
      root.addEventListener("input", (ev) => {
        if (!ev.target.classList.contains("oaddq") || !st.add) return;
        st.add.query = ev.target.value;
        const box = root.querySelector(".oaddres");
        if (box) box.innerHTML = this._occAddResultsHtml(st);
      });
      root.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter") return;
        if (ev.target.classList.contains("oprodq")) {
          ev.preventDefault();
          this._occAction(st, "prod-search", ev.target).catch(() => {});
          return;
        }
        if (!ev.target.classList.contains("oaddq")) return;
        ev.preventDefault();
        this._occAction(st, "add-text", ev.target).catch(() => {});
      });
      this._occLoadExtras(st);
    }, {
      full: true,
      cls: "occmodal",
      sticky: true,
      guard: () => this._occ !== st || !(st.menu?.aiBusy || st.drinks?.aiBusy) || confirm(`${this._aiName()} arbeitet noch. Trotzdem schließen?`),
    });
  }

  _occStepper(key, label, value, min, max) {
    return `<div class="field"><span>${label}</span><span class="stepper2"><button class="icon" data-ostep="${key}" data-delta="-1" aria-label="${label}: weniger" ${value <= min ? "disabled" : ""}>−</button><input type="number" inputmode="numeric" class="o${key}" data-ofocus="${key}" min="${min}" max="${max}" value="${value}" aria-label="${label}"><button class="icon" data-ostep="${key}" data-delta="1" aria-label="${label}: mehr" ${value >= max ? "disabled" : ""}>＋</button></span></div>`;
  }

  _occBodyHtml(st) {
    const o = st.view;
    const templates = this._data.occasion_meta?.templates || [];
    const guests = st.draft.guests ?? o.guests;
    const children = st.draft.children ?? o.children ?? 0;
    const head = `<div class="ochead">
        <label class="field oname">Name<input class="otitle" data-ofocus="title" maxlength="80" value="${esc(o.title)}"></label>
        <label class="field">Vorlage<select class="otpl" data-ofocus="tpl">${templates.map((t) => `<option value="${esc(t.id)}" ${t.id === o.template ? "selected" : ""}>${esc(t.emoji)} ${esc(t.title)}</option>`).join("")}</select></label>
        <label class="field">Datum<input type="date" class="odate" data-ofocus="date" value="${esc(o.date)}"></label>
        <label class="field">Uhrzeit<input type="time" class="otime" data-ofocus="time" value="${esc(o.time || "")}" ${o.time ? "" : "disabled"}></label>
        <label class="switch"><input type="checkbox" class="oallday" data-ofocus="allday" ${o.time ? "" : "checked"}> ganztägig</label>
        ${this._occStepper("guests", "Gäste", guests, 1, 200)}
        ${this._occStepper("children", "Kinder", children, 0, 100)}
      </div>`;
    const cost = o.cost || {};
    const sum = `<div class="ocsum">
        <span class="big">≈ ${eur(cost.total || 0)}</span>
        <span class="meta">${eur(cost.per_person || 0)} pro Person · ${o.persons || guests} Personen, ${o.servings || guests} Portionen · Schätzung</span>
        ${cost.on_offer?.length ? `<span class="meta">🏷️ Im Angebot: ${esc(cost.on_offer.slice(0, 4).join(", "))}</span>` : ""}
        ${cost.unknown?.length ? `<span class="meta">Ohne Preis: ${esc(cost.unknown.slice(0, 5).join(", "))}${cost.unknown.length > 5 ? " …" : ""}</span>` : ""}
      </div>`;
    const busy = Boolean(st.menu?.loading || st.menu?.aiBusy || st.applying);
    const ai = this._aiOn("occasions");
    const tools = `<div class="ocmore">
        <button class="btn small" data-oc="menu" ${busy ? "disabled" : ""}>💡 Menü vorschlagen</button>
        ${ai ? `<button class="btn small" data-oc="menu-ai" ${busy ? "disabled" : ""} title="${esc(this._aiOffline("occasions") ? `${this._aiName()} ist gerade nicht erreichbar` : `${this._aiName()} stellt ein Menü aus deinen Rezepten zusammen`)}">${st.menu?.aiBusy ? `<span class="spin">⏳</span> ${esc(this._aiName())} denkt nach …` : "🤖 KI-Menü"}</button>` : ""}
        <span class="ocstate" aria-live="polite">${st.saving ? "⏳ Speichere …" : st.saved ? "✓ gespeichert" : ""}</span>
      </div>`;
    const shown = (o.courses || []).map((c) => c.id);
    for (const c of [...st.extraCourses, "drink", "extra"]) if (!shown.includes(c)) shown.push(c);
    shown.sort((a, b) => OCC_COURSES.indexOf(a) - OCC_COURSES.indexOf(b));
    const others = OCC_COURSES.filter((c) => !shown.includes(c));
    const more = others.length ? `<div class="ocmore"><span class="meta">Weitere Gänge:</span>${others.map((c) => `<button class="chip ocplus" data-oc="course-add" data-course="${c}">${esc(COURSE_ADD[c])}</button>`).join("")}</div>` : "";
    const notes = `<details class="ocnotes" ${o.notes ? "open" : ""}><summary>📝 Notizen</summary><textarea class="onotes" data-ofocus="notes" maxlength="500" placeholder="z. B. wer was mitbringt, Allergien …">${esc(o.notes || "")}</textarea></details>`;
    return `${head}${sum}${st.error ? `<div class="notice err">${esc(st.error)}</div>` : ""}${tools}${this._occMenuHtml(st)}
      <div class="occourses">${shown.map((c) => this._occCourseHtml(st, c)).join("")}</div>
      ${more}${notes}`;
  }

  _occCourseHtml(st, course) {
    const o = st.view;
    const info = (o.courses || []).find((c) => c.id === course) || { ...this._courseInfo(course), cost: null };
    const items = (o.items || []).filter((i) => i.course === course);
    const head = `<h4>${esc(info.emoji || this._courseInfo(course).emoji)} ${esc(info.label || this._courseInfo(course).label)}${items.length && info.cost != null ? `<span class="meta">≈ ${eur(info.cost)}</span>` : ""}</h4>`;
    const adding = st.add?.course === course;
    const addBtn = adding ? this._occAddHtml(st) : `<div><button class="btn small" data-oc="add" data-course="${course}">${esc(COURSE_ADD[course])}</button></div>`;
    if (course === "extra") {
      const prod = st.prod && items.some((i) => i.uid === st.prod.uid) ? this._occProdHtml(st) : "";
      return `<section class="ocsec ${prod ? "wide" : ""}" data-course="extra">${head}${this._occExtrasHtml(st, items)}${prod}${addBtn}</section>`;
    }
    const chips = items.map((i) => this._occChipHtml(st, i)).join("");
    const prod = st.prod && items.some((i) => i.uid === st.prod.uid) ? this._occProdHtml(st) : "";
    return `<section class="ocsec ${adding || prod ? "wide" : ""}" data-course="${course}">${head}
        ${chips ? `<div class="ocitems">${chips}</div>` : `<div class="hint">${course === "drink" ? "Noch keine Getränke." : "Noch nichts geplant."}</div>`}
        ${prod}
        ${this._occMissingHtml(st, course)}
        ${addBtn}
      </section>`;
  }

  _occChipHtml(st, i) {
    const recipe = i.recipe_id ? this._recipe(i.recipe_id) : null;
    const icon = i.course === "drink" ? drinkEmoji(i) : recipe ? dishEmoji(recipe.name) : i.product ? "📦" : "📝";
    const thumb = i.image && safeUrl(i.image) ? `<span class="othumb" ${bg(i.image)}></span>` : `<span class="othumb" aria-hidden="true">${icon}</span>`;
    const product = i.product ? [i.product.title, i.product.retailer ? this._retailerName(i.product.retailer) : ""].filter(Boolean).join(" · ") : "";
    const sub = [product, i.cost != null ? `≈ ${eur(i.cost)}` : ""].filter(Boolean).join(" · ");
    const title = [i.hint, i.note, i.ai ? "🤖 von der KI vorgeschlagen" : "", i.missing ? "nicht mehr vorhanden" : ""].filter(Boolean).join(" · ");
    const inner = `${thumb}<span>${esc(i.title)}${i.ai ? " 🤖" : ""}</span>${sub ? `<span class="meta">${esc(sub)}</span>` : ""}${i.course === "drink" ? alcBadge(i.alcohol) : ""}`;
    const main = recipe ? `<button class="on" data-oc="recipe" data-id="${esc(recipe.id)}" title="${esc(title || "Rezept öffnen")}">${inner}</button>` : `<span class="on" title="${esc(title)}">${inner}</span>`;
    const why = i.reason ? `<span class="why">🤖 ${esc(i.reason)}</span>` : "";
    return `<span class="occhip ${i.ai ? "ai" : ""} ${i.missing ? "missing" : ""} ${st.prod?.uid === i.uid ? "sel" : ""}"><span class="ocr1">${main}<button class="icon" data-oc="remove" data-uid="${esc(i.uid)}" aria-label="${esc(i.title)} entfernen" title="Entfernen">✕</button></span><span class="ocr2">${this._occAmtHtml(st, i)}</span>${why}</span>`;
  }

  /** 1.5.1: the amount of an item – servings of a dish, packs of a product, quantity and
   *  unit of anything else (− / ＋ or typed; saved after a short pause); 📦 links a
   *  product of the user's stores. */
  _occAmtHtml(st, i) {
    if (i.missing) return "";
    const uid = esc(i.uid);
    const d = st.amt?.[i.uid] || {};
    const btn = (delta, label, off) => `<button class="icon" data-oc="amt" data-uid="${uid}" data-delta="${delta}" aria-label="${esc(i.title)}: ${label}" ${off ? "disabled" : ""}>${delta < 0 ? "−" : "＋"}</button>`;
    if (i.recipe_id) {
      const v = Number(d.servings ?? i.servings ?? st.view.servings ?? 1);
      return `<span class="ocamt" role="group" aria-label="Portionen">${btn(-1, "weniger Portionen", v <= 1)}<input type="number" inputmode="numeric" min="1" max="500" step="1" class="oamt" data-uid="${uid}" data-ofocus="amt-${uid}" value="${v}" aria-label="${esc(i.title)}: Portionen"><span class="u">Port.</span>${btn(1, "mehr Portionen", v >= 500)}</span>`;
    }
    const linked = Boolean(i.product_id);
    const unit = linked ? "Pck." : d.unit ?? i.unit ?? "";
    const q = d.quantity ?? i.quantity;
    const value = q != null && q !== "" ? Number(q) : "";
    const step = amtStep(unit);
    const units = [...new Set([...(unit ? [unit] : []), ...OCC_UNITS])];
    const unitHtml = linked
      ? `<span class="u">Pck.</span>`
      : `<select class="ounit" data-uid="${uid}" data-ofocus="unit-${uid}" aria-label="${esc(i.title)}: Einheit">${unit ? "" : '<option value="" selected>–</option>'}${units.map((u) => `<option ${u === unit ? "selected" : ""}>${esc(u)}</option>`).join("")}</select>`;
    const prod = `<button class="icon prodbtn ${linked ? "on" : ""}" data-oc="prod" data-uid="${uid}" title="${linked ? "Anderen Artikel wählen" : "Artikel aus deinen Läden wählen"}" aria-label="${esc(i.title)}: Artikel wählen">📦</button>`;
    return `<span class="ocamt" role="group" aria-label="Menge">${btn(-1, "weniger", value === "" || value <= step)}<input type="number" inputmode="decimal" min="0" step="${step}" class="oamt" data-uid="${uid}" data-ofocus="amt-${uid}" value="${value === "" ? "" : Math.round(value * 1000) / 1000}" placeholder="Menge" aria-label="${esc(i.title)}: Menge">${unitHtml}${btn(1, "mehr", false)}</span>${prod}`;
  }

  /** "📦 Artikel" of an item: the products of the user's stores for its amount. */
  _occProdHtml(st) {
    const p = st.prod;
    const item = (st.view.items || []).find((x) => x.uid === p.uid);
    if (!item) return "";
    let list;
    if (p.loading) list = '<div class="hint">⏳ Suche Artikel …</div>';
    else if (p.error) list = `<div class="notice err">${esc(p.error)}</div>`;
    else {
      const rows = (p.res?.products || [])
        .map((a) => {
          const cur = a.id === item.product_id;
          const sub = [a.store, a.pack, a.on_offer ? `🏷️ Angebot${a.valid_to ? ` bis ${shortDate(a.valid_to)}` : ""}` : ""].filter(Boolean).join(" · ");
          const cost = a.cost != null ? `<b>≈ ${eur(a.cost)}</b>${a.packs > 1 ? `<span class="meta">${a.packs} × ${eur(a.price)}</span>` : ""}` : `<b>${eur(a.price)}</b><span class="meta">je Packung</span>`;
          return `<button class="sg ${cur ? "sel" : ""}" data-oc="prod-pick" data-pid="${esc(a.id)}"><span class="sthumb">${this._img(a.image, CATEGORY_ICONS[a.category] || "📦")}</span><span class="sgt"><b>${a.brand ? `${esc(a.brand)} ` : ""}${esc(a.name || a.title)}</b>${cur ? ' <span class="bdg">aktuell</span>' : ""}<div class="why">${esc(sub)}</div></span><span class="pp">${cost}</span></button>`;
        })
        .join("");
      list = rows ? `<div class="suglist">${rows}</div>` : `<div class="hint">Keine Artikel aus deinen Läden gefunden${p.query ? ` für „${esc(p.query)}“` : ""} – such nach einem anderen Namen. Artikel kommen aus Angeboten, Onlinepreisen und Kassenzetteln.</div>`;
    }
    const amount = p.res?.quantity ? ` (${esc(qtyText(p.res))})` : "";
    return `<div class="ocadd ocprod"><div class="hint">📦 Artikel für „${esc(p.res?.name || item.title)}“${amount} – aus deinen Läden, günstigste zuerst:</div>${list}
        <div class="addq"><input type="search" class="oprodq" data-ofocus="prodq" placeholder="Anderen Artikel suchen …" value="${esc(p.query || "")}" enterkeyhint="search" aria-label="Artikel suchen"><button class="btn small" data-oc="prod-search" title="Suchen">🔎</button>${item.product_id ? '<button class="btn small" data-oc="prod-none" title="Wieder ohne festen Artikel">Ohne Artikel</button>' : ""}<button class="btn small ghost" data-oc="prod-close">Fertig</button></div>
      </div>`;
  }

  /** The template's extras that belong to a dish course and are missing ("＋ Popcorn"). */
  _occMissingHtml(st, course) {
    const all = st.extras?.items || [];
    const missing = all.filter((e) => (e.course || "extra") === course);
    if (!missing.length) return "";
    return `<div class="ocitems">${missing.map((e) => `<button class="chip ocplus" data-oc="extra-on" data-n="${all.indexOf(e)}" title="Aus der Vorlage">＋ ${esc(e.title)}${e.quantity ? ` <span class="meta">${esc(qtyText(e))}</span>` : ""}</button>`).join("")}</div>`;
  }

  /** Zubehör as a checklist: ticked = part of the occasion, unticked = the template's. */
  _occExtrasHtml(st, items) {
    const all = st.extras?.items || [];
    const missing = all.filter((e) => (e.course || "extra") === "extra");
    const rows = [
      ...items.map((i) => `<div class="exrow"><label><input type="checkbox" checked data-oc="extra-off" data-uid="${esc(i.uid)}"><span>${esc(i.title)}${i.product ? ` <span class="meta">📦 ${esc(i.product.title)}</span>` : ""}${i.reason ? `<span class="why">🤖 ${esc(i.reason)}</span>` : ""}</span><span class="meta">${i.cost != null ? `≈ ${eur(i.cost)}` : ""}</span></label><span class="ocr2">${this._occAmtHtml(st, i)}</span></div>`),
      ...missing.map((e) => `<label class="missing"><input type="checkbox" data-oc="extra-on" data-n="${all.indexOf(e)}"><span>${esc(e.title)}</span><span class="meta">${esc(qtyText(e))}</span></label>`),
    ];
    if (rows.length) return `<div class="extras">${rows.join("")}</div>`;
    return `<div class="hint">${st.extras?.loading ? "⏳ …" : "Kein Zubehör."}</div>`;
  }

  _occAddHtml(st) {
    const a = st.add;
    const course = a.course;
    let list = "";
    if (course === "drink") list = this._occDrinksHtml(st);
    else if (DISH_COURSES.has(course)) {
      if (a.loading) list = `<div class="hint">⏳ Suche passende Gerichte …</div>`;
      else if (a.error) list = `<div class="notice err">${esc(a.error)}</div>`;
      else if ((a.items || []).length) list = `<div class="hint">Vorschläge nach deinen Rezepten, Saison und Angeboten:</div><div class="suglist">${a.items.map((s, n) => this._occSuggRow(s, n)).join("")}</div>`;
      else list = `<div class="hint">Keine passenden Rezepte für diesen Gang – such unten oder trag etwas ein.</div>`;
    }
    const placeholder = course === "drink" ? "Anderes Getränk, z. B. Apfelschorle" : course === "extra" ? "z. B. Teelichter, Servietten" : "Rezept suchen oder Freitext …";
    return `<div class="ocadd">${list}
        <div class="addq"><input type="search" class="oaddq" data-ofocus="addq" placeholder="${esc(placeholder)}" value="${esc(a.query || "")}" enterkeyhint="done" aria-label="${esc(placeholder)}"><button class="btn small" data-oc="add-text" title="Hinzufügen">＋</button><button class="btn small ghost" data-oc="add-close">Fertig</button></div>
        <div class="suglist oaddres">${this._occAddResultsHtml(st)}</div>
      </div>`;
  }

  /** Recipes matching what is typed in the add field (drinks only for "Getränke"). */
  _occAddResultsHtml(st) {
    const a = st.add;
    const q = fold(a?.query || "").trim();
    if (!q || a.course === "extra") return "";
    const used = new Set((st.view.items || []).map((i) => i.recipe_id).filter(Boolean));
    const drinks = a.course === "drink";
    const hits = this._data.recipes
      .filter((r) => !used.has(r.id) && isDrinkRecipe(r) === drinks && (fold(r.name).includes(q) || (r.tags || []).some((t) => fold(t).includes(q))))
      .slice(0, 6);
    return hits
      .map((r) => `<button class="sg" data-oc="add-recipe" data-id="${esc(r.id)}"><span class="sthumb">${dishEmoji(r.name)}</span><span class="sgt"><b>${esc(r.name)}</b><div class="why">📖 ${esc((r.tags || []).slice(0, 3).join(" · ") || "Rezept")}</div></span><span class="pp"><span class="meta">＋</span></span></button>`)
      .join("");
  }

  _occSuggRow(s, n) {
    const recipe = s.recipe_id ? this._recipe(s.recipe_id) : null;
    const why = (s.reasons || []).join(" · ") || s.reason || "";
    const img = recipe?.image && safeUrl(recipe.image) ? this._img(recipe.image, dishEmoji(s.title)) : dishEmoji(s.title);
    return `<button class="sg" data-oc="add-sugg" data-n="${n}"><span class="sthumb">${img}</span><span class="sgt"><b>${esc(s.title)}</b>${s.ai ? " 🤖" : ""}${why ? `<div class="why">${esc(why)}</div>` : ""}</span><span class="pp">${s.cost != null ? `<b>≈ ${eur(s.cost)}</b>` : ""}<span class="meta">＋ dazu</span></span></button>`;
  }

  /** A suggested drink (drinks_suggest) as a button row. */
  _drinkRow(x, attrs) {
    const qty = x.recipe_id ? "📖 Rezept" : x.quantity ? `${num(x.quantity)} ${x.unit || "l"}${x.bottles ? ` · ${x.bottles} Fl.` : ""}` : "";
    const offer = x.offer ? `🏷️ ${x.offer.text || `${x.offer.store || ""} ${eur(x.offer.price)}`}` : "";
    const why = [x.ai ? `🤖 ${x.reason || "KI-Vorschlag"}` : x.reason ? `passt zu: ${x.reason}` : "", x.hint, offer].filter(Boolean).join(" · ");
    return `<button class="sg" ${attrs}><span class="sthumb">${drinkEmoji(x)}</span><span class="sgt"><b>${esc(x.title)}</b> ${alcBadge(x.alcohol, x.kids)}${why ? `<div class="why">${esc(why)}</div>` : ""}</span><span class="pp">${qty ? `<span class="meta">${esc(qty)}</span>` : ""}<span class="meta">＋ dazu</span></span></button>`;
  }

  _occDrinksHtml(st) {
    const d = st.drinks || {};
    const alcohol = this._data.occasion_meta?.alcohol !== false;
    const ai = this._aiOn("drinks");
    const tools = `<div class="ocmore">${alcohol ? `<button class="chip ${d.alcohol !== false ? "active" : ""}" data-oc="drinks-alc" aria-pressed="${d.alcohol !== false}">🍷 mit Alkohol</button>` : '<span class="hint">Nur alkoholfreie Vorschläge (⚙️ Budget & Planung).</span>'}
        ${ai ? `<button class="btn small" data-oc="drinks-ai" ${d.aiBusy || d.loading ? "disabled" : ""}>${d.aiBusy ? `<span class="spin">⏳</span> ${esc(this._aiName())} denkt nach …` : "🤖 KI-Vorschläge"}</button>` : ""}</div>`;
    let list;
    if (d.loading) list = `<div class="hint">⏳ Suche passende Getränke …</div>`;
    else if (d.error) list = `<div class="notice err">${esc(d.error)}</div>`;
    else {
      const all = d.result?.drinks || [];
      const have = new Set((st.view.items || []).filter((i) => i.course === "drink").map((i) => fold(i.title)));
      const free = all.filter((x) => !have.has(fold(x.title)));
      list = free.length ? `<div class="suglist">${free.map((x) => this._drinkRow(x, `data-oc="drink-add" data-n="${all.indexOf(x)}"`)).join("")}</div>` : `<div class="hint">${all.length ? "Alle Vorschläge sind schon dabei." : "Keine Vorschläge."}</div>`;
    }
    const busy = d.aiBusy ? `<div class="notice"><span class="spin">⏳</span> ${esc(this._aiName())} sucht Getränke (${AI_WAIT}) – bis dahin die Vorschläge nach Regeln.</div>` : "";
    const note = d.aiNote ? `<div class="notice warn">🤖 ${esc(d.aiNote)}</div>` : "";
    const q = d.result?.quantities;
    const amount = q?.liters ? `<div class="hint">Für ${q.guests} Gäste${q.children ? ` und ${q.children} Kinder` : ""}${q.hours ? ` in ${num(q.hours)} Stunden` : ""} etwa ${num(q.liters)} l Getränke.</div>` : "";
    return tools + busy + note + list + amount;
  }

  _occMenuHtml(st) {
    const m = st.menu;
    if (!m) return "";
    const head = m.source === "ai" ? `🤖 Menü-Vorschlag von ${esc(this._aiName())}` : "💡 Menü-Vorschlag nach Regeln";
    const busy = m.aiBusy ? `<div class="notice"><span class="spin">⏳</span> ${esc(this._aiName())} stellt das Menü zusammen (${AI_WAIT}) – bis dahin die Vorschläge nach Regeln.</div>` : "";
    const note = m.aiError
      ? `<div class="notice warn">🤖 ${esc(m.aiError)} Hier die Vorschläge nach Regeln.</div>`
      : m.source === "ai"
        ? `<div class="notice">🤖 ${esc(this._aiName())} hat aus deinen Rezepten und den Artikeln deiner Läden ein komplettes Menü mit Mengen geplant – geprüft gegen Gäste, Alkohol und was schon dabei ist.${m.notes ? `<br><span class="meta">„${esc(m.notes)}“</span>` : ""}</div>`
        : "";
    if (m.loading && !m.suggestions) return `<div class="ocmenu"><h4>${head}</h4>${busy}<div class="hint">⏳ Stelle zusammen …</div></div>`;
    if (m.error) return `<div class="ocmenu"><h4>${head}</h4><div class="notice err">${esc(m.error)}</div><div class="ocmore"><button class="btn small ghost" data-oc="menu-close">Schließen</button></div></div>`;
    const sugg = this._occFreshMenu(st, m.suggestions);
    const groups = OCC_COURSES.filter((c) => (sugg[c] || []).length)
      .map((c) => {
        const info = this._courseInfo(c);
        const rows = sugg[c]
          .slice(0, m.source === "ai" ? Math.max(c === "drink" ? 5 : c === "extra" ? 8 : 3, sugg[c].filter((s) => s.ai).length) : c === "drink" ? 5 : c === "extra" ? 8 : 3)
          .map((s, n) => {
            const why = (s.reasons || []).join(" · ") || s.reason || s.hint || "";
            const amount = s.servings_ai ? `${s.servings_ai} Port.` : s.product_id && s.quantity ? `${num(s.quantity)} Pck.` : qtyText(s);
            const right = [s.ai ? amount : "", s.cost != null ? `≈ ${eur(s.cost)}` : s.ai ? "" : qtyText(s)].filter(Boolean).join(" · ");
            return `<div class="ocrow"><span class="oi"><b>${esc(s.title)}</b>${s.ai ? " 🤖" : ""}${c === "drink" ? ` ${alcBadge(s.alcohol, s.kids)}` : ""}${why ? `<div class="why">${esc(why)}</div>` : ""}</span>${right ? `<span class="meta">${esc(right)}</span>` : ""}<button class="btn small" data-oc="menu-add" data-course="${c}" data-n="${n}" aria-label="${esc(s.title)} hinzufügen">＋</button></div>`;
          })
          .join("");
        return `<div class="mc"><b>${esc(info.emoji)} ${esc(info.label)}</b>${rows}</div>`;
      })
      .join("");
    const picks = this._occMenuPicks(st, sugg).length;
    return `<div class="ocmenu" aria-live="polite"><h4>${head}</h4>${busy}${note}${groups ? `<div class="mcs">${groups}</div>` : '<div class="hint">Keine weiteren Vorschläge – es ist schon alles dabei.</div>'}
        <div class="ocmore">${picks || st.applying ? `<button class="btn small primary" data-oc="menu-apply" ${st.applying ? "disabled" : ""} title="Je Gang so viele wie die Vorlage vorsieht, Getränke (wenn noch keine da sind) und fehlendes Zubehör">${st.applying ? "⏳ Übernehme …" : `${m.source === "ai" ? "✓ Menü übernehmen" : "✓ Fehlendes übernehmen"} (${picks})`}</button>` : groups ? '<span class="hint">Es fehlt nichts – einzelne Vorschläge kommen mit ＋ dazu.</span>' : ""}<button class="btn small ghost" data-oc="menu-close">Schließen</button></div>
      </div>`;
  }

  /** Suggestions without what the occasion already has. */
  _occFreshMenu(st, suggestions) {
    const items = st.view.items || [];
    const used = new Set(items.map((i) => i.recipe_id).filter(Boolean));
    const titles = new Set(items.map((i) => fold(i.title)));
    const out = {};
    for (const [c, list] of Object.entries(suggestions || {})) out[c] = (list || []).filter((s) => !(s.recipe_id && used.has(s.recipe_id)) && !titles.has(fold(s.title)));
    return out;
  }

  /** What "✓ Fehlendes übernehmen" adds (like occasions.apply_menu): per dish course up to
   *  the template's count, drinks when there are none yet, the missing extras. */
  _occMenuPicks(st, sugg) {
    const counts = this._occTemplate(st.view.template)?.counts || {};
    const items = st.view.items || [];
    const picks = [];
    for (const c of OCC_COURSES) {
      const list = sugg[c] || [];
      if (!list.length) continue;
      // 1.5.1: the AI's whole plan (with its amounts); the rules where it left a course out
      const fromAi = st.menu?.source === "ai" ? list.filter((s) => s.ai) : [];
      if (fromAi.length) {
        picks.push(...fromAi.map((s) => occItem(s, c)));
        continue;
      }
      const present = items.filter((i) => i.course === c).length;
      if (c === "drink") {
        if (!present) picks.push(...list.slice(0, 5).map((s) => occItem(s, c)));
      } else if (c === "extra") picks.push(...list.map((s) => occItem(s, c)));
      else picks.push(...list.slice(0, Math.max(0, (counts[c] ?? 1) - present)).map((s) => occItem(s, c)));
    }
    return picks;
  }

  _occChange(st, t) {
    if (t.matches("input[type=checkbox][data-oc]")) return this._occAction(st, t.dataset.oc, t).catch(() => {});
    const o = st.view;
    if (t.classList.contains("otitle")) {
      const title = t.value.trim();
      if (title && title !== o.title) this._occSave(st, { title });
      else t.value = o.title;
    } else if (t.classList.contains("otpl")) this._occSave(st, { template: t.value }, { extras: true });
    else if (t.classList.contains("odate")) {
      if (t.value && t.value !== o.date) this._occSave(st, { date: t.value });
    } else if (t.classList.contains("otime")) {
      if (t.value && t.value !== o.time) this._occSave(st, { time: t.value });
    } else if (t.classList.contains("oallday")) this._occSave(st, { time: t.checked ? "" : this._occTemplate(o.template)?.time || "19:00" });
    else if (t.classList.contains("oguests") || t.classList.contains("ochildren")) this._occStep(st, t.classList.contains("oguests") ? "guests" : "children", 0, Number(t.value));
    else if (t.classList.contains("oamt")) this._occAmt(st, t.dataset.uid, 0, t.value === "" ? 0 : Number(String(t.value).replace(",", ".")));
    else if (t.classList.contains("ounit")) this._occAmt(st, t.dataset.uid, 0, null, t.value);
    else if (t.classList.contains("onotes")) {
      if (t.value !== (o.notes || "")) this._occSave(st, { notes: t.value });
    }
  }

  /** Guests / children: − / ＋ (saved after a short pause) or typed. */
  _occStep(st, key, delta, value = null) {
    const [min, max] = key === "guests" ? [1, 200] : [0, 100];
    const cur = st.draft[key] ?? st.view[key] ?? min;
    const typed = value != null && Number.isFinite(value);
    const next = Math.max(min, Math.min(max, typed ? Math.round(value) : cur + delta));
    st.draft[key] = next;
    const input = st.root?.querySelector(`.o${key}`);
    if (input && Number(input.value) !== next) input.value = String(next);
    st.root?.querySelectorAll(`[data-ostep="${key}"]`).forEach((b) => (b.disabled = Number(b.dataset.delta) < 0 ? next <= min : next >= max));
    clearTimeout(st.stepTimer);
    st.stepTimer = setTimeout(() => {
      const patch = {};
      for (const k of ["guests", "children"]) if (st.draft[k] != null && st.draft[k] !== st.view[k]) patch[k] = st.draft[k];
      if (Object.keys(patch).length) this._occSave(st, patch, { extras: true });
    }, typed ? 0 : 500);
  }

  /** Save a change (one after the other); the answer is the new view. Errors show in the
   *  editor. Returns the occasion or null. */
  _occSave(st, patch, opts = {}) {
    st.saving += 1;
    st.saved = false;
    this._occState(st);
    const run = async () => {
      let result = null;
      try {
        const res = await this._hass.callWS({ type: `${DOMAIN}/occasion_save`, occasion: { id: st.id, ...patch } });
        result = res.occasion;
        if (this._occ === st) {
          st.view = res.occasion;
          st.error = null;
          for (const k of Object.keys(st.draft)) if (st.draft[k] === st.view[k]) delete st.draft[k];
          if (opts.extras) this._occLoadExtras(st);
        }
      } catch (err) {
        if (this._occ === st) {
          st.error = errText(err);
          st.draft = {};
        }
      } finally {
        st.saving -= 1;
        if (this._occ === st) {
          st.saved = !st.error && !st.saving;
          this._occRender(st);
        }
      }
      return result;
    };
    st.queue = st.queue.then(run, run);
    return st.queue;
  }

  _occState(st) {
    const el = st.root?.querySelector(".ocstate");
    if (el) el.textContent = st.saving ? "⏳ Speichere …" : st.saved ? "✓ gespeichert" : "";
  }

  /** Render the editor again (keeps the focus, the typed text and the scroll position). */
  _occRender(st) {
    if (this._occ !== st || !st.root?.isConnected) return;
    const modal = st.root.querySelector(".modal");
    const body = st.root.querySelector(".mbody");
    const active = this.shadowRoot.activeElement;
    const key = active && body.contains(active) ? active.dataset?.ofocus : null;
    const typed = key ? { value: active.value, caret: active.selectionStart } : null;
    const top = modal.scrollTop;
    body.innerHTML = this._occBodyHtml(st);
    st.root.querySelector(".mhead h2").textContent = st.view.label || st.view.title;
    modal.scrollTop = top;
    if (!key) return;
    const el = body.querySelector(`[data-ofocus="${key}"]`);
    if (!el) return;
    if (["title", "notes", "addq", "prodq"].includes(key) && typed.value != null) el.value = typed.value;
    el.focus({ preventScroll: true });
    try {
      if (typed.caret != null && el.setSelectionRange) el.setSelectionRange(typed.caret, typed.caret);
    } catch (e) {
      /* no caret (number, date) */
    }
  }

  async _occAction(st, action, el) {
    const d = el.dataset;
    switch (action) {
      case "remove":
      case "extra-off":
        await this._occSave(st, { remove_items: [d.uid] }, { extras: action === "extra-off" });
        break;
      case "extra-on": {
        const e = st.extras?.items?.[Number(d.n)];
        if (!e) break;
        st.extras.items = st.extras.items.filter((x) => x !== e);
        this._occRender(st);
        await this._occSave(st, { add_items: [occItem(e, e.course || "extra")] });
        break;
      }
      case "recipe":
        this._openRecipe(d.id, undefined, { occasion: st.id });
        break;
      case "course-add":
        st.extraCourses.add(d.course);
      // falls through: the new course opens with its suggestions
      case "add": {
        const course = d.course;
        st.add = { course, query: "", items: null, loading: DISH_COURSES.has(course), error: null };
        this._occRender(st);
        if (course === "drink") this._occLoadDrinks(st);
        else if (DISH_COURSES.has(course)) this._occLoadCourse(st, course);
        st.root.querySelector(`.ocsec[data-course="${course}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        break;
      }
      case "add-close":
        st.add = null;
        this._occRender(st);
        break;
      case "add-sugg": {
        const s = st.add?.items?.[Number(d.n)];
        if (!s) break;
        const course = st.add.course;
        st.add.items = st.add.items.filter((x) => x !== s);
        await this._occSave(st, { add_items: [occItem(s, course)] });
        break;
      }
      case "add-recipe": {
        if (!st.add) break;
        const course = st.add.course;
        st.add.query = "";
        await this._occSave(st, { add_items: [{ recipe_id: d.id, course }] });
        break;
      }
      case "add-text": {
        if (!st.add) break;
        const input = st.root.querySelector(".oaddq");
        const text = String(input?.value || st.add.query || "").trim();
        if (!text) {
          input?.focus();
          break;
        }
        const course = st.add.course;
        st.add.query = "";
        if (input) input.value = "";
        const recipe = this._data.recipes.find((r) => fold(r.name) === fold(text));
        await this._occSave(st, { add_items: [recipe ? { recipe_id: recipe.id, course } : { title: text, course }] });
        break;
      }
      case "drink-add": {
        const x = st.drinks?.result?.drinks?.[Number(d.n)];
        if (x) await this._occSave(st, { add_items: [drinkItem(x)] });
        break;
      }
      case "drinks-alc":
        st.drinks = { ...(st.drinks || {}), alcohol: st.drinks?.alcohol === false };
        this._occLoadDrinks(st);
        break;
      case "drinks-ai":
        this._occLoadDrinks(st, true);
        break;
      case "menu":
      case "menu-ai":
        this._occMenu(st, action === "menu-ai");
        break;
      case "menu-add": {
        const list = this._occFreshMenu(st, st.menu?.suggestions)[d.course] || [];
        const s = list[Number(d.n)];
        if (s) await this._occSave(st, { add_items: [occItem(s, d.course)] });
        break;
      }
      case "menu-apply": {
        const picks = this._occMenuPicks(st, this._occFreshMenu(st, st.menu?.suggestions));
        if (!picks.length || st.applying) break;
        st.applying = true;
        st.menuSeq = (st.menuSeq || 0) + 1; // a later AI answer is not shown any more
        this._occRender(st);
        const saved = await this._occSave(st, { add_items: picks });
        st.applying = false;
        if (saved) {
          st.menu = null;
          const names = picks.map((p) => p.title || this._recipe(p.recipe_id)?.name).filter(Boolean);
          this._toast(`✓ ${names.length} übernommen: ${names.slice(0, 3).join(", ")}${names.length > 3 ? " …" : ""}`);
          this._occLoadExtras(st);
        }
        this._occRender(st);
        break;
      }
      case "menu-close":
        st.menu = null;
        st.menuSeq = (st.menuSeq || 0) + 1;
        this._occRender(st);
        break;
      case "amt":
        this._occAmt(st, d.uid, Number(d.delta));
        break;
      case "prod":
        if (st.prod?.uid === d.uid) {
          st.prod = null;
          this._occRender(st);
          break;
        }
        st.prod = { uid: d.uid, query: "", loading: true, res: null, error: null };
        this._occRender(st);
        this._occLoadProducts(st);
        break;
      case "prod-search": {
        if (!st.prod) break;
        const input = st.root.querySelector(".oprodq");
        st.prod.query = String(input?.value || "").trim();
        st.prod.loading = true;
        this._occRender(st);
        this._occLoadProducts(st);
        break;
      }
      case "prod-pick":
      case "prod-none": {
        const uid = st.prod?.uid;
        if (!uid) break;
        st.prod = null;
        const saved = await this._occSave(st, { update_items: [{ uid, product_id: action === "prod-pick" ? d.pid : null }] });
        const item = saved?.items?.find((x) => x.uid === uid);
        if (saved && action === "prod-pick" && item) this._toast(`📦 ${item.title}: ${item.product?.title || "Artikel"}${item.quantity_text ? ` · ${item.quantity_text}` : ""}${item.cost != null ? ` ≈ ${eur(item.cost)}` : ""}`);
        break;
      }
      case "prod-close":
        st.prod = null;
        this._occRender(st);
        break;
      case "shop":
        await this._occShopping(st, el);
        break;
      case "delete": {
        const o = st.view;
        if (!confirm(`„${o.title}“ (${this._dateLabel(o.date)}) löschen? Einträge auf der Einkaufsliste bleiben.`)) break;
        try {
          await this._hass.callWS({ type: `${DOMAIN}/occasion_delete`, occasion_id: st.id });
        } catch (err) {
          st.error = errText(err);
          this._occRender(st);
          break;
        }
        this._toast(`🗑 ${o.label || o.title} gelöscht`);
        this._closeModal();
        break;
      }
      default:
        break;
    }
  }

  /** − / ＋ or a typed amount (value; 0 = no quantity) or a unit of an item: shown at
   *  once, saved after a short pause (typed: at once) – the answer brings the new costs. */
  _occAmt(st, uid, delta, value = null, unit = null) {
    const i = (st.view.items || []).find((x) => x.uid === uid);
    if (!i) return;
    st.amt = st.amt || {};
    st.amtTimers = st.amtTimers || {};
    const d = (st.amt[uid] = st.amt[uid] || {});
    const typed = value != null && Number.isFinite(value);
    if (i.recipe_id) {
      const cur = Number(d.servings ?? i.servings ?? st.view.servings ?? 1);
      d.servings = Math.max(1, Math.min(500, typed ? Math.round(value) || 1 : cur + delta));
    } else {
      if (unit != null) d.unit = unit;
      const u = i.product_id ? "Pck." : d.unit ?? i.unit ?? "";
      const step = amtStep(u);
      const cur = Number(d.quantity ?? i.quantity ?? 0) || 0;
      let next = typed ? value : unit != null ? cur || step : Math.round((cur + delta * step) / step) * step;
      if (i.product_id) next = Math.max(1, Math.round(next));
      next = Math.max(0, Math.min(10000, Math.round(next * 1000) / 1000));
      d.quantity = next || null;
    }
    const input = st.root?.querySelector(`.oamt[data-uid="${CSS.escape(uid)}"]`);
    const shown = i.recipe_id ? d.servings : d.quantity ?? "";
    if (input && String(input.value) !== String(shown)) input.value = String(shown);
    clearTimeout(st.amtTimers[uid]);
    st.amtTimers[uid] = setTimeout(() => {
      const draft = st.amt?.[uid];
      if (!draft) return;
      const change = { uid };
      if (i.recipe_id) change.servings = draft.servings;
      else {
        change.quantity = draft.quantity ?? null;
        if (draft.unit != null) change.unit = draft.unit;
      }
      this._occSave(st, { update_items: [change] }).then(() => {
        if (st.amt?.[uid] === draft) delete st.amt[uid];
      });
    }, typed || unit != null ? 0 : 500);
  }

  /** The products of the user's stores for the item of "📦" (or what is searched). */
  async _occLoadProducts(st) {
    const p = st.prod;
    if (!p) return;
    const my = (st.prodSeq = (st.prodSeq || 0) + 1);
    const msg = { type: `${DOMAIN}/occasion_products`, occasion_id: st.id, uid: p.uid, limit: 30 };
    if (p.query) msg.query = p.query;
    try {
      const res = await this._hass.callWS(msg);
      if (this._occ !== st || st.prodSeq !== my || st.prod !== p) return;
      Object.assign(p, { res, loading: false, error: null });
    } catch (err) {
      if (this._occ !== st || st.prodSeq !== my || st.prod !== p) return;
      Object.assign(p, { loading: false, error: errText(err) });
    }
    this._occRender(st);
    st.root?.querySelector(".ocprod")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async _occLoadCourse(st, course) {
    const my = (st.addSeq = (st.addSeq || 0) + 1);
    try {
      const res = await this._hass.callWS({ type: `${DOMAIN}/occasion_suggest`, occasion_id: st.id, course, count: 5 });
      if (this._occ !== st || st.addSeq !== my || st.add?.course !== course) return;
      Object.assign(st.add, { items: res.suggestions?.[course] || [], loading: false });
    } catch (err) {
      if (this._occ !== st || st.addSeq !== my || st.add?.course !== course) return;
      Object.assign(st.add, { loading: false, error: errText(err) });
    }
    this._occRender(st);
  }

  /** Drinks for the occasion (rules; ai: the AI's first – a failing AI keeps the rules). */
  async _occLoadDrinks(st, ai = false) {
    const dr = (st.drinks = { ...(st.drinks || {}), error: null, aiNote: null, loading: !ai || !st.drinks?.result, aiBusy: ai });
    const my = (st.drinkSeq = (st.drinkSeq || 0) + 1);
    this._occRender(st);
    const msg = { type: `${DOMAIN}/drinks_suggest`, occasion_id: st.id };
    if (dr.alcohol === false) msg.alcohol = false;
    if (ai) msg.ai = true;
    try {
      const res = await this._hass.callWS(msg);
      if (this._occ !== st || st.drinkSeq !== my) return;
      dr.result = res;
      if (ai && res.ai && !res.ai.ok) dr.aiNote = `${res.ai.error || "Die KI hat nicht geantwortet."} Hier die Vorschläge nach Regeln.`;
    } catch (err) {
      if (this._occ !== st || st.drinkSeq !== my) return;
      dr.error = errText(err);
    }
    dr.loading = false;
    dr.aiBusy = false;
    this._occRender(st);
  }

  /** The template's extras that are missing (checklist, "＋ Popcorn"). */
  async _occLoadExtras(st) {
    const my = (st.extraSeq = (st.extraSeq || 0) + 1);
    st.extras = { ...(st.extras || { items: [] }), loading: true };
    let items = [];
    try {
      const res = await this._hass.callWS({ type: `${DOMAIN}/occasion_suggest`, occasion_id: st.id, course: "extra" });
      items = res.suggestions?.extra || [];
    } catch (err) {
      items = [];
    }
    if (this._occ !== st || st.extraSeq !== my) return;
    st.extras = { loading: false, items };
    this._occRender(st);
  }

  /** "💡 Menü vorschlagen" / "🤖 KI-Menü": the rule menu at once, the AI's when it answers
   *  (a failing AI keeps the rules and says why). */
  async _occMenu(st, ai) {
    const my = (st.menuSeq = (st.menuSeq || 0) + 1);
    st.menu = { loading: true, aiBusy: ai, source: "rules", suggestions: null, aiError: null, error: null };
    this._occRender(st);
    const ask = (withAi) => this._hass.callWS({ type: `${DOMAIN}/occasion_suggest`, occasion_id: st.id, count: 3, ai: withAi });
    const live = () => this._occ === st && st.menuSeq === my && st.menu;
    ask(false)
      .then((res) => {
        if (!live() || st.menu.source === "ai") return;
        st.menu.suggestions = res.suggestions || {};
        st.menu.loading = false;
        this._occRender(st);
      })
      .catch((err) => {
        if (!live() || st.menu.suggestions) return;
        st.menu.loading = false;
        if (!st.menu.aiBusy) st.menu.error = errText(err);
        this._occRender(st);
      });
    if (!ai) return;
    try {
      const res = await ask(true);
      if (!live()) return;
      if (res.ai?.ok) {
        st.menu.suggestions = res.suggestions || {};
        st.menu.source = "ai";
        st.menu.notes = res.ai.notes || "";
      } else {
        st.menu.aiError = res.ai?.error || "Die KI hat nicht geantwortet.";
        st.menu.suggestions = st.menu.suggestions || res.suggestions || {};
      }
    } catch (err) {
      if (!live()) return;
      st.menu.aiError = errText(err);
    }
    st.menu.loading = false;
    st.menu.aiBusy = false;
    this._occRender(st);
  }

  async _occShopping(st, el) {
    const label = el.innerHTML;
    el.disabled = true;
    el.textContent = "⏳ Erstelle die Liste …";
    let res;
    try {
      res = await this._service("generate_shopping_list", { start_date: st.view.date, days: 1, occasion: st.id }, true);
    } catch (e) {
      el.disabled = false;
      el.innerHTML = label;
      return;
    }
    const n = res?.items?.length || 0;
    this._toast(n ? `🛒 ${n} Artikel für ${st.view.label || st.view.title} auf der Einkaufsliste` : `Für ${st.view.label || st.view.title} gibt es nichts einzukaufen.`);
    this._closeModal();
    if (n) this._goTab("shopping");
  }

  /** "🍷 Passt dazu" in a recipe: drink chips; a tap shows why, the offer and actions. */
  async _fillDrinks(root, recipe, ctx) {
    const box = root.querySelector(".drinkbox");
    if (!box) return;
    this._drinkCache = this._drinkCache || {};
    let res = this._drinkCache[recipe.id];
    if (!res) {
      try {
        res = await this._hass.callWS({ type: `${DOMAIN}/drinks_suggest`, recipe_ids: [recipe.id] });
        this._drinkCache[recipe.id] = res;
      } catch (err) {
        if (box.isConnected) box.querySelector(".dchips").innerHTML = `<span class="hint">${esc(errText(err))}</span>`;
        return;
      }
    }
    if (!box.isConnected) return;
    const drinks = (res.drinks || []).slice(0, 6);
    const chips = box.querySelector(".dchips");
    const info = box.querySelector(".dinfo");
    const entry = ctx?.date && ctx?.meal ? (this._data.plan[ctx.date] || {})[ctx.meal] : null;
    if (!drinks.length) {
      chips.innerHTML = '<span class="hint">Keine Vorschläge.</span>';
      return;
    }
    chips.innerHTML = drinks.map((x, n) => `<button class="chip ${x.alcohol ? "alc" : ""}" data-dn="${n}" aria-expanded="false" title="${esc(x.reason || x.hint || "")}">${drinkEmoji(x)} ${esc(x.title)}</button>`).join("") + (res.alcohol ? "" : '<span class="meta">nur alkoholfrei</span>');
    let open = -1;
    chips.addEventListener("click", (ev) => {
      const chip = ev.target.closest("[data-dn]");
      if (!chip) return;
      const n = Number(chip.dataset.dn);
      open = open === n ? -1 : n;
      chips.querySelectorAll("[data-dn]").forEach((c) => {
        c.classList.toggle("on", Number(c.dataset.dn) === open);
        c.setAttribute("aria-expanded", String(Number(c.dataset.dn) === open));
      });
      if (open < 0) {
        info.hidden = true;
        return;
      }
      const x = drinks[open];
      const has = (entry?.drinks || []).some((y) => fold(y.title) === fold(x.title));
      info.hidden = false;
      info.innerHTML = `<div><b>${drinkEmoji(x)} ${esc(x.title)}</b> ${alcBadge(x.alcohol, x.kids)}${x.hint ? ` <span class="meta">· ${esc(x.hint)}</span>` : ""}</div>
        ${x.reason ? `<div class="meta">Passt zu: ${esc(x.reason)}</div>` : ""}
        ${x.offer ? `<div class="meta">🏷️ Im Angebot: ${esc(x.offer.title || x.title)} · ${esc(x.offer.text || eur(x.offer.price))}</div>` : ""}
        <div class="row">
          ${entry && !has ? `<button class="btn small primary" data-dact="meal">＋ Zur Mahlzeit</button>` : entry ? '<span class="meta">✓ bei dieser Mahlzeit</span>' : ""}
          <button class="btn small" data-dact="list">🛒 Auf die Einkaufsliste</button>
          ${x.recipe_id && this._recipe(x.recipe_id) ? `<button class="btn small" data-dact="recipe">📖 Rezept</button>` : ""}
        </div>`;
    });
    info.addEventListener("click", async (ev) => {
      const act = ev.target.closest("[data-dact]")?.dataset.dact;
      const x = drinks[open];
      if (!act || !x) return;
      if (act === "recipe") return this._openRecipe(x.recipe_id);
      if (act === "list") {
        await this._todo("add_item", { item: x.name || x.title });
        this._toast(`🛒 ${x.name || x.title} auf die Einkaufsliste gesetzt`);
        return;
      }
      const drinksNow = [...(entry.drinks || []), { title: x.title, alcohol: Boolean(x.alcohol), ...(x.recipe_id ? { recipe_id: x.recipe_id } : {}) }];
      let saved;
      try {
        saved = await this._planDrinks(ctx.date, ctx.meal, entry, drinksNow);
      } catch (e) {
        return;
      }
      entry.drinks = saved?.entry?.drinks || drinksNow;
      this._toast(`🥤 ${x.title} zu ${entry.title}`);
      ev.target.closest(".row").innerHTML = '<span class="meta">✓ bei dieser Mahlzeit</span>';
    });
  }

  /** The drinks of a plan entry (plan_meal with the same dish keeps it, also "gekocht"). */
  async _planDrinks(date, meal, entry, drinks) {
    // a typed drink without "alcohol": the backend tells by its name
    const data = { date, meal, drinks: drinks.map((x) => ({ title: x.title, ...(typeof x.alcohol === "boolean" ? { alcohol: x.alcohol } : {}), ...(x.recipe_id ? { recipe_id: x.recipe_id } : {}) })) };
    if (entry.servings) data.servings = entry.servings;
    if (entry.recipe_id) data.recipe = entry.recipe_id;
    else data.title = entry.title;
    if (entry.note) data.note = entry.note;
    return this._service("plan_meal", data, true);
  }

  /** "🥤 Getränke" of the meal-entry dialog: chips with ✕, "🍷 Getränk hinzufügen". */
  _entryDrinks(root, date, meal, entry) {
    const box = root.querySelector(".drinksec");
    if (!box) return;
    const st = { drinks: [...(entry.drinks || [])], sugg: null, open: false, loading: false, busy: false };
    const render = () => {
      const chips = st.drinks.map((x, n) => `<span class="dchip-x">${drinkEmoji(x)} ${esc(x.title)} ${alcBadge(x.alcohol)}<button class="icon" data-dx="${n}" aria-label="${esc(x.title)} entfernen" title="Entfernen">✕</button></span>`).join("");
      const have = new Set(st.drinks.map((x) => fold(x.title)));
      const list = st.loading ? '<div class="hint">⏳ Suche passende Getränke …</div>' : (st.sugg || []).filter((x) => !have.has(fold(x.title))).map((x) => this._drinkRow(x, `data-dadd="${st.sugg.indexOf(x)}"`)).join("");
      box.querySelector(".dchips").innerHTML = chips || '<span class="hint">Noch kein Getränk.</span>';
      box.querySelector(".dadd").innerHTML = st.open
        ? `<div class="suglist">${list}</div><div class="addq" style="display:flex;gap:6px"><input type="search" class="dq" placeholder="Anderes Getränk, z. B. Apfelschorle" aria-label="Anderes Getränk" style="flex:1;min-width:0" enterkeyhint="done"><button class="btn small" data-dfree>＋</button></div>`
        : `<button class="btn small" data-dopen>🍷 Getränk hinzufügen</button>`;
    };
    const save = async (drinks) => {
      if (st.busy) return false;
      st.busy = true;
      try {
        const res = await this._planDrinks(date, meal, entry, drinks);
        st.drinks = res?.entry?.drinks || drinks;
        entry.drinks = st.drinks;
        return true;
      } catch (e) {
        return false;
      } finally {
        st.busy = false;
        render();
      }
    };
    const add = (x) => save([...st.drinks, { title: x.title, ...(typeof x.alcohol === "boolean" ? { alcohol: x.alcohol } : {}), ...(x.recipe_id ? { recipe_id: x.recipe_id } : {}) }]);
    box.addEventListener("click", async (ev) => {
      const t = ev.target;
      const dx = t.closest("[data-dx]");
      if (dx) return save(st.drinks.filter((_, n) => n !== Number(dx.dataset.dx)));
      if (t.closest("[data-dopen]")) {
        st.open = true;
        st.loading = true;
        render();
        const msg = { type: `${DOMAIN}/drinks_suggest` };
        if (entry.recipe_id) msg.recipe_ids = [entry.recipe_id];
        else msg.titles = [entry.title];
        try {
          st.sugg = (await this._hass.callWS(msg)).drinks || [];
        } catch (err) {
          st.sugg = [];
          this._toast(errText(err));
        }
        st.loading = false;
        render();
        box.querySelector(".dq")?.focus({ preventScroll: true });
        return;
      }
      const dadd = t.closest("[data-dadd]");
      if (dadd) return add(st.sugg[Number(dadd.dataset.dadd)]);
      if (t.closest("[data-dfree]")) {
        const text = box.querySelector(".dq")?.value.trim();
        if (text) add({ title: text });
      }
    });
    box.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" || !ev.target.classList.contains("dq")) return;
      ev.preventDefault();
      const text = ev.target.value.trim();
      if (text) add({ title: text });
    });
    render();
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
        ${this._data?.ai?.sort ? `<div class="hint">🗂️ <b>Sortieren:</b> ${this._aiSortLine("products", true)}<br>${this._aiSortLine("recipes", true)}</div>` : ""}
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
