"""Config flow: pick regions from the live region tree."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util

from .api.errors import TransportError
from .const import CONF_REGIONS, DOMAIN
from .regions import async_fetch_regions, async_get_region_tree

__all__ = ["async_fetch_regions"]

# The administrative tree is oblast > raion > hromada; the cap only keeps a
# malformed or self-referential feed from blowing the Python stack.
_MAX_TREE_DEPTH = 8


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
    flat: dict[str, dict[str, Any]],
    selected: list[str],
    stored: dict[str, dict[str, Any]] | None = None,
) -> vol.Schema:
    options = [
        SelectOptionDict(value=rid, label=info["label"])
        for rid, info in sorted(flat.items(), key=lambda kv: kv[1]["label"])
    ]
    # A monitored region the current tree lacks stays selectable, never dropped.
    options += [
        SelectOptionDict(value=rid, label=f"{info.get('name', rid)} ({rid}) ⚠")
        for rid, info in (stored or {}).items()
        if rid not in flat
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
    flat: dict[str, dict[str, Any]],
    region_ids: list[str],
    stored: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    selected = {}
    stored = stored or {}
    for rid in region_ids:
        if rid in flat:
            selected[rid] = {
                "name": flat[rid]["name"],
                "ancestors": flat[rid]["ancestors"],
                "descendants": flat[rid]["descendants"],
            }
        elif rid in stored:
            # Missing from this tree (outage, rename): keep what we had.
            selected[rid] = stored[rid]
    return selected


def _tree_note(cached_at, language: str) -> str:
    if cached_at is None:
        return ""
    stamp = dt_util.as_local(cached_at).strftime("%Y-%m-%d %H:%M")
    if language == "uk":
        return f"Не вдалося отримати перелік регіонів; показано копію від {stamp}."
    return f"The region list could not be fetched; showing the copy saved {stamp}."


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
        if user_input is not None and CONF_REGIONS in user_input:
            if not user_input[CONF_REGIONS]:
                # An entry watching nothing looks installed and warns about nothing.
                return self.async_show_form(
                    step_id="user",
                    data_schema=_regions_schema(self._flat, []),
                    errors={"base": "no_regions"},
                    description_placeholders={"tree_note": ""},
                )
            return self.async_create_entry(
                title="Ukraine Alarm Pro",
                data={
                    CONF_REGIONS: _selected_regions(
                        self._flat, user_input[CONF_REGIONS]
                    )
                },
            )

        # An empty submit is the retry after a failed fetch.
        try:
            self._flat, cached_at = await async_get_region_tree(
                self.hass, async_fetch_regions
            )
        except TransportError:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_connect"},
                description_placeholders={"tree_note": ""},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_regions_schema(self._flat, []),
            description_placeholders={"tree_note": _tree_note(cached_at, self.hass.config.language)},
        )


class UkraineAlarmProOptionsFlow(config_entries.OptionsFlow):
    """Change the monitored regions without removing the integration."""

    def __init__(self) -> None:
        self._flat: dict[str, dict[str, Any]] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None and not user_input.get(CONF_REGIONS):
            stored = self.config_entry.data.get(CONF_REGIONS, {})
            return self.async_show_form(
                step_id="init",
                data_schema=_regions_schema(self._flat, list(stored), stored),
                errors={"base": "no_regions"},
                description_placeholders={"tree_note": ""},
            )
        if user_input is not None:
            # Re-read at submit: another flow or the backfill may have written
            # the entry since this form was opened.
            data = self.config_entry.data
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **data,
                    CONF_REGIONS: _selected_regions(
                        self._flat,
                        user_input[CONF_REGIONS],
                        data.get(CONF_REGIONS, {}),
                    ),
                },
            )
            return self.async_create_entry(title="", data={})

        try:
            self._flat, cached_at = await async_get_region_tree(
                self.hass, async_fetch_regions
            )
        except TransportError:
            return self.async_abort(reason="cannot_connect")

        stored = self.config_entry.data.get(CONF_REGIONS, {})
        return self.async_show_form(
            step_id="init",
            data_schema=_regions_schema(self._flat, list(stored), stored),
            description_placeholders={"tree_note": _tree_note(cached_at, self.hass.config.language)},
        )
