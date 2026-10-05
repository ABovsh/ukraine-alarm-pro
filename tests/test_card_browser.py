"""Real browser coverage for request cost, visibility, focus and mobile layout."""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pytest
import pytest_asyncio

playwright = pytest.importorskip("playwright.async_api")

CARD = (
    Path(__file__).parent.parent
    / "custom_components/ukraine_alarm_pro/frontend/ukraine-alarm-pro-card.js"
)
T0 = 1791115200000  # 2026-10-04 12:00 UTC

BOOT = """
window.calls = []; window.opened = [];
window.connection = {};
window.makeHass = () => {
  const states = {}, entities = {};
  const add = (id, key, state, attributes={}) => {
    states[id] = { state, attributes: { region_id: "31", ...attributes }, last_updated: "a" };
    entities[id] = { platform: "ukraine_alarm_pro", translation_key: key };
  };
  add("binary_sensor.uap_31_alert", "alert", "off", { friendly_name: "Kyiv alert" });
  add("sensor.uap_31_threat", "threat", "none", { region_name: "Kyiv", coverage: "none" });
  add("sensor.uap_31_air_alert_level", "air_alert_level", "none");
  add("sensor.uap_31_alert_started", "alert_started", "unknown");
  add("event.uap_31_event", "event", "event1");
  add("sensor.uap_last_update", "last_update", new Date(Date.now()).toISOString());
  add("binary_sensor.uap_data_stale", "data_stale", "off");
  add("sensor.uap_31_alert_percentage_24h", "alert_percentage_24h", "4.2", { quality: "complete" });
  add("sensor.uap_31_alert_percentage_7d", "alert_percentage_7d", "0.6", { quality: "complete" });
  const day = { percentage: 4.2, coverage_complete: true, quality: "complete", count: 60,
    observed_duration_seconds: 3600, intervals: [{ start: new Date(Date.now()-3600000).toISOString(), end: new Date(Date.now()).toISOString() }] };
  const week = { ...day, percentage: 0.6 };
  const episode = { observed_started_at: new Date(Date.now()-7200000).toISOString(), observed_cleared_at: new Date(Date.now()-3600000).toISOString() };
  return { states, entities, connection: window.connection, language: "en", locale: { language: "en" }, config: { time_zone: "Europe/Kyiv" },
    callWS: async (request) => { window.calls.push(request); return { response: request.service === "get_summary"
      ? { rolling_24h: day, rolling_7d: week, rolling_calculated_at: new Date(Date.now()).toISOString(), last_episode: [episode] }
      : { episodes: [episode] } }; } };
};
window.makeCard = (hass, layout="full") => {
  const card = document.createElement("ukraine-alarm-pro-card");
  card.setConfig({ entity: "binary_sensor.uap_31_alert", layout, language: "en" });
  card.hass = hass;
  card.addEventListener("hass-more-info", (e) => window.opened.push(e.detail.entityId));
  document.body.appendChild(card);
  return card;
};
"""


@pytest_asyncio.fixture
async def page():
    paths = sorted(
        glob.glob(
            str(
                Path.home()
                / ".cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"
            )
        )
    )
    libs = Path.home() / ".cache/shahed-radar-browser/usr/lib/x86_64-linux-gnu"
    env = dict(os.environ)
    if libs.is_dir():
        env["LD_LIBRARY_PATH"] = f"{libs}:{env.get('LD_LIBRARY_PATH', '')}"
    async with playwright.async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path=paths[-1] if paths else None, env=env
        )
        try:
            page = await browser.new_page(viewport={"width": 360, "height": 800})
            await page.clock.install(time=T0)
            await page.set_content('<body style="margin:8px"></body>')
            await page.add_script_tag(path=str(CARD))
            await page.evaluate(BOOT)
            yield page
        finally:
            await browser.close()


async def test_full_cards_share_requests_and_server_percentages(page):
    await page.evaluate(
        "window.hass = makeHass(); window.c = makeCard(hass); window.c2 = makeCard(hass)"
    )
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats !== null && c2._stats !== null")
    assert await page.evaluate("calls.length") == 1
    text = await page.evaluate("c.shadowRoot.textContent")
    assert "60 alerts" in text
    assert "4.2%" in text
    assert "0.6%" in text
    assert await page.evaluate("calls[0].service_data.days") == 7


async def test_compact_active_card_does_not_fetch_journal(page):
    await page.evaluate(
        "window.hass=makeHass(); hass.states['binary_sensor.uap_31_alert'].state='on'; window.c=makeCard(hass,'compact')"
    )
    await page.clock.run_for(360000)
    assert await page.evaluate("calls.length") == 0


async def test_keyboard_and_focus_survive_dom_updates(page):
    await page.evaluate("window.hass=makeHass(); window.c=makeCard(hass,'status')")
    await page.clock.run_for(200)
    await page.evaluate(
        "window.button=c.shadowRoot.querySelector('ha-card'); button.focus()"
    )
    await page.keyboard.press("Enter")
    await page.clock.run_for(30000)
    await page.evaluate(
        "hass.states['sensor.uap_31_threat'].attributes.region_name='Renamed Kyiv'; c.hass={...hass}"
    )
    assert await page.evaluate(
        "c.shadowRoot.querySelector('ha-card')===button && c.shadowRoot.activeElement===button"
    )
    await page.keyboard.press("Space")
    assert await page.evaluate("opened") == ["binary_sensor.uap_31_alert"] * 2


async def test_hidden_and_offscreen_cards_suspend_requests(page):
    await page.evaluate("window.hass=makeHass(); window.c=makeCard(hass)")
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats !== null")
    assert await page.evaluate("calls.length") == 1
    await page.evaluate(
        "Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    await page.clock.run_for(700000)
    assert await page.evaluate("calls.length") == 1
    await page.evaluate(
        "Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'}); document.dispatchEvent(new Event('visibilitychange'))"
    )
    await page.clock.run_for(200)
    assert await page.evaluate("calls.length") == 2
    await page.evaluate("c.style.display='block'; c.style.marginTop='10000px'")
    await page.clock.run_for(200)
    await page.wait_for_function("c._inView===false")
    await page.clock.run_for(700000)
    assert await page.evaluate("calls.length") == 2


async def test_mobile_stale_incomplete_and_partial_are_distinct(page, tmp_path):
    await page.evaluate("""window.hass=makeHass(); window.c=makeCard(hass);
      hass.states['binary_sensor.uap_31_alert'].state='on';
      hass.states['binary_sensor.uap_data_stale'].state='on';
      hass.states['sensor.uap_31_threat'].attributes.coverage='partial';
      hass.states['sensor.uap_31_threat'].attributes.active_threat_types='air';
      c.hass={...hass};""")
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats !== null")
    await page.evaluate(
        "c._stats.summary.rolling_24h.coverage_complete=false; hass.states['sensor.uap_31_alert_percentage_24h'].state='unknown'; c._render()"
    )
    text = await page.evaluate("c.shadowRoot.textContent")
    assert "Part of the region" in text
    assert "Data is stale" in text
    assert "Incomplete statistics" in text
    assert await page.evaluate("document.documentElement.scrollWidth <= 360")
    await page.screenshot(path=str(tmp_path / "uap-mobile.png"))
