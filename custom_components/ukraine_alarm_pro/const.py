"""Constants."""

from homeassistant.const import Platform

DOMAIN = "ukraine_alarm_pro"
CONF_REGIONS = "regions"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]

# No snapshot for this long means the feed went silent, not that the country
# is calm — surfaced as a diagnostic problem sensor and a transport restart.
STALE_AFTER_SECONDS = 900.0

ISSUE_WS_UNAVAILABLE = "websocket_unavailable"
