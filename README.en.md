# Ukraine Alarm Pro

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
![Version](https://img.shields.io/badge/version-0.8.0-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=for-the-badge&logo=home-assistant)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_ukraine-alarm-pro)
[![Coverage](https://img.shields.io/sonar/coverage/ABovsh_ukraine-alarm-pro?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge&logo=sonarcloud&label=coverage)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=coverage)

🇺🇦 [Українська](README.md) · **English**

Air-raid alerts for Home Assistant. The data comes from the official
[alert map](https://map.ukrainealarm.com/) over a WebSocket — as soon as it is published,
without an API key.

## How it differs from `ukraine_alarm`

[`ukraine_alarm`](https://www.home-assistant.io/integrations/ukraine_alarm/) ships with
Home Assistant and uses the same source through siren.pp.ua.
This comparison was checked against [Home Assistant 2026.9.2 source](https://github.com/home-assistant/core/tree/2026.9.2/homeassistant/components/ukraine_alarm).
What this integration does differently:

- **Accounts for alerts at every administrative level.** For a selected oblast, raion
  or hromada, it checks the region itself, its ancestors and its descendants;
  `ukraine_alarm` reads the API response for one region without aggregating descendant
  alerts itself, and does not offer oblasts with districts as a final selection.
- **Serves every selected region over one WebSocket connection** without a region-count
  limit in its settings; `ukraine_alarm` polls the proxy every 10 seconds in a separate
  loop per region and allows up to five regions.
- **Reports the highest active threat, the list of types and the air alert level.**
  A separate sensor exposes yellow or red and the reasons when supplied by the source;
  `ukraine_alarm` creates six binary sensors by threat type, without levels or reasons.
- **Keeps the last received state on connection loss.** After more than 15 minutes
  without new data, `binary_sensor.uap_data_stale` marks it as stale; in `ukraine_alarm`
  a failed poll makes the entities `unavailable`.
- **Restores the saved alert map after a restart.** A changed map is saved every five
  minutes and on integration unload, and restored at startup if the saved copy is no
  more than six hours old; it is marked stale until new data arrives.
- **Reports when the oldest active alert was declared** as a separate sensor — using
  the source timestamp, not the time Home Assistant received it.
- **Reports its own state:** the data channel, the time of the last data received, a
  staleness flag, an entry under Repairs while it runs on the fallback, and a diagnostics
  download.

After repeated WebSocket failures, the integration switches to polling siren.pp.ua
with a 60-second pause between requests. It periodically retries the WebSocket and
switches back after receiving data.

## Entities

| Entity | Type | Description |
| --- | --- | --- |
| `binary_sensor.uap_<id>_alert` | safety | on while any alert is active in the region |
| `sensor.uap_<id>_threat` | enum | highest active threat: `none`, `air`, `artillery`, `urban_fights`, `chemical`, `nuclear`, `unrecognized` |
| `sensor.uap_<id>_air_alert_level` | enum | air alert level: `none`, `yellow`, `red`, `unrecognized` |
| `sensor.uap_<id>_alert_started` | timestamp | when the oldest active alert was declared; `unknown` while the region is quiet |
| `event.uap_<id>_event` | event | alert changes in the region: one event per accepted change |
| `sensor.uap_transport` | diagnostic | `websocket` or `polling` |
| `sensor.uap_last_update` | diagnostic | time of the last data received |
| `sensor.uap_active_regions` | diagnostic | how many regions are in alert country-wide |
| `binary_sensor.uap_data_stale` | diagnostic | on when no data has arrived for 15 minutes |

`sensor.uap_<id>_threat` carries an `active_alerts` attribute — the active alerts with the
name of the region that declared each one (at most 25 entries, the full number is in
`active_alert_count`). The complete list is in the diagnostics.

The `coverage` attribute tells whether the alert covers the whole region:

- `whole` — the region itself or a higher-level region containing it declared the alert;
- `partial` — alerts are declared only in part of the region, such as one raion of an
  oblast;
- `unrecognized` — an alert exists, but its region is not among the stored higher and
  lower levels;
- `none` — no active alerts.

If `whole` and `partial` apply together, the attribute shows `whole`. `coverage_by_type`
gives the coverage of each threat type. `affected_regions` lists up to 25 regions that
declared active alerts; `affected_region_count` is the full number of such regions. It
is not the number of hromadas in alert or a share of the area. Coverage does not change
`binary_sensor.uap_<id>_alert`: a partial alert is still an alert.

The air alert level covers the same region and its ancestors and descendants.
If yellow and red are active together, the sensor reports `red`; `active_levels`
contains both. `unrecognized` means an air alert exists but the source supplied no
recognized level. `none` means no air alert; other threat types remain on `threat`.

The `reasons` attribute contains up to 25 source reasons, each limited to 256 characters;
`reason_count` is the full count of distinct nonempty reasons. An empty reason does
not imply a weapon type. Full reasons and each level's declaration time are available
in diagnostics. The sensor has no long-term statistics: history is written only when
its state or attributes change. Repeated publications and changes in unrelated regions
produce no additional history rows for this sensor.

### Alert events

`event.uap_<id>_event` has these event types:

- `started` — an alert started in the region;
- `escalated` — the air alert level rose to yellow or red;
- `threat_added` — a new threat type joined an active alert;
- `updated` — any other change: a lower level, different reasons or coverage, or one of
  several types ended;
- `cleared` — the alert ended while data arrived without a gap;
- `data_stale` — the data went stale; the last known state is kept;
- `resynced` — the first data after startup or after a gap.

One change produces one event. If a type is added and the level rises together, one
`escalated` event arrives with the new type in `added_types`. After startup or a gap
the integration does not know what happened meanwhile, so it sends `resynced` with the
current state instead of `started` or `cleared`.

Event attributes: `schema_version`, `transition_id`, `region_id`, `region_name`,
`event_type`, `observed_at` (when the integration accepted the change, not an official
time), `origin` (`live`, `recovery` or `bootstrap`), `previous` and `current` (`active`,
`threat_types`, `air_level`, `reasons`, `coverage`, `declared_started_at`),
`added_types`, `removed_types`, `had_gap`, plus `observed_active_since` and
`active_since_known` — when the integration first saw the current alert and whether that
was its real start.

## Installation

HACS → custom repository → `ABovsh/ukraine-alarm-pro` → install → add the integration →
pick the regions. The whole tree is available, down to hromadas.

To change the regions later: **Settings → Devices & services → Ukraine Alarm Pro →
Configure**. Entities of removed regions are deleted automatically.

The integration keeps a copy of the region list and refreshes it once a day. If the
proxy is unavailable, the options show the saved copy with its date. A selected region
missing from the current list stays selected with a ⚠ mark and is not removed. A first
installation without network and without a saved copy is not possible: the form offers
a retry.

## Dashboard

An example dashboard on standard cards is in [`docs/examples/dashboard.yaml`](docs/examples/dashboard.yaml).
It shows the alert state, threat types, level, declaration time and duration, coverage,
reasons, the last event and data freshness. Stale data with a last known quiet state is
shown as "no fresh data", not as a confirmed quiet. Replace `31` with your region ID and
paste the YAML into the dashboard's raw configuration editor.

## Notifications

### Notifications from events

The [event notification blueprint](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fukraine_alarm_pro%2Falert_notify_events.yaml) reads one `event.uap_<id>_event` entity and
sends ready-made messages in Ukrainian or English, for example
"м. Київ: air raid alert since 14:32. Level: red. Reason: …" or
"м. Київ: all clear. Observed duration: 1 h 12 min."

Separate actions cover the start, a raised level or a new threat, the all clear, stale
data and restored data; an empty action sends nothing. The first data after a Home
Assistant start is silent by default. If an alert ended during a data gap, a
connection-restored message is sent, not an all clear. Actions can use `message`,
`event_type`, `origin`, `region`, `threat_types`, `added_types`, `level`, `reason` and
`payload`.

To check the actions without an alert, import the [test script](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fscript%2Fukraine_alarm_pro%2Ftest_notification.yaml). It sends a
message marked "TEST" and changes no alert entity, event or history.

### Sensor-based blueprint

The repository ships a blueprint —
[import it](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fukraine_alarm_pro%2Falert_notify.yaml).
One action for the start of an alert, another for the all-clear; anything fits — a phone
notification, Telegram, TTS, a siren.

The automation does not fire when Home Assistant restarts during an alert, and sends
nothing while the data is stale. The actions can use `region`, `threat`, `threat_types`,
`started`, `started_local`, `duration` and a ready-made `message`.

If you write the automation by hand, add the same condition:

```yaml
condition:
  - condition: state
    entity_id: binary_sensor.uap_data_stale
    state: "off"
```

For escalation notifications, select `sensor.uap_<id>_air_alert_level` in the blueprint
and configure the optional yellow-to-red action. Actions can use `level` and `reason`;
the ready-made `message` includes them. Existing automations continue working without
selecting this sensor. Update the imported blueprint separately: HACS installs only
the integration.

## Duration and statistics

The length of the current alert comes from `sensor.uap_<id>_alert_started`:

```jinja
{{ now() - states('sensor.uap_31_alert_started') | as_datetime }}
```

How much of the day was under alert — Home Assistant's own
[`history_stats`](https://www.home-assistant.io/integrations/history_stats/) over
`binary_sensor.uap_<id>_alert`. It reads the recorder history that already exists, so the
numbers are right immediately:

```yaml
sensor:
  - platform: history_stats
    name: Alarm ratio 7d
    entity_id: binary_sensor.uap_31_alert
    state: "on"
    type: ratio
    end: "{{ now() }}"
    duration:
      days: 7
```

The same for the current day — replace `duration` with `start: "{{ today_at() }}"`.

## Alert history

The integration keeps a journal of alert episodes for each region. An episode is one
continuous period while `binary_sensor.uap_<id>_alert` is on: two overlapping alerts
form one episode from the first start to the last clear.

Read it with actions that return a response:

```yaml
action: ukraine_alarm_pro.get_history
data:
  region_id: "31"
  limit: 20
response_variable: history
```

`get_history` returns up to 100 episodes, newest first, including the current one.
`get_summary` with `days: 1` (today) or `days: 7` returns the episode count,
`observed_duration_seconds` and `has_gaps` over Home Assistant's local days.

Episode times are when the integration received the data, not official times:
`observed_started_at`, `observed_cleared_at` and `declared_started_at` from the source.
If data was interrupted or an alert was already active at startup, `had_gap` is `true`
and `source_start_known` is `false`; missed episodes are not reconstructed.
`coverage_start` shows when the journal started: it has no earlier data.

Completed episodes are kept for up to 90 days and at most 1000 in total; current
episodes are never removed. Recorder history is not affected.

## What to know about the data

- `sensor.uap_active_regions` never reaches zero: the occupied territories carry
  permanently active alerts in the source, going back to 2022.
- For the same reason `sensor.uap_<id>_alert_started` shows an old date for an oblast that
  contains such a region. Pick your own raion or hromada.
- An alert type the integration does not know is reported as `unrecognized` and logged once.

## Diagnostics

**Settings → Devices & services → Ukraine Alarm Pro → Diagnostics** — the data channel, the
age of the last data, the selected regions and every active alert. There is nothing to
redact: the integration is fully anonymous.

## Data sources

[ukrainealarm.com](https://map.ukrainealarm.com/) — primary, push.
[siren.pp.ua](https://siren.pp.ua/) — volunteer proxy, fallback.
