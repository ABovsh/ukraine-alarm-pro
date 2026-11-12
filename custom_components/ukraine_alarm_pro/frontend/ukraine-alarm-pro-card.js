/*
 * Ukraine Alarm Pro card — shipped with the integration, no HACS frontend
 * resource needed. Pick a region's alert sensor; with one region the card
 * finds it on its own. Durations tick in the browser and statistics come from
 * the integration's journal services, so nothing is written to the recorder.
 */
const DOMAIN = "ukraine_alarm_pro";
const CARD = "ukraine-alarm-pro-card";

const I18N = {
  uk: {
    alert: "Тривога",
    quiet: "Тихо",
    noData: "Даних ще немає",
    stale: "Немає свіжих даних",
    staleNote: "Дані застаріли — стан може бути неактуальним",
    since: "з",
    d: "дн",
    h: "год",
    m: "хв",
    whole: "Увесь регіон",
    partial: "Частина регіону",
    unknownCoverage: "Охоплення не визначено",
    level: { yellow: "Жовтий рівень", red: "Червоний рівень", unrecognized: "Рівень не вказано" },
    types: {
      air: "Повітряна тривога",
      artillery: "Загроза артобстрілу",
      urban_fights: "Вуличні бої",
      chemical: "Хімічна загроза",
      nuclear: "Радіаційна загроза",
      unrecognized: "Невідомий тип",
    },
    updated: "оновлено",
    notFound: "Не знайдено сутностей Ukraine Alarm Pro",
    last24: "24 год",
    week: "7 днів",
    today: "Сьогодні",
    avgShort: "середня",
    now: "зараз",
    noAlerts: "без тривог",
    quietFor: "без тривог з",
    longest: "Найдовша",
    longestShort: "найдовша",
    average: "Середня",
    ongoing: "триває",
    journalSince: "дані з",
    gaps: "були перерви в даних",
    dataOk: "Дані повні",
    dataNearlyComplete: "Дані практично повні",
    sec: "с",
    shareH: "частка",
    totalH: "разом",
    countH: "к-сть",
    incomplete: "Неповна статистика",
    plural: ["тривога", "тривоги", "тривог"],
    levelWord: { yellow: "жовтий", red: "червоний", unrecognized: "рівень не вказано" },
    clearedAt: "відбій",
    mig: { takeoff: "Зліт МіГ-31К", launch: "Пуск «Кинджала» з МіГ-31К" },
    airfields: { savasleika: "Саваслейка", mozdok: "Моздок" },
    country: {
      ballistics: { active: "Загроза балістики" },
      strategic_aviation: { active: "Стратегічна авіація в повітрі", launch: "Пуск ракет зі стратегічної авіації" },
      tactical_aviation: { active: "Тактична авіація в повітрі", launch: "Пуск ракет з тактичної авіації" },
      missile_carriers: { active: "Ракетоносії в морі", launch: "Пуск ракет з кораблів" },
    },
    usually: "Зазвичай",
    oneInFour: "кожна четверта довше",
    days: "днів",
    chartTitle: "години тривоги",
    max: "макс.",
  },
  en: {
    alert: "Alert",
    quiet: "All quiet",
    noData: "No data yet",
    stale: "No fresh data",
    staleNote: "Data is stale — the state may be outdated",
    since: "since",
    d: "d",
    h: "h",
    m: "min",
    whole: "Whole region",
    partial: "Part of the region",
    unknownCoverage: "Coverage unknown",
    level: { yellow: "Yellow level", red: "Red level", unrecognized: "Level not specified" },
    types: {
      air: "Air raid alert",
      artillery: "Artillery threat",
      urban_fights: "Urban fighting",
      chemical: "Chemical threat",
      nuclear: "Nuclear threat",
      unrecognized: "Unknown type",
    },
    updated: "updated",
    notFound: "No Ukraine Alarm Pro entities found",
    last24: "24 h",
    week: "7 days",
    today: "Today",
    avgShort: "average",
    now: "now",
    noAlerts: "no alerts",
    quietFor: "no alerts since",
    longest: "Longest",
    longestShort: "longest",
    average: "Average",
    ongoing: "ongoing",
    journalSince: "data since",
    gaps: "data had gaps",
    dataOk: "Data is complete",
    dataNearlyComplete: "Data is nearly complete",
    sec: "s",
    shareH: "share",
    totalH: "total",
    countH: "count",
    incomplete: "Incomplete statistics",
    plural: ["alert", "alerts", "alerts"],
    levelWord: { yellow: "yellow", red: "red", unrecognized: "level not specified" },
    clearedAt: "cleared",
    mig: { takeoff: "MiG-31K take-off", launch: "Kinzhal launch from MiG-31K" },
    airfields: { savasleika: "Savasleyka", mozdok: "Mozdok" },
    country: {
      ballistics: { active: "Ballistic threat" },
      strategic_aviation: { active: "Strategic aviation airborne", launch: "Missile launch from strategic aviation" },
      tactical_aviation: { active: "Tactical aviation airborne", launch: "Missile launch from tactical aviation" },
      missile_carriers: { active: "Missile carriers at sea", launch: "Missile launch from ships" },
    },
    usually: "Usually",
    oneInFour: "one in four over",
    days: "days",
    chartTitle: "alert hours",
    max: "max",
  },
};

const TYPE_ICONS = {
  air: "mdi:airplane-alert",
  artillery: "mdi:bomb",
  urban_fights: "mdi:pistol",
  chemical: "mdi:biohazard",
  nuclear: "mdi:radioactive",
  unrecognized: "mdi:help-circle-outline",
};

// The card language wins over the user's profile language.
const languageOf = (hass, forced) =>
  forced === "uk" || forced === "en" ? forced : hass?.locale?.language || hass?.language;

const lang = (hass, forced) => ((languageOf(hass, forced) || "en").startsWith("uk") ? I18N.uk : I18N.en);

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const ours = (hass, id) => hass.entities?.[id]?.platform === DOMAIN;

function alertEntities(hass) {
  return Object.keys(hass.states)
    .filter((id) => id.startsWith("binary_sensor.") && ours(hass, id) && hass.entities[id].translation_key === "alert")
    .sort((a, b) => a.localeCompare(b));
}

function regionIdOf(hass, alertId) {
  const attr = hass.states[alertId]?.attributes?.region_id;
  if (attr) return String(attr);
  const match = /^binary_sensor\.uap_(.+)_alert$/.exec(alertId);
  return match ? match[1] : null;
}

function sibling(hass, key, regionId) {
  return Object.keys(hass.states).find((id) => {
    const entry = hass.entities?.[id];
    if (entry?.platform !== DOMAIN || entry.translation_key !== key) return false;
    return regionId === null || String(hass.states[id].attributes.region_id ?? "") === regionId;
  });
}

function hub(hass, key) {
  return Object.keys(hass.states).find((id) => ours(hass, id) && hass.entities[id].translation_key === key);
}

function span(t, seconds) {
  const minutes = Math.max(0, Math.floor(seconds / 60));
  const d = Math.floor(minutes / 1440);
  const h = Math.floor(minutes / 60);
  if (d >= 2) return `${d} ${t.d} ${Math.floor((minutes % 1440) / 60)} ${t.h}`;
  return h ? `${h} ${t.h} ${minutes % 60} ${t.m}` : `${minutes} ${t.m}`;
}

const duration = (t, from) => span(t, (Date.now() - from.getTime()) / 1000);

// Ukrainian plural: 1 тривога, 2–4 тривоги, 5+ тривог (11–14 always the last).
function ukrainianForm(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return 0;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 1;
  return 2;
}

function alerts(t, n) {
  if (t === I18N.en) return `${n} ${n === 1 ? t.plural[0] : t.plural[1]}`;
  return `${n} ${t.plural[ukrainianForm(n)]}`;
}

const dateOf = (stamp) => {
  const date = stamp ? new Date(stamp) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
};

const dayMonth = (date, hass) =>
  date.toLocaleDateString(hass?.locale?.language || undefined, {
    day: "2-digit",
    month: "2-digit",
    timeZone: hass?.config?.time_zone || undefined,
  });

// The card is built from sections the user picks and orders in the editor.
const SECTIONS = ["status", "details", "timeline", "stats"];
// 0.12 saved a fifth section, "records" (longest and average); the statistics table carries both now, so it is dropped.
const RETIRED_SECTIONS = ["records"];
// What each section is made of. `hide: [section.item]` drops an item; the ids are part of saved configs.
const ITEMS = {
  status: ["timer", "updated", "typical", "mig"],
  details: ["level", "types", "coverage", "reason"],
  stats: ["today", "day", "week", "month", "bar", "total", "count", "longest", "average", "lamp", "chart"],
};
// The 0.11 card's `layout` values, as the sections that show the same things.
const LEGACY_LAYOUTS = {
  compact: { sections: ["status"], hide: ["status.updated", "status.typical"] },
  status: { sections: ["status", "details"], hide: [] },
  full: { sections: SECTIONS, hide: [] },
};
// Sections drawn from the journal's 24 h / 7 d summary.
const JOURNAL_SECTIONS = ["timeline", "stats"];
// Of a section's items, these must keep one shown; the rest (bar, longest, average) only trim the table.
const REQUIRED = { stats: ["today", "day", "week", "month"] };
// Hiding `item` would leave its section with nothing to show.
const lastShown = (section, hide, item) => {
  const group = REQUIRED[section] || ITEMS[section];
  return group.includes(item) && group.filter((other) => !hide.includes(`${section}.${other}`)).length === 1;
};
const validItem = (id) => {
  const [section, item] = String(id).split(".");
  return Boolean(ITEMS[section]?.includes(item));
};

// A saved `layout:` opens as its sections; an unknown one as the full card.
function normalizeConfig(config) {
  const { layout, ...rest } = config || {};
  const legacy = rest.sections === undefined ? LEGACY_LAYOUTS[layout] || LEGACY_LAYOUTS.full : null;
  const picked = rest.sections ?? legacy.sections;
  const kept = Array.isArray(picked) ? picked.filter((section) => !RETIRED_SECTIONS.includes(section)) : picked;
  const sections = Array.isArray(kept) && !kept.length && picked.length ? ["status"] : kept;
  if (!Array.isArray(sections) || !sections.length || sections.some((section) => !SECTIONS.includes(section))) {
    throw new Error(`sections: choose from ${SECTIONS.join(", ")}`);
  }
  const hide = [...new Set([...(Array.isArray(rest.hide) ? rest.hide : []), ...(legacy?.hide || [])])].filter(validItem);
  // Several regions make a list; a list of one is the usual card for that region.
  const listed = Array.isArray(rest.entities) ? [...new Set(rest.entities.filter((id) => typeof id === "string" && id))] : [];
  delete rest.entities;
  if (listed.length > 1) rest.entities = listed;
  else if (listed.length === 1 && !rest.entity) rest.entity = listed[0];
  return { ...rest, sections: [...new Set(sections)], hide };
}
const STATS_FRESH_ACTIVE = 300000;
const STATS_FRESH_QUIET = 600000;
// A failed call (a reconnect, a restart, an older integration) is retried, not final.
const STATS_RETRY = 120000;


// One cache per HA connection: multiple cards share both in-flight calls and
// answers. It disappears with the connection and never crosses HA instances.
const requestCaches = new WeakMap();
function sharedRequest(hass, rid, full, trigger, maxAge) {
  const owner = hass.connection || hass.callWS;
  let cache = requestCaches.get(owner);
  if (!cache) { cache = new Map(); requestCaches.set(owner, cache); }
  const key = `${rid}|${full ? "full" : "history"}`;
  const previous = cache.get(key);
  if (!previous?.failed && previous?.trigger === trigger && Date.now() - previous.fetched < maxAge) return previous.promise;
  if (previous?.pending && previous.trigger === trigger) return previous.promise;
  if (previous?.failed && Date.now() - previous.fetched < STATS_RETRY) return previous.promise;
  const record = { trigger, fetched: Date.now(), pending: true };
  record.promise = hass.callWS({ type: "call_service", domain: DOMAIN,
    service: full ? "get_summary" : "get_history", service_data: { region_id: rid, ...(full ? { days: 7 } : { limit: 1 }) },
    return_response: true }).then(({ response }) => full
      ? { summary: response, episodes: response.last_episode || [] }
      : { summary: null, episodes: response.episodes || [] })
    .catch((error) => { record.failed = true; throw error; })
    .finally(() => { record.pending = false; record.fetched = Date.now(); });
  cache.set(key, record);
  return record.promise;
}

// Preserve the ha-card (and keyboard focus). Only changed text, attributes
// and child nodes are patched; timers do not replace the entire shadow DOM.
function patchAttributes(old, node) {
  // Attribute removal mutates a live NamedNodeMap; snapshot the names first.
  for (const name of old.getAttributeNames()) {
    if (!node.hasAttribute(name)) old.removeAttribute(name);
  }
  for (const attr of node.attributes) {
    if (old.getAttribute(attr.name) !== attr.value) old.setAttribute(attr.name, attr.value);
  }
}

function patchNode(old, node) {
  if (node.nodeType === 3) {
    if (old.nodeValue !== node.nodeValue) old.nodeValue = node.nodeValue;
  } else if (node.nodeType === 1) {
    patchAttributes(old, node);
    patchChildren(old, node);
  }
}

function patchChildren(parent, incoming) {
  const next = [...incoming.childNodes];
  for (let i = 0; i < next.length; i++) {
    const old = parent.childNodes[i];
    const node = next[i];
    if (!old || old.nodeType !== node.nodeType || old.nodeName !== node.nodeName) {
      const replacement = node.cloneNode(true);
      if (old) old.replaceWith(replacement); else parent.appendChild(replacement);
      continue;
    }
    patchNode(old, node);
  }
  while (parent.childNodes.length > next.length) parent.lastChild.remove();
}

function patchDOM(root, html) {
  if (typeof document === "undefined") { root.innerHTML = html; return; }
  const template = document.createElement("template");
  template.innerHTML = html;
  patchChildren(root, template.content);
}

// Positions of the local 00/06/12/18 o'clock hours inside a [lo, hi) window.
function clockMarks(lo, hi, timeZone) {
  let hourOf;
  try {
    hourOf = new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: timeZone || undefined });
  } catch {
    hourOf = new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23" });
  }
  const marks = [];
  for (let at = Math.ceil(lo / 3600000) * 3600000; at < hi; at += 3600000) {
    const hour = Number(hourOf.format(new Date(at)));
    if (hour % 6 === 0) marks.push({ hour, left: ((at - lo) / (hi - lo)) * 100 });
  }
  return marks;
}

const hhmm = (date, hass) =>
  date.toLocaleTimeString(hass?.locale?.language || undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: hass?.config?.time_zone || undefined,
  });

class UkraineAlarmProCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement(`${CARD}-editor`);
  }

  static getStubConfig(hass) {
    const [first] = alertEntities(hass);
    return first ? { entity: first, sections: [...SECTIONS] } : { sections: [...SECTIONS] };
  }

  setConfig(config) {
    this._config = normalizeConfig(config);
    this._stats = null;
    this._key = null;
    this._generation = (this._generation || 0) + 1;
    this._loading = false;
    this._statsFailed = null;
    this._entityCache = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    const owner = hass?.connection || hass?.callWS;
    if (this._connectionOwner !== owner) {
      this._connectionOwner = owner;
      this._generation = (this._generation || 0) + 1;
      this._loading = false;
      this._stats = null;
      this._statsFailed = null;
      this._entityCache = null;
      this._key = null;
    }
    this._hass = hass;
    const key = this._stateKey();
    if (key !== this._key) {
      this._key = key;
      this._render();
    }
    this._maybeRefresh();
  }

  connectedCallback() {
    this._inView = typeof IntersectionObserver === "undefined";
    const tick = () => {
      if (!this._visible()) return;
      this._maybeRefresh();
      this._render();
    };
    this._visibility = tick;
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", tick);
    if (typeof IntersectionObserver !== "undefined") {
      this._observer = new IntersectionObserver(([entry]) => { this._inView = entry.isIntersecting; tick(); });
      this._observer.observe(this);
    }
    clearInterval(this._timer);
    this._timer = setInterval(tick, 30000);
    tick();
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._observer?.disconnect();
    if (typeof document !== "undefined") document.removeEventListener("visibilitychange", this._visibility);
    this._generation = (this._generation || 0) + 1;
    this._loading = false;
  }

  _visible() {
    return this.isConnected && this._inView !== false && (typeof document === "undefined" || document.visibilityState !== "hidden");
  }

  getCardSize() {
    if (this._config?.entities) return Math.max(1, Math.ceil(this._config.entities.length * 0.8 + (this._config.name ? 0.5 : 0)));
    // The statistics table: a header and a line per period, and the month chart under it.
    const periods = ["stats.day", "stats.week", "stats.today", "stats.month"].filter((id) => !this._config?.hide?.includes(id)).length;
    const chart = this._config?.hide?.includes("stats.chart") ? 0 : 1.5;
    const weight = { status: 1, details: 1, timeline: 0.5, stats: 0.5 + 0.5 * periods + chart };
    return Math.max(1, Math.ceil((this._config?.sections || SECTIONS).reduce((sum, section) => sum + weight[section], 0)));
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _on(section) {
    return this._config.sections.includes(section);
  }

  _shows(section, item) {
    return this._on(section) && !this._config.hide.includes(`${section}.${item}`);
  }

  _statsOn() {
    return JOURNAL_SECTIONS.some((section) => this._on(section));
  }

  // Statistics come from the journal services: fetched again after every alert
  // event, and on a timer so ongoing durations and the 24 h window move.
  _maybeRefresh() {
    // The list reads entity states only; it never calls the journal.
    if (!this._hass || !this._config || this._config.entities || this._loading || !this._visible()) return;
    const ids = this._entities();
    const rid = ids && regionIdOf(this._hass, ids.alert);
    if (!rid) return;
    const alertOn = this._hass.states[ids.alert].state === "on";
    // The usual length of an alert comes with the summary, wanted only while one runs.
    const full = this._statsOn() || (alertOn && this._shows("status", "typical"));
    // Without statistics the journal only supplies "quiet since" for the timer;
    // an active alert gets its start time directly from states.
    // The alert_cleared sensor (0.12+) supplies "quiet since" without a call.
    if (!full && (this._hass.states[ids.alert].state === "on" || !this._shows("status", "timer") || ids.cleared)) return;
    if (this._statsFailed?.rid === rid && Date.now() - this._statsFailed.at < STATS_RETRY) return;
    const event = ids.event ? this._hass.states[ids.event] : undefined;
    const percentages = [ids.percentage24h, ids.percentage7d].map((id) => this._hass.states[id]?.last_updated).join("|");
    const day = new Date().toLocaleDateString("sv", { timeZone: this._hass.config?.time_zone || undefined });
    const trigger = `${rid}|${event?.state}|${this._hass.states[ids.alert].state}|${percentages}|${day}`;
    const age = this._stats ? Date.now() - this._stats.fetched : Infinity;
    const maxAge = this._hass.states[ids.alert].state === "on" ? STATS_FRESH_ACTIVE : STATS_FRESH_QUIET;
    if (this._stats?.trigger === trigger && age < maxAge) return;
    const generation = this._generation;
    this._loading = true;
    sharedRequest(this._hass, rid, full, trigger, maxAge)
      .then((result) => {
        if (generation !== this._generation) return;
        this._stats = { rid, trigger, fetched: Date.now(), ...result };
        this._statsFailed = null;
      })
      .catch(() => {
        if (generation === this._generation) this._statsFailed = { rid, at: Date.now() };
      })
      .finally(() => {
        if (generation !== this._generation) return;
        this._loading = false;
        if (this._visible()) this._render();
      });
  }

  _entities() {
    const hass = this._hass;
    const cached = this._entityCache;
    if (cached && cached.registry === hass.entities && cached.configured === this._config.entity &&
        Object.values(cached.ids).every((id) => id && hass.states[id])) return cached.ids;
    const alert = this._config.entity || alertEntities(hass)[0];
    if (!alert || !hass.states[alert]) return null;
    const rid = regionIdOf(hass, alert);
    const ids = {
      alert,
      threat: sibling(hass, "threat", rid),
      level: sibling(hass, "air_alert_level", rid),
      started: sibling(hass, "alert_started", rid),
      cleared: sibling(hass, "alert_cleared", rid),
      event: sibling(hass, "event", rid),
      stale: hub(hass, "data_stale"),
      updated: hub(hass, "last_update"),
      percentage24h: sibling(hass, "alert_percentage_24h", rid),
      percentage7d: sibling(hass, "alert_percentage_7d", rid),
      mig: hub(hass, "mig_status"),
      ...countryHubs(hass),
    };
    this._entityCache = { registry: hass.entities, configured: this._config.entity, ids };
    return ids;
  }

  _stateKey() {
    if (this._config?.entities && this._hass) {
      const rows = this._list();
      return [...rows.flatMap((row) => Object.values(row)), ...Object.values(this._listCache.hubs)]
        .map((id) => { const s = id && this._hass.states[id]; return s ? `${s.state}|${s.last_updated}` : "-"; })
        .join(";") + `;${this._hass.locale?.language};${this._config.language}`;
    }
    const ids = this._hass && this._config ? this._entities() : null;
    if (!ids) return "none";
    return Object.values(ids)
      .map((id) => {
        const s = id && this._hass.states[id];
        return s ? `${s.state}|${s.last_updated}` : "-";
      })
      .join(";") + `;${this._hass.locale?.language};${this._config.language}`;
  }

  // Times and dates follow the card language, not only the user's profile.
  _fmt() {
    return { locale: { language: languageOf(this._hass, this._config.language) }, config: this._hass.config };
  }

  // The 24 h and 7 d results, with the live percentage sensors taking precedence.
  _rolling(stats) {
    const { summary } = stats;
    const ids = this._entities();
    const current = (result, id) => {
      const state = id && this._hass.states[id];
      if (!state) return result;
      const numeric = known(state) && Number.isFinite(Number(state.state));
      return { ...result, percentage: numeric ? Number(state.state) : null,
        coverage_complete: numeric && (state.attributes.coverage_complete ?? result?.coverage_complete ?? false),
        quality: state.attributes.quality || result?.quality };
    };
    const day = current(summary?.rolling_24h, ids?.percentage24h);
    const week = current(summary?.rolling_7d, ids?.percentage7d);
    const hi = dateOf(summary?.rolling_calculated_at)?.getTime() || Date.now();
    return { day, week, hi };
  }

  _timelineHtml(t, stats) {
    const fmt = this._fmt();
    const { day, hi } = this._rolling(stats);
    // The strip draws only the last 24 hours: a gap earlier in the week does not hatch it,
    // nor does a gap too short to withhold the share (under 1 % of the day).
    const incomplete = !Number.isFinite(day?.percentage);
    // Complete 24 h union supplied by the same calculation as the sensors.
    const lo = hi - 86400000;
    const segments = (day?.intervals || []).map((interval) => {
      const from = Math.max(dateOf(interval.start)?.getTime() || lo, lo);
      const to = Math.min(dateOf(interval.end)?.getTime() || hi, hi);
      const left = ((from - lo) / 86400000) * 100;
      const width = Math.max(((to - from) / 86400000) * 100, 0.6);
      const title = `${hhmm(new Date(from), fmt)}–${hhmm(new Date(to), fmt)} · ${span(t, (to-from)/1000)}`;
      const level = ["red", "yellow"].includes(interval.maximum_air_level) ? interval.maximum_air_level : "other";
      return `<span class="seg ${level}${interval.ongoing ? " live" : ""}${interval.had_gap ? " gap" : ""}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" title="${esc(title)}"></span>`;
    }).join("");
    // The strip is a rolling 24 h; mark the real local 00/06/12/18 hours on it.
    const marks = clockMarks(lo, hi, fmt.config?.time_zone);
    const ticks = marks.map((mark) => `<span class="tick" style="left:${mark.left.toFixed(2)}%"></span>`).join("");
    const labels = marks
      .filter((mark) => mark.left > 7 && mark.left < 86)
      .map((mark) => `<span style="left:${mark.left.toFixed(2)}%">${String(mark.hour).padStart(2, "0")}:00</span>`)
      .join("");
    return `<div class="strip${incomplete ? " incomplete" : ""}">${ticks}${segments}</div>
      <div class="axis">${labels}<span class="end">${esc(t.now)}</span></div>`;
  }

  // The share of time as text; the sensors know it only with complete coverage.
  _pct(t, value) {
    const language = this._fmt().locale.language;
    return `${value.toLocaleString(language, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}${t === I18N.en ? "%" : " %"}`;
  }

  // A lamp per period: green when its data is complete, yellow when it is partial. The tooltip says why;
  // a gap too short to move the share (under 1 % of the period) leaves the lamp green.
  _lamp(t, result, stats) {
    const quality = result?.quality;
    const length = result?.window_seconds || ((dateOf(result?.end) - dateOf(result?.start)) / 1000) || 0;
    const noticeable = length ? (result?.gap_seconds || 0) / length >= 0.01 : false;
    const since = dateOf(stats.summary?.coverage_start);
    const reasons = [];
    if (quality === "incomplete") reasons.push(`${t.incomplete}${since ? `: ${t.journalSince} ${dayMonth(since, this._hass)}` : ""}`);
    else if (quality && !["complete", "gaps"].includes(quality)) reasons.push(t.incomplete);
    const gap = result?.gap_seconds || 0;
    if (quality === "gaps") reasons.push(`${t.gaps}: ${gap < 60 ? `${Math.round(gap)} ${t.sec}` : span(t, gap)}`);
    const warn = Boolean(quality && !["complete", "gaps"].includes(quality)) || (quality === "gaps" && noticeable);
    const status = quality === "gaps" ? t.dataNearlyComplete : t.dataOk;
    return { warn, tip: warn ? reasons.join(" · ") : [status, ...reasons].join(" · ") };
  }

  _statsHtml(t, stats) {
    const fmt = this._fmt();
    const { day, week } = this._rolling(stats);
    // With gaps the sensors say unknown; the share of the time that has data is still a fair number.
    const share = (result) => {
      if (Number.isFinite(result?.percentage)) return result.percentage;
      const known = (result?.window_seconds || 0) - (result?.gap_seconds || 0);
      return result?.quality === "gaps" && known > 0 ? (100 * (result.observed_duration_seconds || 0)) / known : null;
    };
    // Today and the month are cut at local midnight on the server; the same response carries them.
    const calendar = stats.summary?.calendar;
    const monthName = (period) => {
      const name = new Intl.DateTimeFormat(fmt.locale.language, { month: "long", timeZone: fmt.config?.time_zone || undefined })
        .format(dateOf(period.start) || new Date());
      return name.charAt(0).toUpperCase() + name.slice(1);
    };
    const own = (result) => (Number.isFinite(result?.percentage) ? result.percentage : null);
    const periods = [
      calendar?.today ? ["today", t.today, calendar.today, own(calendar.today)] : null,
      ["day", t.last24, day, share(day)],
      ["week", t.week, week, share(week)],
      calendar?.month ? ["month", monthName(calendar.month), calendar.month, own(calendar.month)] : null,
    ].filter((period) => period && this._shows("stats", period[0]));
    const table = periods.length ? this._tableHtml(t, stats, periods) : "";
    const chart = calendar?.month && this._shows("stats", "chart") ? this._monthChartHtml(t, calendar.month, monthName(calendar.month)) : "";
    return table + chart;
  }

  // Hours under alert per day of the current month; days still to come stay empty.
  _monthChartHtml(t, month, name) {
    const daily = Array.isArray(month.daily) ? month.daily : [];
    const match = /^(\d{4})-(\d{2})-/.exec(daily[0]?.date || "");
    if (!match) return "";
    const [year, mon] = [Number(match[1]), Number(match[2])];
    const days = new Date(Date.UTC(year, mon, 0)).getUTCDate();
    const byDay = new Map(daily.map((day) => [Number(String(day.date).slice(8, 10)), day]));
    const label = (day) => `${String(day).padStart(2, "0")}.${String(mon).padStart(2, "0")}`;
    let top = null;
    for (const [day, entry] of byDay) {
      if ((entry.observed_duration_seconds || 0) > (top?.seconds || 0)) top = { day, seconds: entry.observed_duration_seconds };
    }
    const bars = Array.from({ length: days }, (_, i) => {
      const entry = byDay.get(i + 1);
      if (!entry) return `<div class="bar future"></div>`;
      const seconds = Math.max(entry.observed_duration_seconds || 0, 0);
      const title = seconds ? `${label(i + 1)} · ${span(t, seconds)} · ${alerts(t, entry.count || 0)}` : `${label(i + 1)} · ${t.noAlerts}`;
      const height = Math.min(seconds / 86400, 1) * 100;
      return `<div class="bar${top?.day === i + 1 ? " top" : ""}" title="${esc(title)}"><i style="height:${(seconds ? Math.max(height, 2) : 0).toFixed(1)}%"></i></div>`;
    }).join("");
    const hint = top ? `${t.max} ${label(top.day)} · ${span(t, top.seconds)}` : t.noAlerts;
    const axis = [1, 8, 15, 22, 29].filter((day) => day <= days)
      .map((day) => `<span style="left:${(((day - 0.5) / days) * 100).toFixed(2)}%">${day}</span>`).join("");
    return `<div class="mchart"><div class="mtitle"><span>${esc(name)} · ${esc(t.chartTitle)}</span><span class="mhint">${esc(hint)}</span></div>`
      + `<div class="mbars"><span class="mgrid"></span>${bars}</div><div class="axis">${axis}</div></div>`;
  }

  // A line per period; the columns shrink on a narrow card instead of switching to another view.
  _tableHtml(t, stats, periods) {
    const shown = (item) => this._shows("stats", item);
    const columns = ["total", "count", "longest", "average"].filter(shown);
    const head = (text, right) => `<div class="hd${right ? " n" : ""}">${esc(text)}</div>`;
    const labels = { total: t.totalH, count: t.countH, longest: t.longestShort, average: t.avgShort };
    const cells = periods.map(([, label, result, percentage]) => {
      const { warn, tip } = this._lamp(t, result, stats);
      const lamp = shown("lamp") && result ? `<i class="lamp ${warn ? "warn" : "ok"}" role="img" aria-label="${esc(tip)}"></i>` : "";
      const count = result?.count || 0;
      const seconds = result?.observed_duration_seconds || 0;
      const average = result?.average_duration_seconds ?? (count ? seconds / count : null);
      const bar = shown("bar") ? `<i style="width:${(Math.min(Math.max(percentage ?? 0, 0), 100) * 0.9).toFixed(1)}%"></i>` : "";
      const value = {
        total: result ? span(t, seconds) : "—",
        count: result ? String(count) : "—",
        longest: count ? span(t, result.longest_duration_seconds || 0) : "—",
        average: count && average !== null ? span(t, average) : "—",
      };
      return `<div class="c l"${lamp ? ` title="${esc(tip)}"` : ""}>${lamp}${esc(label)}</div>`
        + `<div class="c p">${esc(percentage === null ? "—" : this._pct(t, percentage))}${bar}</div>`
        + columns.map((column) => `<div class="c n${column === "count" ? " dim" : ""}">${esc(value[column])}</div>`).join("");
    });
    return `<div class="tbl" style="grid-template-columns: repeat(${columns.length + 2}, auto)">`
      + head("") + head(t.shareH) + columns.map((column) => head(labels[column], true)).join("") + cells.join("") + "</div>";
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const t = lang(this._hass, this._config.language);
    if (this._config.entities) { this._renderList(t); return; }
    const ids = this._entities();
    if (!ids) {
      patchDOM(this.shadowRoot, `${STYLE}<ha-card><div class="empty">${esc(t.notFound)}</div></ha-card>`);
      return;
    }
    const view = this._view(t, ids);
    const { sections } = this._config;
    const compact = sections.length === 1 && sections[0] === "status";
    const parts = sections.map((section) => this._sectionHtml(section, t, view)).filter(Boolean);
    // An active alert on stale data is flagged whatever the user picked: a
    // quiet card says "no fresh data" in its title, an active one must not
    // let an old alert pass for a current one.
    if (view.stale && view.active) {
      parts.splice(sections[0] === "status" ? 1 : 0, 0, `<div class="foot"><span class="dot"></span>${esc(t.staleNote)}</div>`);
    }
    patchDOM(this.shadowRoot, `${STYLE}
      <ha-card class="${view.status}${compact ? " compact" : ""}" tabindex="0" role="button" aria-label="${esc(view.name)}: ${esc(view.title)}">
        ${this._countryHtml(t, ids)}${parts.join("\n")}
      </ha-card>`);
    this._bindOpen();
  }

  // A tap opens the region (the row's in the list, the card's otherwise) unless
  // tap_action says otherwise; hold_action and double_tap_action are HA's usual.
  _bindOpen() {
    const card = this.shadowRoot.querySelector("ha-card");
    if (!card || this._eventCard === card) return;
    this._eventCard = card;
    const aim = (event) => {
      const path = event?.composedPath?.() || [];
      const chip = path.find((el) => el?.dataset?.more);
      if (chip) return { more: chip.dataset.more };
      const row = path.find((el) => el?.dataset?.entity);
      return { entity: row ? row.dataset.entity : !this._config.entities && this._entities()?.alert };
    };
    let holdTimer = null;
    let held = false;
    let start = null;
    let pending = null;
    const release = () => { clearTimeout(holdTimer); holdTimer = null; };
    card.addEventListener("pointerdown", (event) => {
      held = false;
      start = [event.clientX, event.clientY];
      release();
      const target = aim(event);
      if (!this._hasAction("hold_action") || !target.entity) return;
      holdTimer = setTimeout(() => { held = true; holdTimer = null; this._act("hold", target.entity); }, HOLD_MS);
    });
    card.addEventListener("pointermove", (event) => {
      if (holdTimer && start && Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 10) release();
    });
    for (const type of ["pointerup", "pointercancel", "pointerleave"]) card.addEventListener(type, release);
    card.addEventListener("contextmenu", (event) => { if (this._hasAction("hold_action")) event.preventDefault(); });
    const tap = (event, now) => {
      const target = aim(event);
      if (target.more) { this._moreInfo(target.more); return; }
      if (!target.entity) return;
      if (now || !this._hasAction("double_tap_action")) { this._act("tap", target.entity); return; }
      if (pending) { clearTimeout(pending); pending = null; this._act("double_tap", target.entity); return; }
      pending = setTimeout(() => { pending = null; this._act("tap", target.entity); }, DOUBLE_TAP_MS);
    };
    card.addEventListener("click", (event) => {
      // The release that ends a hold is not also a tap.
      if (held) { held = false; return; }
      tap(event, false);
    });
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); tap(event, true); }
    });
  }

  _hasAction(key) {
    const action = this._config[key]?.action;
    return Boolean(action) && action !== "none";
  }

  // Without a tap_action a tap opens the entity directly, as before; anything
  // configured goes to Home Assistant's own action handler.
  _act(action, entity) {
    if (action === "tap" && !this._config.tap_action) { this._moreInfo(entity); return; }
    const { tap_action, hold_action, double_tap_action } = this._config;
    this.dispatchEvent(new CustomEvent("hass-action", { bubbles: true, composed: true,
      detail: { config: { entity, tap_action, hold_action, double_tap_action }, action } }));
  }

  // Country-wide threats in one row, only while one is up: the MiG-31K, ballistics,
  // strategic and tactical aviation, missile carriers. An unknown state draws nothing.
  // A chip opens its own sensor (`data-more`), not the card's tap action.
  _countryHtml(t, ids) {
    if (this._config.hide.includes("status.mig")) return "";
    const chips = [];
    const mig = ids.mig && this._hass.states[ids.mig];
    if (mig && t.mig[mig.state]) {
      const since = dateOf(mig.attributes.since);
      const parts = [t.mig[mig.state], t.airfields[mig.attributes.airfield], since && `${t.since} ${hhmm(since, this._fmt())}`];
      chips.push(["mig", mig.state, ids.mig, "mdi:airplane-alert", parts]);
    }
    for (const [key, icon] of COUNTRY) {
      const state = ids[key] && this._hass.states[ids[key]];
      const text = state && t.country[key][state.state];
      if (!text) continue;
      const since = dateOf(state.attributes.since);
      chips.push([key, state.state, ids[key], icon, [text, since && `${t.since} ${hhmm(since, this._fmt())}`]]);
    }
    if (!chips.length) return "";
    return `<div class="country">${chips.map(countryChip).join("")}</div>`;
  }

  // The listed regions that exist, each with the sensors its row reads.
  // After a restart states arrive one by one while the registry stays the same:
  // a region or sensor still missing is looked up again on the next update.
  _list() {
    const hass = this._hass;
    const cached = this._listCache;
    const present = this._config.entities.filter((id) => hass.states[id]);
    const found = (ids) => Object.values(ids).every((id) => id && hass.states[id]);
    if (cached && cached.registry === hass.entities && cached.configured === this._config.entities &&
        cached.rows.length === present.length && cached.rows.every(found) && found(cached.hubs)) return cached.rows;
    const rows = present.map((alert) => {
      const rid = regionIdOf(hass, alert);
      return {
        alert,
        threat: sibling(hass, "threat", rid),
        level: sibling(hass, "air_alert_level", rid),
        started: sibling(hass, "alert_started", rid),
        cleared: sibling(hass, "alert_cleared", rid),
        percentage24h: sibling(hass, "alert_percentage_24h", rid),
      };
    });
    const hubs = { stale: hub(hass, "data_stale"), mig: hub(hass, "mig_status"), ...countryHubs(hass) };
    this._listCache = { registry: hass.entities, configured: this._config.entities, rows, hubs };
    return rows;
  }

  // How long the alert or the quiet has lasted; nothing when the data cannot say.
  _rowTime(t, flags, started, cleared) {
    const fmt = this._fmt();
    if (flags.active) {
      const since = dateOf(known(started)?.state);
      return since ? `${esc(duration(t, since))}<div class="lsub">${esc(t.since)} ${esc(hhmm(since, fmt))}</div>` : "";
    }
    const ended = !flags.noData && !flags.stale ? dateOf(known(cleared)?.state) : null;
    if (!ended) return "";
    const day = Date.now() - ended > 86400000 ? `${dayMonth(ended, fmt)} ` : "";
    return `${esc(duration(t, ended))}<div class="lsub">${esc(t.clearedAt)} ${esc(day)}${esc(hhmm(ended, fmt))}</div>`;
  }

  _renderList(t) {
    const hass = this._hass;
    const listed = this._list();
    const { hubs } = this._listCache;
    const stale = hass.states[hubs.stale]?.state === "on";
    const rows = listed.map((ids) => {
      const st = (id) => (id ? hass.states[id] : undefined);
      const alert = st(ids.alert);
      const threat = st(ids.threat);
      const flags = {
        active: alert.state === "on",
        noData: ["unavailable", "unknown"].includes(alert.state),
        stale,
        air: st(ids.level)?.state,
        types: String(threat?.attributes?.active_threat_types || "").split(",").filter(Boolean),
      };
      // A line is narrow: an air alert with a known level says only the level.
      const word = flags.active && t.levelWord[flags.air];
      let sub = esc(titleOf(t, flags));
      if (word && flags.types[0] === "air") sub = `<b class="lv ${esc(flags.air)}">${esc(t.level[flags.air])}</b>`;
      else if (word) sub += ` · <b class="lv ${esc(flags.air)}">${esc(word)}</b>`;
      const time = this._rowTime(t, flags, st(ids.started), st(ids.cleared));
      const share = known(st(ids.percentage24h));
      const value = share && Number.isFinite(Number(share.state)) ? this._pct(t, Number(share.state)) : "—";
      const name = shortName(threat?.attributes?.region_name || alert.attributes.friendly_name || ids.alert);
      return `<div class="lrow ${statusOf(flags)}" data-entity="${esc(ids.alert)}" role="button" tabindex="0" aria-label="${esc(name)}: ${esc(titleOf(t, flags))}">`
        + `<span class="ldot"></span><div class="lname">${esc(name)}<div class="lsub">${sub}</div></div>`
        + `<div class="ltime">${time}</div><div class="lpct">${esc(value)}<div class="lsub">${esc(t.last24)}</div></div></div>`;
    });
    const head = this._config.name ? `<div class="lhead">${esc(this._config.name)}</div>` : "";
    const note = stale ? `<div class="foot"><span class="dot"></span>${esc(t.staleNote)}</div>` : "";
    const body = rows.length ? rows.join("") : `<div class="empty">${esc(t.notFound)}</div>`;
    patchDOM(this.shadowRoot, `${STYLE}<ha-card class="list">${head}${this._countryHtml(t, hubs)}${note}${body}</ha-card>`);
    this._bindOpen();
  }

  // Everything the markup needs, read once from the entities.
  _view(t, ids) {
    const hass = this._hass;
    const st = (id) => (id ? hass.states[id] : undefined);
    const alert = st(ids.alert);
    const threat = st(ids.threat);
    const flags = {
      active: alert.state === "on",
      noData: ["unavailable", "unknown"].includes(alert.state),
      stale: st(ids.stale)?.state === "on",
      air: st(ids.level)?.state,
      types: String(threat?.attributes?.active_threat_types || "")
        .split(",")
        .filter(Boolean),
    };
    return {
      ...flags,
      name: this._config.name || threat?.attributes?.region_name || alert.attributes.friendly_name,
      status: statusOf(flags),
      title: titleOf(t, flags),
      threat,
      level: st(ids.level),
      started: st(ids.started),
      cleared: st(ids.cleared),
      updated: st(ids.updated),
      journal: this._stats?.rid === regionIdOf(hass, ids.alert) ? this._stats : null,
    };
  }

  _timerHtml(t, view) {
    const fmt = this._fmt();
    if (view.active) {
      const since = dateOf(known(view.started)?.state);
      if (!since) return "";
      return `<div class="timer"><div class="big">${esc(duration(t, since))}</div><div class="small">${esc(t.since)} ${esc(hhmm(since, fmt))}</div></div>`;
    }
    if (view.noData || view.stale) return "";
    const cleared = dateOf(known(view.cleared)?.state)
      || dateOf(view.journal?.episodes.find((ep) => ep.observed_cleared_at)?.observed_cleared_at);
    if (!cleared) return "";
    const day = Date.now() - cleared > 86400000 ? dayMonth(cleared, fmt) : "";
    return `<div class="timer quiet"><div class="big">${esc(duration(t, cleared))}</div><div class="small">${esc(t.quietFor)} ${esc(day)} ${esc(hhmm(cleared, fmt))}</div></div>`;
  }

  _chips(t, view) {
    if (!view.active) return [];
    const chips = !this._shows("details", "types") ? [] : view.types
      .slice(1)
      .map((type) => chip(TYPE_ICONS[type] || TYPE_ICONS.unrecognized, t.types[type] || type));
    const levelText = this._shows("details", "level") && t.level[view.air];
    // The feed's reason already names the level ("Ракетна загроза (червоний рівень)"):
    // the chip says the threat and the level once, and the reason line goes.
    const merged = this._mergedReasons(view);
    const label = merged ? `${merged.join(" · ")} · ${t.levelWord[view.air]}` : levelText;
    if (levelText) chips.push(`<span class="chip level ${esc(view.air)}"><span class="dot"></span>${esc(label)}</span>`);
    const coverage = this._shows("details", "coverage") ? view.threat?.attributes?.coverage : undefined;
    if (coverage === "whole") chips.push(chip("mdi:map", t.whole));
    if (coverage === "unrecognized") chips.push(chip("mdi:map-search", t.unknownCoverage));
    if (coverage === "partial") {
      const areas = (view.threat.attributes.affected_regions || []).map((r) => r.region_name).filter(Boolean);
      const listed = areas.length > 3 ? `${areas.slice(0, 3).join(", ")}…` : areas.join(", ");
      chips.push(chip("mdi:map-marker-radius", areas.length ? `${t.partial}: ${listed}` : t.partial));
    }
    return chips;
  }

  // The reasons without their "(… рівень)" tail, when the level chip carries them.
  _mergedReasons(view) {
    if (!view.active || !hasLevel(view) || !this._shows("details", "level") || !this._shows("details", "reason")) return null;
    const names = [...new Set((view.level?.attributes?.reasons || []).map(withoutLevel).filter(Boolean))];
    return names.length ? names : null;
  }

  // The update time rides quietly in the region line; stale data turns it red.
  _meta(t, view) {
    const updated = dateOf(known(view.updated)?.state);
    if (!updated || view.noData) return "";
    const cls = view.stale ? "meta bad" : "meta";
    return ` <span class="${cls}">· ${esc(t.updated)} ${esc(hhmm(updated, this._fmt()))}</span>`;
  }

  _sectionHtml(section, t, view) {
    if (section === "status") return this._headHtml(t, view) + this._typicalHtml(t, view);
    if (section === "details") {
      const chips = this._chips(t, view);
      const reasons = view.active && this._shows("details", "reason") && !this._mergedReasons(view)
        ? (view.level?.attributes?.reasons || []).join(" · ") : "";
      if (!chips.length && !reasons) return "";
      const chipsHtml = chips.length ? `<div class="chips">${chips.join("")}</div>` : "";
      const reasonsHtml = reasons ? `<div class="reasons">${esc(reasons)}</div>` : "";
      return `<div class="sec details">${chipsHtml}${reasonsHtml}</div>`;
    }
    if (!view.journal) return "";
    const html = { timeline: this._timelineHtml, stats: this._statsHtml }[section].call(this, t, view.journal);
    return html ? `<div class="sec ${section}">${html}</div>` : "";
  }

  // How long an alert here usually lasts, against how long this one has run.
  _typicalHtml(t, view) {
    const typical = view.journal?.summary?.typical;
    const since = view.active && dateOf(known(view.started)?.state);
    if (!typical || !since || !this._shows("status", "typical")) return "";
    const median = typical.median_seconds;
    const upper = typical.p75_seconds;
    if (!positive(median) || !positive(upper)) return "";
    const elapsed = Math.max((Date.now() - since.getTime()) / 1000, 0);
    const scale = Math.max(upper * 1.25, elapsed);
    const at = (seconds) => `${((seconds / scale) * 100).toFixed(1)}%`;
    return `<div class="typ" title="${esc(alerts(t, typical.count))}"><div class="typbar"><i style="width:${at(elapsed)}"></i>`
      + `<b style="left:${at(median)}"></b><b style="left:${at(upper)}"></b></div>`
      + `<div class="typtxt"><span>${esc(t.usually)} ~${esc(span(t, median))}, ${esc(t.oneInFour)} ${esc(span(t, upper))}</span>`
      + `<span>${esc(typical.days)} ${esc(t.days)}</span></div></div>`;
  }

  _headHtml(t, view) {
    // Without the level chip the level still shows, next to the region name.
    const inline = this._shows("details", "level") ? "" : levelSuffix(t, view);
    const meta = this._shows("status", "updated") ? this._meta(t, view) : "";
    return `<div class="sec head">
          <div class="badge"><span class="pulse"></span><ha-icon icon="${STATUS_ICONS[view.status]}"></ha-icon></div>
          <div class="titles">
            <div class="region">${esc(view.name)}${inline}${meta}</div>
            <div class="status">${esc(view.title)}</div>
          </div>
          ${this._shows("status", "timer") ? this._timerHtml(t, view) : ""}
        </div>`;
  }
}

// Country-wide threat sensors, in the feed's order, with their chip icons.
const COUNTRY = [
  ["ballistics", "mdi:rocket-launch"],
  ["strategic_aviation", "mdi:airplane"],
  ["tactical_aviation", "mdi:airplane-takeoff"],
  ["missile_carriers", "mdi:ferry"],
];
const countryHubs = (hass) => Object.fromEntries(COUNTRY.map(([key]) => [key, hub(hass, key)]));
const countryChip = ([key, state, id, icon, parts]) =>
  `<span class="ct ${key} ${esc(state)}" data-more="${esc(id)}" role="button" tabindex="0">`
  + `<ha-icon icon="${icon}"></ha-icon><span>${esc(parts.filter(Boolean).join(" · "))}</span></span>`;
// "Ракетна загроза (червоний рівень)" -> "Ракетна загроза": drop a trailing "(…)".
const withoutLevel = (reason) => {
  const text = String(reason).trim();
  const open = text.lastIndexOf("(");
  return (text.endsWith(")") && open >= 0 ? text.slice(0, open) : text).trim();
};
const positive = (value) => Number.isFinite(value) && value > 0;
const hasLevel = (view) => ["red", "yellow", "unrecognized"].includes(view.air);
const HOLD_MS = 500;
const DOUBLE_TAP_MS = 250;

const STATUS_ICONS = {
  red: "mdi:alarm-light",
  yellow: "mdi:alarm-light",
  alert: "mdi:alarm-light",
  quiet: "mdi:shield-check",
  stale: "mdi:cloud-off-outline",
  nodata: "mdi:timer-sand",
};

const known = (state) => (state && !["unknown", "unavailable"].includes(state.state) ? state : null);

const chip = (icon, text) => `<span class="chip"><ha-icon icon="${icon}"></ha-icon>${esc(text)}</span>`;

function statusOf({ noData, active, stale, air }) {
  if (noData) return "nodata";
  if (active) return air === "red" || air === "yellow" ? air : "alert";
  return stale ? "stale" : "quiet";
}

function titleOf(t, { noData, active, stale, types }) {
  if (noData) return t.noData;
  if (active) return t.types[types[0]] || t.alert;
  return stale ? t.stale : t.quiet;
}

// "… територіальна громада" is the official name; a list line keeps "… громада".
const OFFICIAL_HROMADA = " територіальна громада";
const shortName = (name) => {
  const text = String(name);
  return text.endsWith(OFFICIAL_HROMADA) ? `${text.slice(0, -OFFICIAL_HROMADA.length)} громада` : text;
};

// Without the level chip, the level sits next to the region name.
function levelSuffix(t, view) {
  const text = view.active && t.level[view.air];
  return text ? ` <span class="lvl ${esc(view.air)}"><span class="dot"></span>${esc(text)}</span>` : "";
}

const STYLE = `<style>
  :host { --uap-red: #e5393b; --uap-yellow: #f2a900; --uap-green: #2e9d57; --uap-gray: #8a8f98; }
  ha-card { display: block; position: relative; overflow: hidden; padding: 12px 14px; cursor: pointer; --accent: var(--uap-green);
    container-type: inline-size; }
  ha-card.red, ha-card.alert { --accent: var(--uap-red); }
  ha-card.yellow { --accent: var(--uap-yellow); }
  ha-card.stale, ha-card.nodata { --accent: var(--uap-gray); }
  /* An active alert tints the whole card; a quiet one stays neutral. */
  ha-card.red, ha-card.alert, ha-card.yellow {
    background: color-mix(in srgb, var(--accent) 10%, var(--ha-card-background, var(--card-background-color, #fff))); }
  ha-card:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .head { display: flex; align-items: center; gap: 12px; }
  .badge { position: relative; flex: none; width: 38px; height: 38px; border-radius: 11px;
    display: grid; place-items: center; color: var(--accent); background: color-mix(in srgb, var(--accent) 16%, transparent); }
  ha-card.red .badge, ha-card.alert .badge, ha-card.yellow .badge { color: #fff; background: var(--accent); }
  .badge ha-icon { --mdc-icon-size: 22px; display: flex; }
  .pulse { display: none; position: absolute; inset: 0; border-radius: inherit; }
  ha-card.red .pulse, ha-card.alert .pulse, ha-card.yellow .pulse { display: block; animation: pulse 1.8s ease-out infinite; }
  @keyframes pulse { from { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 55%, transparent); }
    to { box-shadow: 0 0 0 9px transparent; } }
  .titles { min-width: 0; flex: 1; }
  .region { font-size: 12.5px; line-height: 1.3; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .meta.bad { color: var(--uap-red); }
  .status { font-size: 16px; font-weight: 600; line-height: 1.25; color: var(--primary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  ha-card.red .status, ha-card.alert .status { color: var(--uap-red); }
  ha-card.yellow .status { color: color-mix(in srgb, var(--uap-yellow) 70%, var(--primary-text-color)); }
  ha-card.stale .status, ha-card.nodata .status { color: var(--secondary-text-color); }
  .timer { flex: none; text-align: right; }
  .timer .big { font-size: 16px; font-weight: 600; line-height: 1.25; white-space: nowrap;
    font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
  .timer .small { font-size: 12px; line-height: 1.3; white-space: nowrap; color: var(--secondary-text-color); }
  .dot { flex: none; width: 8px; height: 8px; border-radius: 50%; display: inline-block; background: currentColor; }
  .lvl { display: inline-flex; align-items: center; gap: 4px; margin-left: 4px; font-weight: 600; }
  .lvl .dot { width: 7px; height: 7px; }
  .lvl.red { color: var(--uap-red); }
  .lvl.yellow { color: color-mix(in srgb, var(--uap-yellow) 75%, var(--primary-text-color)); }
  .sec + .sec, .foot + .sec, .sec + .foot { margin-top: 10px; }
  .sec.timeline + .sec.stats { margin-top: 6px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; padding: 3px 8px; border-radius: 6px;
    font-size: 12px; line-height: 1.35; color: var(--primary-text-color);
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); }
  .chip ha-icon { --mdc-icon-size: 15px; display: flex; color: var(--secondary-text-color); }
  .chip.level.red .dot { background: var(--uap-red); }
  .chip.level.yellow .dot { background: var(--uap-yellow); }
  .chip.level.unrecognized .dot { background: var(--uap-gray); }
  .chips + .reasons { margin-top: 6px; }
  .reasons { font-size: 12.5px; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .foot { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--uap-red); }
  .strip { position: relative; height: 8px; border-radius: 4px; overflow: hidden;
    background: color-mix(in srgb, var(--uap-green) 22%, transparent); }
  .strip.incomplete { background: repeating-linear-gradient(45deg, rgba(127,127,127,.14) 0 3px, transparent 3px 7px); }
  .tick { position: absolute; top: 0; bottom: 0; width: 1px; background: color-mix(in srgb, var(--primary-text-color) 18%, transparent); }
  .seg { position: absolute; top: 0; bottom: 0; border-radius: 2px; background: var(--uap-red); }
  .seg.yellow { background: var(--uap-yellow); }
  .seg.other { background: color-mix(in srgb, var(--uap-red) 70%, var(--uap-gray)); }
  .seg.gap { background-image: repeating-linear-gradient(45deg, rgba(255,255,255,.35) 0 3px, transparent 3px 6px); }
  .seg.live { animation: live 1.8s ease-in-out infinite; }
  @keyframes live { 50% { opacity: .55; } }
  .axis { position: relative; height: 13px; margin-top: 3px; font-size: 10.5px; line-height: 13px;
    color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
  .axis span { position: absolute; top: 0; transform: translateX(-50%); }
  .axis .end { right: 0; transform: none; }
  /* A line per period; a narrow card gets smaller type and tighter columns, not another layout. */
  .tbl { display: grid; justify-content: space-between; column-gap: 6px; align-items: center; font-variant-numeric: tabular-nums; font-size: 11px; }
  .tbl .hd { padding-bottom: 3px; font-size: 10.5px; color: var(--secondary-text-color); white-space: nowrap; }
  .tbl .c { padding: 5px 0; white-space: nowrap; border-top: 1px solid color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .tbl .n { text-align: right; }
  .tbl .dim { color: var(--secondary-text-color); }
  .tbl .p { position: relative; font-size: 13.5px; font-weight: 600; color: var(--primary-text-color); }
  .tbl .p i { position: absolute; left: 0; bottom: 3px; height: 3px; border-radius: 2px; background: var(--primary-color); }
  .tbl .l { color: var(--primary-text-color); font-size: 11.5px; }
  .lamp { display: inline-block; width: 7px; height: 7px; margin-right: 6px; border-radius: 50%; vertical-align: middle; position: relative; top: -1px; }
  .lamp.ok { background: var(--uap-green); }
  .lamp.warn { background: var(--uap-yellow); }
  @container (max-width: 319px) {
    .tbl { column-gap: 4px; font-size: 10px; }
    .tbl .hd { font-size: 9.5px; }
    .tbl .p { font-size: 12.5px; }
    .tbl .l { font-size: 10.5px; }
  }
  @container (max-width: 270px) { .tbl { overflow-x: auto; justify-content: start; } }
  ha-card.compact { padding: 10px 12px; }
  ha-card.compact .badge { width: 34px; height: 34px; border-radius: 10px; }
  ha-card.compact .badge ha-icon { --mdc-icon-size: 20px; }
  @media (prefers-reduced-motion: reduce) { .pulse, .seg.live { animation: none !important; } }
  /* The timer keeps the right-hand column; only a very narrow card (a half-width
     tile on a phone) moves it under the title instead of colliding with it. */
  @container (max-width: 280px) {
    .head { flex-wrap: wrap; row-gap: 2px; }
    .timer { order: 3; flex-basis: 100%; display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 8px;
      text-align: left; padding-left: 50px; }
    ha-card.compact .timer { padding-left: 46px; }
    .timer .small { white-space: normal; }
  }
  .empty { padding: 8px; color: var(--secondary-text-color); }
  /* The month chart: a bar per day, the height is the hours under alert out of 24. */
  .mchart { margin-top: 10px; }
  .mtitle { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 6px; font-size: 11.5px; color: var(--primary-text-color); }
  .mtitle span:first-child { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .mtitle .mhint { color: var(--secondary-text-color); white-space: nowrap; }
  .mbars { position: relative; height: 64px; display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 2px; align-items: end;
    border-bottom: 1px solid color-mix(in srgb, var(--primary-text-color) 15%, transparent); }
  .mgrid { position: absolute; left: 0; right: 0; bottom: 50%; border-top: 1px dashed color-mix(in srgb, var(--primary-text-color) 15%, transparent); }
  .bar { height: 100%; display: flex; align-items: flex-end; }
  .bar i { display: block; width: 100%; border-radius: 2px 2px 0 0; background: color-mix(in srgb, var(--primary-color) 70%, transparent); }
  .bar.top i { background: var(--primary-color); }
  /* Country-wide threats: the MiG-31K, ballistics, aviation, missile carriers. */
  .country { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 9px; }
  .ct { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; padding: 4px 8px; border-radius: 6px; font-size: 12px;
    font-weight: 600; line-height: 1.3; color: var(--primary-text-color); --c: var(--uap-yellow);
    background: color-mix(in srgb, var(--c) 18%, transparent); cursor: pointer; }
  .ct.launch, .ct.ballistics { --c: var(--uap-red); background: color-mix(in srgb, var(--c) 28%, transparent); }
  .ct ha-icon { --mdc-icon-size: 15px; display: flex; flex: none; color: var(--c); }
  .ct:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
  ha-card.list .country { margin: 6px 0 2px; }
  /* How long an alert here usually lasts. */
  .typ { margin-top: 9px; }
  .typ + .sec, .typ + .foot { margin-top: 10px; }
  .typbar { position: relative; height: 5px; border-radius: 3px; background: color-mix(in srgb, var(--primary-text-color) 10%, transparent); }
  .typbar i { position: absolute; left: 0; top: 0; bottom: 0; max-width: 100%; border-radius: 3px; background: var(--accent); }
  .typbar b { position: absolute; top: -3px; width: 2px; height: 11px; margin-left: -1px; border-radius: 1px;
    background: var(--primary-text-color); opacity: .5; }
  .typtxt { display: flex; justify-content: space-between; gap: 8px; margin-top: 4px; font-size: 11.5px; color: var(--secondary-text-color); }
  .typtxt span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .typtxt span:last-child { flex: none; }
  /* Several regions: a line each. */
  ha-card.list { padding: 6px 14px; }
  .lhead { padding: 6px 0 2px; font-size: 14px; font-weight: 600; color: var(--primary-text-color); }
  ha-card.list .foot { padding: 6px 0 0; }
  .lrow { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 8px 0; cursor: pointer;
    --accent: var(--uap-green); }
  .lrow + .lrow { border-top: 1px solid color-mix(in srgb, var(--primary-text-color) 8%, transparent); }
  .lrow.red, .lrow.alert { --accent: var(--uap-red); }
  .lrow.yellow { --accent: var(--uap-yellow); }
  .lrow.stale, .lrow.nodata { --accent: var(--uap-gray); }
  .lrow:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; border-radius: 6px; }
  .ldot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); }
  .lrow.red .ldot, .lrow.alert .ldot, .lrow.yellow .ldot { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 22%, transparent); }
  .lname { min-width: 0; font-size: 14px; font-weight: 600; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .lsub { font-size: 11.5px; font-weight: 400; line-height: 1.3; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .lv { font-weight: 600; }
  .lv.red { color: var(--uap-red); }
  .lv.yellow { color: color-mix(in srgb, var(--uap-yellow) 75%, var(--primary-text-color)); }
  .ltime, .lpct { text-align: right; font-size: 14px; font-weight: 600; white-space: nowrap; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
  .lrow.quiet .ltime { font-weight: 500; color: var(--secondary-text-color); }
  .lpct { font-size: 13px; min-width: 52px; }
  @container (max-width: 300px) { .lrow { grid-template-columns: 10px minmax(0, 1fr) auto; } .lpct { display: none; } }
</style>`;

// Editor words, in Home Assistant's language; the card's own `language` is a setting in it.
const EDITOR_I18N = {
  uk: {
    entity: "Регіони", name: "Назва", language: "Мова картки",
    tap_action: "Дія при натисканні", hold_action: "Дія при утриманні",
    listNote: "Кілька регіонів показуються списком: рядок на регіон. Розділи нижче стосуються картки одного регіону.",
    head: "Розділи", reset: "Скинути", up: "Вище", down: "Нижче", items: "Що показувати",
    names: {
      status: ["Стан", "регіон, тривога чи тихо, тривалість"],
      details: ["Деталі тривоги", "рівень, інші загрози, охоплення, причина"],
      timeline: ["Смуга 24 год", "коли були тривоги за добу"],
      stats: ["Статистика", "частка часу під тривогою, кількість, найдовша й середня тривога за 24 год, 7 днів, сьогодні й місяць; графік за місяць"],
    },
    item: {
      status: { timer: "Тривалість", updated: "Час оновлення", typical: "Зазвичай триває", mig: "Загрози по країні" },
      details: { level: "Рівень", types: "Інші загрози", coverage: "Охоплення", reason: "Причина" },
      stats: { today: "Сьогодні", day: "24 год", week: "7 днів", month: "Поточний місяць", bar: "Смужка частки", total: "Разом", count: "Кількість", longest: "Найдовша", average: "Середня", lamp: "Індикатор повноти даних", chart: "Графік за місяць" },
    },
    languages: { auto: "Як у Home Assistant", uk: "Українська", en: "English" },
  },
  en: {
    entity: "Regions", name: "Name", language: "Card language",
    tap_action: "Tap action", hold_action: "Hold action",
    listNote: "Several regions are shown as a list, a line each. The sections below apply to a one-region card.",
    head: "Sections", reset: "Reset", up: "Move up", down: "Move down", items: "What to show",
    names: {
      status: ["Status", "region, alert or quiet, duration"],
      details: ["Alert details", "level, other threats, coverage, reason"],
      timeline: ["24 h strip", "when the alerts were over the day"],
      stats: ["Statistics", "share of time under alert, count, longest and average alert over 24 h, 7 days, today and this month; month chart"],
    },
    item: {
      status: { timer: "Duration", updated: "Update time", typical: "Usual length", mig: "Country-wide threats" },
      details: { level: "Level", types: "Other threats", coverage: "Coverage", reason: "Reason" },
      stats: { today: "Today", day: "24 h", week: "7 days", month: "This month", bar: "Share bar", total: "Total", count: "Count", longest: "Longest", average: "Average", lamp: "Data completeness lamp", chart: "Month chart" },
    },
    languages: { auto: "As in Home Assistant", uk: "Українська", en: "English" },
  },
};

class UkraineAlarmProCardEditor extends HTMLElement {
  setConfig(config) {
    const { sections, hide, entity, entities } = normalizeConfig(config);
    const next = { ...config, sections, hide };
    delete next.entity;
    delete next.entities;
    if (entity) next.entity = entity;
    if (entities) next.entities = entities;
    this._config = next;
    this._render();
  }

  // HA sets `hass` on every state change. Redrawing the section list then would
  // drop keyboard focus and lose a click pressed across the update, so only a
  // language change (or the first `hass`) redraws; the form just gets the new one.
  set hass(hass) {
    const before = this._labels();
    const first = !this._hass;
    this._hass = hass;
    if (first || !this._form || this._labels() !== before) this._render();
    else this._form.hass = hass;
  }

  _labels() {
    return (this._hass?.locale?.language || this._hass?.language || "en").startsWith("uk") ? EDITOR_I18N.uk : EDITOR_I18N.en;
  }

  // Only what the user set is written: no `layout`, and no empty `hide`.
  _emit(next) {
    const { layout, ...rest } = { ...this._config, ...next };
    if (!rest.hide?.length) delete rest.hide;
    this._config = { ...rest, hide: rest.hide || [] };
    this._render();
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: rest }, bubbles: true, composed: true }));
  }

  _toggle(key) {
    const on = this._config.sections;
    if (on.includes(key)) {
      if (on.length > 1) this._emit({ sections: on.filter((section) => section !== key) });
      else this._render();
    } else this._emit({ sections: [...on, key] });
  }

  _move(key, dir) {
    const on = [...this._config.sections];
    const i = on.indexOf(key);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= on.length) return;
    [on[i], on[j]] = [on[j], on[i]];
    this._emit({ sections: on });
  }

  // Items hide one at a time; a section always keeps at least one of its required items.
  _toggleItem(id) {
    const [section, item] = id.split(".");
    const hide = [...this._config.hide];
    if (hide.includes(id)) hide.splice(hide.indexOf(id), 1);
    else if (!lastShown(section, hide, item)) hide.push(id);
    else { this._render(); return; }
    this._emit({ hide });
  }

  _expand(key) {
    this._open = this._open || new Set();
    if (!this._open.delete(key)) this._open.add(key);
    this._render();
  }

  _sectionsHtml() {
    const l = this._labels();
    const on = this._config.sections;
    const hide = this._config.hide;
    const rows = [...on, ...SECTIONS.filter((section) => !on.includes(section))];
    return rows.map((key) => {
      const [name, hint] = l.names[key];
      const shown = on.includes(key);
      const i = on.indexOf(key);
      const lock = shown && on.length === 1 ? " disabled" : "";
      const expandable = shown && Boolean(ITEMS[key]);
      const open = expandable && this._open?.has(key);
      const openClass = open ? "open" : "";
      const expand = expandable
        ? `<button type="button" data-expand="${key}" class="${openClass}" title="${esc(l.items)}" aria-expanded="${Boolean(open)}"><ha-icon icon="mdi:tune-variant"></ha-icon></button>`
        : "";
      const move = (dir, off) => {
        const label = dir < 0 ? l.up : l.down;
        const icon = dir < 0 ? "up" : "down";
        return `<button type="button" data-move="${key}" data-dir="${dir}"${off ? " disabled" : ""} title="${esc(label)}"><ha-icon icon="mdi:chevron-${icon}"></ha-icon></button>`;
      };
      const items = open
        ? `<div class="items">${ITEMS[key].map((item) => {
          const id = `${key}.${item}`;
          const checked = !hide.includes(id);
          return `<label><input type="checkbox" data-item="${id}"${checked ? " checked" : ""}${checked && lastShown(key, hide, item) ? " disabled" : ""}><span>${esc(l.item[key][item])}</span></label>`;
        }).join("")}</div>`
        : "";
      return `<div class="row${shown ? "" : " off"}"><label><input type="checkbox" data-toggle="${key}"${shown ? " checked" : ""}${lock}><span>${esc(name)}<small>${esc(hint)}</small></span></label>`
        + expand + (shown ? move(-1, i === 0) + move(1, i === on.length - 1) : "") + `</div>${items}`;
    }).join("");
  }

  _render() {
    if (!this._config || typeof document === "undefined") return;
    if (!this._list) {
      this.innerHTML = `<style>${EDITOR_CSS}</style><div class="form"></div><div class="note"></div><div class="top"><b></b><button type="button" class="reset"></button></div><div class="list"></div>`;
      this._list = this.querySelector(".list");
      this.addEventListener("click", (event) => {
        const button = event.target.closest?.("button");
        if (button?.dataset.move) this._move(button.dataset.move, Number(button.dataset.dir));
        else if (button?.dataset.expand) this._expand(button.dataset.expand);
        else if (button?.classList.contains("reset")) this._emit({ sections: [...SECTIONS], hide: [] });
      });
      this.addEventListener("change", (event) => {
        if (event.target.dataset?.toggle) this._toggle(event.target.dataset.toggle);
        else if (event.target.dataset?.item) this._toggleItem(event.target.dataset.item);
      });
    }
    const l = this._labels();
    this.querySelector(".note").textContent = this._config.entities ? l.listNote : "";
    this.querySelector(".top b").textContent = l.head;
    this.querySelector(".top .reset").textContent = l.reset;
    this._list.innerHTML = this._sectionsHtml();
    if (!this._hass || !customElements.get("ha-form")) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (field) => this._labels()[field.name];
      this._form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        const { entity, name, language, tap_action, hold_action } = event.detail.value;
        const next = { ...this._config };
        // One region is `entity`; several are `entities` and make the card a list.
        const picked = (Array.isArray(entity) ? entity : [entity]).filter(Boolean);
        delete next.entity;
        delete next.entities;
        if (picked.length > 1) next.entities = picked;
        else if (picked.length === 1) next.entity = picked[0];
        // Empty fields and the "auto" language are defaults, not written into YAML.
        for (const [key, value] of Object.entries({ name, language })) {
          if (value && value !== "auto") next[key] = value; else delete next[key];
        }
        for (const [key, value] of Object.entries({ tap_action, hold_action })) {
          if (value && typeof value === "object") next[key] = value; else delete next[key];
        }
        this._config = next;
        this._emit({});
      });
      this.querySelector(".form").appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = [
      { name: "entity", selector: { entity: { multiple: true, filter: [{ integration: DOMAIN, domain: "binary_sensor", device_class: "safety" }] } } },
      { name: "name", selector: { text: {} } },
      { name: "language", selector: { select: { mode: "dropdown", options: Object.entries(l.languages).map(([value, label]) => ({ value, label })) } } },
      { name: "tap_action", selector: { ui_action: {} } },
      { name: "hold_action", selector: { ui_action: {} } },
    ];
    this._form.data = { entity: this._config.entities || (this._config.entity ? [this._config.entity] : []),
      name: this._config.name, language: this._config.language || "auto",
      tap_action: this._config.tap_action, hold_action: this._config.hold_action };
  }
}

const EDITOR_CSS = `
  .form { margin-bottom: 12px; }
  .note:not(:empty) { margin: -4px 0 12px; font-size: 13px; color: var(--secondary-text-color); }
  .top { display: flex; align-items: center; justify-content: space-between; margin: 0 0 6px; }
  .top button { border: 0; background: none; color: var(--primary-color); font: inherit; cursor: pointer; }
  .row { display: flex; align-items: center; gap: 4px; min-height: 44px; border-bottom: 1px solid var(--divider-color); }
  .row label { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; cursor: pointer; }
  .row input { flex: none; width: 20px; height: 20px; margin: 0; accent-color: var(--primary-color); }
  .row span { display: flex; flex-direction: column; } .row small { color: var(--secondary-text-color); }
  .row.off span { opacity: .55; }
  .row button { display: flex; width: 40px; height: 40px; align-items: center; justify-content: center; border: 0;
    border-radius: 50%; background: none; color: var(--primary-text-color); cursor: pointer; }
  .row button:disabled { opacity: .25; cursor: default; }
  .row button.open { color: var(--primary-color); }
  .items { display: flex; flex-wrap: wrap; gap: 4px 14px; padding: 6px 0 10px 30px; border-bottom: 1px solid var(--divider-color); }
  .items label { display: flex; align-items: center; gap: 6px; min-height: 32px; cursor: pointer; }
  .items input { flex: none; width: 18px; height: 18px; margin: 0; accent-color: var(--primary-color); }
`;

// Loaded as an early "extra module": the frontend can swap its element registry
// after that, dropping a definition made too soon. Re-check for a while so the
// card always ends up defined in the registry the dashboards actually use.
function register() {
  if (!window.customElements.get(CARD)) window.customElements.define(CARD, UkraineAlarmProCard);
  if (!window.customElements.get(`${CARD}-editor`)) window.customElements.define(`${CARD}-editor`, UkraineAlarmProCardEditor);
}
register();
// Frequent at first, then sparse: a slow phone can finish booting late.
let registerChecks = 0;
const registerTimer = setInterval(() => {
  register();
  if (++registerChecks >= 600) clearInterval(registerTimer);
}, 200);

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD)) {
  window.customCards.push({
    type: CARD,
    name: "Ukraine Alarm Pro",
    description: "Air raid alerts for one region: pick, hide and reorder status, details, timeline and statistics.",
    preview: true,
    documentationURL: "https://github.com/ABovsh/ukraine-alarm-pro",
  });
}
