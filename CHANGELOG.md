# Changelog

All notable changes to this project are documented here.
This project follows [Semantic Versioning](https://semver.org/).

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
