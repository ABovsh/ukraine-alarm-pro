"""Config flow tests."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.ukraine_alarm_pro.const import DOMAIN

REGIONS_TREE = {
    "states": [
        {
            "regionId": "14",
            "regionName": "Київська область",
            "regionType": "State",
            "regionChildIds": [
                {
                    "regionId": "75",
                    "regionName": "Бучанський район",
                    "regionType": "District",
                    "regionChildIds": [
                        {
                            "regionId": "703",
                            "regionName": "Вишнева громада",
                            "regionType": "Community",
                        }
                    ],
                }
            ],
        },
        {"regionId": "31", "regionName": "м. Київ", "regionType": "State"},
    ]
}


async def test_flow_creates_multi_region_entry(
    hass: HomeAssistant, enable_custom_integrations
):
    with patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        return_value=REGIONS_TREE,
    ), patch(
        "custom_components.ukraine_alarm_pro.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == "form"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"regions": ["703", "31"]}
        )
    assert result["type"] == "create_entry"
    regions = result["data"]["regions"]
    assert regions["703"]["name"] == "Вишнева громада"
    assert regions["703"]["ancestors"] == ["75", "14"]
    assert regions["31"]["ancestors"] == []


async def test_flow_aborts_on_regions_fetch_failure(
    hass: HomeAssistant, enable_custom_integrations
):
    from custom_components.ukraine_alarm_pro.api.errors import TransportError

    with patch(
        "custom_components.ukraine_alarm_pro.config_flow.async_fetch_regions",
        side_effect=TransportError("down"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"
