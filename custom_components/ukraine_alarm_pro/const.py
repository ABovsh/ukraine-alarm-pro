"""Constants."""

from homeassistant.const import Platform

DOMAIN = "ukraine_alarm_pro"
CONF_REGIONS = "regions"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.EVENT]

# No snapshot for this long means the feed went silent, not that the country
# is calm — surfaced as a diagnostic problem sensor and a transport restart.
STALE_AFTER_SECONDS = 900.0
# The watchdog cross-checks a quiet feed this much earlier, so a healthy but
# silent WS is refreshed before it counts as stale: one watchdog tick plus a
# request timeout fit in the margin.
CROSS_CHECK_AFTER_SECONDS = STALE_AFTER_SECONDS - 180.0
# While a selected region is under alert, a stalled socket costs the most, so
# the check comes sooner: CROSS_CHECK_MEDIAN_FACTOR x the median interval
# between WebSocket publications of the last CROSS_CHECK_WINDOW_SECONDS, within
# CROSS_CHECK_MIN_SECONDS..CROSS_CHECK_AFTER_SECONDS, once that hour holds at
# least CROSS_CHECK_MIN_INTERVALS intervals. Otherwise CROSS_CHECK_AFTER_SECONDS.
# The floor is the request budget: modelled on 7 days of 2026-11 publications,
# a 120 s floor meant 93 checks a day instead of 5.4; 600 s means 7.4 (+37 %),
# at most 3 an hour. A raid publishes every ~20 s, so the floor usually wins.
CROSS_CHECK_MIN_SECONDS = 600.0
CROSS_CHECK_MEDIAN_FACTOR = 3
CROSS_CHECK_WINDOW_SECONDS = 3600.0
CROSS_CHECK_MIN_INTERVALS = 5

# Retired: polling fallback is not a user problem. Kept to clear leftovers.
ISSUE_WS_UNAVAILABLE = "websocket_unavailable"
ISSUE_FEED_UNAVAILABLE = "feed_unavailable"

# Last-known alert map, kept on disk so a restart does not come up blind.
# Ukraine's reality is that power returns before the uplink does: without this
# every region entity is `unavailable` until a transport connects, and every
# automation reading them is blind exactly then.
STORAGE_KEY = f"{DOMAIN}.snapshot"
STORAGE_VERSION = 1
# Restoring is about bridging a restart, not resurrecting yesterday's raid.
RESTORE_MAX_AGE_SECONDS = 6 * 3600
# The alert map changes ~750 times a day country-wide; coalesce the writes.
SAVE_DELAY_SECONDS = 300
