/*
 * Essensplaner – sidebar panel for Home Assistant.
 * Plain web component (no build step, no external dependencies).
 */

const DOMAIN = "essensplaner";
const WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const MONTHS = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."];
const CATEGORY_ORDER = [
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
const CATEGORY_ICONS = {
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
  [/suppe|eintopf|chili|gulasch|brühe|bruehe/, "🍲"],
  [/curry|dal|reis|risotto|paella|bowl/, "🍛"],
  [/salat/, "🥗"],
  [/lachs|fisch|thunfisch|garnele|shrimp|scampi/, "🐟"],
  [/haehnchen|huhn|chicken|pute/, "🍗"],
  [/schnitzel|steak|braten|fleisch/, "🥩"],
  [/nudel|pasta|spaghetti|lasagne|penne|spaetzle|gnocchi|tagliatelle|maccheroni/, "🍝"],
  [/ramen|pho|asia|wok|nudelsuppe/, "🍜"],
  [/kartoffel|pommes|gratin/, "🥔"],
  [/gemuese|ofen|auflauf/, "🥘"],
];

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const pad = (n) => String(n).padStart(2, "0");
const toIso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fromIso = (s) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const addDays = (d, n) => {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
};
const mondayOf = (d) => addDays(d, -((d.getDay() + 6) % 7));
const weekdayIndex = (d) => (d.getDay() + 6) % 7;
const isoWeek = (d) => {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return Math.ceil(((t - yearStart) / 86400000 + 1) / 7);
};
const dishEmoji = (name) => {
  const key = fold(name);
  for (const [re, emoji] of DISH_EMOJIS) if (re.test(key)) return emoji;
  return "🍽️";
};
const fold = (s) =>
  String(s ?? "")
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss");

const STYLE = `
  :host {
    display: block;
    min-height: 100vh;
    background: var(--primary-background-color, #fafafa);
    color: var(--primary-text-color, #212121);
    font-family: var(--paper-font-body1_-_font-family, Roboto, "Noto Sans", sans-serif);
    --ep-radius: var(--ha-card-border-radius, 12px);
    --ep-card: var(--card-background-color, #fff);
    --ep-divider: var(--divider-color, rgba(0,0,0,.12));
    --ep-primary: var(--primary-color, #03a9f4);
    --ep-secondary-text: var(--secondary-text-color, #727272);
    --ep-accent-bg: color-mix(in srgb, var(--ep-primary) 12%, transparent);
  }
  * { box-sizing: border-box; }
  header {
    position: sticky; top: 0; z-index: 2;
    background: var(--app-header-background-color, var(--ep-primary));
    color: var(--app-header-text-color, #fff);
    box-shadow: var(--card-box-shadow, 0 2px 4px rgba(0,0,0,.15));
  }
  .toolbar { display: flex; align-items: center; height: 56px; padding: 0 12px; gap: 8px; }
  .toolbar .title { font-size: 20px; font-weight: 400; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tabs { display: flex; gap: 4px; padding: 0 8px; overflow-x: auto; }
  .tab {
    background: none; border: none; color: inherit; opacity: .75; cursor: pointer;
    padding: 10px 14px; font-size: 14px; font-weight: 500; letter-spacing: .03em;
    border-bottom: 3px solid transparent; white-space: nowrap;
  }
  .tab.active { opacity: 1; border-bottom-color: currentColor; }
  main { padding: 16px; max-width: 1400px; margin: 0 auto; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 16px; }
  .spacer { flex: 1; }
  button.btn, a.btn {
    display: inline-flex; align-items: center; gap: 6px;
    border: 1px solid var(--ep-divider); background: var(--ep-card); color: var(--primary-text-color);
    border-radius: 999px; padding: 8px 14px; font-size: 14px; cursor: pointer; text-decoration: none;
    font-family: inherit;
  }
  button.btn:hover { border-color: var(--ep-primary); }
  button.btn.primary { background: var(--ep-primary); border-color: var(--ep-primary); color: var(--text-primary-color, #fff); }
  button.btn.danger { color: var(--error-color, #db4437); }
  button.btn.small { padding: 4px 10px; font-size: 13px; }
  button.icon { background: none; border: none; cursor: pointer; color: inherit; font-size: 18px; padding: 6px; border-radius: 50%; line-height: 1; }
  button.icon:hover { background: var(--ep-accent-bg); }
  .weeklabel { font-size: 18px; font-weight: 500; min-width: 180px; text-align: center; }
  input, select, textarea {
    font: inherit; color: var(--primary-text-color);
    background: var(--input-fill-color, var(--ep-card));
    border: 1px solid var(--ep-divider); border-radius: 8px; padding: 8px 10px;
  }
  textarea { width: 100%; min-height: 120px; resize: vertical; }
  input:focus, select:focus, textarea:focus { outline: 2px solid var(--ep-primary); outline-offset: -1px; }
  .card { background: var(--ep-card); border-radius: var(--ep-radius); box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(0,0,0,.12)); border: var(--ha-card-border-width, 0) solid var(--ep-divider); }
  /* week plan */
  .week { display: grid; grid-template-columns: repeat(7, minmax(150px, 1fr)); gap: 12px; }
  @media (max-width: 1100px) { .week { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); } }
  .day { padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .day.today { outline: 2px solid var(--ep-primary); }
  .day.past { opacity: .7; }
  .dayhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; }
  .dayhead .dt { white-space: nowrap; }
  .dayhead .wd { font-weight: 600; font-size: 15px; }
  .dayhead .dt { color: var(--ep-secondary-text); font-size: 13px; }
  .badge { margin-left: auto; font-size: 11px; background: var(--ep-primary); color: var(--text-primary-color, #fff); border-radius: 999px; padding: 2px 8px; }
  .slot { border-top: 1px solid var(--ep-divider); padding-top: 6px; }
  .slot .label { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--ep-secondary-text); margin-bottom: 4px; }
  .meal {
    width: 100%; text-align: left; border: none; cursor: pointer; font: inherit; color: inherit;
    background: var(--ep-accent-bg); border-radius: 8px; padding: 8px; display: flex; gap: 8px; align-items: center;
  }
  .meal .emoji { font-size: 20px; }
  .meal .t { font-weight: 500; line-height: 1.2; }
  .meal .s { font-size: 12px; color: var(--ep-secondary-text); }
  .meal.cooked .t { text-decoration: line-through; opacity: .7; }
  .meal.free { background: color-mix(in srgb, var(--ep-secondary-text) 12%, transparent); }
  .add { width: 100%; border: 1px dashed var(--ep-divider); background: none; color: var(--ep-secondary-text); border-radius: 8px; padding: 8px; cursor: pointer; font: inherit; }
  .add:hover { border-color: var(--ep-primary); color: var(--ep-primary); }
  /* recipes */
  .recipes { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
  .recipe { cursor: pointer; overflow: hidden; display: flex; flex-direction: column; }
  .recipe .img { height: 130px; background: var(--ep-accent-bg) center/cover no-repeat; display: flex; align-items: center; justify-content: center; font-size: 52px; }
  .recipe .body { padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
  .recipe .name { font-weight: 600; font-size: 15px; line-height: 1.25; display: flex; gap: 6px; }
  .recipe .name span { flex: 1; }
  .meta { font-size: 12px; color: var(--ep-secondary-text); }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { font-size: 11px; border-radius: 999px; padding: 2px 8px; background: var(--ep-accent-bg); color: var(--primary-text-color); border: none; cursor: pointer; font-family: inherit; }
  .chip.active { background: var(--ep-primary); color: var(--text-primary-color, #fff); }
  .star { color: #f4b400; }
  /* shopping */
  .shopping { max-width: 760px; }
  .group { margin-bottom: 14px; padding: 6px 0; }
  .group h3 { margin: 0; padding: 8px 14px; font-size: 14px; font-weight: 600; color: var(--ep-secondary-text); }
  .item { display: flex; align-items: center; gap: 10px; padding: 8px 14px; border-top: 1px solid var(--ep-divider); }
  .item input[type=checkbox] { width: 20px; height: 20px; accent-color: var(--ep-primary); flex: none; }
  .item .txt { flex: 1; min-width: 0; }
  .item .sum { font-size: 15px; }
  .item .desc { font-size: 12px; color: var(--ep-secondary-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .item.done .sum { text-decoration: line-through; opacity: .6; }
  .empty { text-align: center; color: var(--ep-secondary-text); padding: 40px 16px; }
  .empty .big { font-size: 46px; }
  /* modal */
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 10; display: flex; align-items: center; justify-content: center; padding: 16px; }
  .modal { background: var(--ep-card); color: var(--primary-text-color); border-radius: var(--ep-radius); width: min(640px, 100%); max-height: calc(100vh - 32px); overflow: auto; box-shadow: 0 10px 40px rgba(0,0,0,.35); }
  .modal .mhead { display: flex; align-items: center; gap: 8px; padding: 16px 16px 8px; position: sticky; top: 0; background: var(--ep-card); z-index: 1; }
  .modal .mhead h2 { margin: 0; font-size: 20px; font-weight: 500; flex: 1; }
  .modal .mbody { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 12px; }
  .modal .mfoot { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 16px 16px; justify-content: flex-end; border-top: 1px solid var(--ep-divider); }
  .modal .hero { height: 180px; border-radius: 10px; background: var(--ep-accent-bg) center/cover no-repeat; display: flex; align-items: center; justify-content: center; font-size: 70px; }
  .modal h4 { margin: 4px 0; font-size: 15px; }
  .modal ul, .modal ol { margin: 0; padding-left: 22px; line-height: 1.55; }
  .modal ol li { margin-bottom: 6px; }
  label.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--ep-secondary-text); }
  label.field input, label.field select, label.field textarea { color: var(--primary-text-color); font-size: 15px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .picklist { display: flex; flex-direction: column; max-height: 300px; overflow: auto; border: 1px solid var(--ep-divider); border-radius: 8px; }
  .pick { text-align: left; background: none; border: none; border-bottom: 1px solid var(--ep-divider); padding: 10px 12px; cursor: pointer; font: inherit; color: inherit; display: flex; gap: 8px; align-items: center; }
  .pick:last-child { border-bottom: none; }
  .pick:hover, .pick.sel { background: var(--ep-accent-bg); }
  .pick .m { margin-left: auto; font-size: 12px; color: var(--ep-secondary-text); }
  .stepper { display: inline-flex; align-items: center; gap: 6px; }
  .stepper input { width: 64px; text-align: center; }
  .hint { font-size: 12px; color: var(--ep-secondary-text); }
  .error { color: var(--error-color, #db4437); padding: 24px; }
  .loading { padding: 40px; text-align: center; color: var(--ep-secondary-text); }
  @media (max-width: 600px) { main { padding: 10px; } .grid2 { grid-template-columns: 1fr; } .weeklabel { min-width: 0; font-size: 16px; } }
`;

class EssensplanerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tab = this._loadPref("tab", "plan");
    this._weekStart = null;
    this._data = null;
    this._search = "";
    this._tag = "";
    this._favOnly = false;
    this._modal = null;
    this._unsub = null;
    this._reloadTimer = null;
    this._onKey = (ev) => {
      if (ev.key === "Escape" && this._modal) this._closeModal();
    };
  }

  /* ------------------------------------------------------------ HA props */
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._init();
    if (this._menuButton) this._menuButton.hass = hass;
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
    if (this._hass && !this._unsub && this._data) this._subscribe();
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
    if (this._unsub) {
      Promise.resolve(this._unsub).then((unsub) => typeof unsub === "function" && unsub());
      this._unsub = null;
    }
  }

  _loadPref(key, fallback) {
    try {
      return localStorage.getItem(`essensplaner-${key}`) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  _savePref(key, value) {
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
    try {
      this._data = await this._hass.callWS({ type: `${DOMAIN}/data` });
      if (!this._weekStart) this._weekStart = mondayOf(fromIso(this._data.today));
      this._renderContent();
      if (this._modal && this._modal.refresh) this._modal.refresh();
    } catch (err) {
      this._content.innerHTML = `<div class="error">Essensplaner konnte nicht geladen werden: ${esc(
        err.message || err.code || err
      )}<br><br>Ist die Integration eingerichtet?</div>`;
    }
  }

  async _subscribe() {
    if (this._unsub) return;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(() => this._scheduleReload(), {
        type: `${DOMAIN}/subscribe`,
      });
    } catch (err) {
      /* integration not loaded – ignore */
    }
  }

  _scheduleReload() {
    clearTimeout(this._reloadTimer);
    this._reloadTimer = setTimeout(() => this._load(), 250);
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
      this._toast(err.message || String(err));
      throw err;
    }
  }

  async _todo(service, data) {
    const entity = this._data?.entities?.shopping_list;
    if (!entity) return;
    try {
      await this._hass.callService("todo", service, { entity_id: entity, ...data });
    } catch (err) {
      this._toast(err.message || String(err));
    }
  }

  _toast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true })
    );
  }

  _recipe(id) {
    return this._data?.recipes.find((r) => r.id === id);
  }

  _todayIso() {
    return this._data?.today || toIso(new Date());
  }

  /* ------------------------------------------------------------ shell */
  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <header>
        <div class="toolbar"><span class="menu"></span><div class="title">🍽️ Essensplaner</div></div>
        <div class="tabs">
          <button class="tab" data-tab="plan">Wochenplan</button>
          <button class="tab" data-tab="recipes">Rezepte</button>
          <button class="tab" data-tab="shopping">Einkaufsliste</button>
        </div>
      </header>
      <main><div class="loading">Lade …</div></main>
      <div class="modalroot"></div>`;
    this._content = this.shadowRoot.querySelector("main");
    this._modalRoot = this.shadowRoot.querySelector(".modalroot");
    const menu = document.createElement("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;
    this.shadowRoot.querySelector(".menu").appendChild(menu);
    this._menuButton = menu;
    this.shadowRoot.querySelectorAll(".tab").forEach((tab) =>
      tab.addEventListener("click", () => {
        this._tab = tab.dataset.tab;
        this._savePref("tab", this._tab);
        this._renderContent();
      })
    );
    this._content.addEventListener("click", (ev) => this._onClick(ev));
    this._content.addEventListener("input", (ev) => this._onInput(ev));
    this._content.addEventListener("change", (ev) => this._onChange(ev));
    this._content.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && ev.target.dataset.enter) {
        ev.preventDefault();
        this._action(ev.target.dataset.enter, ev.target);
      }
    });
  }

  _renderContent() {
    if (!this._data) return;
    this.shadowRoot
      .querySelectorAll(".tab")
      .forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === this._tab));
    const focused = this.shadowRoot.activeElement;
    const focusKey = focused?.dataset?.focuskey;
    const caret = focused?.selectionStart;
    if (this._tab === "recipes") this._content.innerHTML = this._renderRecipes();
    else if (this._tab === "shopping") this._content.innerHTML = this._renderShopping();
    else this._content.innerHTML = this._renderPlan();
    if (focusKey) {
      const el = this._content.querySelector(`[data-focuskey="${focusKey}"]`);
      if (el) {
        el.focus();
        if (caret != null && el.setSelectionRange) el.setSelectionRange(caret, caret);
      }
    }
  }

  /* ------------------------------------------------------------ plan */
  _renderPlan() {
    const start = this._weekStart;
    const end = addDays(start, 6);
    const today = this._todayIso();
    const label = `KW ${isoWeek(start)} · ${start.getDate()}. ${start.getMonth() === end.getMonth() ? "" : MONTHS[start.getMonth()] + " "}– ${end.getDate()}. ${MONTHS[end.getMonth()]}`;
    let days = "";
    for (let i = 0; i < 7; i++) {
      const day = addDays(start, i);
      const iso = toIso(day);
      const meals = this._data.plan[iso] || {};
      const slots = this._data.meals
        .map((meal) => {
          const entry = meals[meal.id];
          let inner;
          if (entry) {
            const recipe = this._recipe(entry.recipe_id);
            const sub = [entry.servings ? `${entry.servings} Port.` : "", recipe?.total_time ? `${recipe.total_time} min` : "", entry.note || ""]
              .filter(Boolean)
              .join(" · ");
            inner = `<button class="meal ${recipe ? "" : "free"} ${entry.cooked ? "cooked" : ""}" data-action="open-entry" data-date="${iso}" data-meal="${meal.id}">
                <span class="emoji">${entry.cooked ? "✅" : recipe ? dishEmoji(recipe.name) : "📝"}</span>
                <span><div class="t">${esc(entry.title)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ""}</span>
              </button>`;
          } else {
            inner = `<button class="add" data-action="add-entry" data-date="${iso}" data-meal="${meal.id}">＋</button>`;
          }
          return `<div class="slot"><div class="label">${esc(meal.label)}</div>${inner}</div>`;
        })
        .join("");
      // meals that are planned for slots which are currently disabled
      const extra = Object.entries(meals)
        .filter(([id]) => !this._data.meals.some((m) => m.id === id))
        .map(([id, entry]) => {
          const label = this._data.all_meals.find((m) => m.id === id)?.label || id;
          return `<div class="slot"><div class="label">${esc(label)}</div><button class="meal" data-action="open-entry" data-date="${iso}" data-meal="${id}"><span class="emoji">🍽️</span><span class="t">${esc(entry.title)}</span></button></div>`;
        })
        .join("");
      const cls = iso === today ? "today" : iso < today ? "past" : "";
      days += `<div class="card day ${cls}">
          <div class="dayhead"><span class="wd">${WEEKDAYS[i]}</span><span class="dt">${day.getDate()}. ${MONTHS[day.getMonth()]}</span>${iso === today ? '<span class="badge">Heute</span>' : ""}</div>
          ${slots}${extra}
        </div>`;
    }
    return `
      <div class="row">
        <button class="icon" data-action="week" data-delta="-7" title="Vorherige Woche">◀</button>
        <div class="weeklabel">${esc(label)}</div>
        <button class="icon" data-action="week" data-delta="7" title="Nächste Woche">▶</button>
        <button class="btn small" data-action="week" data-delta="0">Heute</button>
        <span class="spacer"></span>
        <button class="btn" data-action="auto-plan">✨ Woche automatisch füllen</button>
        <button class="btn primary" data-action="shopping-from-week">🛒 Einkaufsliste erstellen</button>
      </div>
      <div class="week">${days}</div>`;
  }

  _weekRemaining() {
    const today = fromIso(this._todayIso());
    const start = this._weekStart < today ? today : this._weekStart;
    const end = addDays(this._weekStart, 6);
    const days = Math.round((end - start) / 86400000) + 1;
    return { start: toIso(start), days: Math.max(days, 0) };
  }

  /* ------------------------------------------------------------ recipes */
  _filteredRecipes() {
    const q = fold(this._search).trim();
    return this._data.recipes.filter((r) => {
      if (this._favOnly && !r.favorite) return false;
      if (this._tag && !(r.tags || []).some((t) => fold(t) === fold(this._tag))) return false;
      if (!q) return true;
      const hay = fold([r.name, ...(r.tags || []), ...(r.ingredients || []).map((i) => i.name)].join(" "));
      return q.split(/\s+/).every((w) => hay.includes(w));
    });
  }

  _renderRecipes() {
    const tags = [...new Set(this._data.recipes.flatMap((r) => r.tags || []))].sort((a, b) =>
      a.localeCompare(b, "de")
    );
    const recipes = this._filteredRecipes();
    const cards = recipes
      .map((r) => {
        const img = r.image ? `style="background-image:url('${esc(r.image)}')"` : "";
        const meta = [r.total_time ? `⏱ ${r.total_time} min` : "", r.servings ? `👥 ${r.servings}` : "", r.cooked_count ? `🍳 ${r.cooked_count}×` : ""]
          .filter(Boolean)
          .join(" · ");
        return `<div class="card recipe" data-action="open-recipe" data-id="${esc(r.id)}">
            <div class="img" ${img}>${r.image ? "" : dishEmoji(r.name)}</div>
            <div class="body">
              <div class="name"><span>${esc(r.name)}</span><button class="icon star" data-action="toggle-fav" data-id="${esc(r.id)}" title="Favorit">${r.favorite ? "★" : "☆"}</button></div>
              ${meta ? `<div class="meta">${meta}</div>` : ""}
              <div class="chips">${(r.tags || []).slice(0, 4).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
            </div>
          </div>`;
      })
      .join("");
    return `
      <div class="row">
        <input type="search" placeholder="Rezepte oder Zutaten suchen …" value="${esc(this._search)}" data-input="search" data-focuskey="search" style="flex:1;min-width:200px">
        <button class="btn ${this._favOnly ? "primary" : ""}" data-action="fav-only">★ Favoriten</button>
        <button class="btn" data-action="import">🌐 Von URL importieren</button>
        <button class="btn primary" data-action="new-recipe">＋ Neues Rezept</button>
      </div>
      <div class="row chips">
        <button class="chip ${this._tag ? "" : "active"}" data-action="tag" data-tag="">Alle (${this._data.recipes.length})</button>
        ${tags.map((t) => `<button class="chip ${fold(t) === fold(this._tag) ? "active" : ""}" data-action="tag" data-tag="${esc(t)}">${esc(t)}</button>`).join("")}
      </div>
      ${recipes.length ? `<div class="recipes">${cards}</div>` : `<div class="empty"><div class="big">📖</div>Keine Rezepte gefunden.</div>`}`;
  }

  /* ------------------------------------------------------------ shopping */
  _renderShopping() {
    const items = this._data.shopping || [];
    const open = items.filter((i) => i.status !== "completed");
    const done = items.filter((i) => i.status === "completed");
    const groups = {};
    for (const item of open) {
      const cat = item.category || "Sonstiges";
      (groups[cat] = groups[cat] || []).push(item);
    }
    const order = (c) => {
      const i = CATEGORY_ORDER.indexOf(c);
      return i === -1 ? 99 : i;
    };
    const describe = (item) => {
      const desc = item.description || "";
      const prefix = `${item.category} · `;
      if (item.status !== "completed" && item.category && desc.startsWith(prefix)) return desc.slice(prefix.length);
      if (item.status !== "completed" && desc === item.category) return "";
      return desc;
    };
    const renderItem = (item) => `
      <div class="item ${item.status === "completed" ? "done" : ""}">
        <input type="checkbox" data-change="toggle-item" data-uid="${esc(item.uid)}" ${item.status === "completed" ? "checked" : ""}>
        <div class="txt"><div class="sum">${esc(item.summary)}</div>${describe(item) ? `<div class="desc">${esc(describe(item))}</div>` : ""}</div>
        <button class="icon" data-action="delete-item" data-uid="${esc(item.uid)}" title="Entfernen">✕</button>
      </div>`;
    const groupHtml = Object.keys(groups)
      .sort((a, b) => order(a) - order(b))
      .map(
        (cat) => `<div class="card group"><h3>${CATEGORY_ICONS[cat] || "🛒"} ${esc(cat)} <span class="meta">(${groups[cat].length})</span></h3>${groups[cat].map(renderItem).join("")}</div>`
      )
      .join("");
    return `<div class="shopping">
      <div class="row">
        <input placeholder="Artikel hinzufügen, z. B. „2 Liter Milch“" data-enter="add-item" data-focuskey="additem" style="flex:1;min-width:200px">
        <button class="btn primary" data-action="add-item">Hinzufügen</button>
      </div>
      <div class="row">
        <button class="btn" data-action="shopping-next-week">🗓️ Aus Plan der nächsten 7 Tage erstellen</button>
        <span class="spacer"></span>
        ${done.length ? `<button class="btn" data-action="clear-done">Erledigte entfernen (${done.length})</button>` : ""}
      </div>
      ${open.length ? groupHtml : `<div class="empty"><div class="big">🛒</div>Die Einkaufsliste ist leer.<br><span class="hint">Plane Mahlzeiten und erstelle die Liste per Knopfdruck – oder sag „Jarvis, erstelle die Einkaufsliste“.</span></div>`}
      ${done.length ? `<div class="card group"><h3>✅ Erledigt</h3>${done.map(renderItem).join("")}</div>` : ""}
    </div>`;
  }

  /* ------------------------------------------------------------ events */
  _onInput(ev) {
    const key = ev.target.dataset.input;
    if (key === "search") {
      this._search = ev.target.value;
      this._renderContent();
    }
  }

  async _onChange(ev) {
    const t = ev.target;
    if (t.dataset.change === "toggle-item") {
      await this._todo("update_item", { item: t.dataset.uid, status: t.checked ? "completed" : "needs_action" });
    }
  }

  _onClick(ev) {
    const el = ev.target.closest("[data-action]");
    if (!el || !this._content.contains(el)) return;
    ev.stopPropagation();
    this._action(el.dataset.action, el);
  }

  async _action(action, el) {
    const d = el.dataset;
    switch (action) {
      case "week":
        this._weekStart = d.delta === "0" ? mondayOf(fromIso(this._todayIso())) : addDays(this._weekStart, Number(d.delta));
        this._renderContent();
        break;
      case "add-entry":
        this._openPicker(d.date, d.meal);
        break;
      case "open-entry":
        this._openEntry(d.date, d.meal);
        break;
      case "auto-plan": {
        const { start, days } = this._weekRemaining();
        if (!days) return this._toast("Diese Woche liegt in der Vergangenheit.");
        const res = await this._service("auto_plan", { start_date: start, days, meals: [this._data.default_meal] }, true);
        this._toast(res?.planned?.length ? `${res.planned.length} Mahlzeiten eingeplant` : "Keine freien Plätze oder passenden Rezepte");
        break;
      }
      case "shopping-from-week": {
        const { start, days } = this._weekRemaining();
        if (!days) return this._toast("Diese Woche liegt in der Vergangenheit.");
        const res = await this._service("generate_shopping_list", { start_date: start, days }, true);
        this._toast(`Einkaufsliste: ${res?.items?.length || 0} Artikel für ${res?.meals || 0} Mahlzeiten`);
        this._tab = "shopping";
        this._savePref("tab", "shopping");
        break;
      }
      case "shopping-next-week": {
        const res = await this._service("generate_shopping_list", { start_date: this._todayIso(), days: 7 }, true);
        this._toast(`Einkaufsliste: ${res?.items?.length || 0} Artikel für ${res?.meals || 0} Mahlzeiten`);
        break;
      }
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
        this._openRecipe(d.id);
        break;
      case "new-recipe":
        this._openEditor(null);
        break;
      case "import":
        this._openImport();
        break;
      case "add-item": {
        const input = this._content.querySelector('[data-focuskey="additem"]');
        const value = input?.value.trim();
        if (!value) return;
        input.value = "";
        await this._todo("add_item", { item: value });
        break;
      }
      case "delete-item":
        await this._todo("remove_item", { item: d.uid });
        break;
      case "clear-done":
        await this._todo("remove_completed_items", {});
        break;
      default:
        break;
    }
  }

  /* ------------------------------------------------------------ modals */
  _showModal(title, body, footer, onMount, refresh) {
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
      if (ev.target === overlay || ev.target.closest("[data-close]")) this._closeModal();
    });
    this._modal = { root: overlay, refresh };
    if (onMount) onMount(overlay);
  }

  _closeModal() {
    this._modalRoot.innerHTML = "";
    this._modal = null;
  }

  _mealLabel(id) {
    return this._data.all_meals.find((m) => m.id === id)?.label || id;
  }

  _dateLabel(iso) {
    const d = fromIso(iso);
    return `${WEEKDAYS[weekdayIndex(d)]}, ${d.getDate()}. ${MONTHS[d.getMonth()]}`;
  }

  _openPicker(date, meal, current) {
    const servings = current?.servings || this._data.default_servings;
    let selected = current?.recipe_id || null;
    let query = "";
    const listHtml = () => {
      const q = fold(query).trim();
      const items = this._data.recipes
        .filter((r) => !q || fold(r.name).includes(q) || (r.tags || []).some((t) => fold(t).includes(q)))
        .slice(0, 80);
      if (!items.length) return `<div class="pick" style="cursor:default">Kein Rezept gefunden – als Freitext eintragen?</div>`;
      return items
        .map(
          (r) => `<button class="pick ${r.id === selected ? "sel" : ""}" data-pick="${esc(r.id)}">${dishEmoji(r.name)} ${esc(r.name)}${r.favorite ? ' <span class="star">★</span>' : ""}<span class="m">${r.total_time ? r.total_time + " min" : ""}</span></button>`
        )
        .join("");
    };
    const body = `
      <div class="hint">${esc(this._dateLabel(date))} · ${esc(this._mealLabel(meal))}</div>
      <input type="search" placeholder="Rezept suchen oder Freitext eingeben …" class="q" value="${esc(current && !current.recipe_id ? current.title : "")}">
      <div class="row" style="margin:0"><button class="btn small suggest">💡 Vorschläge</button><span class="suggestions chips"></span></div>
      <div class="picklist">${listHtml()}</div>
      <div class="grid2">
        <label class="field">Portionen<input type="number" min="1" max="50" class="servings" value="${servings}"></label>
        <label class="field">Notiz<input class="note" value="${esc(current?.note || "")}" placeholder="optional"></label>
      </div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">Einplanen</button>`;
    this._showModal("Mahlzeit planen", body, footer, (root) => {
      const q = root.querySelector(".q");
      const list = root.querySelector(".picklist");
      q.focus();
      q.addEventListener("input", () => {
        query = q.value;
        selected = null;
        list.innerHTML = listHtml();
      });
      list.addEventListener("click", (ev) => {
        const pick = ev.target.closest("[data-pick]");
        if (!pick) return;
        selected = pick.dataset.pick;
        list.innerHTML = listHtml();
      });
      list.addEventListener("dblclick", (ev) => {
        if (ev.target.closest("[data-pick]")) root.querySelector(".save").click();
      });
      root.querySelector(".suggest").addEventListener("click", async () => {
        const res = await this._service("suggest_recipes", { count: 3, meal, date }, true);
        root.querySelector(".suggestions").innerHTML = (res?.recipes || [])
          .map((r) => `<button class="chip" data-sugg="${esc(r.id)}">${esc(r.name)}</button>`)
          .join("") || '<span class="hint">Keine passenden Rezepte</span>';
      });
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
      <div class="hint">${esc(this._dateLabel(date))} · ${esc(this._mealLabel(meal))}</div>
      ${recipe?.image ? `<div class="hero" style="background-image:url('${esc(recipe.image)}')"></div>` : `<div class="hero">${recipe ? dishEmoji(recipe.name) : "📝"}</div>`}
      <div>${entry.servings ? `👥 ${entry.servings} Portionen` : ""} ${recipe?.total_time ? ` · ⏱ ${recipe.total_time} min` : ""}</div>
      ${entry.note ? `<div>📝 ${esc(entry.note)}</div>` : ""}
      ${!recipe ? `<div class="hint">Freitext ohne Rezept – Zutaten landen nicht auf der Einkaufsliste.</div>` : ""}
      ${entry.cooked ? `<div>✅ Gekocht</div>` : ""}`;
    const footer = `
      <button class="btn danger remove">Entfernen</button>
      <button class="btn change">Ändern</button>
      ${entry.cooked ? "" : `<button class="btn cooked">✅ Gekocht</button>`}
      ${recipe ? `<button class="btn primary show">Rezept ansehen</button>` : ""}`;
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
      root.querySelector(".show")?.addEventListener("click", () => this._openRecipe(recipe.id, entry.servings));
    });
  }

  async _openRecipe(id, servingsOverride) {
    const base = this._recipe(id);
    if (!base) return;
    let servings = servingsOverride || base.servings || this._data.default_servings;
    const render = async () => {
      const res = await this._service("get_recipe", { recipe: id, servings }, true);
      const r = res?.recipe || base;
      const body = `
        ${r.image ? `<div class="hero" style="background-image:url('${esc(r.image)}')"></div>` : `<div class="hero">${dishEmoji(r.name)}</div>`}
        <div class="row" style="margin:0">
          <span class="stepper">👥 <button class="icon minus">−</button><input type="number" class="servings" min="1" max="50" value="${servings}"><button class="icon plus">＋</button> Portionen</span>
          <span class="spacer"></span>
          <span class="meta">${[r.prep_time ? `Vorbereitung ${r.prep_time} min` : "", r.cook_time ? `Kochen ${r.cook_time} min` : "", r.total_time ? `Gesamt ${r.total_time} min` : ""].filter(Boolean).join(" · ")}</span>
        </div>
        <div class="chips">${(r.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        <div><h4>Zutaten</h4>${(r.ingredient_lines || []).length ? `<ul>${r.ingredient_lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : '<div class="hint">Keine Zutaten hinterlegt.</div>'}</div>
        <div><h4>Zubereitung</h4>${(r.steps || []).length ? `<ol>${r.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>` : '<div class="hint">Keine Schritte hinterlegt.</div>'}</div>
        ${r.notes ? `<div><h4>Notizen</h4><div>${esc(r.notes)}</div></div>` : ""}
        ${r.source_url ? `<div><a class="btn small" href="${esc(r.source_url)}" target="_blank" rel="noreferrer">🔗 Originalrezept</a></div>` : ""}
        <div class="card" style="padding:12px;display:flex;flex-direction:column;gap:8px">
          <h4>Einplanen</h4>
          <div class="grid2">
            <label class="field">Datum<input type="date" class="pdate" value="${esc(this._todayIso())}"></label>
            <label class="field">Mahlzeit<select class="pmeal">${this._data.all_meals.map((m) => `<option value="${m.id}" ${m.id === this._data.default_meal ? "selected" : ""}>${esc(m.label)}</option>`).join("")}</select></label>
          </div>
          <div><button class="btn primary plan">📅 Einplanen</button></div>
        </div>`;
      const footer = `
        <button class="btn danger delete">Löschen</button>
        <button class="btn fav">${base.favorite ? "★ Favorit" : "☆ Favorit"}</button>
        <button class="btn edit">✏️ Bearbeiten</button>`;
      this._showModal(r.name, body, footer, (root) => {
        const input = root.querySelector(".servings");
        const set = (v) => {
          servings = Math.max(1, Math.min(50, v || 1));
          render();
        };
        root.querySelector(".minus").addEventListener("click", () => set(servings - 1));
        root.querySelector(".plus").addEventListener("click", () => set(servings + 1));
        input.addEventListener("change", () => set(Number(input.value)));
        root.querySelector(".plan").addEventListener("click", async () => {
          const date = root.querySelector(".pdate").value;
          const meal = root.querySelector(".pmeal").value;
          if (!date) return;
          await this._service("plan_meal", { date, meal, recipe: id, servings });
          this._toast(`${r.name} eingeplant: ${this._dateLabel(date)}, ${this._mealLabel(meal)}`);
          this._closeModal();
        });
        root.querySelector(".fav").addEventListener("click", async () => {
          await this._service("update_recipe", { recipe: id, favorite: !base.favorite });
          base.favorite = !base.favorite;
          root.querySelector(".fav").textContent = base.favorite ? "★ Favorit" : "☆ Favorit";
        });
        root.querySelector(".edit").addEventListener("click", () => this._openEditor(this._recipe(id)));
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
      <label class="field">Zutaten (eine pro Zeile, z. B. „400 g Spaghetti“)<textarea class="ingredients">${esc((r.ingredients || []).map((i) => this._ingredientLine(i)).join("\n"))}</textarea></label>
      <label class="field">Zubereitung (ein Schritt pro Zeile)<textarea class="steps">${esc((r.steps || []).join("\n"))}</textarea></label>
      <label class="field">Notizen<textarea class="notes" style="min-height:60px">${esc(r.notes || "")}</textarea></label>
      <div class="grid2">
        <label class="field">Bild-URL<input class="image" value="${esc(r.image || "")}" placeholder="https://…"></label>
        <label class="field">Quelle<input class="source" value="${esc(r.source_url || "")}" placeholder="https://…"></label>
      </div>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary save">Speichern</button>`;
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
        let res;
        if (recipe) res = await this._service("update_recipe", { recipe: recipe.id, ...data }, true);
        else res = await this._service("add_recipe", data, true);
        this._closeModal();
        if (res?.recipe?.id) setTimeout(() => this._openRecipe(res.recipe.id), 350);
      });
    });
  }

  _openImport() {
    const body = `
      <div class="hint">Funktioniert mit allen Seiten, die Rezepte im schema.org-Format bereitstellen (z. B. Chefkoch, Lecker, Eat Smarter, BBC Good Food …).</div>
      <input type="url" class="url" placeholder="https://www.chefkoch.de/rezepte/…">
      <label class="field">Zusätzliche Kategorien (optional)<input class="tags" placeholder="z. B. Hauptgericht"></label>`;
    const footer = `<button class="btn" data-close>Abbrechen</button><button class="btn primary go">Importieren</button>`;
    this._showModal("Rezept importieren", body, footer, (root) => {
      const url = root.querySelector(".url");
      url.focus();
      const go = async () => {
        const value = url.value.trim();
        if (!value) return;
        const btn = root.querySelector(".go");
        btn.disabled = true;
        btn.textContent = "Importiere …";
        try {
          const data = { url: value };
          const tags = root.querySelector(".tags").value.trim();
          if (tags) data.tags = tags;
          const res = await this._service("import_recipe", data, true);
          this._closeModal();
          this._toast(`${res.recipe.name} ${res.created ? "importiert" : "aktualisiert"}`);
          setTimeout(() => this._openRecipe(res.recipe.id), 350);
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "Importieren";
        }
      };
      root.querySelector(".go").addEventListener("click", go);
      url.addEventListener("keydown", (ev) => ev.key === "Enter" && go());
    });
  }
}

if (!customElements.get("essensplaner-panel")) {
  customElements.define("essensplaner-panel", EssensplanerPanel);
}
