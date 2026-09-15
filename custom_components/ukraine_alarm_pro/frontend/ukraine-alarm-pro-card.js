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
    quietNote: "Активних тривог немає",
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
    quietNote: "No active alerts",
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

const lang = (hass, forced) =>
  (forced === "uk" || forced === "en" ? forced : hass?.locale?.language || hass?.language || "en").startsWith("uk")
    ? I18N.uk
    : I18N.en;

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
    if (!entry || entry.platform !== DOMAIN || entry.translation_key !== key) return false;
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

function alerts(t, n) {
  if (t === I18N.en) return `${n} ${n === 1 ? t.plural[0] : t.plural[1]}`;
  const mod10 = n % 10;
  const mod100 = n % 100;
  const form = mod10 === 1 && mod100 !== 11 ? 0 : mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? 1 : 2;
  return `${n} ${t.plural[form]}`;
}

const dateOf = (stamp) => {
  const date = stamp ? new Date(stamp) : null;
  return date && !isNaN(date) ? date : null;
};

const dayMonth = (date, hass) =>
  date.toLocaleDateString(hass?.locale?.language || undefined, {
    day: "2-digit",
    month: "2-digit",
    timeZone: hass?.config?.time_zone || undefined,
  });

const LAYOUTS = ["full", "status", "compact"];
const STATS_FRESH_ACTIVE = 60000;
const STATS_FRESH_QUIET = 600000;
// A failed call (a reconnect, a restart, an older integration) is retried, not final.
const STATS_RETRY = 120000;

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
    this._config = { ...config, layout: LAYOUTS.includes(config.layout) ? config.layout : "full" };
    this._stats = null;
    this._key = null;
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
    // Durations tick locally; state writes stay untouched.
    this._timer = setInterval(() => {
      this._maybeRefresh();
      this._render();
    }, 30000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
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
    // Every layout needs the journal for the time since the last all clear.
    if (!this._hass || !this._config || this._loading || !this.isConnected) return;
    const ids = this._entities();
    const rid = ids && regionIdOf(this._hass, ids.alert);
    if (!rid) return;
    if (this._statsFailed?.rid === rid && Date.now() - this._statsFailed.at < STATS_RETRY) return;
    const event = ids.event ? this._hass.states[ids.event] : undefined;
    const trigger = `${rid}|${event?.state}|${this._hass.states[ids.alert].state}`;
    const age = this._stats ? Date.now() - this._stats.fetched : Infinity;
    const maxAge = this._hass.states[ids.alert].state === "on" ? STATS_FRESH_ACTIVE : STATS_FRESH_QUIET;
    if (this._stats?.trigger === trigger && age < maxAge) return;
    this._loading = true;
    const call = (service, data) =>
      this._hass
        .callWS({ type: "call_service", domain: DOMAIN, service, service_data: { region_id: rid, ...data }, return_response: true })
        .then((result) => result.response);
    Promise.all([call("get_summary", { days: 7 }), call("get_history", { limit: 50 })])
      .then(([summary, history]) => {
        this._stats = { rid, trigger, fetched: Date.now(), summary, episodes: history.episodes || [] };
        this._statsFailed = null;
      })
      .catch(() => {
        // The card works without statistics until a later attempt succeeds.
        this._statsFailed = { rid, at: Date.now() };
      })
      .finally(() => {
        this._loading = false;
        this._render();
      });
  }

  _entities() {
    const hass = this._hass;
    const alert = this._config.entity || alertEntities(hass)[0];
    if (!alert || !hass.states[alert]) return null;
    const rid = regionIdOf(hass, alert);
    return {
      alert,
      threat: sibling(hass, "threat", rid),
      level: sibling(hass, "air_alert_level", rid),
      started: sibling(hass, "alert_started", rid),
      event: sibling(hass, "event", rid),
      stale: hub(hass, "data_stale"),
      updated: hub(hass, "last_update"),
    };
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
    const forced = this._config.language;
    const language = forced === "uk" || forced === "en" ? forced : this._hass.locale?.language || this._hass.language;
    return { locale: { language }, config: this._hass.config };
  }

  _statsHtml(t, stats) {
    const fmt = this._fmt();
    const now = Date.now();
    const dayAgo = now - 86400000;
    const { summary } = stats;
    const journalStart = dateOf(summary?.coverage_start)?.getTime() ?? 0;
    const episodes = stats.episodes
      .map((ep) => ({ ...ep, start: dateOf(ep.observed_started_at), end: dateOf(ep.observed_cleared_at) }))
      .filter((ep) => ep.start);
    // Share of the time the journal actually covered, not of time it did not exist.
    const share = (seconds, from) => {
      const covered = (now - Math.max(from, journalStart)) / 1000;
      if (covered <= 0) return "";
      const pct = Math.min((seconds / covered) * 100, 100);
      return pct.toLocaleString(fmt.locale.language, { maximumFractionDigits: pct < 10 ? 1 : 0 }) + (t === I18N.en ? "%" : " %");
    };
    const line = (count, seconds, from) =>
      count ? [alerts(t, count), span(t, seconds), share(seconds, from)].filter(Boolean).join(" · ") : t.noAlerts;

    // Rolling 24 h: absolute times, so the browser's zone does not matter.
    const recent = episodes.filter((ep) => (ep.end ? ep.end.getTime() : now) > dayAgo);
    const recentSeconds = recent.reduce(
      (sum, ep) => sum + Math.max(0, ((ep.end ? ep.end.getTime() : now) - Math.max(ep.start.getTime(), dayAgo)) / 1000),
      0,
    );
    const segments = recent
      .map((ep) => {
        const from = Math.max(ep.start.getTime(), dayAgo);
        const to = ep.end ? ep.end.getTime() : now;
        const left = ((from - dayAgo) / 86400000) * 100;
        const width = Math.max(((to - from) / 86400000) * 100, 0.8);
        const level = ["red", "yellow"].includes(ep.maximum_air_level) ? ep.maximum_air_level : "other";
        const title = `${hhmm(new Date(from), fmt)}–${ep.end ? hhmm(ep.end, fmt) : t.now} · ${span(t, (to - from) / 1000)}`;
        return `<span class="seg ${level}${ep.end ? "" : " live"}${ep.had_gap ? " gap" : ""}" style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" title="${esc(title)}"></span>`;
      })
      .join("");
    const ticks = [6, 12, 18].map((h) => `<span class="tick" style="left:${(h / 24) * 100}%"></span>`).join("");

    // 7 calendar days from the server, in Home Assistant's own time zone.
    const weekCount = summary?.count ?? 0;
    const periodStart = dateOf(summary?.period_start)?.getTime() ?? now - 7 * 86400000;

    const extras = [];
    if (weekCount) {
      extras.push(`${t.longest} ${span(t, summary.longest_duration_seconds || 0)}`);
      extras.push(`${t.average} ${span(t, (summary.observed_duration_seconds || 0) / weekCount)}`);
    }
    if (journalStart > now - 7 * 86400000) {
      extras.push(`${t.journalSince} ${dayMonth(new Date(journalStart), fmt)}`);
    }
    if (summary?.has_gaps || recent.some((ep) => ep.had_gap)) extras.push(t.gaps);

    return `<div class="stats">
      <div class="row"><span class="lbl">${esc(t.last24)}</span><div class="timeline">${ticks}${segments}</div><b>${esc(line(recent.length, recentSeconds, dayAgo))}</b></div>
      ${summary ? `<div class="row plain"><span class="lbl">${esc(t.week)}</span><b>${esc(line(weekCount, summary.observed_duration_seconds, periodStart))}</b></div>` : ""}
      ${extras.length ? `<div class="hint">${extras.map(esc).join(" · ")}</div>` : ""}
    </div>`;
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const hass = this._hass;
    const fmt = this._fmt();
    const t = lang(hass, this._config.language);
    const ids = this._entities();
    if (!ids) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card><div class="empty">${esc(t.notFound)}</div></ha-card>`;
      return;
    }
    const st = (id) => (id ? hass.states[id] : undefined);
    const alert = st(ids.alert);
    const threat = st(ids.threat);
    const level = st(ids.level);
    const started = st(ids.started);
    const stale = st(ids.stale)?.state === "on";
    const updated = st(ids.updated);

    const name = this._config.name || threat?.attributes?.region_name || alert.attributes.friendly_name;
    const active = alert.state === "on";
    const noData = ["unavailable", "unknown"].includes(alert.state);
    const types = String(threat?.attributes?.active_threat_types || "")
      .split(",")
      .filter(Boolean);
    const air = level?.state;
    const status = noData ? "nodata" : active ? (air === "red" ? "red" : air === "yellow" ? "yellow" : "alert") : stale ? "stale" : "quiet";
    const icon = { red: "mdi:alarm-light", yellow: "mdi:alarm-light", alert: "mdi:alarm-light", quiet: "mdi:shield-check", stale: "mdi:cloud-off-outline", nodata: "mdi:timer-sand" }[status];

    const title = noData ? t.noData : active ? t.types[types[0]] || t.alert : stale ? t.stale : t.quiet;
    const startDate = started && !["unknown", "unavailable"].includes(started.state) ? new Date(started.state) : null;
    const since = active && startDate && !isNaN(startDate) ? startDate : null;
    const journal = this._stats?.rid === regionIdOf(hass, ids.alert) ? this._stats : null;
    const stats = this._statsOn() ? journal : null;
    const lastCleared = !active && !noData && !stale && journal ? dateOf(journal.episodes.find((ep) => ep.observed_cleared_at)?.observed_cleared_at) : null;

    const chips = [];
    if (active) {
      types.slice(active ? 1 : 0).forEach((type) =>
        chips.push(`<span class="chip"><ha-icon icon="${TYPE_ICONS[type] || TYPE_ICONS.unrecognized}"></ha-icon>${esc(t.types[type] || type)}</span>`),
      );
      if (t.level[air]) chips.push(`<span class="chip level ${esc(air)}"><span class="dot"></span>${esc(t.level[air])}</span>`);
      const coverage = threat?.attributes?.coverage;
      if (coverage === "whole") chips.push(`<span class="chip"><ha-icon icon="mdi:map"></ha-icon>${esc(t.whole)}</span>`);
      if (coverage === "partial") {
        const areas = (threat.attributes.affected_regions || []).map((r) => r.region_name).filter(Boolean);
        chips.push(`<span class="chip"><ha-icon icon="mdi:map-marker-radius"></ha-icon>${esc(t.partial)}${areas.length ? `: ${esc(areas.slice(0, 3).join(", "))}${areas.length > 3 ? "…" : ""}` : ""}</span>`);
      }
      if (coverage === "unrecognized") chips.push(`<span class="chip"><ha-icon icon="mdi:map-search"></ha-icon>${esc(t.unknownCoverage)}</span>`);
    }
    const reasons = active ? (level?.attributes?.reasons || []).join(" · ") : "";

    const updatedDate = updated && !["unknown", "unavailable"].includes(updated.state) ? new Date(updated.state) : null;
    const freshness = stale ? t.staleNote : `${t.fresh}${updatedDate ? ` · ${t.updated} ${hhmm(updatedDate, fmt)}` : ""}`;

    const compact = this._config.layout === "compact";
    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card class="${status}${compact ? " compact" : ""}" tabindex="0">
        <div class="glow"></div>
        <div class="head">
          <div class="badge"><span class="pulse"></span><ha-icon icon="${icon}"></ha-icon></div>
          <div class="titles">
            <div class="region">${esc(name)}${compact && active && t.level[air] ? ` · <span class="lvl ${esc(air)}">${esc(t.level[air])}</span>` : ""}</div>
            <div class="status">${esc(title)}</div>
          </div>
          ${since ? `<div class="timer"><div class="big">${esc(duration(t, since))}</div><div class="small">${esc(t.since)} ${esc(hhmm(since, fmt))}</div></div>` : ""}
          ${lastCleared ? `<div class="timer quiet"><div class="big">${esc(duration(t, lastCleared))}</div><div class="small">${esc(t.quietFor)} ${esc(Date.now() - lastCleared > 86400000 ? dayMonth(lastCleared, fmt) : "")} ${esc(hhmm(lastCleared, fmt))}</div></div>` : ""}
        </div>
        ${compact ? "" : `
          ${chips.length ? `<div class="chips">${chips.join("")}</div>` : ""}
          ${reasons ? `<div class="reasons">${esc(reasons)}</div>` : ""}
          ${!active && !noData && !stale && !stats ? `<div class="note">${esc(t.quietNote)}</div>` : ""}
          ${stats ? this._statsHtml(t, stats) : ""}
          <div class="foot">
            <span class="fresh ${stale ? "bad" : "ok"}"><span class="dot"></span>${esc(freshness)}</span>
          </div>`}
      </ha-card>`;
    const card = this.shadowRoot.querySelector("ha-card");
    card.addEventListener("click", () => this._moreInfo(ids.alert));
  }
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
  .timer .small { font-size: 12px; color: var(--secondary-text-color); }
  .chips { position: relative; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: 999px; font-size: 12px;
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--primary-text-color); }
  .chip ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .chip .dot, .fresh .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .chip.level.yellow .dot { background: var(--uap-yellow); }
  .chip.level.red .dot { background: var(--uap-red); }
  .chip.level.unrecognized .dot { background: var(--uap-gray); }
  .reasons { position: relative; margin-top: 8px; font-size: 13px; color: var(--secondary-text-color);
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .note { position: relative; margin-top: 10px; font-size: 13px; color: var(--secondary-text-color); }
  .foot { position: relative; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px;
    margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.2));
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
  /* Narrow card (phone): the timer moves under the title instead of colliding with it. */
  @container (max-width: 420px) {
    .head { column-gap: 12px; row-gap: 2px; }
    .timer { order: 3; flex-basis: 100%; display: flex; align-items: baseline; gap: 8px;
      text-align: left; padding-left: 56px; }
    ha-card.compact .timer { padding-left: 52px; }
    .status { font-size: 17px; }
    .timer .big { font-size: 16px; }
  }
  .timer.quiet .big { color: var(--uap-green); }
  .stats { position: relative; margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
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
