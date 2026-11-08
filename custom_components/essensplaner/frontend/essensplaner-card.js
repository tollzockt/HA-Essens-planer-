/*
 * Essensplaner – dashboard card.
 *
 *   type: custom:essensplaner-card
 *   mode: today | next | week      (default: today)
 *   title: optional heading
 *   days: 7                         (week mode)
 *   start: today | monday           (week mode)
 *   show_images: true
 *   show_ingredients: false         (next mode)
 *   show_occasions: true            (today: "Heute: 🎬 Filmabend", week: occasion chips)
 *
 * Loaded automatically by the integration – no resource needs to be added.
 */

import {
  DOMAIN,
  MEAL_STYLE,
  MONTHS,
  WEEKDAYS,
  WEEKDAYS_SHORT,
  addDays,
  dishEmoji,
  esc,
  eur,
  fromIso,
  mondayOf,
  relativeDay,
  toIso,
  upcomingMeal,
  weekdayIndex,
} from "./essensplaner-common.js";

// 1.5.1 (here, not in common.js: a cached old common.js must not break the card)
const MEAL_NAMES = { fruehstueck: "Frühstück", mittagessen: "Mittagessen", snack: "Snack", abendessen: "Abendessen" };
/** "🍲 Reste von Dienstag (Lasagne)" for leftovers, else the entry's title. */
const entryTitle = (entry, iso) => {
  const lo = entry?.leftover_of;
  if (!lo?.date) return entry?.title || "";
  const when = lo.date === iso ? `vom ${MEAL_NAMES[lo.meal] || lo.meal}` : `von ${WEEKDAYS[weekdayIndex(fromIso(lo.date))]}`;
  return `🍲 Reste ${when}${entry.title ? ` (${entry.title})` : ""}`;
};

const safeUrl = (url) => {
  const u = String(url || "").trim();
  if (!/^(https?:\/\/|\/)/i.test(u)) return "";
  return encodeURI(u).replace(/['"()\\]/g, (c) => "%" + c.charCodeAt(0).toString(16));
};

const CARD_STYLE = `
  :host { display: block; }
  ha-card { overflow: hidden; height: 100%; }
  .wrap { padding: 14px 16px 16px; }
  .head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
  .head .title { font-size: 18px; font-weight: 500; flex: 1; }
  .head .sub { font-size: 13px; color: var(--secondary-text-color); }
  .open { background: none; border: none; color: var(--primary-color); cursor: pointer; font: inherit; font-size: 13px; padding: 4px 6px; border-radius: 8px; }
  .open:hover { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
  .meals { display: flex; flex-direction: column; gap: 8px; }
  .meal { display: flex; gap: 12px; align-items: center; padding: 8px; border-radius: 12px; cursor: pointer;
    background: color-mix(in srgb, var(--meal-color) 11%, transparent); border-left: 4px solid var(--meal-color); }
  .meal.empty { background: none; border-left-color: color-mix(in srgb, var(--meal-color) 35%, transparent); }
  .meal.empty .thumb { opacity: .45; filter: grayscale(.6); background: color-mix(in srgb, var(--meal-color) 10%, transparent); }
  .meal.empty .t { color: var(--secondary-text-color); font-weight: 400; font-size: 14px; }
  .thumb { width: 48px; height: 48px; border-radius: 10px; flex: none; display: flex; align-items: center; justify-content: center; font-size: 26px; background: var(--card-background-color) center/cover no-repeat; }
  .meal .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .07em; color: var(--secondary-text-color); }
  .meal .t { font-size: 16px; font-weight: 500; line-height: 1.2; }
  .meal .s { font-size: 12px; color: var(--secondary-text-color); }
  .meal .cooked { margin-left: auto; }
  .foot { margin-top: 10px; font-size: 13px; color: var(--secondary-text-color); display: flex; gap: 6px; flex-wrap: wrap; }
  .foot b { color: var(--primary-text-color); font-weight: 500; }
  /* next */
  .hero { position: relative; min-height: 170px; display: flex; flex-direction: column; justify-content: flex-end; padding: 16px; cursor: pointer;
    background: linear-gradient(135deg, color-mix(in srgb, var(--meal-color) 30%, var(--card-background-color)), var(--card-background-color)); }
  .hero.img { color: #fff; background-size: cover; background-position: center; }
  .hero.img::before { content: ""; position: absolute; inset: 0; background: linear-gradient(0deg, rgba(0,0,0,.75), rgba(0,0,0,.05) 75%); }
  .hero > * { position: relative; }
  .hero .emoji { position: absolute; right: 16px; top: 12px; font-size: 64px; }
  .hero .k { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; opacity: .85; font-weight: 600; }
  .hero .t { font-size: 24px; font-weight: 600; line-height: 1.15; margin: 2px 0 4px; }
  .hero .s { font-size: 13px; opacity: .9; }
  .ing { padding: 10px 16px 14px; columns: 2; column-gap: 18px; font-size: 13.5px; line-height: 1.6; }
  .ing div { break-inside: avoid; }
  /* week */
  .days { display: flex; flex-direction: column; }
  .day { display: grid; grid-template-columns: 54px 1fr; gap: 10px; align-items: center; padding: 7px 0; border-top: 1px solid var(--divider-color); cursor: pointer; }
  .day:first-child { border-top: none; }
  .day.today .wd { color: var(--primary-color); }
  .day .wd { font-weight: 600; font-size: 14px; line-height: 1.1; }
  .day .wd small { display: block; font-weight: 400; font-size: 11.5px; color: var(--secondary-text-color); }
  .day .items { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { display: inline-flex; gap: 5px; align-items: center; font-size: 13px; padding: 3px 10px 3px 8px; border-radius: 999px;
    background: color-mix(in srgb, var(--meal-color) 13%, transparent); }
  .chip i { width: 7px; height: 7px; border-radius: 50%; background: var(--meal-color); }
  .chip.done { opacity: .55; text-decoration: line-through; }
  .chip.occ { font-weight: 500; }
  .free { font-size: 13px; color: var(--secondary-text-color); }
  .msg { padding: 16px; color: var(--secondary-text-color); }
`;

class EssensplanerCard extends HTMLElement {
  static getStubConfig() {
    return { mode: "today" };
  }

  static getConfigElement() {
    return document.createElement("essensplaner-card-editor");
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._unsub = null;
  }

  setConfig(config) {
    this._config = { mode: "today", days: 7, start: "today", show_images: true, show_ingredients: false, show_occasions: true, ...config };
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._connect();
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._connect();
    this._timer = setInterval(() => this._render(), 5 * 60 * 1000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    if (this._unsub) {
      Promise.resolve(this._unsub).then((u) => typeof u === "function" && u());
      this._unsub = null;
    }
  }

  async _connect() {
    await this._load();
    if (this._unsub || !this._hass?.connection) return;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(() => {
        clearTimeout(this._reload);
        this._reload = setTimeout(() => this._load(), 300);
      }, { type: `${DOMAIN}/subscribe` });
    } catch (e) {
      /* not loaded */
    }
  }

  async _load() {
    try {
      this._data = await this._hass.callWS({ type: `${DOMAIN}/data` });
      this._error = null;
    } catch (err) {
      this._error = err.message || "Essensplaner ist nicht eingerichtet.";
    }
    this._render();
  }

  getCardSize() {
    return this._config?.mode === "week" ? 6 : this._config?.mode === "next" ? 4 : 3;
  }

  getGridOptions() {
    const rows = this._config?.mode === "week" ? 6 : this._config?.mode === "next" ? 4 : 3;
    return { columns: 6, rows, min_columns: 4, min_rows: 2 };
  }

  _open(path = "") {
    history.pushState(null, "", `/essensplaner${path}`);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  _label(id) {
    return this._data.all_meals.find((m) => m.id === id)?.label || id;
  }

  /** Occasions of a day (1.5; none with show_occasions: false or an older backend). */
  _occasions(iso) {
    if (this._config.show_occasions === false) return [];
    return (this._data.occasions || []).filter((o) => o.date === iso);
  }

  _thumb(entry, mealId) {
    const recipe = this._data.recipes.find((r) => r.id === entry?.recipe_id);
    const url = this._config.show_images && recipe && safeUrl(recipe.image);
    if (url) return `<span class="thumb" style="background-image:url('${url}')"></span>`;
    const fallback = MEAL_STYLE[mealId]?.icon || "🍽️";
    return `<span class="thumb">${entry?.cooked ? "✅" : recipe ? dishEmoji(recipe.name) : entry ? "📝" : fallback}</span>`;
  }

  _render() {
    if (!this._config) return;
    let body;
    if (this._error) body = `<div class="msg">${esc(this._error)}</div>`;
    else if (!this._data) body = `<div class="msg">Lade …</div>`;
    else if (this._config.mode === "week") body = this._renderWeek();
    else if (this._config.mode === "next") body = this._renderNext();
    else body = this._renderToday();
    this.shadowRoot.innerHTML = `<style>${CARD_STYLE}</style><ha-card>${body}</ha-card>`;
    this.shadowRoot.querySelectorAll("[data-open]").forEach((el) => el.addEventListener("click", () => this._open()));
  }

  _budgetLine() {
    const week = this._data?.economy?.week;
    if (!week || !week.total) return "";
    const budget = this._data.economy.budget;
    if (!budget) return `<span>💶 Woche ≈ <b>${eur(week.total)}</b></span>`;
    const over = week.total > budget;
    return `<span>💶 Woche ≈ <b style="color:${over ? "#c62828" : "inherit"}">${eur(week.total)}</b> / ${eur(budget)}</span>`;
  }

  _head(title, sub) {
    const t = this._config.title ?? title;
    if (t === "") return "";
    return `<div class="head"><div class="title">${esc(t)}</div>${sub ? `<span class="sub">${esc(sub)}</span>` : ""}<button class="open" data-open title="Essensplaner öffnen">Öffnen ›</button></div>`;
  }

  _renderToday() {
    const today = this._data.today;
    const d = fromIso(today);
    const plan = this._data.plan[today] || {};
    const ids = [...this._data.meals.map((m) => m.id), ...Object.keys(plan).filter((k) => !this._data.meals.some((m) => m.id === k))];
    const rows = ids
      .map((id) => {
        const entry = plan[id];
        const color = MEAL_STYLE[id]?.color || "var(--primary-color)";
        const recipe = this._data.recipes.find((r) => r.id === entry?.recipe_id);
        const sub = entry ? [entry.servings ? `${entry.servings} Portionen` : "", recipe?.total_time ? `${recipe.total_time} min` : "", entry.note || ""].filter(Boolean).join(" · ") : "";
        return `<div class="meal ${entry ? "" : "empty"}" style="--meal-color:${color}" data-open>
            ${this._thumb(entry, id)}
            <div><div class="lbl">${esc(this._label(id))}</div><div class="t">${entry ? esc(entryTitle(entry, today)) : "noch nichts geplant"}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>
          </div>`;
      })
      .join("");
    const tomorrow = toIso(addDays(d, 1));
    const tPlan = Object.entries(this._data.plan[tomorrow] || {});
    const tMain = tPlan.find(([m]) => m === this._data.default_meal) || tPlan[0];
    const occasions = this._occasions(today);
    const occLine = occasions.length ? `<span>Heute: <b>${occasions.map((o) => `${esc(o.label || o.title)}${o.time ? ` ${esc(o.time)}` : ""}`).join(", ")}</b></span>` : "";
    return `<div class="wrap">
        ${this._head("Heute", `${WEEKDAYS[weekdayIndex(d)]}, ${d.getDate()}. ${MONTHS[d.getMonth()]}`)}
        <div class="meals">${rows}</div>
        <div class="foot">${occLine}<span>Morgen: <b>${tMain ? esc(entryTitle(tMain[1], tomorrow)) : "noch frei"}</b></span><span style="flex:1"></span>${this._budgetLine()}</div>
      </div>`;
  }

  _renderNext() {
    const up = upcomingMeal(this._data, new Date());
    if (!up) {
      return `<div class="wrap">${this._head("Nächste Mahlzeit")}<div class="msg" data-open>Es ist nichts geplant. Tippe, um den Essensplaner zu öffnen.</div></div>`;
    }
    const recipe = this._data.recipes.find((r) => r.id === up.entry.recipe_id);
    const url = this._config.show_images && recipe && safeUrl(recipe.image);
    const color = MEAL_STYLE[up.meal]?.color || "var(--primary-color)";
    const sub = [up.time ? `${up.time} Uhr` : "", up.entry.servings ? `${up.entry.servings} Portionen` : "", recipe?.total_time ? `⏱ ${recipe.total_time} min` : ""].filter(Boolean).join(" · ");
    let ingredients = "";
    if (this._config.show_ingredients && recipe?.ingredients?.length) {
      // nicely formatted (scaled) lines from the "next meal" sensor, if it shows the same meal
      const sensor = this._hass?.states?.[this._data.entities?.next_meal];
      let lines = sensor?.attributes?.date === up.date && sensor?.attributes?.meal === up.meal ? sensor.attributes.ingredients : null;
      if (!lines) {
        const factor = (up.entry.servings || recipe.servings || 1) / (recipe.servings || 1);
        const fmt = (n) => (Math.round(n * 100) / 100).toString().replace(".", ",");
        lines = recipe.ingredients.map((i) => [i.amount != null ? fmt(i.amount * factor) : "", i.unit, i.name].filter(Boolean).join(" "));
      }
      ingredients = `<div class="ing">${lines.map((l) => `<div>• ${esc(l)}</div>`).join("")}</div>`;
    }
    const title = this._config.title;
    return `${title ? `<div class="wrap" style="padding-bottom:0">${this._head(title)}</div>` : ""}
      <div class="hero ${url ? "img" : ""}" style="--meal-color:${color};${url ? `background-image:url('${url}')` : ""}" data-open>
        ${url ? "" : `<div class="emoji">${recipe ? dishEmoji(recipe.name) : "📝"}</div>`}
        <div class="k">${esc(relativeDay(up.date, this._data.today))} · ${esc(this._label(up.meal))}</div>
        <div class="t">${esc(entryTitle(up.entry, up.date))}</div>
        <div class="s">${esc(sub)}</div>
      </div>${ingredients}`;
  }

  _renderWeek() {
    const today = fromIso(this._data.today);
    const start = this._config.start === "monday" ? mondayOf(today) : today;
    const days = Math.max(1, Math.min(14, Number(this._config.days) || 7));
    const rows = [];
    for (let i = 0; i < days; i++) {
      const d = addDays(start, i);
      const iso = toIso(d);
      const plan = this._data.plan[iso] || {};
      const order = this._data.all_meals.map((m) => m.id);
      const entries = Object.entries(plan).sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
      const occasions = this._occasions(iso)
        .map((o) => `<span class="chip occ" style="--meal-color:#8e24aa" title="Anlass${o.time ? ` · ${esc(o.time)}` : ""}">${esc(o.emoji || "🎉")} ${esc(o.title)}</span>`)
        .join("");
      const meals = entries
        .map(([id, e]) => `<span class="chip ${e.cooked ? "done" : ""}" style="--meal-color:${MEAL_STYLE[id]?.color || "var(--primary-color)"}" title="${esc(this._label(id))}"><i></i>${esc(entryTitle(e, iso))}</span>`)
        .join("");
      const items = occasions || meals ? occasions + meals : `<span class="free">–</span>`;
      rows.push(`<div class="day ${iso === this._data.today ? "today" : ""}" data-open><div class="wd">${WEEKDAYS_SHORT[weekdayIndex(d)]}<small>${d.getDate()}. ${MONTHS[d.getMonth()]}</small></div><div class="items">${items}</div></div>`);
    }
    const budget = this._budgetLine();
    return `<div class="wrap">${this._head("Essensplan")}<div class="days">${rows.join("")}</div>${budget ? `<div class="foot">${budget}</div>` : ""}</div>`;
  }
}

class EssensplanerCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = { mode: "today", ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  _render() {
    const c = this._config;
    this.innerHTML = `
      <style>
        .ep-ed { display: flex; flex-direction: column; gap: 12px; padding: 4px 0; }
        .ep-ed label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--secondary-text-color); }
        .ep-ed label.cb { flex-direction: row; align-items: center; gap: 8px; color: var(--primary-text-color); }
        .ep-ed input:not([type=checkbox]), .ep-ed select { font: inherit; padding: 8px; border-radius: 8px; border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
      </style>
      <div class="ep-ed">
        <label>Ansicht
          <select data-key="mode">
            <option value="today" ${c.mode === "today" ? "selected" : ""}>Heute (alle Mahlzeiten)</option>
            <option value="next" ${c.mode === "next" ? "selected" : ""}>Nächste Mahlzeit (groß, mit Bild)</option>
            <option value="week" ${c.mode === "week" ? "selected" : ""}>Wochenübersicht</option>
          </select>
        </label>
        <label>Titel (leer = Standard)<input data-key="title" value="${esc(c.title || "")}"></label>
        ${c.mode === "week" ? `
          <label>Tage<input type="number" min="1" max="14" data-key="days" value="${esc(c.days || 7)}"></label>
          <label>Beginn
            <select data-key="start">
              <option value="today" ${c.start !== "monday" ? "selected" : ""}>Ab heute</option>
              <option value="monday" ${c.start === "monday" ? "selected" : ""}>Ab Montag</option>
            </select>
          </label>` : ""}
        ${c.mode === "next" ? `<label class="cb"><input type="checkbox" data-key="show_ingredients" ${c.show_ingredients ? "checked" : ""}> Zutaten anzeigen</label>` : ""}
        <label class="cb"><input type="checkbox" data-key="show_images" ${c.show_images !== false ? "checked" : ""}> Bilder anzeigen</label>
        ${c.mode !== "next" ? `<label class="cb"><input type="checkbox" data-key="show_occasions" ${c.show_occasions !== false ? "checked" : ""}> Anlässe anzeigen (z. B. „Heute: 🎬 Filmabend“)</label>` : ""}
      </div>`;
    this.querySelectorAll("[data-key]").forEach((el) =>
      el.addEventListener("change", () => {
        const key = el.dataset.key;
        let value = el.type === "checkbox" ? el.checked : el.value;
        if (key === "days") value = Number(value) || 7;
        const config = { ...this._config, [key]: value };
        if (key === "title" && !value) delete config.title;
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
        if (key === "mode") this._render();
      })
    );
  }
}

if (!customElements.get("essensplaner-card")) customElements.define("essensplaner-card", EssensplanerCard);
if (!customElements.get("essensplaner-card-editor")) customElements.define("essensplaner-card-editor", EssensplanerCardEditor);

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "essensplaner-card")) {
  window.customCards.push({
    type: "essensplaner-card",
    name: "Essensplaner",
    description: "Was gibt es heute? Heute, nächste Mahlzeit oder Wochenübersicht aus dem Essensplaner.",
    preview: true,
    documentationURL: "https://github.com/tollzockt/HA-Essens-planer-",
  });
}
