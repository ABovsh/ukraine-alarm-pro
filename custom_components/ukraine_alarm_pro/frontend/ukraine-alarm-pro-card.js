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
    fresh: "Дані актуальні",
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
    now: "зараз",
    noAlerts: "без тривог",
    quietFor: "без тривог з",
    longest: "Найдовша",
    average: "Середня",
    ongoing: "триває",
    journalSince: "дані з",
    gaps: "були перерви в даних",
    incomplete: "Неповна статистика",
    plural: ["тривога", "тривоги", "тривог"],
  },
  en: {
    alert: "Alert",
    quiet: "All quiet",
    noData: "No data yet",
    stale: "No fresh data",
    staleNote: "Data is stale — the state may be outdated",
    fresh: "Data is current",
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
    now: "now",
    noAlerts: "no alerts",
    quietFor: "no alerts since",
    longest: "Longest",
    average: "Average",
    ongoing: "ongoing",
    journalSince: "data since",
    gaps: "data had gaps",
    incomplete: "Incomplete statistics",
    plural: ["alert", "alerts", "alerts"],
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

const LAYOUTS = new Set(["full", "status", "compact"]);
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
function patchDOM(root, html) {
  if (typeof document === "undefined") { root.innerHTML = html; return; }
  const template = document.createElement("template");
  template.innerHTML = html;
  function patch(parent, incoming) {
    const next = [...incoming.childNodes];
    for (let i = 0; i < next.length; i++) {
      let old = parent.childNodes[i];
      const node = next[i];
      if (!old || old.nodeType !== node.nodeType || old.nodeName !== node.nodeName) {
        const replacement = node.cloneNode(true);
        if (old) parent.replaceChild(replacement, old); else parent.appendChild(replacement);
        continue;
      }
      if (node.nodeType === 3) {
        if (old.nodeValue !== node.nodeValue) old.nodeValue = node.nodeValue;
      } else if (node.nodeType === 1) {
        for (const attr of [...old.attributes]) if (!node.hasAttribute(attr.name)) old.removeAttribute(attr.name);
        for (const attr of [...node.attributes]) if (old.getAttribute(attr.name) !== attr.value) old.setAttribute(attr.name, attr.value);
        patch(old, node);
      }
    }
    while (parent.childNodes.length > next.length) parent.lastChild.remove();
  }
  patch(root, template.content);
}

const hhmm = (date, hass) =>
  date.toLocaleTimeString(hass?.locale?.language || undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: hass?.config?.time_zone || undefined,
  });

class UkraineAlarmProCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          selector: { entity: { filter: [{ integration: DOMAIN, domain: "binary_sensor", device_class: "safety" }] } },
        },
        { name: "name", selector: { text: {} } },
        {
          name: "layout",
          selector: {
            select: {
              mode: "list",
              options: [
                { value: "full", label: "Full: status and statistics / Повний: стан і статистика" },
                { value: "status", label: "Status only / Лише стан" },
                { value: "compact", label: "Compact: one row / Компактний: один рядок" },
              ],
            },
          },
        },
        {
          name: "language",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "auto", label: "Auto / Як у Home Assistant" },
                { value: "uk", label: "Українська" },
                { value: "en", label: "English" },
              ],
            },
          },
        },
      ],
      computeLabel: (schema) =>
        ({
          entity: "Region / Регіон",
          name: "Name / Назва",
          layout: "Layout / Вигляд",
          language: "Language / Мова",
        })[schema.name],
    };
  }

  static getStubConfig(hass) {
    const [first] = alertEntities(hass);
    return first ? { entity: first } : {};
  }

  setConfig(config) {
    // One layout choice instead of switches that can contradict each other.
    this._config = { ...config, layout: LAYOUTS.has(config.layout) ? config.layout : "full" };
    this._stats = null;
    this._key = null;
    this._generation = (this._generation || 0) + 1;
    this._entityCache = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
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
    return { compact: 1, status: 3, full: 4 }[this._config?.layout] ?? 4;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  _statsOn() {
    return this._config.layout === "full";
  }

  // Statistics come from the journal services: fetched again after every alert
  // event, and on a timer so ongoing durations and the 24 h window move.
  _maybeRefresh() {
    if (!this._hass || !this._config || this._loading || !this._visible()) return;
    const ids = this._entities();
    const rid = ids && regionIdOf(this._hass, ids.alert);
    if (!rid) return;
    const full = this._statsOn();
    // An active compact/status card gets its start time directly from states.
    if (!full && this._hass.states[ids.alert].state === "on") return;
    if (this._statsFailed?.rid === rid && Date.now() - this._statsFailed.at < STATS_RETRY) return;
    const event = ids.event ? this._hass.states[ids.event] : undefined;
    const percentages = [ids.percentage24h, ids.percentage7d].map((id) => this._hass.states[id]?.last_updated).join("|");
    const trigger = `${rid}|${event?.state}|${this._hass.states[ids.alert].state}|${percentages}`;
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
        Object.values(cached.ids).filter(Boolean).every((id) => hass.states[id])) return cached.ids;
    const alert = this._config.entity || alertEntities(hass)[0];
    if (!alert || !hass.states[alert]) return null;
    const rid = regionIdOf(hass, alert);
    const ids = {
      alert,
      threat: sibling(hass, "threat", rid),
      level: sibling(hass, "air_alert_level", rid),
      started: sibling(hass, "alert_started", rid),
      event: sibling(hass, "event", rid),
      stale: hub(hass, "data_stale"),
      updated: hub(hass, "last_update"),
      percentage24h: sibling(hass, "alert_percentage_24h", rid),
      percentage7d: sibling(hass, "alert_percentage_7d", rid),
    };
    this._entityCache = { registry: hass.entities, configured: this._config.entity, ids };
    return ids;
  }

  _stateKey() {
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

  _statsHtml(t, stats) {
    const fmt = this._fmt();
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
    const line = (result) => {
      if (!result?.coverage_complete || result.percentage === null) return result?.count
        ? `${t.incomplete} · ${alerts(t, result.count)} · ${span(t, result.observed_duration_seconds)}` : t.incomplete;
      const pct = result.percentage.toLocaleString(fmt.locale.language, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
      return `${alerts(t, result.count)} · ${span(t, result.observed_duration_seconds)} · ${pct}${t === I18N.en ? "%" : " %"}`;
    };
    // Complete 24 h union supplied by the same calculation as the sensors.
    const intervals = day?.intervals || [];
    const hi = dateOf(summary?.rolling_calculated_at)?.getTime() || Date.now();
    const lo = hi - 86400000;
    const segments = intervals.map((interval) => {
      const from = Math.max(dateOf(interval.start)?.getTime() || lo, lo);
      const to = Math.min(dateOf(interval.end)?.getTime() || hi, hi);
      const left = ((from - lo) / 86400000) * 100;
      const width = Math.max(((to - from) / 86400000) * 100, 0.2);
      const title = `${hhmm(new Date(from), fmt)}–${hhmm(new Date(to), fmt)} · ${span(t, (to-from)/1000)}`;
      const level = ["red", "yellow"].includes(interval.maximum_air_level) ? interval.maximum_air_level : "other";
      return `<span class="seg ${level}${interval.ongoing ? " live" : ""}${interval.had_gap ? " gap" : ""}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" title="${esc(title)}"></span>`;
    }).join("");
    const ticks = [6, 12, 18].map((h) => `<span class="tick" style="left:${(h/24)*100}%"></span>`).join("");
    const incomplete = !day?.coverage_complete || !week?.coverage_complete;
    const extras = week?.count ? `${t.longest} ${span(t, week.longest_duration_seconds || 0)} · ${t.average} ${span(t, week.observed_duration_seconds / week.count)}` : "";
    return `<div class="stats">
      <div class="row"><span class="lbl">${esc(t.last24)}</span><div class="timeline${incomplete ? " incomplete" : ""}">${ticks}${segments}</div><b>${esc(line(day))}</b></div>
      <div class="row plain"><span class="lbl">${esc(t.week)}</span><b>${esc(line(week))}</b></div>
      ${extras ? `<div class="hint">${esc(extras)}</div>` : ""}
      ${incomplete ? `<div class="hint">${esc(t.incomplete)}${day?.quality === "gaps" || week?.quality === "gaps" ? ` · ${esc(t.gaps)}` : ""}</div>` : ""}
    </div>`;
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const t = lang(this._hass, this._config.language);
    const ids = this._entities();
    if (!ids) {
      patchDOM(this.shadowRoot, `${STYLE}<ha-card><div class="empty">${esc(t.notFound)}</div></ha-card>`);
      return;
    }
    const view = this._view(t, ids);
    const compact = this._config.layout === "compact";
    const region = compact ? `${esc(view.name)}${levelSuffix(t, view)}` : esc(view.name);
    const body = compact ? "" : this._bodyHtml(t, view);
    patchDOM(this.shadowRoot, `${STYLE}
      <ha-card class="${view.status}${compact ? " compact" : ""}" tabindex="0" role="button" aria-label="${esc(view.name)}: ${esc(view.title)}">
        <div class="glow"></div>
        <div class="head">
          <div class="badge"><span class="pulse"></span><ha-icon icon="${STATUS_ICONS[view.status]}"></ha-icon></div>
          <div class="titles">
            <div class="region">${region}</div>
            <div class="status">${esc(view.title)}</div>
          </div>
          ${this._timerHtml(t, view)}
        </div>
        ${body}
      </ha-card>`);
    const card = this.shadowRoot.querySelector("ha-card");
    if (this._eventCard !== card) {
      this._eventCard = card;
      const open = () => { const id = this._entities()?.alert; if (id) this._moreInfo(id); };
      card.addEventListener("click", open);
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
      });
    }
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
    if (view.noData || view.stale || !view.journal) return "";
    const cleared = dateOf(view.journal.episodes.find((ep) => ep.observed_cleared_at)?.observed_cleared_at);
    if (!cleared) return "";
    const day = Date.now() - cleared > 86400000 ? dayMonth(cleared, fmt) : "";
    return `<div class="timer quiet"><div class="big">${esc(duration(t, cleared))}</div><div class="small">${esc(t.quietFor)} ${esc(day)} ${esc(hhmm(cleared, fmt))}</div></div>`;
  }

  _chips(t, view) {
    if (!view.active) return [];
    const chips = view.types
      .slice(1)
      .map((type) => chip(TYPE_ICONS[type] || TYPE_ICONS.unrecognized, t.types[type] || type));
    const levelText = t.level[view.air];
    if (levelText) chips.push(`<span class="chip level ${esc(view.air)}"><span class="dot"></span>${esc(levelText)}</span>`);
    const coverage = view.threat?.attributes?.coverage;
    if (coverage === "whole") chips.push(chip("mdi:map", t.whole));
    if (coverage === "unrecognized") chips.push(chip("mdi:map-search", t.unknownCoverage));
    if (coverage === "partial") {
      const areas = (view.threat.attributes.affected_regions || []).map((r) => r.region_name).filter(Boolean);
      const listed = areas.length > 3 ? `${areas.slice(0, 3).join(", ")}…` : areas.join(", ");
      chips.push(chip("mdi:map-marker-radius", areas.length ? `${t.partial}: ${listed}` : t.partial));
    }
    return chips;
  }

  _freshness(t, view) {
    if (view.stale) return t.staleNote;
    const updated = dateOf(known(view.updated)?.state);
    return updated ? `${t.fresh} · ${t.updated} ${hhmm(updated, this._fmt())}` : t.fresh;
  }

  _bodyHtml(t, view) {
    const chips = this._chips(t, view);
    const reasons = view.active ? (view.level?.attributes?.reasons || []).join(" · ") : "";
    const stats = this._statsOn() ? view.journal : null;
    const parts = [
      chips.length ? `<div class="chips">${chips.join("")}</div>` : "",
      reasons ? `<div class="reasons">${esc(reasons)}</div>` : "",
      stats ? this._statsHtml(t, stats) : "",
      `<div class="foot">
            <span class="fresh ${view.stale ? "bad" : "ok"}"><span class="dot"></span>${esc(this._freshness(t, view))}</span>
          </div>`,
    ];
    return `
          ${parts.join("\n")}`;
  }
}

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

// In the compact layout the level sits next to the region name.
function levelSuffix(t, view) {
  const text = view.active && t.level[view.air];
  return text ? ` · <span class="lvl ${esc(view.air)}">${esc(text)}</span>` : "";
}

const STYLE = `<style>
  :host { --uap-red: #e5393b; --uap-yellow: #f2a900; --uap-green: #2e9d57; --uap-gray: #8a8f98; }
  ha-card { position: relative; overflow: hidden; padding: 12px 14px; cursor: pointer; --accent: var(--uap-green);
    container-type: inline-size; }
  ha-card.red, ha-card.alert { --accent: var(--uap-red); }
  ha-card.yellow { --accent: var(--uap-yellow); }
  ha-card.stale, ha-card.nodata { --accent: var(--uap-gray); }
  .glow { position: absolute; inset: 0; pointer-events: none;
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 22%, transparent), transparent 65%); }
  ha-card.red .glow, ha-card.alert .glow, ha-card.yellow .glow {
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 34%, transparent), color-mix(in srgb, var(--accent) 6%, transparent) 70%); }
  .head { position: relative; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .badge { position: relative; flex: none; width: 44px; height: 44px; border-radius: 50%;
    display: grid; place-items: center; color: #fff; background: var(--accent);
    box-shadow: 0 4px 14px color-mix(in srgb, var(--accent) 45%, transparent); }
  .badge ha-icon { --mdc-icon-size: 24px; }
  .pulse { display: none; position: absolute; inset: 0; border-radius: 50%; border: 3px solid var(--accent); }
  ha-card.red .pulse, ha-card.alert .pulse, ha-card.yellow .pulse { display: block; animation: pulse 1.8s ease-out infinite; }
  @keyframes pulse { from { transform: scale(1); opacity: .8; } to { transform: scale(1.7); opacity: 0; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none !important; } }
  .titles { min-width: 0; flex: 1; }
  .region { font-size: 14px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .status { font-size: 18px; font-weight: 700; line-height: 1.2; color: var(--primary-text-color); }
  ha-card.red .status, ha-card.alert .status { color: var(--uap-red); }
  ha-card.yellow .status { color: color-mix(in srgb, var(--uap-yellow) 75%, var(--primary-text-color)); }
  .timer { text-align: right; flex: none; }
  .timer .big { font-size: 18px; white-space: nowrap; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
  .timer .small { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; }
  .chips { position: relative; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 999px; font-size: 12px;
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--primary-text-color); }
  .chip ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .chip .dot, .fresh .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .chip.level.yellow .dot { background: var(--uap-yellow); }
  .chip.level.red .dot { background: var(--uap-red); }
  .chip.level.unrecognized .dot { background: var(--uap-gray); }
  .reasons { position: relative; margin-top: 8px; font-size: 13px; color: var(--secondary-text-color);
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .foot { position: relative; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px;
    margin-top: 8px; padding-top: 6px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.2));
    font-size: 12px; color: var(--secondary-text-color); }
  .fresh { display: inline-flex; align-items: center; gap: 6px; }
  .fresh.ok .dot { background: var(--uap-green); }
  .fresh.bad { color: var(--uap-red); }
  .fresh.bad .dot { background: var(--uap-red); }
  ha-card.compact { padding: 12px 14px; }
  ha-card.compact .badge { width: 40px; height: 40px; }
  ha-card.compact .badge ha-icon { --mdc-icon-size: 22px; }
  ha-card.compact .status, ha-card.compact .timer .big { font-size: 17px; }
  .lvl.red { color: var(--uap-red); font-weight: 600; }
  .lvl.yellow { color: color-mix(in srgb, var(--uap-yellow) 75%, var(--primary-text-color)); font-weight: 600; }
  .timer.quiet .big { color: var(--uap-green); }
  .stats { position: relative; margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
  .row { display: grid; grid-template-columns: auto 1fr; grid-template-areas: "lbl val" "viz viz"; align-items: center; gap: 3px 10px; }
  .lbl { grid-area: lbl; } .row b { grid-area: val; } .timeline { grid-area: viz; }
  .row.plain { display: flex; justify-content: space-between; gap: 10px; }
  @container (min-width: 520px) {
    .row { grid-template-columns: 52px minmax(120px, 1fr) auto; grid-template-areas: "lbl viz val"; }
  }
  .lbl { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; }
  .row b { font-size: 12px; font-weight: 600; color: var(--primary-text-color); white-space: nowrap;
    font-variant-numeric: tabular-nums; text-align: right; }
  .timeline { position: relative; height: 12px; border-radius: 4px; overflow: hidden; }
  .timeline.incomplete { background: repeating-linear-gradient(45deg, rgba(127,127,127,.16) 0 4px, transparent 4px 8px); }
  ha-card:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  .timeline { background: color-mix(in srgb, var(--uap-green) 18%, transparent); }
  .tick { position: absolute; top: 0; bottom: 0; width: 1px; background: color-mix(in srgb, var(--primary-text-color) 12%, transparent); }
  .seg { position: absolute; top: 0; bottom: 0; background: var(--uap-red); }
  .seg.yellow { background: var(--uap-yellow); }
  .seg.other { background: color-mix(in srgb, var(--uap-red) 70%, var(--uap-gray)); }
  .seg.gap { background-image: repeating-linear-gradient(45deg, rgba(255,255,255,.35) 0 3px, transparent 3px 6px); }
  .seg.live { animation: live 1.8s ease-in-out infinite; }
  @keyframes live { 50% { opacity: .6; } }
  @media (prefers-reduced-motion: reduce) { .seg.live { animation: none; } }
  .hint { font-size: 11px; color: var(--secondary-text-color); }
  /* The timer keeps the right-hand column; only a very narrow card (a half-width
     tile on a phone) moves it under the title instead of colliding with it. */
  @container (max-width: 280px) {
    .head { column-gap: 12px; row-gap: 2px; }
    .timer { order: 3; flex-basis: 100%; display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 8px;
      text-align: left; padding-left: 56px; }
    ha-card.compact .timer { padding-left: 52px; }
    .status { font-size: 17px; }
    .timer .big { font-size: 16px; }
    .timer .small { white-space: normal; }
    /* Statistics values wrap under their label instead of being cut off. */
    .row, .row.plain { display: grid; grid-template-columns: 1fr; grid-template-areas: "lbl" "val" "viz"; }
    .row.plain { grid-template-areas: "lbl" "val"; }
    .row b { text-align: left; white-space: normal; }
  }
  .empty { padding: 8px; color: var(--secondary-text-color); }
</style>`;

// Loaded as an early "extra module": the frontend can swap its element registry
// after that, dropping a definition made too soon. Re-check for a while so the
// card always ends up defined in the registry the dashboards actually use.
function register() {
  if (!window.customElements.get(CARD)) window.customElements.define(CARD, UkraineAlarmProCard);
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
    description: "Alert status of one region: threat, level, duration, coverage and data freshness.",
    preview: true,
    documentationURL: "https://github.com/ABovsh/ukraine-alarm-pro",
  });
}
