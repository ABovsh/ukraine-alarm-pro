"""rc audit 2026-09-15: quiet-feed resyncs, level flicker, card retry."""

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_entities import ENTRY_DATA

from custom_components.ukraine_alarm_pro.api.poll import DEFAULT_TIMEOUT
from custom_components.ukraine_alarm_pro.api.supervisor import (
    DEFAULT_STALE_AFTER,
    DEFAULT_WATCHDOG_INTERVAL,
)
from custom_components.ukraine_alarm_pro.const import DOMAIN, STALE_AFTER_SECONDS
from custom_components.ukraine_alarm_pro.events import (
    ORIGIN_BOOTSTRAP,
    ORIGIN_LIVE,
    AlertEventHub,
    RegionState,
)

CARD = (
    Path(__file__).parent.parent
    / "custom_components/ukraine_alarm_pro/frontend/ukraine-alarm-pro-card.js"
)


async def test_watchdog_cross_checks_a_quiet_feed_before_it_counts_as_stale(
    hass: HomeAssistant, enable_custom_integrations
):
    """A healthy but quiet WS must be refreshed before the stale limit.

    The cross-check used to start only once the data was already 900 s old —
    exactly the stale limit — so every quiet quarter hour published a
    `resynced` event for every region and marked journal gaps.
    """
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, entry_id="wd1")
    entry.add_to_hass(hass)
    sup = AsyncMock()
    sup.mode = "websocket"
    sup.set_listener = MagicMock()
    sup.set_mode_listener = MagicMock()
    with patch(
        "custom_components.ukraine_alarm_pro.TransportSupervisor", return_value=sup
    ) as factory:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    kwargs = factory.call_args.kwargs
    check_after = kwargs.get("stale_after", DEFAULT_STALE_AFTER)
    interval = kwargs.get("watchdog_interval", DEFAULT_WATCHDOG_INTERVAL)
    # Worst case: the check starts one tick late and the request times out.
    assert check_after + interval + DEFAULT_TIMEOUT < STALE_AFTER_SECONDS


def _air(level: str) -> RegionState:
    return RegionState(active=True, threat_types=("air",), air_level=level)


def _run(hub: AlertEventHub, levels: list[str]) -> list[str]:
    seen: list[str] = []
    hub.add_listener("31", lambda event_type, _payload: seen.append(event_type))
    hub.accept({"31": ("Київ", RegionState())}, origin=ORIGIN_BOOTSTRAP, observed_at="t0")
    for i, level in enumerate(levels, 1):
        hub.accept({"31": ("Київ", _air(level))}, origin=ORIGIN_LIVE, observed_at=f"t{i}")
    return seen


def test_level_briefly_unspecified_does_not_escalate_on_its_return():
    """yellow → unrecognized → yellow is no rise; the level was just missing."""
    assert _run(AlertEventHub(), ["yellow", "unrecognized", "yellow"])[1:] == [
        "started",
        "updated",
        "updated",
    ]
    assert _run(AlertEventHub(), ["red", "unrecognized", "red"])[1:] == [
        "started",
        "updated",
        "updated",
    ]


def test_real_rise_across_an_unspecified_level_still_escalates():
    assert _run(AlertEventHub(), ["yellow", "unrecognized", "red"])[1:] == [
        "started",
        "updated",
        "escalated",
    ]
    assert _run(AlertEventHub(), ["yellow", "red"])[1:] == ["started", "escalated"]


def test_known_level_is_forgotten_after_the_air_alert_ends():
    hub = AlertEventHub()
    seen = _run(hub, ["red"])
    hub.accept({"31": ("Київ", RegionState())}, origin=ORIGIN_LIVE, observed_at="c")
    hub.accept({"31": ("Київ", _air("unrecognized"))}, origin=ORIGIN_LIVE, observed_at="s")
    hub.accept({"31": ("Київ", _air("red"))}, origin=ORIGIN_LIVE, observed_at="r")
    assert seen[1:] == ["started", "cleared", "started", "escalated"]


_CARD_HARNESS = r"""
const fs = require("fs");
let now = 1_000_000;
Date.now = () => now;
let Card;
globalThis.HTMLElement = class {};
globalThis.window = globalThis;
globalThis.customElements = {
  get: () => Card,
  define: (_name, cls) => { Card = cls; },
};
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
eval(fs.readFileSync(process.argv[2], "utf8"));
Card.prototype._render = () => {};
const card = new Card();
Object.defineProperty(card, "isConnected", { value: true });
card.setConfig({ entity: "binary_sensor.uap_31_alert", layout: "compact" });
let calls = 0;
let fail = true;
const hass = {
  states: { "binary_sensor.uap_31_alert": { state: "off", attributes: { region_id: "31" } } },
  entities: {},
  callWS: () => {
    calls += 1;
    return fail ? Promise.reject(new Error("not connected")) : Promise.resolve({ response: {} });
  },
};
const settle = () => new Promise((resolve) => setImmediate(resolve));
(async () => {
  card.hass = hass;
  await settle();
  const afterFailure = calls;
  fail = false;
  // Not on every state update: the retry waits.
  card._maybeRefresh();
  await settle();
  const immediate = calls;
  now += 5 * 60 * 1000;
  card._maybeRefresh();
  await settle();
  console.log(JSON.stringify({ afterFailure, immediate, afterRetry: calls }));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_card_retries_statistics_after_a_failed_call(tmp_path):
    """One failed call (a reconnect, a restart) must not end statistics for good."""
    harness = tmp_path / "harness.js"
    harness.write_text(_CARD_HARNESS, encoding="utf-8")
    out = subprocess.run(
        ["node", str(harness), str(CARD)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["afterFailure"] == 2  # get_summary + get_history
    assert result["immediate"] == result["afterFailure"]
    assert result["afterRetry"] > result["afterFailure"]
