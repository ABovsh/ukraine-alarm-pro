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


def _lcov(profiles: list[dict]) -> str:
    """Map Chromium's precise function ranges to line coverage for Sonar."""
    source = CARD.read_text()
    source_lines = source.splitlines(keepends=True)
    starts = []
    offset = 0
    for line in source_lines:
        starts.append(offset)
        offset += len(line.encode("utf-16-le")) // 2
    end_offset = offset
    executable: set[int] = set()
    covered: set[int] = set()

    for profile in profiles:
        scripts = [
            script for script in profile.get("result", [])
            if script.get("url", "").endswith(CARD.name)
        ]
        if not scripts:
            raise AssertionError("Chromium did not report the Ukraine Alarm Pro card script")
        for script in scripts:
            functions = script.get("functions", [])
            root_ranges = [
                item for function in functions for item in function.get("ranges", [])
                if item.get("startOffset") == 0 and item.get("endOffset") == end_offset
            ]
            root_hit = any(item.get("count", 0) > 0 for item in root_ranges)
            ranges = [
                item for function in functions for item in function.get("ranges", [])
                if not (item.get("startOffset") == 0 and item.get("endOffset") == end_offset)
            ]
            for number, line in enumerate(source_lines, 1):
                stripped = line.strip()
                if (not stripped or stripped.startswith(("//", "/*", "*"))
                        or all(char in "{}[]();, " for char in stripped)):
                    continue
                start = starts[number - 1]
                line_executable = False
                line_hit = False
                for position, char in enumerate(line):
                    if char.isspace():
                        continue
                    point = start + len(line[:position].encode("utf-16-le")) // 2
                    active = [item for item in ranges
                              if item["startOffset"] <= point < item["endOffset"]]
                    if active:
                        line_executable = True
                        narrowest = min(item["endOffset"] - item["startOffset"] for item in active)
                        line_hit |= any(
                            item.get("count", 0) > 0
                            for item in active
                            if item["endOffset"] - item["startOffset"] == narrowest
                        )
                    elif root_ranges:
                        line_executable = True
                        line_hit |= root_hit
                if line_executable:
                    executable.add(number)
                    if line_hit:
                        covered.add(number)

    source_path = CARD.relative_to(Path(__file__).parent.parent).as_posix()
    records = [f"SF:{source_path}"]
    records.extend(f"DA:{number},{int(number in covered)}" for number in sorted(executable))
    records.append("end_of_record")
    return "\n".join(records) + "\n"


def test_lcov_does_not_let_the_script_scope_hide_unvisited_functions():
    source = CARD.read_text()
    lines = source.splitlines(keepends=True)
    starts = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line.encode("utf-16-le")) // 2
    target = next(index for index, line in enumerate(lines, 1) if line.startswith("function alertEntities"))
    end = starts[target - 1] + len(lines[target - 1].encode("utf-16-le")) // 2
    profile = {"result": [{
        "url": CARD.as_uri(),
        "functions": [
            {"functionName": "", "ranges": [{"startOffset": 0, "endOffset": offset, "count": 1}]},
            {"functionName": "alertEntities", "ranges": [{
                "startOffset": starts[target - 1], "endOffset": end, "count": 0,
            }]},
        ],
    }]}

    report = _lcov([profile])
    assert f"SF:{CARD.relative_to(Path(__file__).parent.parent).as_posix()}" in report
    assert f"DA:{target},0" in report


_CARD_COVERAGE_PROFILES: list[dict] = []


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
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Profiler.enable")
            await cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
            await page.add_script_tag(path=str(CARD))
            await page.evaluate(BOOT)
            yield page
        finally:
            if "cdp" in locals():
                _CARD_COVERAGE_PROFILES.append(await cdp.send("Profiler.takePreciseCoverage"))
                await cdp.detach()
            await browser.close()


async def test_full_cards_share_requests_and_server_percentages(page):
    await page.evaluate(
        "window.hass = makeHass(); window.c = makeCard(hass); window.c2 = makeCard(hass)"
    )
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats !== null && c2._stats !== null")
    assert await page.evaluate("calls.length") == 1
    text = await page.evaluate("c.shadowRoot.textContent")
    cells = await page.evaluate("[...c.shadowRoot.querySelectorAll('.tbl .c')].map((el) => el.textContent.trim())")
    assert "60" in cells  # the count column
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
    # The partial 24 h tile shows a yellow lamp; the reason is in its tooltip.
    assert await page.evaluate("c.shadowRoot.querySelectorAll('.tbl .lamp.warn').length") == 1
    assert "Incomplete statistics" in await page.evaluate("c.shadowRoot.querySelector('.tbl .lamp.warn').closest('.c').title")
    assert await page.evaluate("document.documentElement.scrollWidth <= 360")
    await page.screenshot(path=str(tmp_path / "uap-mobile.png"))


async def test_editor_picks_hides_and_reorders_sections(page):
    """The visual editor writes `sections`/`hide`, drops a saved `layout`, and
    never lets the last section go."""
    await page.evaluate("""customElements.define('ha-form', class extends HTMLElement {});
      window.changes = [];
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
    # Every item the editor offers has a label, in the table's own order.
    labels = await page.evaluate("[...ed.querySelectorAll('.items label')].map((l) => [l.querySelector('input').dataset.item, l.textContent.trim()])")
    assert [item for item, _text in labels] == [
        "stats.today", "stats.day", "stats.week", "stats.month", "stats.bar", "stats.total", "stats.count",
        "stats.longest", "stats.average", "stats.lamp",
    ]
    assert all(text for _item, text in labels), labels
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
    await page.evaluate("""ed._form.dispatchEvent(new CustomEvent('value-changed', {detail:{value:{
      entity:'binary_sensor.uap_31_alert', name:'', language:'auto'}}, bubbles:true}));""")
    assert await page.evaluate("changes.at(-1)") == {
        "entity": "binary_sensor.uap_31_alert", "sections": ["status"],
        "hide": ["stats.day", "stats.week", "stats.today", "stats.bar", "stats.longest", "stats.average"],
    }
    await page.evaluate("""ed._form.dispatchEvent(new CustomEvent('value-changed', {detail:{value:{
      entity:'binary_sensor.uap_31_alert', name:'Kyiv', language:'uk'}}, bubbles:true}));""")
    assert await page.evaluate("changes.at(-1).name") == "Kyiv"
    assert await page.evaluate("changes.at(-1).language") == "uk"


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


async def test_the_table_is_the_only_view_and_fits_every_phone_width(page):
    """No tiles: one table, compact enough for a 360 px phone and not overflowing at any width."""
    await page.evaluate("window.hass=makeHass(); window.c=makeCard(hass)")
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats !== null")
    assert await page.evaluate("c.shadowRoot.querySelector('.kpis') === null")
    for width in (320, 360, 390, 430, 700):
        await page.set_viewport_size({"width": width, "height": 800})
        state = await page.evaluate("""(() => {
          const table = c.shadowRoot.querySelector('.tbl');
          return { shown: getComputedStyle(table).display !== 'none', overflow: table.scrollWidth - table.clientWidth,
            height: table.getBoundingClientRect().height };
        })()""")
        assert state["shown"], width
        assert state["overflow"] <= 0, width
        assert state["height"] < 150, width  # a header and four lines, never wrapped
        # The completeness lamp is drawn: a coloured dot, not an empty inline element.
        lamp = await page.evaluate("""(() => {
          const el = c.shadowRoot.querySelector('.tbl .lamp.ok'), r = el.getBoundingClientRect();
          return [r.width, r.height, getComputedStyle(el).backgroundColor];
        })()""")
        assert lamp[0] >= 6 and lamp[1] >= 6 and lamp[2] != "rgba(0, 0, 0, 0)", width
