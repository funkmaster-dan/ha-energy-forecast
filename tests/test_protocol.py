import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "energy_forecast"
spec = importlib.util.spec_from_file_location("protocol", ROOT / "protocol.py")
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


def test_cached_ready_expires_without_service():
    now = datetime.now(timezone.utc)
    snapshot = {
        "schema_version": "1.0",
        "status": "ready",
        "forecast_id": "generation",
        "issued_at": now.isoformat(),
        "valid_until": (now + timedelta(seconds=60)).isoformat(),
        "export_plan": {"replacement_budget": True},
    }
    assert protocol.ready(snapshot, now)
    assert not protocol.ready(snapshot, now + timedelta(seconds=61))
    assert not protocol.unexpired(snapshot, now + timedelta(seconds=61))
    snapshot["status"] = "shadow"
    assert not protocol.ready(snapshot, now)


def test_output_feedback_including_renamed_entities():
    mapping = {
        "source": "sensor.load",
        "feature": "household_load",
        "unit": "W",
        "kind": "mean_power",
        "boundary": "AC",
        "epoch": "original",
    }
    assert protocol.validate_inputs([mapping])
    with pytest.raises(ValueError):
        protocol.validate_inputs([{**mapping, "source": "sensor.energy_forecast_load"}])
    with pytest.raises(ValueError):
        protocol.validate_inputs([mapping], {"sensor.load"})


def test_statistics_reset_aware_change_and_missing():
    mapping = {
        "source": "sensor.energy",
        "feature": "household_load",
        "unit": "kWh",
        "kind": "counter",
        "boundary": "AC",
        "epoch": "original",
    }
    rows = protocol.statistics_observations(
        mapping, [{"start": 1767225600, "change": 2}, {"start": 1767229200, "change": None}]
    )
    assert rows[0]["kind"] == "interval_energy" and rows[0]["value"] == 2
    assert rows[1]["value"] is None and rows[1]["quality"] == "invalid"
    assert protocol.timestamp(rows[0]["end"]) - protocol.timestamp(rows[0]["start"]) == timedelta(
        hours=1
    )


def test_url_and_nonfinite_rejection():
    assert protocol.valid_url("http://192.168.1.10:18080/") == "http://192.168.1.10:18080"
    for url in ["file:///etc/passwd", "http://user:pass@example.org", "https://example.org/api"]:
        with pytest.raises(ValueError):
            protocol.valid_url(url)
    assert protocol.value_or_none("unavailable") is None
    assert protocol.value_or_none("nan") is None
