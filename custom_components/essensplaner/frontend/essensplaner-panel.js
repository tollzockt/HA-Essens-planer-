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
};

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
  }
  * { box-sizing: border-box; }
  button { font-family: inherit; }
  header {
    position: sticky; top: 0; z-index: 3;
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
  .btn.danger { color: var(--error-color, #db4437); }
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
  .cost { font-size: 11px; font-weight: 600; color: #2e7d32; white-space: nowrap; }
  .tagoffer { font-size: 11px; background: #fff3e0; color: #e65100; border-radius: 6px; padding: 0 5px; margin-left: 4px; white-space: nowrap; }
  .budget { display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px; font-size: 13px; font-weight: 500; background: color-mix(in srgb, #2e7d32 14%, transparent); color: #2e7d32; }
  .budget.warn { background: color-mix(in srgb, #ef6c00 16%, transparent); color: #ef6c00; }
  .budget.over { background: color-mix(in srgb, #c62828 16%, transparent); color: #c62828; }
  .price { font-size: 13px; color: var(--ep-secondary-text); white-space: nowrap; text-align: right; }
  .price .o { display: block; font-size: 11px; color: #e65100; }
  .offers { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
  .offer { display: flex; gap: 12px; padding: 12px; align-items: flex-start; }
  .offer .oimg { width: 64px; height: 64px; border-radius: 10px; flex: none; background: #fff center/contain no-repeat; display: flex; align-items: center; justify-content: center; font-size: 30px; border: 1px solid var(--ep-divider); }
  .offer .ot { font-weight: 600; line-height: 1.25; }
  .offer .store { display: inline-block; font-size: 11px; font-weight: 600; border-radius: 6px; padding: 1px 7px; background: var(--ep-accent-bg); margin: 3px 0; }
  .offer .pr { font-size: 18px; font-weight: 700; color: #c62828; }
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
  .costbox .big { font-size: 20px; font-weight: 700; color: #2e7d32; }
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
  @media (max-width: 600px) { main { padding: 10px; } .grid2 { grid-template-columns: 1fr; } .weeklabel { font-size: 16px; } .btn { padding: 7px 12px; } }
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
    this._onKey = (ev) => this._handleKey(ev);
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
    if (this._hass && !this._unsub && this._data) this._subscribe();
  }

  disconnectedCallback() {
    window.removeEventListener("keydown", this._onKey);
    document.removeEventListener("visibilitychange", this._onVisibility);
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
    try {
      this._data = await this._hass.callWS({ type: `${DOMAIN}/data` });
      this._costs = {};
      if (!this._weekStart) this._weekStart = mondayOf(fromIso(this._data.today));
      this._renderContent();
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
        <div class="toolbar"><span class="menu"></span><div class="title">🍽️ Essensplaner</div></div>
        <div class="tabs">
          <button class="tab" data-tab="plan">🗓️ Wochenplan</button>
          <button class="tab" data-tab="recipes">📖 Rezepte <span class="count" data-count="recipes"></span></button>
          <button class="tab" data-tab="shopping">🛒 Einkaufsliste <span class="count" data-count="shopping"></span></button>
          <button class="tab" data-tab="offers">💶 Angebote<span class="long"> & Budget</span> <span class="count" data-count="offers"></span></button>
        </div>
      </header>
      <main><div class="loading">Lade …</div></main>
      <div class="modalroot"></div>
      <div class="cookroot"></div>
      <input type="file" accept=".json,application/json" class="fileinput" hidden>`;
    this._content = this.shadowRoot.querySelector("main");
    this._modalRoot = this.shadowRoot.querySelector(".modalroot");
    this._cookRoot = this.shadowRoot.querySelector(".cookroot");
    const menu = document.createElement("ha-menu-button");
    menu.hass = this._hass;
    menu.narrow = this._narrow;
    this.shadowRoot.querySelector(".menu").appendChild(menu);
    this._menuButton = menu;
    this.shadowRoot.querySelectorAll(".tab").forEach((tab) =>
      tab.addEventListener("click", () => {
        this._tab = tab.dataset.tab;
        this._setPref("tab", this._tab);
        this._renderContent();
      })
    );
    const c = this._content;
    c.addEventListener("click", (ev) => this._onClick(ev));
    c.addEventListener("input", (ev) => this._onInput(ev));
    c.addEventListener("change", (ev) => this._onChange(ev));
    c.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && ev.target.dataset.enter) {
        ev.preventDefault();
        this._action(ev.target.dataset.enter, ev.target);
      }
    });
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
    if (this._tab === "recipes") this._content.innerHTML = this._renderRecipes();
    else if (this._tab === "shopping") this._content.innerHTML = this._renderShopping();
    else if (this._tab === "offers") this._content.innerHTML = this._renderOffers();
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
  _renderShopping() {
    const items = this._data.shopping || [];
    const open = items.filter((i) => i.status !== "completed");
    const done = items.filter((i) => i.status === "completed");
    const groups = {};
    for (const item of open) (groups[item.category || "Sonstiges"] ||= []).push(item);
    const order = (c) => {
      const i = CATEGORY_ORDER.indexOf(c);
      return i === -1 ? 99 : i;
    };
    const describe = (item) => {
      const desc = (item.description || "").split(" · ").filter((p) => !p.startsWith("≈ ") && !p.startsWith("🏷️ ")).join(" · ");
      const prefix = `${item.category} · `;
      if (item.status !== "completed" && item.category && desc.startsWith(prefix)) return desc.slice(prefix.length);
      if (item.status !== "completed" && desc === item.category) return "";
      return desc;
    };
    const renderItem = (item) => `
      <div class="item ${item.status === "completed" ? "done" : ""}">
        <input type="checkbox" data-change="toggle-item" data-uid="${esc(item.uid)}" ${item.status === "completed" ? "checked" : ""}>
        <div class="txt"><div class="sum">${esc(item.summary)}</div>${describe(item) ? `<div class="desc">${esc(describe(item))}</div>` : ""}</div>
        ${item.price != null ? `<div class="price">≈ ${eur(item.price)}${item.offer ? `<span class="o">🏷️ ${esc(item.offer.store)}</span>` : ""}</div>` : ""}
        <button class="icon" data-action="delete-item" data-uid="${esc(item.uid)}" title="Entfernen">✕</button>
      </div>`;
    const groupHtml = Object.keys(groups)
      .sort((a, b) => order(a) - order(b))
      .map((cat) => `<div class="card group"><h3>${CATEGORY_ICONS[cat] || "🛒"} ${esc(cat)} <span class="meta">${groups[cat].length}</span></h3>${groups[cat].map(renderItem).join("")}</div>`)
      .join("");
    const total = items.length;
    const pct = total ? Math.round((done.length / total) * 100) : 0;
    const priced = open.filter((i) => i.price != null);
    const sum = priced.reduce((acc, i) => acc + i.price, 0);
    const offersUsed = open.filter((i) => i.offer).length;
    return `<div class="shopping">
      ${total ? `<div class="card shopstat"><span class="num">${open.length}</span><span class="meta">offen<br>${done.length} erledigt</span><div class="progress"><div style="width:${pct}%"></div></div><span class="meta">${pct}%</span>${priced.length ? `<span class="meta" style="text-align:right"><b style="font-size:16px;color:var(--primary-text-color)">≈ ${eur(sum)}</b><br>${offersUsed ? `🏷️ ${offersUsed} im Angebot · ` : ""}ganze Packungen</span>` : ""}</div>` : ""}
      <div class="row">
        <input placeholder="Artikel hinzufügen, z. B. „2 Liter Milch“" data-enter="add-item" data-focuskey="additem" style="flex:1;min-width:200px">
        <button class="btn primary" data-action="add-item">Hinzufügen</button>
      </div>
      <div class="row">
        <button class="btn" data-action="shopping-next-week">🗓️ Aus Plan (7 Tage) erstellen</button>
        ${open.length ? `<button class="btn" data-action="share-list">📤 Teilen / Kopieren</button>` : ""}
        <span class="spacer"></span>
        ${done.length ? `<button class="btn ghost" data-action="clear-done">🧹 Erledigte entfernen (${done.length})</button>` : ""}
        ${total ? `<button class="btn danger" data-action="clear-all">🗑 Liste leeren</button>` : ""}
      </div>
      ${open.length ? groupHtml : `<div class="empty"><div class="big">${done.length ? "🎉" : "🛒"}</div>${done.length ? "Alles erledigt!" : "Die Einkaufsliste ist leer."}<br><span class="hint">Plane Mahlzeiten und erstelle die Liste per Knopfdruck – oder sag „Jarvis, erstelle die Einkaufsliste“.</span></div>`}
      ${done.length ? `<div class="card group"><h3>✅ Erledigt</h3>${done.map(renderItem).join("")}</div>` : ""}
    </div>`;
  }

  _shoppingText() {
    const groups = {};
    for (const item of this._data.shopping.filter((i) => i.status !== "completed")) (groups[item.category || "Sonstiges"] ||= []).push(item.summary);
    return Object.entries(groups)
      .sort((a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]))
      .map(([cat, list]) => `${CATEGORY_ICONS[cat] || "🛒"} ${cat}\n${list.map((s) => `• ${s}`).join("\n")}`)
      .join("\n\n");
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
    if (this._cook) {
      if (ev.key === "Escape") this._closeCooking();
      else if (ev.key === "ArrowRight" || ev.key === " ") {
        ev.preventDefault();
        this._cookGo(1);
      } else if (ev.key === "ArrowLeft") this._cookGo(-1);
      return;
    }
    if (ev.key === "Escape" && this._modal) this._closeModal();
  }

  _onInput(ev) {
    if (ev.target.dataset.input === "search") {
      this._search = ev.target.value;
      this._renderContent();
    }
  }

  async _onChange(ev) {
    const t = ev.target;
    if (t.dataset.change === "toggle-item") {
      await this._todo("update_item", { item: t.dataset.uid, status: t.checked ? "completed" : "needs_action" });
    } else if (t.dataset.change === "sort") {
      this._sort = t.value;
      this._setPref("sort", t.value);
      this._renderContent();
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
        await this._todo("add_item", { item: value });
        break;
      }
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
        el.disabled = true;
        el.textContent = "⏳ Lade Angebote …";
        try {
          const res = await this._service("refresh_offers", {}, true);
          this._toast(res?.status === "ok" ? `🏷️ ${res.count} passende Angebote geladen` : `Fehler: ${(res?.errors || []).join("; ")}`);
        } catch (e) {
          el.disabled = false;
          el.textContent = "🔄 Aktualisieren";
        }
        break;
      }
      case "add-offer":
        this._openOfferForm();
        break;
      case "remove-offer":
        await this._service("remove_offer", { id: d.id });
        break;
      case "offer-to-list": {
        const o = (this._data.offers || []).find((x) => x.id === d.id);
        if (o) await this._todo("add_item", { item: `${o.title} (${o.store} ${eur(o.price)})` });
        this._toast("🛒 Auf die Einkaufsliste gesetzt");
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
  _showModal(title, body, footer, onMount) {
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
    this._modal = { root: overlay };
    if (onMount) onMount(overlay);
  }

  _closeModal() {
    this._modalRoot.innerHTML = "";
    this._modal = null;
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
    const eco = this._data.economy || {};
    const week = eco.week || {};
    const next = eco.next_week || {};
    const budget = eco.budget;
    const meta = eco.offers_meta || {};
    const online = eco.offers_source === "marktguru";
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
          ${budget ? `<div class="meta">Budget ${eur(budget)} · ${week.remaining >= 0 ? `noch <b>${eur(week.remaining)}</b> frei` : `<b style="color:#c62828">${eur(-week.remaining)} drüber</b>`}</div>
          <div class="progress" style="height:10px;max-width:none;margin-top:6px"><div style="width:${Math.min(100, Math.round(ratio * 100))}%;background:${ratio > 1 ? "#c62828" : ratio > 0.85 ? "#ef6c00" : "#2e7d32"}"></div></div>` : `<div class="hint">Kein Wochenbudget festgelegt – in den Optionen unter „Budget & Angebote“ einstellen.</div>`}
          <div class="meta" style="margin-top:6px">${week.savings ? `🏷️ ${eur(week.savings)} durch Angebote gespart · ` : ""}Nächste Woche bisher ≈ ${eur(next.total || 0)}</div>
        </div>
        <div class="bars" style="margin:6px 0 18px">${bars}</div>
      </div>`;
    const info = online
      ? `<div class="meta">Quelle: marktguru.de (inoffiziell) · PLZ ${esc(eco.zip_code || "–")} · ${meta.last_update ? `aktualisiert ${new Date(meta.last_update).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })}` : "noch nicht geladen"}${meta.status === "error" ? ` · ⚠️ ${esc((meta.errors || [])[0] || "Fehler")}` : ""}</div>`
      : `<div class="card infobox"><b>Online-Angebote sind aus.</b> Unter <i>Einstellungen → Geräte &amp; Dienste → Essensplaner → Konfigurieren → Budget &amp; Angebote</i> kannst du Postleitzahl und Supermärkte (Aldi, Lidl, REWE, EDEKA, Penny, Netto, Kaufland …) eintragen. Angebote aus dem Prospekt kannst du jederzeit selbst eintragen – oder Jarvis sagen: „Bei Lidl gibt es Hähnchenbrust für 4,99 Euro bis Samstag“.</div>`;
    const cards = offers
      .map((o) => {
        const img = safeUrl(o.image);
        return `<div class="card offer">
          <div class="oimg" ${img ? `style="background-image:url('${img}')"` : ""}>${img ? "" : "🏷️"}</div>
          <div style="flex:1;min-width:0">
            <div class="ot">${esc(o.title)}</div>
            <span class="store">${esc(o.store || "?")}</span>${o.loyalty ? ' <span class="meta">(mit App/Karte)</span>' : ""}
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
        ${online ? `<button class="btn" data-action="refresh-offers">🔄 Aktualisieren</button>` : ""}
        <button class="btn" data-action="add-offer">＋ Angebot eintragen</button>
        <button class="btn ghost" data-action="open-prices">💶 Preise</button>
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

  _openOfferForm() {
    const stores = ["Aldi Süd", "Aldi Nord", "Lidl", "REWE", "EDEKA", "Penny", "Netto", "Kaufland", "Norma"];
    const body = `
      <div class="hint">Ein Angebot aus dem Prospekt eintragen – es wird bei Rezeptkosten, Planung und Einkaufsliste berücksichtigt.</div>
      <label class="field">Produkt<input class="product" placeholder="z. B. Hähnchenbrustfilet"></label>
      <div class="grid2">
        <label class="field">Markt<input class="store" list="ep-stores" placeholder="z. B. Lidl"><datalist id="ep-stores">${stores.map((x) => `<option value="${x}">`).join("")}</datalist></label>
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
    const body = `
      <div class="hint">Richtwerte sind typische Discounter-Preise. Eigene Preise haben Vorrang; Normalpreise aus Prospekten werden automatisch gelernt.</div>
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
    this._showModal("Preise", body, "", (root) => {
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
