# Ukraine Alarm Pro

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
![Version](https://img.shields.io/badge/version-0.10.0-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=for-the-badge&logo=home-assistant)
[![Downloads](https://img.shields.io/github/downloads/ABovsh/ukraine-alarm-pro/total?style=for-the-badge&color=41BDF5&label=downloads)](https://github.com/ABovsh/ukraine-alarm-pro/releases)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_ukraine-alarm-pro)

🇺🇦 [Українська](README.md) · **English**

Air-raid alerts for Home Assistant from the official [alert map](https://map.ukrainealarm.com/).
Updates arrive over WebSocket without an API key; fresh data requires an internet connection.

[Installation](#installation) · [Card](#dashboard-card) · [Notifications](#notifications) ·
[Entities](#entities) · [Help](#help) · [Updating](#updating) · [Changelog](CHANGELOG.md)

<a id="how-it-differs-from-ukraine_alarm"></a>

## Features

- **Alerts for an oblast, raion or hromada.** Each selected region includes alerts
  from its administrative ancestors and the regions within it. Coverage shows
  whether an alert affects the whole region or only part of it.
- **Dashboard card.** Current state, alert duration or time since the all clear,
  statistics for 24 hours and 7 days, and three layouts.
- **Up to 90 days of history.** Local observations are supplemented with official
  air-alert history. That source has no alert levels or alerts declared for an individual hromada.
- **Events and notification blueprints.** Alert start, escalation, new threats,
  all clear and data gaps, with messages in Ukrainian or English.
- **Air alert level and reason.** Yellow or red and the reason, when supplied by
  the source; other threat types are available separately.
- **Last known state during outages.** The saved alert map is restored after a
  restart; a separate sensor and the card indicate stale data.
- **One shared connection for selected regions.** The integration does not limit
  their number and switches to a fallback source after repeated WebSocket failures.

## Installation

You need **Home Assistant 2025.1 or newer**, internet access and a configured **HACS**.

1. In HACS, open **⋮ → Custom repositories**, add
   `https://github.com/ABovsh/ukraine-alarm-pro` with type **Integration**
   ([HACS instructions](https://www.hacs.xyz/docs/faq/custom_repositories/)).
2. Find **Ukraine Alarm Pro** in HACS, download the integration and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration** and find **Ukraine Alarm Pro**.
4. In **Regions to monitor**, select at least one region and save.
   The full tree is available, down to hromadas.
5. Add a [dashboard card](#adding-the-card). Wait for fresh data:
   `binary_sensor.uap_data_stale` should be `off`. Then set up
   [event notifications](#notifications-from-events) if needed.

### Changing regions

**Settings → Devices & services → Ukraine Alarm Pro → Configure**.
Entities of removed regions are deleted automatically; check any automations and cards
that use them.

The region list is saved locally and refreshed daily. If the proxy is unavailable,
the form uses the saved copy and shows its date. A selected region missing from the
current list stays selected with a ⚠ mark. First-time setup without a saved copy
requires the region-list source to be available.

## Dashboard card

The card is part of the integration; there is nothing else to install. The screenshot
shows its three layouts, top to bottom:

<img src="docs/images/status-card.jpg" alt="Ukraine Alarm Pro card: compact, status only and full layouts" width="420">

- **Compact** — region name, state and time: how long the alert has lasted or how long
  since the all clear. During an alert the level is shown next to the name.
- **Status only** — the same, plus threat types, level, reason, coverage (the whole
  region or part of it) and whether the data is current. When data is stale the card
  says "No fresh data", not "All quiet".
- **Full** — the same, plus statistics for 24 hours and 7 days: alert count, their
  duration, share of time under alert, a day strip with the alerts, and the longest and
  average alert.

Tapping the card opens the alert sensor with its history.

### Adding the card

1. After installing the integration, reload Home Assistant in your browser or app.
2. On a dashboard, choose **Edit dashboard → Add card** and find **Ukraine Alarm Pro**.
3. In **Region / Регіон**, pick your region's alert sensor.
   With a single region, the card selects it automatically.
4. In **Layout / Вигляд**, choose a layout. Optionally set **Name / Назва**
   (for example, "Home") and **Language / Мова**.
5. Press **Save**. Add one card per region.

For YAML-mode dashboards, add the resource manually:
`/ukraine_alarm_pro/ukraine-alarm-pro-card.js`, type `module`.
If the card does not appear, see [Help](#help).

### Card in YAML

```yaml
type: custom:ukraine-alarm-pro-card
entity: binary_sensor.uap_31_alert  # optional with a single region
name: Home                          # optional
layout: full                        # full, status (status only) or compact
language: auto                      # auto (Home Assistant language), uk or en
```

Statistics come from the [alert journal](#alert-history). Fetching official history
starts five minutes after startup and depends on the source being available.
The card creates no entities and no database rows. Entities may be renamed: the card finds
them by region.

## Notifications

### Notifications from events

The [event notification blueprint](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fukraine_alarm_pro%2Falert_notify_events.yaml) reads one `event.uap_<id>_event` entity and
sends ready-made messages in Ukrainian or English, for example
"м. Київ: air raid alert since 14:32. Level: red. Reason: …" or
"м. Київ: all clear. Observed duration: 1 h 12 min."

To get started:

1. Import the blueprint linked above and create an automation from it.
2. In **Alert events**, select your region's `event.uap_<id>_event`, then choose
   **Message language**.
3. For each event you want reported, add a notification action with `{{ message }}`
   as its message and save the automation.

Separate actions cover the start, a raised level or a new threat, the all clear, stale
data and restored data; an empty action sends nothing. The first data after a Home
Assistant start is silent by default. If an alert ended during a data gap, a
connection-restored message is sent, not an all clear. Actions can use `message`,
`event_type`, `origin`, `region`, `threat_types`, `added_types`, `level`, `reason` and
`payload`.

To check the actions without an alert, import the [test script](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fscript%2Fukraine_alarm_pro%2Ftest_notification.yaml). It sends a
message marked "TEST" and changes no alert entity, event or history.

### Earlier sensor-based blueprint

Use notifications from events for new automations. The [sensor-based blueprint](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fukraine_alarm_pro%2Falert_notify.yaml)
stays for existing automations: an action for the start of an alert, one for the
all clear and an optional yellow-to-red action. It does not fire when Home Assistant
restarts during an alert, and sends nothing while the data is stale.

If you write a sensor-based automation by hand, add the same condition:

```yaml
condition:
  - condition: state
    entity_id: binary_sensor.uap_data_stale
    state: "off"
```

See [Updating](#updating) for imported blueprint updates.

## Entities

`<id>` is the numeric region ID (for example, `31`). These are the initial entity IDs;
if you rename them, use your own IDs in automations.

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

### Alert coverage

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

### Level and reasons

The air alert level covers the same region and its ancestors and descendants.
If yellow and red are active together, the sensor reports `red`; `active_levels`
contains both. `unrecognized` means an air alert exists but the source supplied no
recognized level. `none` means no air alert; other threat types remain on `threat`.

The `reasons` attribute contains up to 25 source reasons, each limited to 256 characters;
`reason_count` is the full count of distinct nonempty reasons. An empty reason does
not imply a weapon type. Full reasons and each level's declaration time are available
in diagnostics. The sensor has no long-term statistics; repeated publications without changes
do not add history rows.

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
`observed_duration_seconds`, `longest_duration_seconds`, `has_gaps` and `daily` — count and
duration per day — over Home Assistant's local days.

`observed_started_at` and `observed_cleared_at` are when the integration received the
data; `declared_started_at` is the declaration time from the source. If data was
interrupted or an alert was already active at startup, `had_gap` is `true` and
`source_start_known` is `false`.

Five minutes after startup and then once a day, the integration requests official alert
history from the map: 90 days on the first run, the last few days after
that. When the source is available, this also supplements periods when Home Assistant
was off. Such episodes have
`start_origin: history`, the official start and all-clear times and the type `air`: the
history has no levels. It holds alerts of oblasts, raions and cities; alerts declared
for a single hromada are not in it. Episodes the integration received itself are never
replaced. `coverage_start` shows the date the journal has data from.

Completed episodes are kept for up to 90 days and at most 1000 in total; current
episodes are never removed. Recorder history is not affected.

## Help

- **Card will not load.** For "Custom element doesn't exist", first reload the page
  or clear the app's frontend cache. Check that Home Assistant was restarted after
  installation and that YAML-mode dashboards have the card resource. For
  "Configuration error", also check `type`, `entity`, `layout` and `language` against the example above.
- **No fresh data.** Check access to the [data sources](#data-sources) and
  `sensor.uap_last_update`. A saved state does not confirm a current alert or all clear.
- **No notifications.** Check the selected event entity and automation actions.
  Empty actions send nothing; the test script helps check delivery.

### What to know about the data

- `sensor.uap_active_regions` may stay above zero because the source carries
  permanent alerts for occupied territories.
- For the same reason `sensor.uap_<id>_alert_started` shows an old date for an oblast that
  contains such a region. Pick your own raion or hromada.
- An alert type the integration does not know is reported as `unrecognized` and logged once.

## Diagnostics

Download diagnostics from the integration menu under
**Settings → Devices & services → Ukraine Alarm Pro**. The file includes the data channel,
age of the last data, selected regions and active alerts with full reasons.
There are no API keys, but the selected regions may reveal places you are interested in;
review the file before publishing it.

If the problem persists, [open an issue](https://github.com/ABovsh/ukraine-alarm-pro/issues)
with your integration and Home Assistant versions, a description and relevant diagnostics.

## Updating

Update through HACS, restart Home Assistant and reload the page containing the card.
Read the [changelog](CHANGELOG.md) and
[release notes](https://github.com/ABovsh/ukraine-alarm-pro/releases) before updating.
Update imported notification blueprints separately; the earlier sensor-based blueprint
remains available for existing automations.

## Data sources

- [ukrainealarm.com](https://map.ukrainealarm.com/) — primary, push over a WebSocket.
- [siren.pp.ua](https://siren.pp.ua/) — volunteer proxy, fallback.
- Alert history for the journal — from the [alert map](https://map.ukrainealarm.com/).

After repeated WebSocket failures, the integration switches to polling siren.pp.ua
with a 60-second pause between requests. It periodically retries the WebSocket and
switches back after receiving data. The data channel and the time of the last data
received are visible in the diagnostic entities. An issue appears under Repairs only when
neither the WebSocket nor the fallback source has delivered data for 15 minutes.

License: [MIT](LICENSE).
