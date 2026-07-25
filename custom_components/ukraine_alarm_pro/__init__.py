"""Ukraine Alarm Pro — keyless push alerts from the official map WebSocket."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.poll import PollTransport
from .api.supervisor import MODE_POLL, TransportSupervisor
from .api.ws import WsTransport
from .const import CONF_REGIONS, DOMAIN, ISSUE_WS_UNAVAILABLE, PLATFORMS
from .coordinator import AlarmCoordinator
from .models import Snapshot

_LOGGER = logging.getLogger(__name__)

type UkraineAlarmProConfigEntry = ConfigEntry[AlarmCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> bool:
    session = async_get_clientsession(hass)
    await _async_backfill_descendants(hass, entry, session)

    supervisor = TransportSupervisor(
        ws=WsTransport(session), poll=PollTransport(session)
    )
    coordinator = AlarmCoordinator(hass, entry, supervisor)

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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.supervisor.stop()
        ir.async_delete_issue(hass, DOMAIN, ISSUE_WS_UNAVAILABLE)
    return ok


async def _async_reload_entry(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry
) -> None:
    """Rebuild the entities after the region selection changed."""
    await hass.config_entries.async_reload(entry.entry_id)


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


async def _async_backfill_descendants(
    hass: HomeAssistant, entry: UkraineAlarmProConfigEntry, session
) -> None:
    """Add descendant ids to entries created before they were stored.

    Without them a raion-level alert never reaches the oblast sensor. Best
    effort: if the region tree is unreachable the entry keeps working with
    ancestor-only inheritance until the next reload.
    """
    regions: dict[str, dict[str, Any]] = entry.data.get(CONF_REGIONS, {})
    if not regions or all("descendants" in info for info in regions.values()):
        return

    # Imported late: config_flow pulls in voluptuous/selectors that setup
    # does not otherwise need.
    from .config_flow import _flatten, async_fetch_regions

    try:
        flat = _flatten(await async_fetch_regions(session))
    # Best effort only: a broken region tree must never block setup.
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
