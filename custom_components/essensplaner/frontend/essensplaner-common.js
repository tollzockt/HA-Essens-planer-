/*
 * Essensplaner – shared helpers for the panel and the dashboard card.
 */

export const DOMAIN = "essensplaner";
export const WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
export const WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
export const MONTHS = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."];

export const MEAL_STYLE = {
  fruehstueck: { color: "#f2a10f", icon: "☕" },
  mittagessen: { color: "#3fa34d", icon: "🥗" },
  snack: { color: "#a35bd4", icon: "🍪" },
  abendessen: { color: "#e2553f", icon: "🍽️" },
};

export const CATEGORY_ORDER = [
  "Obst & Gemüse",
  "Brot & Backwaren",
  "Fleisch & Fisch",
  "Milchprodukte & Eier",
  "Käse & Aufschnitt",
  "Nudeln, Reis & Getreide",
  "Konserven & Gläser",
  "Gewürze, Öle & Saucen",
  "Backen & Süßes",
  "Nüsse & Trockenobst",
  "Tiefkühl",
  "Getränke",
  "Sonstiges",
];

export const CATEGORY_ICONS = {
  "Obst & Gemüse": "🥕",
  "Brot & Backwaren": "🥖",
  "Fleisch & Fisch": "🥩",
  "Milchprodukte & Eier": "🥛",
  "Käse & Aufschnitt": "🧀",
  "Nudeln, Reis & Getreide": "🍝",
  "Konserven & Gläser": "🥫",
  "Gewürze, Öle & Saucen": "🧂",
  "Backen & Süßes": "🍫",
  "Nüsse & Trockenobst": "🥜",
  "Tiefkühl": "🧊",
  "Getränke": "🧃",
  "Sonstiges": "🛒",
};

const DISH_EMOJIS = [
  [/pizza/, "🍕"],
  [/burger/, "🍔"],
  [/wrap|burrito|taco|tortilla|fajita/, "🌯"],
  [/pfannkuchen|pancake|crepe|waffel/, "🥞"],
  [/oats|muesli|porridge|haferbrei|granola/, "🥣"],
  [/shakshuka|ruehrei|spiegelei|omelett|eier/, "🍳"],
  [/kuchen|torte|bananenbrot|muffin|brownie|cookie|keks/, "🍰"],
  [/brot|broetchen|toast|sandwich/, "🥪"],
  [/suppe|eintopf|chili|gulasch|bruehe/, "🍲"],
  [/curry|dal|reis|risotto|paella|bowl/, "🍛"],
  [/salat/, "🥗"],
  [/lachs|fisch|thunfisch|garnele|shrimp|scampi/, "🐟"],
  [/haehnchen|huhn|chicken|pute/, "🍗"],
  [/schnitzel|steak|braten|fleisch/, "🥩"],
  [/nudel|pasta|spaghetti|lasagne|penne|spaetzle|gnocchi|tagliatelle|maccheroni/, "🍝"],
  [/ramen|pho|asia|wok/, "🍜"],
  [/kartoffel|pommes|gratin/, "🥔"],
  [/gemuese|ofen|auflauf/, "🥘"],
  [/reste|bestellen|lieferdienst|essen gehen|restaurant/, "🛵"],
];

export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

export const fold = (s) =>
  String(s ?? "")
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss");

export const dishEmoji = (name) => {
  const key = fold(name);
  for (const [re, emoji] of DISH_EMOJIS) if (re.test(key)) return emoji;
  return "🍽️";
};

const pad = (n) => String(n).padStart(2, "0");
export const toIso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const fromIso = (s) => {
  const [y, m, d] = String(s).split("-").map(Number);
  return new Date(y, m - 1, d);
};
export const addDays = (d, n) => {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
};
export const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
export const weekdayIndex = (d) => (d.getDay() + 6) % 7;
export const isoWeek = (d) => {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
};

export const relativeDay = (iso, todayIso) => {
  const diff = Math.round((fromIso(iso) - fromIso(todayIso)) / 86400000);
  if (diff === 0) return "Heute";
  if (diff === 1) return "Morgen";
  if (diff === 2) return "Übermorgen";
  if (diff === -1) return "Gestern";
  const d = fromIso(iso);
  return `${WEEKDAYS[weekdayIndex(d)]}, ${d.getDate()}. ${MONTHS[d.getMonth()]}`;
};

export const greeting = (date = new Date()) => {
  const h = date.getHours();
  if (h < 5) return "Gute Nacht";
  if (h < 11) return "Guten Morgen";
  if (h < 14) return "Mahlzeit";
  if (h < 18) return "Guten Tag";
  return "Guten Abend";
};

export const stars = (rating, interactive = false) =>
  [1, 2, 3, 4, 5]
    .map((n) =>
      interactive
        ? `<button class="starbtn ${n <= (rating || 0) ? "on" : ""}" data-rate="${n}" title="${n} Sterne">★</button>`
        : `<span class="${n <= (rating || 0) ? "on" : ""}">★</span>`
    )
    .join("");

/** Find "10 Minuten", "1 Stunde", "2-3 Min." in a recipe step. Returns seconds. */
export const findTimers = (text) => {
  const re = /(\d+(?:[.,]\d+)?)(?:\s*(?:-|–|bis)\s*(\d+(?:[.,]\d+)?))?\s*(Sekunden|Sek\.?|Minuten|Minute|Min\.?|min|Stunden|Stunde|Std\.?)(?![a-zäöü])/gi;
  const found = [];
  let m;
  while ((m = re.exec(String(text)))) {
    const value = parseFloat((m[2] || m[1]).replace(",", "."));
    const unit = m[3].toLowerCase();
    let seconds = value * 60;
    if (unit.startsWith("sek")) seconds = value;
    else if (unit.startsWith("std") || unit.startsWith("stunde")) seconds = value * 3600;
    if (seconds > 0 && seconds <= 24 * 3600) found.push({ seconds: Math.round(seconds), label: m[0] });
  }
  return found;
};

export const formatClock = (seconds) => {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
};

/** Next upcoming meal (today: still running or later; otherwise the following days). */
export const upcomingMeal = (data, now = new Date()) => {
  if (!data) return null;
  const times = Object.fromEntries((data.all_meals || []).map((m) => [m.id, m.time || "12:00"]));
  for (const meal of data.meals || []) times[meal.id] = meal.time;
  const today = data.today || toIso(now);
  for (let offset = 0; offset < 14; offset++) {
    const iso = toIso(addDays(fromIso(today), offset));
    const meals = Object.entries(data.plan?.[iso] || {}).sort(
      (a, b) => (times[a[0]] || "").localeCompare(times[b[0]] || "")
    );
    for (const [meal, entry] of meals) {
      if (offset === 0) {
        const [h, m] = (times[meal] || "12:00").split(":").map(Number);
        const end = new Date(now);
        end.setHours(h, m + 45, 0, 0);
        if (end < now) continue;
      }
      return { date: iso, meal, entry, time: times[meal] };
    }
  }
  return null;
};

export function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.35, 0.7].forEach((t) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.25, ctx.currentTime + t);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + 0.3);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + t);
      osc.stop(ctx.currentTime + t + 0.3);
    });
    if (navigator.vibrate) navigator.vibrate([300, 150, 300, 150, 300]);
  } catch (e) {
    /* audio not available */
  }
}
