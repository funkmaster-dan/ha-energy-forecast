"""Exercise retry/checkpoint code with lightweight HA adapters, no database SQL."""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "energy_forecast"


def load_bridge(monkeypatch):
    package = types.ModuleType("test_component")
    package.__path__ = [str(ROOT)]
    monkeypatch.setitem(sys.modules, "test_component", package)
    for name in [
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.recorder",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_registry",
        "homeassistant.helpers.storage",
        "homeassistant.util",
        "homeassistant.util.dt",
    ]:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    recorder = sys.modules["homeassistant.components.recorder"]
    recorder.get_instance = lambda hass: None
    recorder.history = types.SimpleNamespace()
    recorder.statistics = types.SimpleNamespace()

    class Storage:
        def __init__(self, *args):
            self.saved = []

        async def async_save(self, value):
            import copy

            self.saved.append(copy.deepcopy(value))

        async def async_load(self):
            return None

    sys.modules["homeassistant.helpers.storage"].Store = Storage
    spec = importlib.util.spec_from_file_location("test_component.bridge", ROOT / "bridge.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pending_retry_acknowledgement_advances_checkpoint_only_once(monkeypatch):
    module = load_bridge(monkeypatch)

    class Client:
        attempts = 0

        async def observations(self, batch):
            self.attempts += 1
            if self.attempts == 1:
                raise ConnectionError()
            return {"accepted": 1}

    entry = types.SimpleNamespace(entry_id="test", options={})
    client = Client()
    bridge = module.Bridge(None, entry, client)

    async def scenario():
        try:
            await bridge.send([{"value": 1}], {"profile": "2026-01-02T00:00:00+00:00"})
        except ConnectionError:
            pass
        assert bridge.state["pending"]
        assert not bridge.state["checkpoints"]
        first = bridge.state["pending"]["batch"]["batch_id"]
        await bridge.retry_pending()
        assert bridge.state["pending"] is None
        assert bridge.state["checkpoints"]["profile"] == "2026-01-02T00:00:00+00:00"
        assert bridge.storage.saved[0]["pending"]["batch"]["batch_id"] == first
        await bridge.retry_pending()
        assert client.attempts == 2

    asyncio.run(scenario())
