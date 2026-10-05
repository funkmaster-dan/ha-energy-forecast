from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .bridge import Bridge
from .client import Client
from .const import INPUT_SECONDS, PLATFORMS
from .coordinator import ForecastCoordinator
from .protocol import validate_inputs


@dataclass
class Runtime:
    client: Client
    coordinator: ForecastCoordinator
    bridge: Bridge


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = Client(async_get_clientsession(hass), **entry.data)
    validate_inputs(entry.options.get("inputs", []))
    coordinator = ForecastCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    bridge = Bridge(hass, entry, client)
    await bridge.load()
    entry.runtime_data = Runtime(client, coordinator, bridge)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # This timer is independent of enabled/disabled output entities.
    entry.async_on_unload(
        async_track_time_interval(hass, bridge.tick, timedelta(seconds=INPUT_SECONDS))
    )
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    entry.async_create_background_task(hass, bridge.tick(), "Energy Forecast initial forwarding")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
