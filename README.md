# Ukraine Alarm Pro

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
![Version](https://img.shields.io/badge/version-0.3.0-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=for-the-badge&logo=home-assistant)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_ukraine-alarm-pro)
[![Reliability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=reliability_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=reliability_rating)
[![Security](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=security_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=security_rating)
[![Maintainability](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=sqale_rating)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=sqale_rating)
[![Coverage](https://img.shields.io/sonar/coverage/ABovsh_ukraine-alarm-pro?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge&logo=sonarcloud&label=coverage)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=coverage)

**English** · [Українська](README.uk.md)

Air-raid alert integration for Home Assistant with **push updates** (~1 s latency) over the
anonymous WebSocket behind the official [alert map](https://map.ukrainealarm.com/) — no API
key required — with automatic fallback to siren.pp.ua polling when the WebSocket is down.

## Why not core `ukraine_alarm`?

The core integration polls the volunteer-run siren.pp.ua proxy every 10 s per region with a
10 s timeout, which fails intermittently when the proxy is under load. This integration:

- **Pushes** alerts over the official map's Centrifugo WebSocket (keyless, ~1 s latency)
- One connection serves **all** configured regions (core: one poll loop per region)
- **Sees alerts declared below your region.** Most alerts are declared for a single raion or
  hromada, not for the whole oblast. Matching only the exact region id leaves an oblast
  entity silent while its raions are under an air raid — at the time of writing that was 6
  of 29 oblasts simultaneously. Here every region also inherits alerts from its ancestors
  **and** its descendants, so no level is a blind spot
- **Reports the threat type**, not just on/off: air raid, artillery, urban fights, chemical
  or nuclear, with a per-alert breakdown of which region each alert came from
- **Populated within seconds of a restart** — the alert map is fetched immediately instead
  of waiting for the feed to publish something
- Auto-degrades to proxy polling (60 s interval, 30 s timeout), auto-recovers, and tells you
  in **Repairs** while it is degraded
- **Never emits a false "all clear".** Entities keep their last state on transport loss, an
  unusable feed response is treated as a failure rather than as silence, and staleness is
  exposed explicitly (`binary_sensor.uap_data_stale`) instead of being hidden
- Ships **Ukrainian and English** translations, diagnostics, and a country-wide alert counter

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
| `sensor.uap_<id>_threat` | enum | `none` / `unrecognized` / `air` / `artillery` / `urban_fights` / `chemical` / `nuclear`, highest active threat; `active_alerts` attribute lists each alert with its source region (capped at 25; `active_alert_count` holds the true total) |
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
