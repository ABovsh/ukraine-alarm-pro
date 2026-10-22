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
  const period = { quality: "complete", coverage_complete: true, gap_seconds: 0, observed_duration_seconds: 5400,
    longest_duration_seconds: 3000, average_duration_seconds: 2700 };
  const episode = { observed_started_at: new Date(Date.now()-7200000).toISOString(), observed_cleared_at: new Date(Date.now()-3600000).toISOString() };
  return { states, entities, connection: window.connection, language: "en", locale: { language: "en" }, config: { time_zone: "Europe/Kyiv" },
    callWS: async (request) => { window.calls.push(request); return { response: request.service === "get_summary"
      ? { rolling_24h: day, rolling_7d: week, rolling_calculated_at: new Date(Date.now()).toISOString(), last_episode: [episode],
          calendar: { today: { ...period, start: new Date(Date.now()-3600000).toISOString(), count: 2, percentage: 12.5 },
                      month: { ...period, start: new Date(Date.now()-86400000).toISOString(), count: 40, percentage: 8.1, daily: [] } } }
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
        "button.setAttribute('data-old-a','a'); button.setAttribute('data-old-b','b'); "
        "hass.states['sensor.uap_31_threat'].attributes.region_name='Renamed Kyiv'; "
        "hass.states['sensor.uap_31_threat'].last_updated='b'; c.hass={...hass}"
    )
    assert await page.evaluate(
        "c.shadowRoot.querySelector('ha-card')===button && c.shadowRoot.activeElement===button"
    )
    assert not await page.evaluate("button.hasAttribute('data-old-a')")
    assert not await page.evaluate("button.hasAttribute('data-old-b')")
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
        "c._stats.summary.rolling_24h.coverage_complete=false; c._stats.summary.rolling_24h.quality='incomplete'; hass.states['sensor.uap_31_alert_percentage_24h'].state='unknown'; hass.states['sensor.uap_31_alert_percentage_24h'].attributes.quality='incomplete'; c._render()"
    )
    text = await page.evaluate("c.shadowRoot.textContent")
    assert "Part of the region" in text
    assert "Data is stale" in text
    assert "Incomplete statistics" in text
    assert await page.evaluate("document.documentElement.scrollWidth <= 360")
    await page.screenshot(path=str(tmp_path / "uap-mobile.png"))


async def test_editor_picks_hides_and_reorders_sections(page):
    """The visual editor writes `sections`/`hide`, drops a saved `layout`, and
    never lets the last section go."""
    await page.evaluate("""window.changes = [];
      window.ed = document.createElement('ukraine-alarm-pro-card-editor');
      ed.addEventListener('config-changed', (e) => changes.push(e.detail.config));
      document.body.appendChild(ed);
      ed.setConfig({ entity: 'binary_sensor.uap_31_alert', layout: 'status' });
      ed.hass = makeHass();""")
    rows = await page.evaluate(
        "[...ed.querySelectorAll('[data-toggle]')].map((i) => [i.dataset.toggle, i.checked])"
    )
    assert rows[:2] == [["status", True], ["details", True]]
    assert [key for key, on in rows if not on] == ["timeline", "stats"]
    await page.evaluate("ed.querySelector('[data-toggle=stats]').click()")
    assert await page.evaluate("changes.at(-1)") == {
        "entity": "binary_sensor.uap_31_alert",
        "sections": ["status", "details", "stats"],
    }
    await page.evaluate("ed.querySelector('[data-move=stats][data-dir=\"-1\"]').click()")
    assert await page.evaluate("changes.at(-1).sections") == ["status", "stats", "details"]
    await page.evaluate("ed.querySelector('[data-expand=stats]').click()")
    await page.evaluate("ed.querySelector('[data-item=\"stats.day\"]').click()")
    assert await page.evaluate("changes.at(-1).hide") == ["stats.day"]
    # The remaining tile cannot be hidden too; bar, longest and average never block one.
    for item in ("week", "today"):
        assert not await page.evaluate(f"ed.querySelector('[data-item=\"stats.{item}\"]').disabled")
        await page.evaluate(f"ed.querySelector('[data-item=\"stats.{item}\"]').click()")
    assert await page.evaluate("changes.at(-1).hide") == ["stats.day", "stats.week", "stats.today"]
    assert await page.evaluate("ed.querySelector('[data-item=\"stats.month\"]').disabled")
    for item in ("bar", "longest", "average"):
        assert not await page.evaluate(f"ed.querySelector('[data-item=\"stats.{item}\"]').disabled")
        await page.evaluate(f"ed.querySelector('[data-item=\"stats.{item}\"]').click()")
    assert await page.evaluate("changes.at(-1).hide") == [
        "stats.day", "stats.week", "stats.today", "stats.bar", "stats.longest", "stats.average"
    ]
    assert await page.evaluate("ed.querySelector('[data-item=\"stats.month\"]').disabled")
    await page.evaluate(
        "for (const k of ['details', 'stats']) ed.querySelector(`[data-toggle=${k}]`).click()"
    )
    assert await page.evaluate("changes.at(-1).sections") == ["status"]
    assert await page.evaluate("ed.querySelector('[data-toggle=status]').disabled")


async def test_quiet_timer_reads_the_cleared_sensor_without_journal_calls(page):
    """With `alert_cleared` published, a card without statistics needs no
    journal request at all; older integrations still get the service call."""
    await page.evaluate("""window.hass = makeHass();
      hass.states['sensor.uap_31_alert_cleared'] = { state: new Date(Date.now() - 5400000).toISOString(),
        attributes: { region_id: '31' }, last_updated: 'a' };
      hass.entities['sensor.uap_31_alert_cleared'] = { platform: 'ukraine_alarm_pro', translation_key: 'alert_cleared' };
      window.c = makeCard(hass, 'status');""")
    await page.clock.run_for(700000)
    assert await page.evaluate("calls.length") == 0
    text = await page.evaluate("c.shadowRoot.textContent")
    assert "no alerts since" in text
    assert "h" in text


async def test_all_four_tiles_have_the_same_compact_size(page):
    """24 h, 7 d, today and the month fill a two-by-two grid, every tile the same size."""
    await page.evaluate("window.hass=makeHass(); window.c=makeCard(hass)")
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats !== null")
    tiles = await page.evaluate(
        "[...c.shadowRoot.querySelectorAll('.sec.stats .kpi')].map((el) => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })"
    )
    assert len(tiles) == 4
    assert len({round(width) for _l, _t, width, _h in tiles}) == 1
    assert len({round(height) for _l, _t, _w, height in tiles}) == 1
    assert tiles[0][1] == tiles[1][1] and tiles[2][1] == tiles[3][1] and tiles[2][1] > tiles[0][1]
    assert tiles[0][2] < 200  # compact: half of a phone card, not the full width
