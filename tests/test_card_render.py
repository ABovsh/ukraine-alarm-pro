"""The card renders the same HTML for fixed scenarios (node harness snapshot).

Regenerate after an intentional change: UAP_UPDATE_SNAPSHOTS=1 pytest tests/test_card_render.py
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).parent
CARD = HERE.parent / "custom_components/ukraine_alarm_pro/frontend/ukraine-alarm-pro-card.js"
SNAPSHOT = HERE / "snapshots/card_render.json"


def _render() -> dict:
    out = subprocess.run(
        ["node", str(HERE / "card_render_harness.js"), str(CARD)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        env={**os.environ, "TZ": "UTC"},
    )
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_card_render_matches_the_snapshot():
    rendered = _render()
    if os.environ.get("UAP_UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(json.dumps(rendered, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert rendered.keys() == expected.keys()
    for name, html in expected.items():
        assert rendered[name] == html, name


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_card_layouts_show_what_the_readme_promises():
    rendered = _render()
    assert "stats" not in rendered["quiet_status"]
    assert "stats" in rendered["quiet_full"]
    assert "chips" not in rendered["alert_red_compact"]
    assert "Червоний рівень" in rendered["alert_red_compact"]
    assert "Немає свіжих даних" in rendered["stale"]
    assert "&lt;b&gt;" in rendered["forced_uk_on_en"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_card_is_compact_on_a_phone():
    """Region, status and duration used to stack into three rows on any card
    under 420 px — every phone — leaving the right half empty. The timer keeps
    the right-hand column down to a half-width tile, and the quiet layouts no
    longer repeat "all quiet" in a second line."""
    rendered = _render()
    for name in ("quiet_status", "quiet_full_no_stats"):
        assert "Активних тривог немає" not in rendered[name], name
        assert 'class="note"' not in rendered[name], name
    # The harness drops the stylesheet, so the breakpoint is read from the source.
    style = CARD.read_text(encoding="utf-8")
    assert "@container (max-width: 280px)" in style
    assert "max-width: 420px" not in style


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_fresh_data_needs_no_footer_but_stale_data_is_explicit():
    """A footer saying "data is current" on every card is noise; the update time
    rides in the region line, and only stale data gets its own warning."""
    rendered = _render()
    for name in ("quiet_status", "quiet_full", "alert_red_status"):
        assert 'class="foot' not in rendered[name], name
        assert "Дані актуальні" not in rendered[name], name
        assert "оновлено" in rendered[name], name
    assert "оновлено" not in rendered["quiet_compact"]
    assert "Немає свіжих даних" in rendered["stale"]
    assert "оновлено" in rendered["stale"]
    alert_stale = _render_one("alert_stale")
    assert "Дані застаріли" in alert_stale


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_full_layout_shows_two_percentage_tiles_and_clock_marks():
    rendered = _render()
    full = rendered["quiet_full"]
    assert len(re.findall(r'class="kpi[" ]', full)) == 2
    assert "24 год" in full
    assert "7 днів" in full
    # Rolling 24 h strip labelled with real Kyiv clock hours, ending at "now".
    assert "зараз" in full
    assert "18:00" in full or "12:00" in full


def _render_one(name: str) -> str:
    return _render()[name]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_card_is_built_from_the_sections_the_user_picked():
    """One modular card: sections render in the chosen order, items hide one by
    one, and saved layout configs open as the sections they used to show."""
    rendered = _render()
    reordered = rendered["sections_reordered"]
    assert reordered.index('sec stats') < reordered.index('sec head')
    assert 'class="strip' not in reordered
    assert 'class="chips' not in reordered
    details = rendered["sections_details_only"]
    assert 'sec head' not in details
    assert "Червоний рівень" in details
    assert "Загроза артобстрілу" in details
    assert "Частина регіону" not in details
    assert "Балістика" not in details
    assert 'class="timer' not in rendered["sections_status_no_timer"]
    # Without the details section the level still shows, next to the region.
    assert "Червоний рівень" in rendered["sections_status_no_timer"]
    week = rendered["sections_week_only"]
    assert "7 днів" in week
    assert "24 год" not in week
    sizes = {row[0]: row for row in map(tuple, rendered["card_size"])}
    assert sizes["status"][1] == "status.updated"  # legacy compact
    assert ("status,details", "") in {row[:2] for row in sizes.values()}
    assert "timeline" in rendered["card_size"][0][0]  # legacy full = every section
    assert rendered["card_size"][3][0] == rendered["card_size"][0][0]  # unknown layout = full
    assert "status, details, timeline, stats" in rendered["bad_section"]
    assert rendered["stub"]["sections"] == ["status", "details", "timeline", "stats"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_four_equal_tiles_share_one_format_and_nothing_repeats_below():
    """24 h, 7 d, the month and today look alike: share as the headline with a bar,
    duration and count, then the longest and the average alert. No statistics line
    repeats them under the tiles."""
    rendered = _render()
    full = rendered["calendar_full"]
    assert len(re.findall(r'class="kpi[" ]', full)) == 4
    assert full.count('class="k-bar"') == 4
    assert "36,7 %" in full  # sensor value
    assert "27,4 %" in full  # 165413 / (604800 - 55)
    assert "29,5 %" in full and "35,6 %" in full
    for label in ("24 год", "7 днів", "Сьогодні", "Вересень"):
        assert label in full, label
    assert "вересня" not in full
    assert "1 год 15 хв" in full and "2 тривоги" in full  # today
    assert full.count("найдовша") == 4 and full.count("середня") == 4
    assert 'class="hint"' not in full and "Найдовша" not in full
    assert 'class="sec records"' not in full
    english = rendered["calendar_english"]
    assert "Today" in english and "September" in english and "longest" in english
    # Without `calendar` the rolling tiles keep their format and no calendar tile appears.
    quiet = rendered["quiet_full"]
    assert len(re.findall(r'class="kpi[" ]', quiet)) == 2
    assert "Сьогодні" not in quiet
    # A `records` section saved by 0.12 is dropped, the rest of the card stays.
    legacy = rendered["records_dropped"]
    assert 'class="sec head"' in legacy and "kpi" not in legacy


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_tiles_are_customisable_and_say_what_is_missing():
    rendered = _render()
    bare = rendered["calendar_no_details"]
    assert 'class="k-bar"' not in bare
    assert "найдовша" not in bare and "середня" not in bare
    assert "36,7 %" in bare and "Сьогодні" in bare and "тривог" in bare
    quiet = rendered["calendar_quiet"]
    assert "без тривог" in quiet
    assert "0,0 %" in quiet or "0 %" in quiet
    assert "середня" not in quiet
    # A small lamp in every tile: green when the data is complete, yellow when it is partial.
    full = rendered["calendar_full"]
    assert full.count('class="lamp ok"') == 4 and 'class="lamp warn"' not in full
    gaps = rendered["calendar_gaps_month"]
    assert "були перерви в даних: 55 с" in full  # a week with 55 s of gaps
    assert 'class="lamp ok"' in gaps  # 99 s of a month changes the share by nothing
    assert "були перерви в даних: 1 хв" in gaps  # but the tooltip keeps the exact gap
    assert rendered["calendar_big_gaps_month"].count('class="lamp warn"') == 1
    incomplete = rendered["calendar_incomplete_month"]
    assert incomplete.count('class="lamp warn"') == 1
    assert re.search(r'title="[^"]*Неповна статистика: дані з \d\d\.\d\d', incomplete)
    assert 'class="lamp warn"' in rendered["calendar_today_gaps"]
    assert 'class="lamp warn"' in rendered["calendar_stale_week"]
    no_percent = rendered["calendar_no_percent"]
    assert "—" in no_percent and 'class="lamp warn"' in no_percent
    # The lamp replaces the text under the tile and can be switched off.
    assert 'class="k-note"' not in json.dumps(rendered)
    assert "lamp" not in rendered["calendar_no_details"]
    only = rendered["calendar_today_only"]
    assert len(re.findall(r'class="kpi[" ]', only)) == 1
    assert "Сьогодні" in only and "24 год" not in only and "Вересень" not in only
    assert "Сьогодні" not in rendered["calendar_hidden"] and "Вересень" in rendered["calendar_hidden"]
