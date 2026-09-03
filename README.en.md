# Ukraine Alarm Pro

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
![Version](https://img.shields.io/badge/version-0.7.1-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=for-the-badge&logo=home-assistant)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_ukraine-alarm-pro)
[![Coverage](https://img.shields.io/sonar/coverage/ABovsh_ukraine-alarm-pro?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge&logo=sonarcloud&label=coverage)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=coverage)

🇺🇦 [Українська](README.md) · **English**

Air-raid alerts for Home Assistant. The data comes from the official
[alert map](https://map.ukrainealarm.com/) over a WebSocket — as soon as it is published,
without an API key.

## How it differs from `ukraine_alarm`

`ukraine_alarm` ships with Home Assistant and takes its data from the same source.
What this integration does differently:

- **Sees alerts declared at a lower administrative level than the selected region.**
  Most alerts are declared for a single raion or hromada rather than for a whole oblast.
  Here a region counts as in alert when the alert was declared for the region itself, for
  a level above it or for a level below it; `ukraine_alarm` matches only the selected
  region and the levels above it.
- **Serves every selected region over one WebSocket connection**, however many there are;
  `ukraine_alarm` polls the proxy every 10 seconds in a separate loop per region, and for
  no more than five regions.
- **Tells "no alert" apart from "no data".** While the source is unreachable the last
  known state stays in place and `binary_sensor.uap_data_stale` turns on; in
  `ukraine_alarm` a failed poll makes the entity `unavailable`.
- **Does not lose its state on a restart.** The alert map is written to disk and restored
  at startup — which shows when Home Assistant comes back after a power cut and the uplink
  is not up yet; in `ukraine_alarm` the entities stay empty until the first successful poll.
- **Reports the time the alert was declared** as a separate sensor, rather than the time
  Home Assistant received it.
- **Reports its own state:** the data channel, the time of the last data received, a
  staleness flag, an entry under Repairs while it runs on the fallback, and a diagnostics
  download.

If the WebSocket is unreachable, the integration switches to polling siren.pp.ua every
60 seconds and returns to the WebSocket as soon as it works again.

## Entities

| Entity | Type | Description |
| --- | --- | --- |
| `binary_sensor.uap_<id>_alert` | safety | on while any alert is active in the region |
| `sensor.uap_<id>_threat` | enum | highest active threat: `none`, `air`, `artillery`, `urban_fights`, `chemical`, `nuclear`, `unrecognized` |
| `sensor.uap_<id>_alert_started` | timestamp | when the oldest active alert was declared; `unknown` while the region is quiet |
| `sensor.uap_transport` | diagnostic | `websocket` or `polling` |
| `sensor.uap_last_update` | diagnostic | time of the last data received |
| `sensor.uap_active_regions` | diagnostic | how many regions are in alert country-wide |
| `binary_sensor.uap_data_stale` | diagnostic | on when no data has arrived for 15 minutes |

`sensor.uap_<id>_threat` carries an `active_alerts` attribute — the active alerts with the
name of the region that declared each one (at most 25 entries, the full number is in
`active_alert_count`). The complete list is in the diagnostics.

## Installation

HACS → custom repository → `ABovsh/ukraine-alarm-pro` → install → add the integration →
pick the regions. The whole tree is available, down to hromadas.

To change the regions later: **Settings → Devices & services → Ukraine Alarm Pro →
Configure**. Entities of removed regions are deleted automatically.

## Notifications

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
