# Ukraine Alarm Pro

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
![Version](https://img.shields.io/badge/version-0.2.0-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=for-the-badge&logo=home-assistant)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_ukraine-alarm-pro)
[![Reliability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=reliability_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=reliability_rating)
[![Security](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=security_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=security_rating)
[![Maintainability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=sqale_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=sqale_rating)
[![Coverage](https://img.shields.io/sonar/coverage/ABovsh_ukraine-alarm-pro?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge&logo=sonarcloud&label=coverage)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=coverage)

Air-raid alert integration for Home Assistant with **push updates** (~1 s latency) over the
anonymous WebSocket behind the official [alert map](https://map.ukrainealarm.com/) — no API
key required — with automatic fallback to siren.pp.ua polling when the WebSocket is down.

## Why not core `ukraine_alarm`?

The core integration polls the volunteer-run siren.pp.ua proxy every 10 s per region with a
10 s timeout, which fails intermittently when the proxy is under load. This integration:

- **Pushes** alerts over the official map's Centrifugo WebSocket (keyless, ~1 s latency)
- One connection serves **all** configured regions (core: one poll loop per region)
- Auto-degrades to proxy polling (60 s interval, 30 s timeout) and auto-recovers
- Never emits a false "all clear": entities keep their last state on transport loss, and
  staleness is exposed explicitly instead of being hidden

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
| `sensor.uap_<id>_threat` | enum | `none` / `unrecognized` / `air` / `artillery` / `urban_fights` / `chemical` / `nuclear`, highest active threat; `active_alerts` attribute lists each alert with its source region |
| `binary_sensor.uap_<id>_alert` | safety | on while any threat is active |
| `sensor.uap_transport` | diagnostic | `websocket` or `polling` |
| `sensor.uap_last_update` | diagnostic | timestamp of the last received snapshot |
| `sensor.uap_active_regions` | diagnostic | country-wide count of regions with an active alert |
| `binary_sensor.uap_data_stale` | diagnostic, problem | on when no snapshot arrived for 15 minutes |

Two notes on the data itself:

- `sensor.uap_active_regions` never reaches 0 — occupied regions (Луганська область,
  Автономна Республіка Крим) carry permanently active alerts in the official feed. The
  `region_ids` attribute shows exactly which regions are counted.
- An alert type the integration does not know yet is reported as `unrecognized` and logged
  once with a warning, so it can be mapped in a later release.

## Reliability

- **Watchdog.** A WebSocket that stays connected but stops publishing is detected after
  15 minutes: the socket is dropped, which sends the supervisor through its normal
  reconnect-and-degrade path.
- **Degrade and recover.** Three consecutive WebSocket failures switch the integration to
  polling and raise a repair issue; it keeps probing the WebSocket and clears the issue on
  recovery.
- **No false all-clear.** Entities keep their last known state while transports are down;
  `binary_sensor.uap_data_stale` tells you when that state is no longer trustworthy.

Recommended automation guard:

```yaml
condition:
  - condition: state
    entity_id: binary_sensor.uap_data_stale
    state: "off"
```

## Install

HACS → custom repository → `ABovsh/ukraine-alarm-pro` → install → add integration →
pick regions (full hromada-level list).

To change the monitored regions later: integration → **Configure**. Entities are rebuilt on
save; entities of regions you removed have to be deleted manually from the entity registry.

## Troubleshooting

Download **Settings → Devices & services → Ukraine Alarm Pro → Diagnostics** — it contains
the transport mode, the age of the last snapshot, the configured regions and the currently
active alerts. There are no credentials to redact: the integration is fully anonymous.

## Credits

Alert data comes from [ukrainealarm.com](https://map.ukrainealarm.com/) (push) and the
volunteer-run [siren.pp.ua](https://siren.pp.ua/) proxy (polling fallback).
