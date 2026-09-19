"""Ukraine Alarm Pro — keyless push alerts from the official map WebSocket."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store

from .api.poll import PollTransport
from .api.supervisor import TransportSupervisor
from .api.ws import WsTransport
from .const import (
    CONF_REGIONS,
    CROSS_CHECK_AFTER_SECONDS,
    DOMAIN,
    ISSUE_FEED_UNAVAILABLE,
    ISSUE_WS_UNAVAILABLE,
    PLATFORMS,
    SAVE_DELAY_SECONDS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import AlarmCoordinator
from .history import HISTORY_STORAGE_VERSION, history_storage_key
from .models import Snapshot

_LOGGER = logging.getLogger(__name__)

type UkraineAlarmProConfigEntry = ConfigEntry[AlarmCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The dashboard card ships with the integration: nothing to add by hand.
CARD_URL = f"/{DOMAIN}/ukraine-alarm-pro-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "ukraine-alarm-pro-card.js"

SERVICE_GET_HISTORY = "get_history"
SERVICE_GET_SUMMARY = "get_summary"
_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Required("region_id"): cv.string,
        vol.Optional("limit", default=20): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
    }
)
_SUMMARY_SCHEMA = vol.Schema(
    {
        vol.Required("region_id"): cv.string,
        vol.Optional("days", default=1): vol.All(vol.Coerce(int), vol.In((1, 7))),
    }
)

# Unique-id suffixes of the per-region entities, for the deselection purge.
REGION_ENTITY_KINDS = ("threat", "alert", "started", "level", "event")


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register the history actions and the dashboard card once."""

    async def _register_card(_event=None) -> None:
        # Lovelace resources exist only once the frontend has set up.
        await _async_register_card(hass)

    if hass.is_running:
        await _register_card()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_card)

    def _coordinator(region_id: str) -> AlarmCoordinator:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if (
                entry.state is ConfigEntryState.LOADED
                and region_id in entry.data.get(CONF_REGIONS, {})
            ):
                return entry.runtime_data
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_region",
            translation_placeholders={"region_id": region_id},
        )

    async def _get_history(call: ServiceCall) -> ServiceResponse:
        region_id = call.data["region_id"]
        history = _coordinator(region_id).history
        return {"episodes": history.history(region_id, call.data["limit"])}

    async def _get_summary(call: ServiceCall) -> ServiceResponse:
        region_id = call.data["region_id"]
        return _coordinator(region_id).history.summary(region_id, call.data["days"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HISTORY,
        _get_history,
        schema=_HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SUMMARY,
        _get_summary,
        schema=_SUMMARY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and have every dashboard load it, with a cache-busting hash.

    Storage-mode dashboards get it as a Lovelace resource, exactly like a HACS
    card: resources load after the frontend is ready. An "extra module" loads
    earlier, and its element definition could be lost to the frontend's own
    registry setup — users saw "Custom element doesn't exist". YAML-mode
    resources cannot be written, so those fall back to the extra module.
    """
    if getattr(hass, "http", None) is None or "frontend" not in hass.config.components:
        return
    digest = await hass.async_add_executor_job(
        lambda: hashlib.sha256(CARD_PATH.read_bytes()).hexdigest()[:8]
    )
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), True)]
    )
    url = f"{CARD_URL}?v={digest}"
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if getattr(lovelace, "resource_mode", None) != "storage" or not hasattr(
        resources, "async_create_item"
    ):
        add_extra_js_url(hass, url)
        return
    await resources.async_get_info()  # loads the collection on first use
    ours = [
        item for item in resources.async_items()
        if str(item.get("url", "")).split("?")[0] == CARD_URL
    ]
    if not ours:
        await resources.async_create_item({"res_type": "module", "url": url})
    elif ours[0]["url"] != url:
        await resources.async_update_item(
            ours[0]["id"], {"res_type": "module", "url": url}
        )


async def async_setup_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> bool:
    # Older versions warned about the polling fallback itself; that is not a
    # user problem, so drop a leftover issue on upgrade.
    ir.async_delete_issue(hass, DOMAIN, ISSUE_WS_UNAVAILABLE)
    session = async_get_clientsession(hass)
    supervisor = TransportSupervisor(
        ws=WsTransport(session),
        poll=PollTransport(session),
        stale_after=CROSS_CHECK_AFTER_SECONDS,
    )
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    coordinator = AlarmCoordinator(hass, entry, supervisor, store)
    # Before the transports start, so a snapshot that arrives while the disk
    # read is in flight is not overwritten by the older stored one.
    await coordinator.async_restore()
    await coordinator.history.async_load()
    entry.async_on_unload(
        coordinator.events.add_listener(None, coordinator.history.handle_event)
    )

    @callback
    def _on_snapshot(snap: Snapshot) -> None:
        coordinator.handle_snapshot(snap)

    supervisor.set_listener(_on_snapshot)

    @callback
    def _on_mode_change(mode: str) -> None:
        coordinator.handle_mode_change(mode)

    supervisor.set_mode_listener(_on_mode_change)

    @callback
    def _create_task(coro, name: str) -> asyncio.Task:
        # Entry-owned background tasks: HA cancels them on unload and waits
        # for them at shutdown instead of leaving orphaned loop tasks behind.
        return entry.async_create_background_task(hass, coro, name=name)

    await supervisor.start(_create_task)

    entry.runtime_data = coordinator
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            coordinator.async_save_now,
            timedelta(seconds=SAVE_DELAY_SECONDS),
        )
    )
    entry.async_on_unload(
        async_track_time_interval(
            hass, coordinator.async_check_stale, timedelta(seconds=60)
        )
    )
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            coordinator.async_flush_history,
            timedelta(seconds=SAVE_DELAY_SECONDS),
        )
    )
    async def _async_save_on_stop(_event) -> None:
        # A restart does not unload entries: without this the last few minutes
        # of the map and the journal were lost on every restart.
        await coordinator.async_save_now()
        await coordinator.async_flush_history()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_save_on_stop)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_purge_deselected_regions(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_schedule_descendant_backfill(hass, entry, session)
    _async_schedule_region_cache_refresh(hass, entry)
    _async_schedule_history_backfill(hass, entry)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.supervisor.stop()
        await entry.runtime_data.async_save_now()
        await entry.runtime_data.async_flush_history()
        ir.async_delete_issue(hass, DOMAIN, ISSUE_FEED_UNAVAILABLE)
    return ok


async def async_remove_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> None:
    """Delete what the entry kept on disk; nothing else ever reads it again."""
    history = Store(hass, HISTORY_STORAGE_VERSION, history_storage_key(entry.entry_id))
    await history.async_remove()
    await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()


async def _async_reload_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> None:
    """Rebuild the entities after the region selection changed."""
    await hass.config_entries.async_reload(entry.entry_id)


@callback
def _async_purge_deselected_regions(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> None:
    """Delete the entities of regions the user removed from the selection.

    HA keeps registry entries for entities a platform stopped creating, so
    without this a deselected region stayed behind as a permanently
    unavailable sensor that had to be deleted by hand.
    """
    regions = entry.data.get(CONF_REGIONS, {})
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        # Region unique ids are "<entry_id>_<region_id>_<kind>"; the hub
        # diagnostics never match, so new ones can be added without a whitelist.
        region_id, _, kind = reg_entry.unique_id.removeprefix(
            f"{entry.entry_id}_"
        ).rpartition("_")
        if region_id and kind in REGION_ENTITY_KINDS and region_id not in regions:
            _LOGGER.info(
                "Removing %s: region %s is no longer monitored",
                reg_entry.entity_id,
                region_id,
            )
            registry.async_remove(reg_entry.entity_id)


@callback
def _async_schedule_history_backfill(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> None:
    """Fill the alert journal from the official history, off the startup path.

    Five minutes after setup (a post-blackout boot has better things to do),
    then daily, which also fills any outage since the previous run.
    """

    @callback
    def _run(_now) -> None:
        entry.async_create_background_task(
            hass,
            entry.runtime_data.async_backfill_history(),
            name="alert-history-backfill",
        )

    entry.async_on_unload(async_call_later(hass, 300, _run))
    entry.async_on_unload(async_track_time_interval(hass, _run, timedelta(hours=24)))


@callback
def _async_schedule_region_cache_refresh(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> None:
    """Keep a recent copy of the region tree for editing during an outage.

    Never at startup: the proxy may be the slow part of a post-blackout boot.
    The check is hourly; a request is made only once the copy is a day old.
    """
    from .regions import async_refresh_region_cache

    @callback
    def _refresh(_now) -> None:
        # Late lookup, so a patched fetch in tests is honoured.
        from .config_flow import async_fetch_regions

        entry.async_create_background_task(
            hass,
            async_refresh_region_cache(hass, async_fetch_regions),
            name="region-tree-cache-refresh",
        )

    entry.async_on_unload(async_call_later(hass, 600, _refresh))
    entry.async_on_unload(
        async_track_time_interval(hass, _refresh, timedelta(hours=1))
    )


@callback
def _async_schedule_descendant_backfill(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry, session
) -> None:
    """Upgrade entries created before descendants were stored, off the hot path.

    Runs in the background: the region endpoint is a volunteer-run proxy with a
    30 s timeout, and waiting for it would add that delay to every restart for
    as long as it stays unreachable.
    """
    regions: dict[str, dict[str, Any]] = entry.data.get(CONF_REGIONS, {})
    if not regions or all("descendants" in info for info in regions.values()):
        return
    entry.async_create_background_task(
        hass,
        _async_backfill_descendants(hass, entry, session, regions),
        name="region-tree-backfill",
    )


async def _async_backfill_descendants(
    hass: HomeAssistant,
    entry: UkraineAlarmProConfigEntry,
    session,
    regions: dict[str, dict[str, Any]],
) -> None:
    """Add descendant ids so a raion-level alert reaches the oblast sensor.

    Writing them back triggers the update listener, which reloads the entry
    with the completed region data.
    """
    # Imported late: config_flow pulls in voluptuous/selectors that setup
    # does not otherwise need.
    from .config_flow import async_fetch_regions
    from .regions import async_get_region_tree

    try:
        flat, _ = await async_get_region_tree(hass, async_fetch_regions)
    # Best effort only: a broken region tree must never break the entry.
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Could not refresh the region tree (%s); region alerts declared at "
            "a lower administrative level stay invisible until the next reload",
            err,
        )
        return

    updated = {
        rid: {**info, "descendants": flat.get(rid, {}).get("descendants", [])}
        for rid, info in regions.items()
    }
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_REGIONS: updated}
    )
