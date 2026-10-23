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
def test_full_layout_shows_two_statistics_rows_and_clock_marks():
    rendered = _render()
    full = rendered["quiet_full"]
    assert full.count('class="c l"') == 2  # a row each for 24 h and 7 days
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


def _table(html: str) -> str:
    """The statistics table: one row per period, headers once."""
    return html[html.index('class="tbl"'):]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_statistics_are_one_table_with_a_row_per_period():
    rendered = _render()
    full = rendered["calendar_full"]
    table = _table(full)
    for header in ("частка", "разом", "к-сть", "найдовша", "середня"):
        assert table.count(f">{header}<") == 1, header
    assert table.count('class="c l"') == 4  # one row per period
    for label in ("24 год", "7 днів", "Сьогодні", "Вересень"):
        assert label in table, label
    assert "вересня" not in table
    for share in ("36,7 %", "27,4 %", "35,6 %", "29,5 %"):  # 7 d: 165413 / (604800 - 55)
        assert share in table, share
    order = [table.index(f">{label}<") for label in ("Сьогодні", "24 год", "7 днів", "Вересень")]
    assert order == sorted(order), "rows: today, 24 h, 7 days, the month"
    assert table.count('class="lamp ok"') == 4
    assert table.count('<i style="width:') == 4  # the share bar under each percentage
    today = table[table.index(">Сьогодні<"):]
    assert "1 год 15 хв" in today and ">2<" in today and "50 хв" in today and "37 хв" in today
    assert 'class="sec records"' not in full and 'class="hint"' not in full
    assert 'class="kpi' not in full  # one view: no tiles
    english = _table(rendered["calendar_english"])
    for word in ("Today", "September", "share", "total", "count", "longest", "average"):
        assert word in english, word
    # Without `calendar` the table has the two rolling rows only.
    quiet = _table(rendered["quiet_full"])
    assert quiet.count('class="c l"') == 2 and "Сьогодні" not in quiet
    # A period without alerts says so with dashes, not zeros it cannot know.
    empty = _table(rendered["calendar_quiet"])
    assert "0,0 %" in empty and "без тривог" not in empty and empty.count(">—<") >= 4
    # A `records` section saved by 0.12 is dropped, the rest of the card stays.
    legacy = rendered["records_dropped"]
    assert 'class="sec head"' in legacy and "tbl" not in legacy


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_table_rows_columns_and_lamp_are_customisable():
    rendered = _render()
    bare = _table(rendered["calendar_no_details"])
    assert "lamp" not in bare and '<i style="width:' not in bare
    assert ">найдовша<" not in bare and ">середня<" not in bare and "36,7 %" in bare
    share_only = _table(rendered["table_share_only"])
    for header in ("разом", "к-сть", "найдовша", "середня"):
        assert f">{header}<" not in share_only, header
    assert ">частка<" in share_only and "36,7 %" in share_only
    only = _table(rendered["calendar_today_only"])
    assert only.count('class="c l"') == 1 and "Сьогодні" in only and "24 год" not in only
    assert "Вересень" in _table(rendered["calendar_hidden"]) and "Сьогодні" not in _table(rendered["calendar_hidden"])
    # What is partial gets a yellow lamp.
    assert 'class="lamp warn"' in _table(rendered["calendar_incomplete_month"])
    assert re.search(r'title="[^"]*Неповна статистика: дані з \d\d\.\d\d', _table(rendered["calendar_incomplete_month"]))
    assert 'class="lamp ok"' in _table(rendered["calendar_gaps_month"])  # 99 s of a month
    small_gap = _table(rendered["calendar_gaps_month"])
    assert "були перерви в даних: 1 хв" in small_gap
    assert "Дані практично повні" in small_gap
    assert 'title="Дані практично повні · були перерви в даних: 1 хв"' in small_gap
    assert 'title="Дані повні · були перерви в даних: 1 хв"' not in small_gap
    assert _table(rendered["calendar_big_gaps_month"]).count('class="lamp warn"') == 1
    assert 'class="lamp warn"' in _table(rendered["calendar_today_gaps"])
    assert 'class="lamp warn"' in _table(rendered["calendar_stale_week"])
    assert "були перерви в даних: 55 с" in _table(rendered["calendar_full"])  # a week with 55 s
    assert "—" in _table(rendered["calendar_no_percent"])
    # A YAML hide of every period leaves no empty table behind.
    assert 'class="tbl"' not in rendered["calendar_all_periods_hidden"]
    assert 'class="k-note"' not in json.dumps(rendered)
