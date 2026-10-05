import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

import aiohttp
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

ROOT = Path(tempfile.mkdtemp(prefix="energy-ha-smoke-"))
ROOT.mkdir(exist_ok=True)
(ROOT / "custom_components").mkdir(exist_ok=True)
shutil.copytree(
    str(Path(__file__).resolve().parents[1] / "custom_components" / "energy_forecast"),
    ROOT / "custom_components" / "energy_forecast",
    dirs_exist_ok=True,
)


async def main():
    hass = HomeAssistant(str(ROOT))
    hass.config.skip_pip = True
    from homeassistant import loader

    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    from homeassistant.bootstrap import async_load_base_functionality

    await async_load_base_functionality(hass)
    from homeassistant.helpers.recorder import async_initialize_recorder

    async_initialize_recorder(hass)
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        async with session.post(
            "http://127.0.0.1:18081/auth/login", json={"password": "synthetic-demo-password"}
        ) as response:
            login = await response.json()
        async with session.post(
            "http://127.0.0.1:18081/v1/sites/home/tokens",
            json={"scope": "integration"},
            headers={"X-CSRF-Token": login["csrf"]},
        ) as response:
            token = (await response.json())["token"]
    assert await async_setup_component(
        hass, "recorder", {"recorder": {"db_url": "sqlite:///" + str(ROOT / "recorder.sqlite")}}
    )
    assert await async_setup_component(hass, "network", {"network": {}})
    await hass.async_start()
    result = await hass.config_entries.flow.async_init(
        "energy_forecast",
        context={"source": "user"},
        data={"url": "http://127.0.0.1:18081", "token": token, "site_id": "home"},
    )
    print("Config flow:", result["type"])
    assert result["type"] == "create_entry", result
    entry = result["result"]
    await hass.async_block_till_done()
    print("Entry state:", entry.state)
    print(
        "Entity states:",
        [
            (state.entity_id, state.state)
            for state in hass.states.async_all()
            if "energy_forecast" in state.entity_id or "forecast" in state.entity_id
        ],
    )
    assert entry.state.value == "loaded"
    registry = er.async_get(hass)
    entities = [e for e in registry.entities.values() if e.platform == "energy_forecast"]
    assert len(entities) == 10, len(entities)
    hass.states.async_set("sensor.demo_soc", "80", {"unit_of_measurement": "%"})
    bridge = entry.runtime_data.bridge
    # Configure the bridge directly in the isolated test entry, without touching a live HA.
    hass.config_entries.async_update_entry(
        entry,
        options={
            "inputs": [
                {
                    "source": "sensor.demo_soc",
                    "feature": "battery_soc",
                    "unit": "%",
                    "kind": "state",
                    "boundary": "stored",
                    "epoch": "ha-runtime-synthetic",
                }
            ],
            "enable_backfill": False,
        },
    )
    await hass.async_block_till_done()
    bridge = entry.runtime_data.bridge
    await bridge.tick()
    assert bridge.last_error is None, bridge.last_error
    print("Selected input forwarding:", "passed")
    options = await hass.config_entries.options.async_init(entry.entry_id)
    discovery = await hass.config_entries.options.async_configure(
        options["flow_id"],
        user_input={
            "inputs": "[]",
            "history_start": "2026-10-01",
            "enable_backfill": False,
            "add_source": True,
        },
    )
    assert discovery["type"] == "form" and discovery["step_id"] == "discover", discovery
    print("Inactive/current source discovery:", "passed")
    from datetime import datetime, timedelta, timezone

    current = datetime.now(timezone.utc)
    entry.runtime_data.coordinator.async_set_updated_data(
        {
            "schema_version": "1.0",
            "status": "ready",
            "forecast_id": "synthetic-expiry-test",
            "issued_at": current.isoformat(),
            "valid_until": (current + timedelta(seconds=2)).isoformat(),
            "export_plan": {
                "replacement_budget": True,
                "safe_battery_export_remaining_kwh": 1,
                "reason_codes": [],
            },
        }
    )
    await hass.async_block_till_done()
    ready_id = next(e.entity_id for e in entities if e.domain == "binary_sensor")
    assert hass.states.get(ready_id).state == "on"
    await asyncio.sleep(7)
    assert hass.states.get(ready_id).state == "off"
    print("Cached readiness expires locally:", "passed")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_stop()


logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
