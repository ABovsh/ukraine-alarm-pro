"""Ukraine Alarm Pro — keyless push alerts from the official map WebSocket."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.poll import PollTransport
from .api.supervisor import TransportSupervisor
from .api.ws import WsTransport
from .const import DOMAIN, PLATFORMS
from .coordinator import AlarmCoordinator
from .models import Snapshot


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    supervisor = TransportSupervisor(
        ws=WsTransport(session), poll=PollTransport(session)
    )
    coordinator = AlarmCoordinator(hass, supervisor)

    @callback
    def _on_snapshot(snap: Snapshot) -> None:
        coordinator.handle_snapshot(snap)

    supervisor.set_listener(_on_snapshot)
    await supervisor.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        coordinator: AlarmCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.supervisor.stop()
    return ok
