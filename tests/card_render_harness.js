// Renders the bundled card in node for fixed scenarios and prints the HTML.
const fs = require("fs");
const NOW = Date.parse("2026-09-15T12:30:00Z");
Date.now = () => NOW;
let Card;
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = { innerHTML: "", querySelector: () => ({ addEventListener() {} }) };
    return this.shadowRoot;
  }
  dispatchEvent() {}
};
globalThis.window = globalThis;
globalThis.customElements = { get: () => Card, define: (_n, c) => { Card = c; } };
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
eval(fs.readFileSync(process.argv[2], "utf8"));

const iso = (min) => new Date(NOW - min * 60000).toISOString();
const reg = (key) => ({ platform: "ukraine_alarm_pro", translation_key: key });

function hass({ alert = "off", threat = "none", types = "", level = "none", reasons = [], coverage = "none",
  areas = [], started = "unknown", stale = "off", withHub = true, language = "uk" } = {}) {
  const states = {
    "binary_sensor.uap_31_alert": { state: alert, attributes: { region_id: "31", friendly_name: "Київ тривога" }, last_updated: "a" },
    "sensor.uap_31_threat": { state: threat, attributes: { region_id: "31", region_name: "м. Київ", active_threat_types: types, coverage, affected_regions: areas }, last_updated: "a" },
    "sensor.uap_31_air_alert_level": { state: level, attributes: { region_id: "31", reasons }, last_updated: "a" },
    "sensor.uap_31_alert_started": { state: started, attributes: { region_id: "31" }, last_updated: "a" },
    "event.uap_31_event": { state: "2026-09-15T12:00:00Z", attributes: { region_id: "31" }, last_updated: "a" },
  };
  const entities = {
    "binary_sensor.uap_31_alert": reg("alert"), "sensor.uap_31_threat": reg("threat"),
    "sensor.uap_31_air_alert_level": reg("air_alert_level"), "sensor.uap_31_alert_started": reg("alert_started"),
    "event.uap_31_event": reg("event"),
  };
  if (withHub) {
    states["binary_sensor.uap_data_stale"] = { state: stale, attributes: {}, last_updated: "a" };
    states["sensor.uap_last_update"] = { state: iso(1), attributes: {}, last_updated: "a" };
    entities["binary_sensor.uap_data_stale"] = reg("data_stale");
    entities["sensor.uap_last_update"] = reg("last_update");
  }
  return { states, entities, locale: { language }, language, config: { time_zone: "Europe/Kyiv" }, callWS: () => new Promise(() => {}) };
}

const episodes = [
  { observed_started_at: iso(20), observed_cleared_at: null, maximum_air_level: "red", had_gap: false },
  { observed_started_at: iso(200), observed_cleared_at: iso(170), maximum_air_level: "yellow", had_gap: true },
  { observed_started_at: iso(600), observed_cleared_at: iso(590), maximum_air_level: "none", had_gap: false },
  { observed_started_at: iso(2000), observed_cleared_at: iso(1900), maximum_air_level: "red", had_gap: false },
];
const quietEpisodes = episodes.slice(1);
const summary = (extra = {}) => ({
  count: 3, observed_duration_seconds: 8400, longest_duration_seconds: 6000, has_gaps: false,
  period_start: iso(6 * 1440), coverage_start: iso(3 * 1440), ...extra,
});

const alertRed = { alert: "on", threat: "air", types: "air,artillery", level: "red", reasons: ["Ракетна загроза", "Балістика"],
  coverage: "partial", areas: [{ region_name: "Фастівський район" }, { region_name: "Бучанський район" }, { region_name: "Обухівський район" }, { region_name: "Броварський район" }], started: iso(20) };

const scenarios = {
  quiet_full: [{}, { layout: "full" }, { episodes: quietEpisodes, summary: summary() }],
  quiet_status: [{}, { layout: "status" }, { episodes: quietEpisodes, summary: summary() }],
  quiet_compact: [{}, { layout: "compact" }, { episodes: quietEpisodes, summary: summary() }],
  quiet_full_no_stats: [{}, { layout: "full" }, null],
  quiet_full_no_week: [{}, { layout: "full" }, { episodes: [], summary: null }],
  quiet_full_gaps_old_journal: [{}, { layout: "full" }, { episodes: quietEpisodes, summary: summary({ has_gaps: true, coverage_start: iso(30 * 1440), count: 0 }) }],
  alert_red_full: [alertRed, { layout: "full" }, { episodes, summary: summary() }],
  alert_red_status: [alertRed, { layout: "status" }, { episodes, summary: summary() }],
  alert_red_compact: [alertRed, { layout: "compact" }, { episodes, summary: summary() }],
  alert_yellow_whole: [{ alert: "on", threat: "air", types: "air", level: "yellow", coverage: "whole", started: iso(95) }, { layout: "status" }, null],
  alert_unrecognized: [{ alert: "on", threat: "unrecognized", types: "unrecognized", level: "unrecognized", coverage: "unrecognized", started: "unknown" }, { layout: "status" }, null],
  alert_partial_two: [{ ...alertRed, areas: [{ region_name: "A" }, { region_name: "" }] }, { layout: "status" }, null],
  alert_long: [{ ...alertRed, started: iso(3 * 1440 + 125) }, { layout: "compact" }, null],
  stale: [{ stale: "on" }, { layout: "full" }, { episodes: quietEpisodes, summary: summary() }],
  no_data: [{ alert: "unavailable" }, { layout: "status" }, null],
  no_hub: [{ withHub: false }, { layout: "status" }, null],
  english_full: [{ language: "en" }, { layout: "full", language: "en" }, { episodes: quietEpisodes, summary: summary() }],
  english_alert: [alertRed, { layout: "full", language: "en" }, { episodes, summary: summary({ count: 1 }) }],
  forced_uk_on_en: [{ language: "en" }, { layout: "compact", language: "uk", name: "Дім <b>" }, { episodes: quietEpisodes, summary: summary() }],
  plural_forms: [{}, { layout: "full" }, { episodes: quietEpisodes, summary: summary({ count: 22 }) }],
  alert_three_areas: [{ ...alertRed, areas: alertRed.areas.slice(0, 3) }, { layout: "status" }, null],
  alert_two_days: [{ ...alertRed, started: iso(2 * 1440 + 61) }, { layout: "compact" }, null],
  alert_one_day: [{ ...alertRed, started: iso(1440 + 61) }, { layout: "compact" }, null],
  big_share: [{}, { layout: "full" }, { episodes: [{ observed_started_at: iso(900), observed_cleared_at: iso(100), maximum_air_level: "red", had_gap: false }], summary: summary({ observed_duration_seconds: 200000 }) }],
  share_capped: [{}, { layout: "full" }, { episodes: quietEpisodes, summary: summary({ observed_duration_seconds: 9000000 }) }],
};
for (const n of [1, 2, 4, 5, 11, 12, 14, 15, 21, 25, 111]) {
  scenarios[`plural_${n}`] = [{}, { layout: "full" }, { episodes: quietEpisodes, summary: summary({ count: n }) }];
  scenarios[`plural_en_${n}`] = [{ language: "en" }, { layout: "full", language: "en" }, { episodes: quietEpisodes, summary: summary({ count: n }) }];
}

const out = {};
for (const [name, [h, config, stats]] of Object.entries(scenarios)) {
  const card = new Card();
  Object.defineProperty(card, "isConnected", { value: false });
  card.setConfig(config);
  const hs = hass(h);
  if (stats) card._stats = { rid: "31", trigger: "x", fetched: NOW, ...stats };
  card.hass = hs;
  card._render();
  out[name] = card.shadowRoot.innerHTML.split("</style>").pop().replace(/\s+/g, " ").trim();
}
const empty = new Card();
Object.defineProperty(empty, "isConnected", { value: false });
empty.setConfig({});
empty.hass = { states: {}, entities: {}, locale: { language: "uk" } };
out.not_found = empty.shadowRoot.innerHTML.split("</style>").pop().replace(/\s+/g, " ").trim();
out.card_size = ["full", "status", "compact", "bogus"].map((layout) => { const c = new Card(); c.setConfig({ layout }); return [c._config.layout, c.getCardSize()]; });
console.log(JSON.stringify(out, null, 1));
