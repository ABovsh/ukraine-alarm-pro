"""The repair issue speaks only when no source delivers alert data.

Falling back to polling is the integration doing its job: alerts still arrive,
at most a minute late. A warning under Repairs for that alarmed users about a
problem they could not fix and that did not affect them.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_hardening_0_2_0 import RAION_AIR, _setup

from custom_components.ukraine_alarm_pro.api.supervisor import MODE_POLL
from custom_components.ukraine_alarm_pro.const import (
    DOMAIN,
    ISSUE_FEED_UNAVAILABLE,
    ISSUE_WS_UNAVAILABLE,
    STALE_AFTER_SECONDS,
)


def _issue(hass: HomeAssistant, issue_id: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


async def _tick(hass: HomeAssistant) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()


async def test_polling_fallback_raises_no_issue(
    hass: HomeAssistant, enable_custom_integrations
):
    _, sup = await _setup(hass)
    sup.set_listener.call_args[0][0](RAION_AIR)
    sup.set_mode_listener.call_args[0][0](MODE_POLL)
    await _tick(hass)
    assert _issue(hass, ISSUE_WS_UNAVAILABLE) is None
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is None


async def test_no_data_from_any_source_raises_the_issue_and_data_clears_it(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, sup = await _setup(hass)
    push = sup.set_listener.call_args[0][0]
    push(RAION_AIR)
    entry.runtime_data.last_push = dt_util.utcnow() - timedelta(
        seconds=STALE_AFTER_SECONDS + 60
    )
    await _tick(hass)
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is not None

    push(RAION_AIR)
    await hass.async_block_till_done()
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is None


async def test_start_up_without_data_yet_raises_no_issue(
    hass: HomeAssistant, enable_custom_integrations
):
    await _setup(hass)
    await _tick(hass)
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is None


async def test_no_data_for_the_whole_stale_window_after_start_raises_the_issue(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    entry.runtime_data.started_at = dt_util.utcnow() - timedelta(
        seconds=STALE_AFTER_SECONDS + 60
    )
    await _tick(hass)
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is not None


async def test_setup_clears_a_websocket_issue_left_by_an_older_version(
    hass: HomeAssistant, enable_custom_integrations
):
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_WS_UNAVAILABLE,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_WS_UNAVAILABLE,
    )
    await _setup(hass)
    assert _issue(hass, ISSUE_WS_UNAVAILABLE) is None


async def test_unload_clears_the_issue(
    hass: HomeAssistant, enable_custom_integrations
):
    entry, _ = await _setup(hass)
    entry.runtime_data.started_at = dt_util.utcnow() - timedelta(
        seconds=STALE_AFTER_SECONDS + 60
    )
    await _tick(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert _issue(hass, ISSUE_FEED_UNAVAILABLE) is None
