"""R1: six hours without country-wide data raise a repair issue.

Only the WebSocket carries the country-wide threats and the MiG status; the
HTTP fallbacks keep regional alerts working while those stay blind. The count
runs on the monotonic clock from the last snapshot with country data, or from
start: a Home Assistant restart starts it again.
"""

import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_country_threats import _feed
from test_hardening_0_2_0 import RAION_AIR, _setup

from custom_components.ukraine_alarm_pro.const import (
    COUNTRY_UNAVAILABLE_AFTER_SECONDS,
    DOMAIN,
    ISSUE_COUNTRY_FEED_UNAVAILABLE,
    ISSUE_FEED_UNAVAILABLE,
    STALE_AFTER_SECONDS,
)
from custom_components.ukraine_alarm_pro.models import parse_alert_payload

WS = parse_alert_payload(_feed())


def _issue(hass: HomeAssistant, issue_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def _tick(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()


async def _without_country_data_for(hass, seconds):
    """Regional data keeps arriving (polling); country data stopped `seconds` ago."""
    entry, sup = await _setup(hass)
    push = sup.set_listener.call_args[0][0]
    push(WS)
    coordinator = entry.runtime_data
    coordinator._country_monotonic = time.monotonic() - seconds
    push(RAION_AIR)  # an HTTP snapshot: no country data
    await _tick(hass)
    return entry, push


async def test_five_hours_fifty_nine_minutes_raise_nothing(
    hass: HomeAssistant, enable_custom_integrations
):
    await _without_country_data_for(hass, COUNTRY_UNAVAILABLE_AFTER_SECONDS - 120)
    assert _issue(hass, ISSUE_COUNTRY_FEED_UNAVAILABLE) is None


async def test_six_hours_raise_the_issue_and_a_websocket_snapshot_clears_it(
    hass: HomeAssistant, enable_custom_integrations
):
    _entry, push = await _without_country_data_for(
        hass, COUNTRY_UNAVAILABLE_AFTER_SECONDS + 1
    )
    issue = _issue(hass, ISSUE_COUNTRY_FEED_UNAVAILABLE)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is None
    push(WS)
    await hass.async_block_till_done()
    assert _issue(hass, ISSUE_COUNTRY_FEED_UNAVAILABLE) is None


async def test_no_data_at_all_raises_only_the_feed_issue(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _sup = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator._started_monotonic = time.monotonic() - COUNTRY_UNAVAILABLE_AFTER_SECONDS - 60
    await _tick(hass)
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is not None
    assert _issue(hass, ISSUE_COUNTRY_FEED_UNAVAILABLE) is None


async def test_the_count_starts_at_start_up(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, sup = await _setup(hass)
    coordinator = entry.runtime_data
    coordinator._started_monotonic = time.monotonic() - COUNTRY_UNAVAILABLE_AFTER_SECONDS - 60
    sup.set_listener.call_args[0][0](RAION_AIR)
    await _tick(hass)
    assert _issue(hass, ISSUE_COUNTRY_FEED_UNAVAILABLE) is not None
    # A restart builds a new coordinator: the count starts again.
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert _issue(hass, ISSUE_COUNTRY_FEED_UNAVAILABLE) is None


def test_the_window_is_six_hours():
    assert COUNTRY_UNAVAILABLE_AFTER_SECONDS == 6 * 3600 > STALE_AFTER_SECONDS
