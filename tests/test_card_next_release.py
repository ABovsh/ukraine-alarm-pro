"""Card: country-wide threats, the usual alert length, one level chip, tap and hold actions."""

from test_card_browser import _add_region
from test_card_browser import page as browser_page_fixture

page = browser_page_fixture

HUB = """(() => {
  const hub = (id, key, state, attributes={}) => {
    hass.states[id] = { state, attributes, last_updated: 'a' };
    hass.entities[id] = { platform: 'ukraine_alarm_pro', translation_key: key };
  };
  hub('sensor.uap_mig_status', 'mig_status', 'takeoff', { airfield: 'savasleika', since: new Date(Date.now() - 600000).toISOString() });
  hub('sensor.uap_ballistics', 'ballistics', 'active');
  hub('sensor.uap_strategic_aviation', 'strategic_aviation', 'none');
  hub('sensor.uap_tactical_aviation', 'tactical_aviation', 'unknown');
  hub('sensor.uap_missile_carriers', 'missile_carriers', 'launch', { since: new Date(Date.now() - 300000).toISOString() });
})()"""

ALERT = """(() => {
  hass.states['binary_sensor.uap_31_alert'].state = 'on';
  hass.states['sensor.uap_31_threat'] = { ...hass.states['sensor.uap_31_threat'], state: 'air',
    attributes: { ...hass.states['sensor.uap_31_threat'].attributes, active_threat_types: 'air', coverage: 'whole' } };
  hass.states['sensor.uap_31_air_alert_level'] = { state: 'red', last_updated: 'b',
    attributes: { region_id: '31', reasons: ['Ракетна загроза (червоний рівень)'] } };
  hass.states['sensor.uap_31_alert_started'] = { state: new Date(Date.now() - 25 * 60000).toISOString(),
    attributes: { region_id: '31' }, last_updated: 'b' };
})()"""

TYPICAL = """(() => {
  const plain = hass.callWS;
  hass.callWS = async (request) => {
    const reply = await plain(request);
    if (request.service === 'get_summary') reply.response.typical = { count: 598, median_seconds: 1980, p75_seconds: 4200, days: 90 };
    return reply;
  };
})()"""


def _card(config: str) -> str:
    return f"""window.c = document.createElement('ukraine-alarm-pro-card');
      c.setConfig({{ entity: 'binary_sensor.uap_31_alert', language: 'en', ...{config} }});
      c.hass = hass;
      window.events = [];
      for (const type of ['hass-more-info', 'hass-action']) c.addEventListener(type, (e) => events.push([type, e.detail]));
      document.body.appendChild(c);"""


async def test_country_threats_share_one_row_in_feed_order(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(HUB)
    await page.evaluate(_card("{ sections: ['status'] }"))
    chips = await page.evaluate("[...c.shadowRoot.querySelectorAll('.country .ct')].map((e) => [e.className, e.textContent])")
    assert [cls for cls, _ in chips] == ["ct mig takeoff", "ct ballistics active", "ct missile_carriers launch"]
    assert "Savasleyka" in chips[0][1]
    assert chips[1][1] == "Ballistic threat"
    assert chips[2][1].startswith("Missile launch from ships · since ")
    # A chip opens its own sensor, whatever the card's tap action is.
    await page.evaluate("c.setConfig({ ...c._config, tap_action: { action: 'navigate', navigation_path: '/x' } }); c.hass = { ...hass }")
    await page.evaluate("c.shadowRoot.querySelector('.ct.ballistics').click()")
    assert await page.evaluate("events") == [["hass-more-info", {"entityId": "sensor.uap_ballistics"}]]
    await page.evaluate("c.setConfig({ ...c._config, hide: ['status.mig'] })")
    assert await page.evaluate("c.shadowRoot.querySelector('.country')") is None


async def test_the_list_carries_the_country_row_above_the_regions(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(HUB)
    await page.evaluate(_add_region("692", "Hatne"))
    await page.evaluate("""window.c = document.createElement('ukraine-alarm-pro-card');
      c.setConfig({ entities: ['binary_sensor.uap_31_alert', 'binary_sensor.uap_692_alert'], language: 'en' });
      c.hass = hass; document.body.appendChild(c);""")
    html = await page.evaluate("c.shadowRoot.innerHTML")
    assert html.index('class="country"') < html.index('class="lrow')
    assert html.count('class="ct ') == 3


async def test_quiet_country_draws_no_row(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(_card("{ sections: ['status'] }"))
    assert await page.evaluate("c.shadowRoot.querySelector('.country')") is None


async def test_an_alert_shows_how_long_it_usually_lasts(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(ALERT)
    await page.evaluate(TYPICAL)
    # A status-only card asks for the summary only while an alert runs.
    await page.evaluate(_card("{ sections: ['status'] }"))
    await page.clock.run_for(200)
    await page.wait_for_function("c.shadowRoot.querySelector('.typ')")
    text = await page.evaluate("c.shadowRoot.querySelector('.typ').textContent")
    assert "Usually ~33 min" in text and "one in four over 1 h 10 min" in text and "90 days" in text
    bar = await page.evaluate("c.shadowRoot.querySelector('.typbar i').style.width")
    assert 0 < float(bar.rstrip("%")) < 100
    assert await page.evaluate("calls.map((call) => call.service)") == ["get_summary"]


async def test_the_usual_length_is_optional_and_never_shown_when_quiet(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(TYPICAL)
    await page.evaluate(_card("{ sections: ['status', 'stats'] }"))
    await page.clock.run_for(200)
    await page.wait_for_function("c._stats?.summary")
    await page.evaluate("c._render()")
    assert await page.evaluate("c.shadowRoot.querySelector('.typ')") is None
    await page.evaluate(ALERT)
    await page.evaluate("calls.length = 0")
    for config in ("{ sections: ['status'], hide: ['status.typical'] }", "{ layout: 'compact' }"):
        await page.evaluate(_card(config))
        await page.clock.run_for(200)
        assert await page.evaluate("c.shadowRoot.querySelector('.typ')") is None
    # Neither card needs the journal.
    assert await page.evaluate("calls.length") == 0


async def test_the_reason_joins_the_level_chip(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(ALERT)
    await page.evaluate(_card("{ sections: ['details'] }"))
    assert await page.evaluate("c.shadowRoot.querySelector('.chip.level').textContent") == "Ракетна загроза · red"
    assert await page.evaluate("c.shadowRoot.querySelector('.reasons')") is None
    # Without the level chip the reason keeps its own line, in full.
    await page.evaluate("c.setConfig({ ...c._config, hide: ['details.level'] })")
    assert await page.evaluate("c.shadowRoot.querySelector('.reasons').textContent") == "Ракетна загроза (червоний рівень)"
    await page.evaluate("c.setConfig({ ...c._config, hide: ['details.reason'] })")
    assert await page.evaluate("c.shadowRoot.querySelector('.chip.level').textContent") == "Red level"


async def test_tap_and_hold_run_the_configured_actions(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(_card("{ sections: ['status'] }"))
    await page.evaluate("c.shadowRoot.querySelector('ha-card').click()")
    # No action set: a tap still opens the region, as before.
    assert await page.evaluate("events") == [["hass-more-info", {"entityId": "binary_sensor.uap_31_alert"}]]
    await page.evaluate("""events.length = 0;
      c.setConfig({ ...c._config, tap_action: { action: 'navigate', navigation_path: '/alarm' },
        hold_action: { action: 'more-info' } });""")
    await page.evaluate("c.shadowRoot.querySelector('ha-card').click()")
    tap = await page.evaluate("events")
    assert tap[0][0] == "hass-action" and tap[0][1]["action"] == "tap"
    assert tap[0][1]["config"]["entity"] == "binary_sensor.uap_31_alert"
    assert tap[0][1]["config"]["tap_action"] == {"action": "navigate", "navigation_path": "/alarm"}
    await page.evaluate("""events.length = 0; const card = c.shadowRoot.querySelector('ha-card');
      card.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, composed: true }));""")
    await page.clock.run_for(600)
    await page.evaluate("""const card2 = c.shadowRoot.querySelector('ha-card');
      card2.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, composed: true })); card2.click();""")
    held = await page.evaluate("events")
    # The release after a hold is not also a tap.
    assert [(kind, detail["action"]) for kind, detail in held] == [("hass-action", "hold")]
    # A short press is a tap.
    await page.evaluate("""events.length = 0; const card3 = c.shadowRoot.querySelector('ha-card');
      card3.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, composed: true }));""")
    await page.clock.run_for(100)
    await page.evaluate("const card4 = c.shadowRoot.querySelector('ha-card'); card4.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, composed: true })); card4.click();")
    await page.clock.run_for(600)
    assert [detail["action"] for _kind, detail in await page.evaluate("events")] == ["tap"]


async def test_double_tap_waits_only_when_configured(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(_card("{ sections: ['status'], double_tap_action: { action: 'toggle' } }"))
    await page.evaluate("const k = c.shadowRoot.querySelector('ha-card'); k.click(); k.click();")
    await page.clock.run_for(400)
    assert [detail.get("action") for _kind, detail in await page.evaluate("events")] == ["double_tap"]
    await page.evaluate("events.length = 0; c.shadowRoot.querySelector('ha-card').click()")
    assert await page.evaluate("events.length") == 0
    await page.clock.run_for(400)
    assert await page.evaluate("events[0][0]") == "hass-more-info"


async def test_list_rows_run_the_action_for_their_own_region(page):
    await page.evaluate("window.hass = makeHass()")
    await page.evaluate(_add_region("692", "Hatne"))
    await page.evaluate("""window.c = document.createElement('ukraine-alarm-pro-card');
      c.setConfig({ entities: ['binary_sensor.uap_31_alert', 'binary_sensor.uap_692_alert'], language: 'en',
        tap_action: { action: 'more-info' } });
      c.hass = hass; window.events = [];
      c.addEventListener('hass-action', (e) => events.push(e.detail));
      document.body.appendChild(c);""")
    await page.evaluate("c.shadowRoot.querySelectorAll('.lrow')[1].click()")
    assert await page.evaluate("events[0].config.entity") == "binary_sensor.uap_692_alert"


async def test_editor_sets_tap_and_hold_actions(page):
    await page.evaluate("""customElements.define('ha-form', class extends HTMLElement {});
      window.changes = [];
      window.ed = document.createElement('ukraine-alarm-pro-card-editor');
      ed.addEventListener('config-changed', (e) => changes.push(e.detail.config));
      document.body.appendChild(ed);
      ed.setConfig({ entity: 'binary_sensor.uap_31_alert', hold_action: { action: 'more-info' } });
      ed.hass = makeHass();""")
    names = await page.evaluate("ed._form.schema.map((field) => field.name)")
    assert "tap_action" in names and "hold_action" in names
    assert await page.evaluate("ed._form.data.hold_action") == {"action": "more-info"}
    assert await page.evaluate("ed._form.computeLabel({ name: 'tap_action' })") == "Tap action"
    await page.evaluate("""ed._form.dispatchEvent(new CustomEvent('value-changed', { detail: { value: {
      entity: ['binary_sensor.uap_31_alert'], tap_action: { action: 'navigate', navigation_path: '/a' } } } }));""")
    config = await page.evaluate("changes.at(-1)")
    assert config["tap_action"] == {"action": "navigate", "navigation_path": "/a"}
    assert "hold_action" not in config
    labels = await page.evaluate("""(() => { ed.querySelector('[data-expand=status]').click();
      return [...ed.querySelectorAll('.items label')].map((l) => l.textContent); })()""")
    assert "Country-wide threats" in labels and "Usual length" in labels
