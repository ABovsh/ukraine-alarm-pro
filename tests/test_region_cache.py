"""Region tree cache: options keep working through a proxy outage (UAP-08)."""

import copy
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_config_flow import REGIONS_TREE

from custom_components.ukraine_alarm_pro.api.errors import TransportError
from custom_components.ukraine_alarm_pro.const import DOMAIN
from custom_components.ukraine_alarm_pro.regions import (
    REGION_CACHE_KEY,
    async_get_region_tree,
    validate_region_tree,
)

FETCH = "custom_components.ukraine_alarm_pro.regions.async_fetch_regions"
FLOW_FETCH = "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions"


def _cyclic():
    tree = copy.deepcopy(REGIONS_TREE)
    tree["states"][0]["regionChildIds"][0]["regionChildIds"][0]["regionChildIds"] = [
        {"regionId": "14", "regionName": "loop"}
    ]
    return tree


def _duplicate():
    tree = copy.deepcopy(REGIONS_TREE)
    tree["states"].append({"regionId": "703", "regionName": "twin"})
    return tree


@pytest.mark.parametrize(
    "tree",
    [
        pytest.param(None, id="null"),
        pytest.param([], id="list"),
        pytest.param({}, id="no-states"),
        pytest.param({"states": []}, id="empty"),
        pytest.param({"states": [None]}, id="null-node"),
        pytest.param({"states": [{"regionName": "x"}]}, id="no-id"),
        pytest.param({"states": [{"regionId": True}]}, id="bool-id"),
        pytest.param({"states": [{"regionId": "1", "regionChildIds": "x"}]}, id="bad-children"),
        pytest.param(_cyclic(), id="cycle"),
        pytest.param(_duplicate(), id="duplicate-id"),
    ],
)
def test_invalid_trees_are_rejected(tree):
    with pytest.raises(ValueError):
        validate_region_tree(tree)


def test_too_deep_tree_is_rejected():
    node = {"regionId": "0"}
    root = node
    for i in range(1, 12):
        child = {"regionId": str(i)}
        node["regionChildIds"] = [child]
        node = child
    with pytest.raises(ValueError):
        validate_region_tree({"states": [root]})


def test_valid_tree_flattens_with_descendants():
    flat = validate_region_tree(REGIONS_TREE)
    assert flat["14"]["descendants"] == ["75", "703"]
    assert flat["703"]["ancestors"] == ["75", "14"]


async def test_fetch_success_is_cached_and_used_during_an_outage(hass: HomeAssistant):
    with patch(FETCH, return_value=REGIONS_TREE):
        flat, cached_at = await async_get_region_tree(hass)
    assert cached_at is None
    assert "703" in flat

    with patch(FETCH, side_effect=TransportError("down")):
        flat, cached_at = await async_get_region_tree(hass)
    assert "703" in flat
    assert cached_at is not None
    assert abs((dt_util.utcnow() - cached_at).total_seconds()) < 60


async def test_malformed_response_does_not_replace_a_good_cache(hass: HomeAssistant):
    with patch(FETCH, return_value=REGIONS_TREE):
        await async_get_region_tree(hass)
    with patch(FETCH, return_value={"states": []}):
        flat, cached_at = await async_get_region_tree(hass)
    assert "703" in flat and cached_at is not None
    with patch(FETCH, side_effect=TransportError("down")):
        flat, _ = await async_get_region_tree(hass)
    assert "703" in flat


async def test_no_cache_and_no_network_raises(hass: HomeAssistant):
    with patch(FETCH, side_effect=TransportError("down")), pytest.raises(TransportError):
        await async_get_region_tree(hass)


@pytest.mark.parametrize(
    "stored",
    [
        {"schema": 99, "tree": REGIONS_TREE, "fetched_at": "2026-09-15T00:00:00+00:00"},
        {"schema": 1, "tree": {"states": []}, "fetched_at": "2026-09-15T00:00:00+00:00"},
        {"schema": 1, "tree": REGIONS_TREE, "fetched_at": "garbage"},
        "junk",
    ],
)
async def test_unusable_cache_counts_as_no_cache(hass: HomeAssistant, hass_storage, stored):
    hass_storage[REGION_CACHE_KEY] = {"version": 1, "key": REGION_CACHE_KEY, "data": stored}
    with patch(FETCH, side_effect=TransportError("down")), pytest.raises(TransportError):
        await async_get_region_tree(hass)


async def _entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "regions": {
                "703": {"name": "Вишнева громада", "ancestors": ["75", "14"], "descendants": []},
                "999": {"name": "Зникла громада", "ancestors": ["14"], "descendants": []},
            }
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_options_use_the_cache_and_keep_a_region_missing_from_the_tree(
    hass: HomeAssistant, enable_custom_integrations
):
    entry = await _entry(hass)
    with patch(FETCH, return_value=REGIONS_TREE):
        await async_get_region_tree(hass)

    with patch(FLOW_FETCH, side_effect=TransportError("down")), patch(
        "custom_components.ukraine_alarm_pro.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "form"
        assert result["description_placeholders"]["tree_note"] != ""
        options = result["data_schema"].schema["regions"].config["options"]
        labels = {o["value"]: o["label"] for o in options}
        assert "999" in labels and "Зникла громада" in labels["999"]
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"regions": ["703", "999", "31"]}
        )
    assert result["type"] == "create_entry"
    regions = entry.data["regions"]
    assert set(regions) == {"703", "999", "31"}
    assert regions["999"]["name"] == "Зникла громада"
    assert regions["31"]["ancestors"] == []


async def test_options_without_cache_or_network_abort(
    hass: HomeAssistant, enable_custom_integrations
):
    entry = await _entry(hass)
    with patch(FLOW_FETCH, side_effect=TransportError("down")):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"
    assert set(entry.data["regions"]) == {"703", "999"}


async def test_first_install_without_network_offers_a_retry(
    hass: HomeAssistant, enable_custom_integrations
):
    with patch(FLOW_FETCH, side_effect=TransportError("down")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    with patch(FLOW_FETCH, return_value=REGIONS_TREE):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "form"
    assert result["errors"] in (None, {})


async def test_stale_cache_is_refreshed_in_the_background(hass: HomeAssistant, hass_storage):
    from custom_components.ukraine_alarm_pro.regions import async_refresh_region_cache

    with patch(FETCH, return_value=REGIONS_TREE) as fetch:
        await async_refresh_region_cache(hass)
        await async_refresh_region_cache(hass)  # fresh: no second request
        assert fetch.call_count == 1
    hass_storage[REGION_CACHE_KEY]["data"]["fetched_at"] = (
        dt_util.utcnow() - timedelta(days=2)
    ).isoformat()
    with patch(FETCH, return_value=REGIONS_TREE) as fetch:
        await async_refresh_region_cache(hass)
        assert fetch.call_count == 1
