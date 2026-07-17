"""Config flow: pick regions from the live region tree."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api.errors import TransportError
from .api.poll import DEFAULT_BASE_URL
from .const import CONF_REGIONS, DOMAIN


async def async_fetch_regions(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Fetch the full region tree from the public proxy."""
    try:
        resp = await session.get(
            f"{DEFAULT_BASE_URL}/regions",
            headers={"accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        resp.raise_for_status()
        return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        raise TransportError(f"regions fetch failed: {err}") from err


def _flatten(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten the tree into {region_id: {name, ancestors, path_label}}."""
    flat: dict[str, dict[str, Any]] = {}

    def walk(node: dict[str, Any], ancestors: list[str], path: list[str]) -> None:
        rid = str(node.get("regionId", ""))
        name = node.get("regionName", rid)
        if not rid:
            return
        flat[rid] = {
            "name": name,
            "ancestors": list(ancestors),
            "label": " / ".join([*path, name]),
        }
        for child in node.get("regionChildIds") or []:
            walk(child, [rid, *ancestors], [*path, name])

    for state in tree.get("states", []):
        walk(state, [], [])
    return flat


class UkraineAlarmProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Single-hub, multi-region config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._flat: dict[str, dict[str, Any]] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            regions = {
                rid: {
                    "name": self._flat[rid]["name"],
                    "ancestors": self._flat[rid]["ancestors"],
                }
                for rid in user_input[CONF_REGIONS]
            }
            return self.async_create_entry(
                title="Ukraine Alarm Pro", data={CONF_REGIONS: regions}
            )

        try:
            tree = await async_fetch_regions(async_get_clientsession(self.hass))
        except TransportError:
            return self.async_abort(reason="cannot_connect")
        self._flat = _flatten(tree)

        options = [
            SelectOptionDict(value=rid, label=info["label"])
            for rid, info in sorted(self._flat.items(), key=lambda kv: kv[1]["label"])
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REGIONS): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )
