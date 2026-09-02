"""Constants."""

from homeassistant.const import Platform

DOMAIN = "ukraine_alarm_pro"
CONF_REGIONS = "regions"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

# No snapshot for this long means the feed went silent, not that the country
# is calm — surfaced as a diagnostic problem sensor and a transport restart.
STALE_AFTER_SECONDS = 900.0

ISSUE_WS_UNAVAILABLE = "websocket_unavailable"

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
