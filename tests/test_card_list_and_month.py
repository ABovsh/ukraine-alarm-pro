"""Several regions in one card, and the month chart under the statistics table."""

import re
import shutil

import pytest
from test_card_render import _render

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _rows(html: str) -> list[str]:
    return re.split(r'(?=<div class="lrow)', html)[1:]


def test_several_regions_make_a_list_with_a_row_each():
    rendered = _render()
    html = rendered["list_mixed"]
    rows = _rows(html)
    assert len(rows) == 3
    assert 'class="sec head"' not in html and 'class="tbl"' not in html
    kyiv, hatne, kozhanka = rows
    assert 'data-entity="binary_sensor.uap_31_alert"' in kyiv
    # An air alert with a known level says only the level; the line is narrow.
    assert "м. Київ" in kyiv and '<div class="lsub"><b class="lv red">Червоний рівень</b></div>' in kyiv
    assert "20 хв" in kyiv and "з 15:10" in kyiv and "58,4 %" in kyiv
    assert 'lrow red' in kyiv
    assert "Гатненська громада" in hatne and "Тихо" in hatne
    assert "2 год 15 хв" in hatne and "13:15" in hatne and "71,0 %" in hatne
    assert 'lrow quiet' in hatne
    assert "Кожанська громада" in kozhanka and "Жовтий рівень" in kozhanka and "10 год 12 хв" in kozhanka
    # An unknown 24 h share is a dash, never 0 %.
    assert "—" in kozhanka and "0,0 %" not in kozhanka
    assert rendered["list_mixed_size"] >= 3


def test_the_list_takes_a_title_language_and_flags_stale_data():
    rendered = _render()
    assert "Мої регіони" in rendered["list_named"]
    assert "Мої регіони" not in rendered["list_mixed"]
    assert "Дані застаріли" in rendered["list_stale"]
    english = rendered["list_english"]
    assert "Red level" in english and "All quiet" in english


def test_one_region_in_the_list_is_the_usual_card():
    rendered = _render()
    assert 'class="sec head"' in rendered["list_one"]
    assert "lrow" not in rendered["list_one"]


def test_a_region_that_is_gone_drops_out_of_the_list():
    rows = _rows(_render()["list_missing"])
    assert len(rows) == 1 and "м. Київ" in rows[0]


def _chart(html: str) -> str:
    return html[html.index('class="mchart"'):]


def test_month_chart_has_a_bar_per_day_of_the_month():
    rendered = _render()
    chart = _chart(rendered["month_chart"])
    bars = re.findall(r'<div class="bar[^"]*"[^>]*>', chart)
    assert len(bars) == 30  # September
    assert len([b for b in bars if "future" in b]) == 15
    assert 'title="05.09 · 24 год 0 хв · 2 тривоги"' in chart
    assert 'title="03.09 · 12 год 0 хв · 3 тривоги"' in chart
    assert 'title="01.09 · без тривог"' in chart
    assert "height:100.0%" in chart and "height:50.0%" in chart
    assert "Вересень" in chart and "години тривоги" in chart
    assert "макс. 05.09 · 24 год 0 хв" in chart
    # The chart sits under the table.
    html = rendered["month_chart"]
    assert html.index('class="tbl"') < html.index('class="mchart"')


def test_month_chart_can_be_hidden_and_needs_daily_data():
    rendered = _render()
    assert "mchart" not in rendered["month_chart_hidden"]
    assert 'class="tbl"' in rendered["month_chart_hidden"]
    assert "mchart" not in rendered["month_chart_no_daily"]
    quiet = _chart(rendered["month_chart_quiet"])
    assert "без тривог" in quiet and "макс." not in quiet
    assert "alert hours" in _chart(rendered["month_chart_english"])


def test_list_lines_shorten_the_official_hromada_name():
    html = _render()["list_long_name"]
    assert "Гатненська громада" in html and "територіальна" not in html
    # Another threat keeps its own name, with the level word after it.
    assert "Загроза артобстрілу" in html and "жовтий" in html
