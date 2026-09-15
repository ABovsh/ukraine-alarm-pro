/*
 * Ukraine Alarm Pro card — shipped with the integration, no HACS frontend
 * resource needed. Pick a region's alert sensor; with one region the card
 * finds it on its own. Durations tick in the browser, so nothing is written
 * to the recorder.
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
    events: {
      started: "почалася",
      escalated: "рівень підвищився",
      threat_added: "додалася загроза",
      updated: "оновлення",
      cleared: "відбій",
      data_stale: "дані застаріли",
      resynced: "синхронізовано",
    },
    lastEvent: "Остання подія",
    updated: "оновлено",
    quietNote: "Активних тривог немає",
    notFound: "Не знайдено сутностей Ukraine Alarm Pro",
    editor: { entity: "Регіон (сенсор тривоги)", name: "Назва (необов'язково)", compact: "Компактний вигляд" },
  },
  en: {
    alert: "Alert",
    quiet: "All quiet",
    noData: "No data yet",
    stale: "No fresh data",
    staleNote: "Data is stale — the state may be outdated",
    fresh: "Data is current",
    since: "since",
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
    events: {
      started: "started",
      escalated: "level raised",
      threat_added: "threat added",
      updated: "update",
      cleared: "all clear",
      data_stale: "data stale",
      resynced: "resynchronized",
    },
    lastEvent: "Last event",
    updated: "updated",
    quietNote: "No active alerts",
    notFound: "No Ukraine Alarm Pro entities found",
    editor: { entity: "Region (alert sensor)", name: "Name (optional)", compact: "Compact layout" },
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
    .sort();
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

function duration(t, from) {
  const minutes = Math.max(0, Math.floor((Date.now() - from.getTime()) / 60000));
  const h = Math.floor(minutes / 60);
  return h ? `${h} ${t.h} ${minutes % 60} ${t.m}` : `${minutes} ${t.m}`;
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
        { name: "compact", selector: { boolean: {} } },
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
        ({ entity: "Region / Регіон", name: "Name / Назва", compact: "Compact / Компактно", language: "Language / Мова" })[schema.name],
    };
  }

  static getStubConfig(hass) {
    const [first] = alertEntities(hass);
    return first ? { entity: first } : {};
  }

  setConfig(config) {
    this._config = { compact: false, ...config };
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
  }

  connectedCallback() {
    // Durations tick locally; state writes stay untouched.
    this._timer = setInterval(() => this._render(), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  getCardSize() {
    return this._config?.compact ? 1 : 3;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: this._config?.compact ? 1 : "auto" };
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

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    const hass = this._hass;
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
    const event = st(ids.event);
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

    const eventType = event?.attributes?.event_type;
    const eventTime = event && !["unknown", "unavailable"].includes(event.state) ? new Date(event.state) : null;
    const updatedDate = updated && !["unknown", "unavailable"].includes(updated.state) ? new Date(updated.state) : null;
    const freshness = stale ? t.staleNote : `${t.fresh}${updatedDate ? ` · ${t.updated} ${hhmm(updatedDate, hass)}` : ""}`;

    const compact = this._config.compact;
    this.shadowRoot.innerHTML = `${STYLE}
      <ha-card class="${status}${compact ? " compact" : ""}" tabindex="0">
        <div class="glow"></div>
        <div class="head">
          <div class="badge"><span class="pulse"></span><ha-icon icon="${icon}"></ha-icon></div>
          <div class="titles">
            <div class="region">${esc(name)}${compact && active && t.level[air] ? ` · <span class="lvl ${esc(air)}">${esc(t.level[air])}</span>` : ""}</div>
            <div class="status">${esc(title)}</div>
          </div>
          ${since ? `<div class="timer"><div class="big">${esc(duration(t, since))}</div><div class="small">${esc(t.since)} ${esc(hhmm(since, hass))}</div></div>` : ""}
        </div>
        ${compact ? "" : `
          ${chips.length ? `<div class="chips">${chips.join("")}</div>` : ""}
          ${reasons ? `<div class="reasons">${esc(reasons)}</div>` : ""}
          ${!active && !noData && !stale ? `<div class="note">${esc(t.quietNote)}</div>` : ""}
          <div class="foot">
            <span class="fresh ${stale ? "bad" : "ok"}"><span class="dot"></span>${esc(freshness)}</span>
            ${eventType && eventTime && !isNaN(eventTime) ? `<span class="event">${esc(t.lastEvent)}: ${esc(t.events[eventType] || eventType)} ${esc(hhmm(eventTime, hass))}</span>` : ""}
          </div>`}
      </ha-card>`;
    const card = this.shadowRoot.querySelector("ha-card");
    card.addEventListener("click", () => this._moreInfo(ids.alert));
  }
}

const STYLE = `<style>
  :host { --uap-red: #e5393b; --uap-yellow: #f2a900; --uap-green: #2e9d57; --uap-gray: #8a8f98; }
  ha-card { position: relative; overflow: hidden; padding: 16px; cursor: pointer; --accent: var(--uap-green);
    container-type: inline-size; }
  ha-card.red, ha-card.alert { --accent: var(--uap-red); }
  ha-card.yellow { --accent: var(--uap-yellow); }
  ha-card.stale, ha-card.nodata { --accent: var(--uap-gray); }
  .glow { position: absolute; inset: 0; pointer-events: none;
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 22%, transparent), transparent 65%); }
  ha-card.red .glow, ha-card.alert .glow, ha-card.yellow .glow {
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 34%, transparent), color-mix(in srgb, var(--accent) 6%, transparent) 70%); }
  .head { position: relative; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
  .badge { position: relative; flex: none; width: 52px; height: 52px; border-radius: 50%;
    display: grid; place-items: center; color: #fff; background: var(--accent);
    box-shadow: 0 4px 14px color-mix(in srgb, var(--accent) 45%, transparent); }
  .badge ha-icon { --mdc-icon-size: 28px; }
  .pulse { display: none; position: absolute; inset: 0; border-radius: 50%; border: 3px solid var(--accent); }
  ha-card.red .pulse, ha-card.alert .pulse, ha-card.yellow .pulse { display: block; animation: pulse 1.8s ease-out infinite; }
  @keyframes pulse { from { transform: scale(1); opacity: .8; } to { transform: scale(1.7); opacity: 0; } }
  @media (prefers-reduced-motion: reduce) { .pulse { animation: none !important; } }
  .titles { min-width: 0; flex: 1; }
  .region { font-size: 14px; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .status { font-size: 20px; font-weight: 700; line-height: 1.2; color: var(--primary-text-color); }
  ha-card.red .status, ha-card.alert .status { color: var(--uap-red); }
  ha-card.yellow .status { color: color-mix(in srgb, var(--uap-yellow) 75%, var(--primary-text-color)); }
  .timer { text-align: right; flex: none; }
  .timer .big { font-size: 20px; white-space: nowrap; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
  .timer .small { font-size: 12px; color: var(--secondary-text-color); }
  .chips { position: relative; display: flex; flex-wrap: wrap; gap: 6px; margin-top: 14px; }
  .chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px; font-size: 13px;
    background: color-mix(in srgb, var(--primary-text-color) 7%, transparent); color: var(--primary-text-color); }
  .chip ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .chip .dot, .fresh .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .chip.level.yellow .dot { background: var(--uap-yellow); }
  .chip.level.red .dot { background: var(--uap-red); }
  .chip.level.unrecognized .dot { background: var(--uap-gray); }
  .reasons { position: relative; margin-top: 10px; font-size: 13px; color: var(--secondary-text-color);
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .note { position: relative; margin-top: 10px; font-size: 13px; color: var(--secondary-text-color); }
  .foot { position: relative; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px;
    margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.2));
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
      text-align: left; padding-left: 64px; }
    ha-card.compact .timer { padding-left: 52px; }
    .status { font-size: 19px; }
    .timer .big { font-size: 17px; }
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
