# Ukraine Alarm Pro

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/custom-components/hacs)
![Version](https://img.shields.io/badge/version-0.7.1-blue?style=for-the-badge)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.1%2B-41BDF5?style=for-the-badge&logo=home-assistant)

[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=ABovsh_ukraine-alarm-pro&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ABovsh_ukraine-alarm-pro)
[![Coverage](https://img.shields.io/sonar/coverage/ABovsh_ukraine-alarm-pro?server=https%3A%2F%2Fsonarcloud.io&style=for-the-badge&logo=sonarcloud&label=coverage)](https://sonarcloud.io/component_measures?id=ABovsh_ukraine-alarm-pro&metric=coverage)

🇺🇦 **Українська** · [English](README.en.md)

Повітряні тривоги для Home Assistant. Дані надходять з офіційної
[мапи тривог](https://map.ukrainealarm.com/) через WebSocket — одразу після публікації,
без API-ключа.

## Чим відрізняється від `ukraine_alarm`

`ukraine_alarm` входить до стандартного набору Home Assistant і бере дані з того самого
джерела. Відмінності:

- **Бачить тривоги, оголошені на нижчому адміністративному рівні, ніж обраний регіон.**
  Більшість тривог оголошують для окремого району чи громади, а не для цілої області. Тут
  регіон вважається у тривозі, якщо її оголошено для нього самого, для рівня над ним або
  для рівня під ним; `ukraine_alarm` звіряє лише обраний регіон і рівні над ним.
- **Одним WebSocket-з'єднанням обслуговує всі обрані регіони**, скільки б їх не було;
  `ukraine_alarm` опитує проксі раз на 10 секунд окремим циклом на кожен регіон і не
  більше ніж для п'яти регіонів.
- **Розрізняє «тривоги немає» і «даних немає».** Коли джерело недоступне, останній відомий
  стан лишається на місці, а `binary_sensor.uap_data_stale` вмикається; у `ukraine_alarm`
  невдале опитування робить сутність `unavailable`.
- **Не втрачає стан після перезапуску.** Карта тривог зберігається на диск і відновлюється
  на старті — це помітно, коли Home Assistant вмикається після відключення світла, а
  зв'язку ще немає; у `ukraine_alarm` сутності лишаються порожніми до першого успішного
  опитування.
- **Показує час оголошення тривоги** окремим сенсором, а не час, коли її отримав
  Home Assistant.
- **Показує власний стан:** канал даних, час останніх отриманих даних, ознаку
  застарілості, запис у «Виправленнях» на час роботи в резервному режимі та вивантаження
  діагностики.

Якщо WebSocket недоступний, інтеграція переходить на опитування siren.pp.ua раз на 60
секунд і повертається на WebSocket, щойно той знову працює.

## Сутності

| Сутність | Тип | Опис |
| --- | --- | --- |
| `binary_sensor.uap_<id>_alert` | safety | увімкнений, поки в регіоні активна будь-яка тривога |
| `sensor.uap_<id>_threat` | enum | найвища активна загроза: `none`, `air`, `artillery`, `urban_fights`, `chemical`, `nuclear`, `unrecognized` |
| `sensor.uap_<id>_alert_started` | timestamp | коли оголосили найдавнішу з активних тривог; `unknown`, поки тихо |
| `sensor.uap_transport` | діагностична | `websocket` або `polling` |
| `sensor.uap_last_update` | діагностична | час останніх отриманих даних |
| `sensor.uap_active_regions` | діагностична | скільки регіонів у тривозі по всій країні |
| `binary_sensor.uap_data_stale` | діагностична | увімкнений, якщо даних не було 15 хвилин |

`sensor.uap_<id>_threat` має атрибут `active_alerts` — перелік активних тривог із назвою
регіону, який кожну оголосив (не більше 25 записів, повна кількість у
`active_alert_count`). Повний перелік без обмежень — у діагностиці.

## Встановлення

HACS → користувацький репозиторій → `ABovsh/ukraine-alarm-pro` → встановити → додати
інтеграцію → обрати регіони. Доступне все дерево, аж до громад.

Змінити перелік регіонів потім: **Налаштування → Пристрої та служби → Ukraine Alarm Pro →
Налаштувати**. Сутності знятих регіонів видаляються самі.

## Сповіщення

У репозиторії є готовий blueprint —
[імпортувати](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FABovsh%2Fukraine-alarm-pro%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fukraine_alarm_pro%2Falert_notify.yaml).
Одна дія на початок тривоги, друга на відбій; підходить будь-що — сповіщення на телефон,
Telegram, TTS, сирена.

Автоматизація не спрацьовує після перезапуску Home Assistant посеред тривоги і нічого не
надсилає, поки дані застарілі. У діях доступні `region`, `threat`, `threat_types`,
`started`, `started_local`, `duration` і готовий `message`.

Якщо пишете автоматизацію вручну, додайте ту саму умову:

```yaml
condition:
  - condition: state
    entity_id: binary_sensor.uap_data_stale
    state: "off"
```

## Тривалість і статистика

Тривалість поточної тривоги рахується з `sensor.uap_<id>_alert_started`:

```jinja
{{ now() - states('sensor.uap_31_alert_started') | as_datetime }}
```

Скільки часу доби була тривога — вбудований
[`history_stats`](https://www.home-assistant.io/integrations/history_stats/) по
`binary_sensor.uap_<id>_alert`. Він читає вже наявну історію recorder'а, тож числа
правильні одразу:

```yaml
sensor:
  - platform: history_stats
    name: Тривога за 7 днів
    entity_id: binary_sensor.uap_31_alert
    state: "on"
    type: ratio
    end: "{{ now() }}"
    duration:
      days: 7
```

Те саме за поточну добу — замість `duration` вкажіть `start: "{{ today_at() }}"`.

## Що варто знати про дані

- `sensor.uap_active_regions` ніколи не дорівнює нулю: окуповані території мають у джерелі
  постійно активні тривоги ще з 2022 року.
- З тієї ж причини `sensor.uap_<id>_alert_started` для області, всередині якої є такий
  регіон, показуватиме стару дату. Обирайте свій район чи громаду.
- Невідомий тип тривоги показується як `unrecognized` і один раз пишеться в лог.

## Діагностика

**Налаштування → Пристрої та служби → Ukraine Alarm Pro → Діагностика** — канал даних, вік
останніх даних, обрані регіони та всі активні тривоги. Приховувати там нічого не треба:
інтеграція повністю анонімна.

## Джерела даних

[ukrainealarm.com](https://map.ukrainealarm.com/) — основне, push.
[siren.pp.ua](https://siren.pp.ua/) — волонтерський проксі, резерв.
