# Changelog

All notable changes to this project are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-08-08

### ✨ Added

- **Deselecting a region now deletes its entities.** The region list has always
  been editable from **Settings → Devices & services → Ukraine Alarm Pro →
  Configure**, but Home Assistant keeps registry entries for entities a platform
  stopped creating: a removed region left `sensor.uap_<id>_threat` and
  `binary_sensor.uap_<id>_alert` behind as permanently unavailable entities that
  had to be hunted down in the entity registry by hand. Setup now purges the
  entities of regions that are no longer selected.

## [0.5.1] - 2026-08-08

### 🐛 Fixed

- **The staleness tick republished unchanged state every minute.** 0.5.0 stopped
  the coordinator from notifying entities on an unchanged alert map, but the
  60 s tick that ages the staleness verdict still called
  `async_write_ha_state()` unconditionally. Because `last_update` moves on every
  push, each tick landed a fresh recorder row — `binary_sensor.uap_data_stale`
  and `sensor.uap_last_update` were still writing ~1,700 rows/day each on a
  perfectly healthy feed (measured 2026-08-08). The tick now publishes only when
  the stale/healthy verdict actually changes.

## [0.5.0] - 2026-08-08

### 🐛 Fixed

- **Entities wrote state on every feed republish.** The alert feed resends the
  same alert map every ~2.6 s; each resend updated all entities, which put
  ~65,000 rows/day into the recorder database (measured 2026-08-07) —
  `sensor.uap_last_update` and `binary_sensor.uap_data_stale` alone accounted
  for it. The coordinator now compares the incoming alert map against the
  current one and only notifies entities when it actually changed. The
  liveness clock still advances on every push, so staleness detection is
  unchanged.

## [0.4.0] - 2026-07-26

### ✨ Added

- **`active_threat_types` attribute on the threat sensor.** Comma-separated
  list of every distinct active threat type for the region, most severe
  first (e.g. `artillery,air`). Empty string when no alert is active.

## [0.3.0] - 2026-07-25

### 🐛 Fixed

- **Alert state was blank for minutes after every restart.** The alert feed sends no
  history when it connects — it only publishes when something changes somewhere in the
  country, which was measured at over two minutes on a quiet day. The current alert map is
  now fetched right away, so the entities are populated a couple of seconds after startup.
- **A calm country could be mistaken for a broken connection.** The watchdog dropped the
  connection after 15 quiet minutes even when nothing was wrong. It now cross-checks the
  alert map first and only reconnects when the connection really did miss updates — and
  the cross-check itself keeps the data fresh, so `binary_sensor.uap_data_stale` no longer
  turns on during a quiet night.
- **A healthy connection could fall back to polling.** The server recycles long-lived
  connections (its access token lasts two hours); three of those recycles in a row were
  counted as failures and pushed the integration onto the slower polling fallback.
- **A feed response the integration cannot make sense of no longer reads as an all-clear.**
  An unexpected payload is now handled as a transport failure — it reconnects or falls back
  instead of silently clearing every region.

### ✨ Added

- **Ukrainian interface.** The configuration dialog, the options dialog, the repair message,
  the threat states and every entity name are now translated — Home Assistant picks the
  language from your profile. A Ukrainian README is available at
  [README.uk.md](README.uk.md).

### 🔧 Changed

- Entity names come from the translation files instead of being fixed English strings.
  Entity IDs are unchanged; names you set yourself are unaffected.
- `binary_sensor.uap_data_stale` reports the time of the last update instead of a
  seconds-since counter, which used to write a database row every minute forever. The age
  is still available on `sensor.uap_last_update` and in diagnostics.

## [0.2.0] - 2026-07-25

### 🐛 Fixed

- **Alerts declared below the selected region were invisible.** Alerts are published at
  whichever administrative level they were declared at, so an oblast entity stayed "no
  alert" while its raions were under an air raid — at the time of writing that affected 6
  of 29 oblasts simultaneously. Regions now also inherit alerts from their descendants.
  Existing configurations are upgraded automatically on the next restart.
- Duplicate alerts in the feed are no longer listed twice in the `active_alerts` attribute.
- A manual `homeassistant.update_entity` no longer raises an error in the log.
- The WebSocket read loop now reports a clean transport error instead of an unexpected
  internal error when the connection is closed underneath it.
- A malformed or self-referential region tree can no longer crash the configuration flow.
- Upgrading an older configuration no longer waits for the region endpoint during startup —
  it runs in the background, so an unreachable endpoint cannot slow down every restart.
- The watchdog no longer claims to restart the polling transport (it only ever restarted the
  WebSocket); while polling, it now reports that the feed itself is unavailable.

### ✨ Added

- **Feed watchdog.** A WebSocket that stays connected but stops publishing is now detected
  after 15 minutes and restarted, instead of serving a frozen alert map indefinitely.
- **`binary_sensor.uap_data_stale`** (diagnostic, problem class) — on when no update has
  arrived for 15 minutes, with the age of the last update in its attributes.
- **Repair issue** when the integration falls back to polling, cleared on recovery.
- **Options flow** — the monitored regions can be changed from *Configure* without removing
  and re-adding the integration.
- **Diagnostics download** with transport state, configured regions and active alerts.
- Unknown alert types are logged once with a warning so they can be mapped later.
- `sensor.uap_active_regions` now lists the counted regions in a `region_ids` attribute.
- Region sensors expose `active_alert_count`; the `active_alerts` list is capped at 25
  entries so a country-wide attack does not flood the recorder.

### 🔧 Changed

- Diagnostic entities (transport, last update, data stale) now report immediately after a
  restart instead of staying unavailable until the first alert update arrives.
- Background transport tasks are owned by the config entry, so Home Assistant cancels them
  on unload and waits for them at shutdown.
- Only one instance of the integration can be configured (previously enforced in the flow
  only).
- README rewritten: entity table, region-inheritance rules, reliability and troubleshooting.

## [0.1.2] - 2026-07-18

### 🐛 Fixed

- Transport mode changes reach the entities immediately, so the transport sensor no longer
  lags behind a fallback or recovery.

## [0.1.1] - 2026-07-18

### 🐛 Fixed

- Hardening of the transport supervisor: neither the WebSocket loop nor the polling
  fallback can die silently on an unexpected error.

## [0.1.0] - 2026-07-17

Initial release: keyless push alerts over the official alert map's WebSocket, polling
fallback via siren.pp.ua, per-region threat and alert entities, hub diagnostics.
