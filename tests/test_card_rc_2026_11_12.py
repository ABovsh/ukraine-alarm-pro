"""Card regressions found 2026-11-12: list startup discovery and editor redraws."""

from test_card_browser import _add_region
from test_card_browser import page as browser_page_fixture

page = browser_page_fixture


async def test_list_discovers_regions_and_sensors_that_arrive_after_the_first_render(page):
    """After an HA restart the alert states can arrive before their sensors and
    before other listed regions; the registry object stays the same, so the
    list must not keep the first, partial lookup forever."""
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(_add_region("692", "Hatne"))
    await page.evaluate("""window.full = { ...hass.states };
      hass.states = { 'binary_sensor.uap_31_alert': full['binary_sensor.uap_31_alert'] };
      window.c = document.createElement('ukraine-alarm-pro-card');
      c.setConfig({ entities: ['binary_sensor.uap_31_alert', 'binary_sensor.uap_692_alert'], language: 'en' });
      c.hass = hass;
      document.body.appendChild(c);""")
    assert await page.evaluate("c.shadowRoot.querySelectorAll('.lrow').length") == 1
    await page.evaluate("c.hass = { ...hass, states: full }")
    rows = await page.evaluate("[...c.shadowRoot.querySelectorAll('.lrow')].map((r) => r.textContent)")
    assert len(rows) == 2
    assert "Kyiv" in rows[0] and "4.2%" in rows[0]
    assert "Hatne" in rows[1] and "12.5%" in rows[1]


async def test_editor_keeps_its_controls_while_home_assistant_states_change(page):
    """HA hands the editor a new `hass` on every state change. Rebuilding the
    section list then drops keyboard focus and swallows a click whose press and
    release straddle the update."""
    await page.evaluate("""customElements.define('ha-form', class extends HTMLElement {});
      window.ed = document.createElement('ukraine-alarm-pro-card-editor');
      document.body.appendChild(ed);
      ed.setConfig({ entity: 'binary_sensor.uap_31_alert' });
      ed.hass = makeHass();
      window.box = ed.querySelector('[data-toggle=details]');
      box.focus();
      ed.hass = makeHass();""")
    assert await page.evaluate("ed.querySelector('[data-toggle=details]') === box")
    assert await page.evaluate("document.activeElement === box")
    # A language change still relabels the editor.
    await page.evaluate("const h = makeHass(); h.locale = { language: 'uk' }; ed.hass = h;")
    assert await page.evaluate("ed.querySelector('.top b').textContent") == "Розділи"


async def test_24h_strip_is_marked_incomplete_only_by_the_24h_data(page):
    """The strip draws the last 24 hours; a gap five days ago (a restart) made
    the 7-day share unknown and hatched a complete 24 h strip for a week."""
    await page.evaluate("""window.hass = makeHass();
      hass.states['sensor.uap_31_alert_percentage_7d'] = { ...hass.states['sensor.uap_31_alert_percentage_7d'],
        state: 'unknown', attributes: { region_id: '31', quality: 'gaps', coverage_complete: false } };
      window.c = makeCard(hass);""")
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats?.summary")
    await page.evaluate("c._render()")
    assert await page.evaluate("c.shadowRoot.querySelector('.strip').className") == "strip"
    await page.evaluate("""c.hass = { ...hass, states: { ...hass.states, 'sensor.uap_31_alert_percentage_24h': {
        ...hass.states['sensor.uap_31_alert_percentage_24h'], state: 'unknown', last_updated: 'b',
        attributes: { region_id: '31', quality: 'gaps', coverage_complete: false } } } };""")
    await page.evaluate("c._render()")
    assert await page.evaluate("c.shadowRoot.querySelector('.strip').className") == "strip incomplete"
    # A share given despite a short gap leaves the strip plain.
    await page.evaluate("""c.hass = { ...hass, states: { ...hass.states, 'sensor.uap_31_alert_percentage_24h': {
        ...hass.states['sensor.uap_31_alert_percentage_24h'], state: '3.1', last_updated: 'c',
        attributes: { region_id: '31', quality: 'gaps', coverage_complete: false } } } };""")
    await page.evaluate("c._render()")
    assert await page.evaluate("c.shadowRoot.querySelector('.strip').className") == "strip"
