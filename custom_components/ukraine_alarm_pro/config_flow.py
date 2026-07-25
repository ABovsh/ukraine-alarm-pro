"""Config flow: pick regions from the live region tree."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
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

# The administrative tree is oblast > raion > hromada; the cap only keeps a
# malformed or self-referential feed from blowing the Python stack.
_MAX_TREE_DEPTH = 8


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
    """Flatten the tree into {region_id: {name, ancestors, descendants, label}}."""
    flat: dict[str, dict[str, Any]] = {}

    def walk(
        node: dict[str, Any],
        ancestors: list[str],
        path: list[str],
        seen: frozenset[str],
    ) -> None:
        rid = str(node.get("regionId", ""))
        if not rid or rid in seen or len(ancestors) >= _MAX_TREE_DEPTH:
            return
        name = node.get("regionName", rid)
        flat[rid] = {
            "name": name,
            "ancestors": list(ancestors),
            "descendants": [],
            "label": " / ".join([*path, name]),
        }
        for child in node.get("regionChildIds") or []:
            if isinstance(child, dict):
                walk(child, [rid, *ancestors], [*path, name], seen | {rid})

    for state in tree.get("states") or []:
        if isinstance(state, dict):
            walk(state, [], [], frozenset())

    # Alerts are published at the level they were declared at, so every region
    # also needs to know what lies beneath it.
    for rid, info in flat.items():
        for ancestor in info["ancestors"]:
            if ancestor in flat:
                flat[ancestor]["descendants"].append(rid)
    return flat


def _regions_schema(
    flat: dict[str, dict[str, Any]], selected: list[str]
) -> vol.Schema:
    options = [
        SelectOptionDict(value=rid, label=info["label"])
        for rid, info in sorted(flat.items(), key=lambda kv: kv[1]["label"])
    ]
    return vol.Schema(
        {
            vol.Required(CONF_REGIONS, default=selected): SelectSelector(
                SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _selected_regions(
    flat: dict[str, dict[str, Any]], region_ids: list[str]
) -> dict[str, dict[str, Any]]:
    return {
        rid: {
            "name": flat[rid]["name"],
            "ancestors": flat[rid]["ancestors"],
            "descendants": flat[rid]["descendants"],
        }
        for rid in region_ids
        if rid in flat
    }


class UkraineAlarmProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Single-hub, multi-region config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._flat: dict[str, dict[str, Any]] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> UkraineAlarmProOptionsFlow:
        return UkraineAlarmProOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(
                title="Ukraine Alarm Pro",
                data={
                    CONF_REGIONS: _selected_regions(
                        self._flat, user_input[CONF_REGIONS]
                    )
                },
            )

        try:
            tree = await async_fetch_regions(async_get_clientsession(self.hass))
        except TransportError:
            return self.async_abort(reason="cannot_connect")
        self._flat = _flatten(tree)

        return self.async_show_form(
            step_id="user", data_schema=_regions_schema(self._flat, [])
        )


class UkraineAlarmProOptionsFlow(config_entries.OptionsFlow):
    """Change the monitored regions without removing the integration."""

    def __init__(self) -> None:
        self._flat: dict[str, dict[str, Any]] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_REGIONS: _selected_regions(
                        self._flat, user_input[CONF_REGIONS]
                    ),
                },
            )
            return self.async_create_entry(title="", data={})

        try:
            tree = await async_fetch_regions(async_get_clientsession(self.hass))
        except TransportError:
            return self.async_abort(reason="cannot_connect")
        self._flat = _flatten(tree)

        current = list(self.config_entry.data.get(CONF_REGIONS, {}))
        return self.async_show_form(
            step_id="init", data_schema=_regions_schema(self._flat, current)
        )
