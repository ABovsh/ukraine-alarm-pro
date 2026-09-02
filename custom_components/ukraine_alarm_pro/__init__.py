"""Ukraine Alarm Pro — keyless push alerts from the official map WebSocket."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api.poll import PollTransport
from .api.supervisor import MODE_POLL, TransportSupervisor
from .api.ws import WsTransport
from .const import (
    CONF_REGIONS,
    DOMAIN,
    ISSUE_WS_UNAVAILABLE,
    PLATFORMS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import AlarmCoordinator
from .models import Snapshot

_LOGGER = logging.getLogger(__name__)

type UkraineAlarmProConfigEntry = ConfigEntry[AlarmCoordinator]

# Unique-id suffixes of the per-region entities, for the deselection purge.
REGION_ENTITY_KINDS = ("threat", "alert", "started")


async def async_setup_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> bool:
    session = async_get_clientsession(hass)
    supervisor = TransportSupervisor(
        ws=WsTransport(session), poll=PollTransport(session)
    )
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    coordinator = AlarmCoordinator(hass, entry, supervisor, store)
    # Before the transports start, so a snapshot that arrives while the disk
    # read is in flight is not overwritten by the older stored one.
    await coordinator.async_restore()

    @callback
    def _on_snapshot(snap: Snapshot) -> None:
        coordinator.handle_snapshot(snap)

    supervisor.set_listener(_on_snapshot)

    @callback
    def _on_mode_change(mode: str) -> None:
        coordinator.handle_mode_change(mode)
        _async_report_transport_mode(hass, mode)

    supervisor.set_mode_listener(_on_mode_change)

    @callback
    def _create_task(coro, name: str) -> asyncio.Task:
        # Entry-owned background tasks: HA cancels them on unload and waits
        # for them at shutdown instead of leaving orphaned loop tasks behind.
        return entry.async_create_background_task(hass, coro, name=name)

    await supervisor.start(_create_task)

    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_purge_deselected_regions(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_schedule_descendant_backfill(hass, entry, session)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.supervisor.stop()
        await entry.runtime_data.async_save_now()
        ir.async_delete_issue(hass, DOMAIN, ISSUE_WS_UNAVAILABLE)
    return ok


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
def _async_report_transport_mode(hass: HomeAssistant, mode: str) -> None:
    """Tell the user when we are stuck on the slower polling fallback."""
    if mode == MODE_POLL:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_WS_UNAVAILABLE,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_WS_UNAVAILABLE,
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_WS_UNAVAILABLE)


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
    from .config_flow import _flatten, async_fetch_regions

    try:
        flat = _flatten(await async_fetch_regions(session))
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
