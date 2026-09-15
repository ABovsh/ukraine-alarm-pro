"""Region tree: fetch, strict validation and an on-disk last-known-good copy.

The tree comes from a volunteer-run proxy. Without a copy on disk, changing
the monitored regions was impossible for as long as the proxy was down. Only
a tree that passed validation is cached, so a broken answer can never replace
a good one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .api.errors import TransportError
from .api.poll import DEFAULT_BASE_URL
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

REGION_CACHE_KEY = f"{DOMAIN}.regions"
REGION_CACHE_VERSION = 1
REGION_CACHE_SCHEMA = 1
# Refresh cadence of the copy, not an alert freshness limit or a poll option.
REGION_CACHE_TTL = timedelta(hours=24)
# The administrative tree is oblast > raion > hromada (measured depth 3).
MAX_TREE_DEPTH = 8

Fetch = Callable[[aiohttp.ClientSession], Awaitable[Any]]


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


def validate_region_tree(tree: Any) -> dict[str, dict[str, Any]]:
    """Flatten a tree that is fully usable, or raise ValueError.

    Rejected: wrong types, missing or ambiguous ids, cycles, excessive depth
    and an empty tree — each would silently drop regions from the choice.
    """
    if not isinstance(tree, dict) or not isinstance(tree.get("states"), list):
        raise ValueError("region tree has no list of states")  # noqa: TRY004
    flat: dict[str, dict[str, Any]] = {}

    def walk(node: Any, ancestors: list[str], path: list[str]) -> None:
        if not isinstance(node, dict):
            raise ValueError("region node is not an object")  # noqa: TRY004
        raw = node.get("regionId")
        if isinstance(raw, bool) or not isinstance(raw, (str, int)) or not str(raw).strip():
            raise ValueError("region node has an unusable id")
        rid = str(raw).strip()
        if rid in flat:
            raise ValueError(f"region id {rid} appears twice or in a cycle")
        if len(ancestors) >= MAX_TREE_DEPTH:
            raise ValueError("region tree is too deep")
        name = node.get("regionName")
        name = name if isinstance(name, str) and name else rid
        flat[rid] = {
            "name": name,
            "ancestors": list(ancestors),
            "descendants": [],
            "label": " / ".join([*path, name]),
        }
        children = node.get("regionChildIds")
        if children is None:
            return
        if not isinstance(children, list):
            raise ValueError(f"children of region {rid} are not a list")  # noqa: TRY004
        for child in children:
            walk(child, [rid, *ancestors], [*path, name])

    for state in tree["states"]:
        walk(state, [], [])
    if not flat:
        raise ValueError("region tree is empty")
    for rid, info in flat.items():
        for ancestor in info["ancestors"]:
            flat[ancestor]["descendants"].append(rid)
    return flat


def _store(hass: HomeAssistant) -> Store:
    return Store(hass, REGION_CACHE_VERSION, REGION_CACHE_KEY)


async def _async_load_cache(
    hass: HomeAssistant,
) -> tuple[dict[str, dict[str, Any]], datetime] | None:
    try:
        stored = await _store(hass).async_load()
    # A damaged copy is no copy; it must not break the flow.
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Region tree cache unreadable: %s", err)
        return None
    if not isinstance(stored, dict) or stored.get("schema") != REGION_CACHE_SCHEMA:
        return None
    fetched_at = dt_util.parse_datetime(str(stored.get("fetched_at", "")))
    if fetched_at is None:
        return None
    try:
        return validate_region_tree(stored.get("tree")), fetched_at
    except ValueError:
        return None


async def async_get_region_tree(
    hass: HomeAssistant, fetch: Fetch | None = None
) -> tuple[dict[str, dict[str, Any]], datetime | None]:
    """The live tree, or the cached one with its fetch time during an outage.

    Raises TransportError only when neither is usable.
    """
    fetch = fetch or async_fetch_regions
    try:
        tree = await fetch(async_get_clientsession(hass))
        flat = validate_region_tree(tree)
    except (TransportError, ValueError) as err:
        cached = await _async_load_cache(hass)
        if cached is None:
            raise TransportError(f"no usable region tree: {err}") from err
        _LOGGER.info("Region tree unavailable (%s); using the saved copy", err)
        return cached
    await _store(hass).async_save(
        {
            "schema": REGION_CACHE_SCHEMA,
            "source": f"{DEFAULT_BASE_URL}/regions",
            "fetched_at": dt_util.utcnow().isoformat(),
            "tree": tree,
        }
    )
    return flat, None


async def async_refresh_region_cache(
    hass: HomeAssistant, fetch: Fetch | None = None
) -> None:
    """Keep the saved copy recent, off the hot path and best effort."""
    cached = await _async_load_cache(hass)
    if cached is not None and dt_util.utcnow() - cached[1] < REGION_CACHE_TTL:
        return
    try:
        await async_get_region_tree(hass, fetch)
    # Best effort in the background: nothing here may surface as a task error.
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Region tree cache refresh failed: %s", err)
