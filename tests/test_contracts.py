import hashlib
import json
from pathlib import Path


def test_pinned_contracts_have_matching_hashes():
    root = Path(__file__).parents[1] / "contracts"
    manifest = json.loads((root / "source.json").read_text())
    for name, expected in manifest["sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    fixture = json.loads((root / "synthetic-forecast-v1.json").read_text())
    assert fixture["schema_version"] == "1.0"
    assert fixture["export_plan"]["safe_battery_export_remaining_kwh"] == 0
    assert fixture["status"] == "shadow"
