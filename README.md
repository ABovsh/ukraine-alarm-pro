# Ukraine Alarm Pro

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
![Version](https://img.shields.io/badge/version-0.7.0-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=for-the-badge&logo=home-assistant)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_ukraine-alarm-pro)
[![Reliability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=reliability_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=reliability_rating)
[![Security](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=security_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=security_rating)
[![Maintainability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=sqale_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=sqale_rating)
[![Coverage](https://img.shields.io/sonar/coverage/ABovsh_ukraine-alarm-pro?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge&logo=sonarcloud&label=coverage)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=coverage)

**English** · [Українська](README.uk.md)

> Air-raid alerts for Home Assistant, pushed the moment the official map publishes them —
> no API key, no polling, and no silent oblast while its raions are under fire.

---

## Why this exists

Home Assistant already ships `ukraine_alarm`. This integration was written because that one
has three properties that matter a great deal during an air raid, and the differences below
are all read off core's own source and the live feed rather than claimed.

**It does not see the alerts that are actually declared.** Alerts are published at whichever
administrative level they were declared at, and most are declared for a single raion or
hromada — not for the whole oblast. Core matches the region id you picked and its ancestors,
so an oblast entity stays `off` while the raions inside it are under an air raid. Measured
against the live feed on 2026-09-02: **16 of 29 oblasts were in alert, and for 12 of them
the alert existed only below oblast level.** Here every region inherits alerts from its
ancestors *and* its descendants, so no level is a blind spot.

**It goes `unavailable` when the source fails.** Core polls the volunteer-run siren.pp.ua
proxy every 10 seconds, once per configured region, and the entity has no `available`
override — so a failed poll makes it `unavailable` and a template or automation reading it
mid-outage sees nothing at all. Here the last known state stays put and a separate
`binary_sensor.uap_data_stale` says explicitly when to stop trusting it. An air-raid sensor
that reports "no data" and one that reports "no alert" must never be the same state.

**It has no way to tell you it is broken.** No diagnostics, no transport state, no staleness
signal. Here all three are entities you can put on a dashboard.

| | core `ukraine_alarm` | Ukraine Alarm Pro |
| --- | --- | --- |
| Delivery | polls every 10 s (`cloud_polling`) | pushed over the official map's WebSocket (`cloud_push`) |
| Connections | one poll loop **per region** | one connection serves **every** region |
| Regions | max 5, one config entry each | one entry, any number, the full 1606-region tree |
| Alerts declared below your region | not seen | inherited, so an oblast sees its raions |
| Source unreachable | entities go `unavailable` | last state kept + explicit staleness sensor |
| Restart | blank until the first poll returns | last alert map restored from disk |
| When the alert started | — | `sensor.uap_<id>_alert_started` |
| Per region | 6 binary sensors, one per alert type | alert flag + enum threat + start time |
| Country-wide | — | `sensor.uap_active_regions` |
| Self-diagnosis | — | diagnostics download, transport sensor, Repairs issue |
| Dependencies | `uasiren==0.0.1` | none |
| API key | not needed | not needed |

## How a region ends up "in alert"

Alerts are published at whichever administrative level they were declared at — sometimes an
oblast, more often a single raion or hromada. A selected region therefore reports an alert
when **it**, any **ancestor** or any **descendant** has one:

| You selected | Alert declared for | Result |
| --- | --- | --- |
| Сумська громада | Сумська область (oblast-wide raid) | in alert (ancestor) |
| Сумська область | Сумський район | in alert (descendant) |
| Сумський район | Сумська громада | in alert (descendant) |

Pick whichever level suits you — an oblast entity will not miss raion-level alerts.

## Entities

| Entity | Type | Notes |
| --- | --- | --- |
| `sensor.uap_<id>_threat` | enum | `none` / `unrecognized` / `air` / `artillery` / `urban_fights` / `chemical` / `nuclear`, highest active threat; `active_alerts` attribute lists each alert newest first with the region that **declared** it, by id and name (capped at 25; `active_alert_count` holds the true total) |
| `binary_sensor.uap_<id>_alert` | safety | on while any threat is active |
| `sensor.uap_<id>_alert_started` | timestamp | when the oldest alert now affecting the region was declared; `unknown` while the region is quiet |
| `sensor.uap_transport` | diagnostic | `websocket` or `polling` |
| `sensor.uap_last_update` | diagnostic | timestamp of the last received snapshot, republished at most once a minute |
| `sensor.uap_active_regions` | diagnostic | country-wide count of regions with an active alert |
| `binary_sensor.uap_data_stale` | diagnostic, problem | on when no snapshot arrived for 15 minutes |

### How long the alert has been running

`sensor.uap_<id>_alert_started` carries the moment the feed says the alert was
**declared**, not the moment Home Assistant noticed it. That distinction is the
whole point: it is already correct on the first state after a restart, and it
stays correct for an alert that was declared for your raion an hour before you
selected it. The frontend renders a live "1 hour ago" from it; a template gets
the length with `now() - states('sensor.uap_31_alert_started') | as_datetime`.

Two notes on the data itself:

- `sensor.uap_active_regions` never reaches 0 — occupied regions (Луганська область,
  Автономна Республіка Крим) carry permanently active alerts in the official feed.
  Download the config entry's diagnostics to see exactly which regions are counted.
- An alert type the integration does not know yet is reported as `unrecognized` and logged
  once with a warning, so it can be mapped in a later release.
- For the same reason, `sensor.uap_<id>_alert_started` is pinned to the old date for a
  region that contains a permanently alerting one — the oldest alert affecting Харківська
  область really was declared in 2024. Select the raion or hromada you live in rather than
  such an oblast and the sensor tracks the actual raid.

### How much of the day was under alert

Core's [`history_stats`](https://www.home-assistant.io/integrations/history_stats/)
already answers this, so the integration does not ship its own statistics entities: it
reads the recorder history these entities have been writing all along, which means the
numbers are correct the minute you add it — no waiting for a counter to fill up. Per
region you care about, in `configuration.yaml`:

```yaml
sensor:
  - platform: history_stats
    name: Alarm ratio today
    entity_id: binary_sensor.uap_31_alert   # your region id
    state: "on"
    type: ratio
    start: "{{ today_at() }}"
    end: "{{ now() }}"

  - platform: history_stats
    name: Alarm ratio 7d
    entity_id: binary_sensor.uap_31_alert
    state: "on"
    type: ratio
    end: "{{ now() }}"
    duration:
      days: 7
```

Both come out as a percentage with `state_class: measurement`, so the 7-day one feeds
long-term statistics and a **Statistics graph** card (period: day) plots the trend for
several regions on one chart, well past `purge_keep_days`. `type: time` gives hours
instead, `type: count` the number of alerts.

## Reliability

- **Instant state after a restart.** The WebSocket serves no history, so the first snapshot
  is fetched from the polling endpoint instead of waiting for the map to change somewhere
  in the country — which can take several minutes.
- **Watchdog.** After 15 minutes without a push the alert map is re-checked against the
  polling endpoint. If it agrees, the country simply stayed calm and the connection is left
  alone; if it disagrees or cannot be reached, the socket is dropped, which sends the
  supervisor through its normal reconnect-and-degrade path.
- **Degrade and recover.** Three consecutive *short-lived* WebSocket failures switch the
  integration to polling and raise a repair issue; a long healthy session that ends when the
  server recycles the connection does not count against it. It keeps probing the WebSocket
  and clears the issue on recovery.
- **Unusable data is a failure, not silence.** A feed response the integration cannot make
  sense of is treated as a transport error, never as "no alerts anywhere".
- **No false all-clear.** Entities keep their last known state while transports are down;
  `binary_sensor.uap_data_stale` tells you when that state is no longer trustworthy.
- **Survives a restart with the power.** The alert map is kept on disk and republished at
  startup, so the region entities come up with the last known state instead of
  `unavailable` — which matters most in the case Ukraine actually has, where the power
  comes back before the uplink does. A map older than 6 hours is discarded rather than
  resurrected, and until a transport really delivers, `binary_sensor.uap_data_stale` stays
  on to say the restored state is not confirmed.

Recommended automation guard:

```yaml
condition:
  - condition: state
    entity_id: binary_sensor.uap_data_stale
    state: "off"
```

## Automation blueprint

The repository ships a blueprint that notifies on the start and the end of an alert —
[**import it**](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fukraine_alarm_pro%2Falert_notify.yaml)
or paste that URL into **Settings → Automations & scenes → Blueprints → Import blueprint**.
Any action works for the two slots: a mobile notification, Telegram, a TTS announcement,
a siren.

It exists mostly to get two things right that are easy to get wrong by hand:

- it triggers only on a real `off` → `on` transition, so a Home Assistant restart during a
  raid does not re-announce it, and an entity coming back from `unavailable` does not either
- it is guarded by `binary_sensor.uap_data_stale`, so an alert map that appeared without a
  fresh push is never announced as a new raid

Both actions can use `region`, `threat`, `threat_types`, `started`, `started_local`,
`duration` and a ready-made `message`.

## Install

HACS → custom repository → `ABovsh/ukraine-alarm-pro` → install → add integration →
pick regions (full hromada-level list). HACS installs the `ukraine_alarm_pro.zip`
asset attached to each release, so it offers tagged versions rather than whatever
sits on the default branch.

To change the monitored regions later — add or remove any of them — open **Settings →
Devices & services → Ukraine Alarm Pro → Configure** and edit the same region list. Entities
are rebuilt on save, and entities of regions you removed are deleted automatically.

## Troubleshooting

Download **Settings → Devices & services → Ukraine Alarm Pro → Diagnostics** — it contains
the transport mode, the age of the last snapshot, the configured regions and the currently
active alerts. There are no credentials to redact: the integration is fully anonymous.

## Credits

Alert data comes from [ukrainealarm.com](https://map.ukrainealarm.com/) (push) and the
volunteer-run [siren.pp.ua](https://siren.pp.ua/) proxy (polling fallback).
