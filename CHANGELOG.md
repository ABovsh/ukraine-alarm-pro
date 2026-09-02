# Changelog

All notable changes to this project are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.7.0] - 2026-09-02

### ✨ Added

- **`sensor.uap_<id>_alert_started` — when the alert was declared.** Both feeds
  stamp every alert with its declaration time and the integration was dropping
  it into an attribute string. As a timestamp entity it is correct on the first
  state after a restart and correct for an alert declared before the region was
  selected, which a duration counted from when Home Assistant noticed the alert
  is not. `unknown` while the region is quiet.
- **The alert map survives a restart.** It is written to `.storage` and
  republished at startup, so the region entities come up with the last known
  state instead of `unavailable` — the case that actually happens here is the
  power returning before the uplink. A stored map older than 6 hours is
  discarded rather than resurrected, and `binary_sensor.uap_data_stale` stays
  on until a transport really delivers, so a restored state is never reported
  as confirmed. The write is driven by a 5-minute interval rather than by the
  pushes themselves: `Store.async_delay_save` is a trailing debounce, and a map
  that keeps changing — which is what a mass raid looks like — would postpone
  the write forever (verified on the live feed: 12 consecutive changes, none
  more than ~2 minutes apart, and nothing on disk after 7 minutes).
- **An automation blueprint**, `blueprints/automation/ukraine_alarm_pro/alert_notify.yaml`,
  with an import link in the README. It triggers only on a real `off` → `on`
  transition, so a restart mid-raid does not re-announce it, and it is guarded
  by `binary_sensor.uap_data_stale`. Both actions get `region`, `threat`,
  `threat_types`, `started`, `started_local`, `duration` and a ready `message`.

### 🐛 Fixed

- **One declared alert was counted once per region it reached.** Alerts are
  deduplicated by the region they were found under, but an affected region
  repeats its ancestor's alert verbatim, so a raion-wide raid was counted again
  for every hromada below it that echoed it. Measured against the live feed on
  2026-09-02, Харківська область reported `active_alert_count: 12` for 10
  distinct alerts. The key is now the region that *declared* the alert.
- **`region_id` in `active_alerts` named the wrong region** — where the alert
  was found, not who declared it.
- **README.uk.md documented `region_ids`** on `sensor.uap_active_regions`, an
  attribute 0.6.2 removed.

### ⚠️ Breaking

- `active_alerts` entries changed shape: `region_id` is now the region that
  declared the alert (it used to be the region it was found under), and each
  entry gains `region_name`. The list is ordered newest declaration first, so
  the 25-entry cap drops the oldest rather than an arbitrary slice.
- `sensor.uap_<id>_threat` gains a constant `region_name` attribute. It costs
  bytes on a recorder row but never a row of its own, and it saves templates
  from parsing the friendly name.
- The config entry's diagnostics dump lists each active alert as an object
  (`type`, `declared_by`, `declared_by_name`, `since`) instead of a bare type
  string.

## [0.6.2] - 2026-09-02

### 🏗️ Packaging

- **Distributed as a release asset.** `hacs.json` now sets `zip_release` with
  `ukraine_alarm_pro.zip`, and a workflow builds that zip from the tag and
  attaches it to every published release (it fails if the manifest version and
  the tag disagree). HACS installs tagged versions instead of tracking the
  default branch, and the asset's download counter shows how many installs the
  integration actually has.

### 🐛 Fixed

- **Two entities wrote a recorder row on every country-wide map change.**
  Measured on a live recorder over 24 h with the WebSocket up the whole time:
  `binary_sensor.uap_data_stale` 744 rows and `sensor.uap_active_regions` 739,
  neither of which had anything new to say. Home Assistant stores a row when the
  state *or the attributes* differ, and both entities published a value that
  moves whenever any of Ukraine's regions goes on or off alert.

### ⚠️ Breaking

- `binary_sensor.uap_data_stale` no longer publishes a `last_update` attribute.
  It was the push clock, which moves every few seconds; the same value has its
  own entity, `sensor.uap_last_update`. Templates reading the attribute must
  point at that sensor instead.
- `sensor.uap_active_regions` no longer publishes a `region_ids` attribute. It
  was a ~66-entry list rewritten (state row and all) on every map change, even
  while the count itself sat still. The same breakdown is in the config entry's
  diagnostics download.

### 📝 Docs

- README: how to get "percentage of the day under alert" (today and rolling 7
  days) out of core's `history_stats`, and why the integration does not ship
  those sensors itself — `history_stats` reads the recorder history that already
  exists, so it is correct immediately, while an in-integration counter would
  have to start from zero.

## [0.6.1] - 2026-08-08

### 🐛 Fixed

- **`sensor.uap_last_update` stopped moving on a healthy feed.** 0.5.0 stopped
  the coordinator from notifying on an unchanged alert map and 0.5.1 stopped
  the staleness tick from republishing an unchanged verdict — together they
  took this sensor from ~34,000 recorder rows/day to zero, but
  `coordinator.last_push` keeps moving every couple of seconds, so the
  published state froze at the last alert-map change and a feed that was up
  the whole time was displayed as hours old (measured on the live recorder
  2026-08-08: 0 rows/h after 08:00). The staleness tick now republishes this
  sensor when the push clock enters a new minute — ~1,400 rows/day at worst,
  and the frontend renders a live "x minutes ago" from the static state in
  between. `binary_sensor.uap_data_stale` is unaffected: its state is the
  verdict, so it still publishes only on a transition.

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
