"""Pure contract helpers, also usable in a simulator without HA imports."""

import math
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

UNITS = {"W", "kW", "Wh", "kWh", "%", "°C", "W/m²"}


def timestamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        raise ValueError("UTC offset required")
    return value


def valid_url(value):
    parsed = urlparse(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Use an HTTP(S) service origin without credentials or paths")
    return value.rstrip("/")


def is_output(entity_id, integration_entities=()):
    return entity_id in integration_entities or entity_id.startswith(
        ("sensor.energy_forecast_", "binary_sensor.energy_forecast_")
    )


def value_or_none(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def ready(snapshot, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        return (
            snapshot["schema_version"] == "1.0"
            and snapshot["status"] == "ready"
            and timestamp(snapshot["issued_at"]) <= now < timestamp(snapshot["valid_until"])
            and bool(snapshot["forecast_id"])
            and snapshot["export_plan"].get("replacement_budget") is True
        )
    except (KeyError, TypeError, ValueError):
        return False


def unexpired(snapshot, now=None):
    try:
        now = now or datetime.now(timezone.utc)
        return timestamp(snapshot["issued_at"]) <= now < timestamp(snapshot["valid_until"])
    except (KeyError, TypeError, ValueError):
        return False


def validate_inputs(values, output_entities=()):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError("Supply a list of up to 100 selected sources")
    identities = set()
    for value in values:
        required = {"source", "feature", "unit", "kind", "boundary", "epoch"}
        if (
            not isinstance(value, dict)
            or not required <= value.keys()
            or set(value)
            - (required | {"history", "history_period", "entity_id", "interval_seconds"})
        ):
            raise ValueError("Each source needs source, feature, unit, kind, boundary and epoch")
        if not isinstance(value["feature"], str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", value["feature"]
        ):
            raise ValueError("Use a lowercase logical feature name")
        if (
            not isinstance(value["source"], str)
            or not 1 <= len(value["source"]) <= 150
            or not isinstance(value["epoch"], str)
            or not 1 <= len(value["epoch"]) <= 80
        ):
            raise ValueError("Source and epoch must be bounded nonempty strings")
        if is_output(value["source"], output_entities) or is_output(
            value.get("entity_id", ""), output_entities
        ):
            raise ValueError("Forecast outputs cannot be selected as inputs")
        key = (value["source"], value["feature"])
        if key in identities:
            raise ValueError("Duplicate input")
        identities.add(key)
        if (
            value["unit"] not in UNITS
            or value["kind"] not in ("mean_power", "interval_energy", "counter", "state")
            or value["boundary"] not in ("AC", "DC", "stored", "environment")
        ):
            raise ValueError("Unsupported unit, kind or boundary")
        if value["kind"] == "mean_power" and value["unit"] not in ("W", "kW"):
            raise ValueError("Mean power uses W or kW")
        if value["kind"] in ("interval_energy", "counter") and value["unit"] not in ("Wh", "kWh"):
            raise ValueError("Energy uses Wh or kWh")
        if (
            value["kind"] == "interval_energy"
            and not 1 <= value.get("interval_seconds", 0) <= 86400
        ):
            raise ValueError("Interval energy needs its actual interval_seconds")
        if value.get("history_period", "hour") not in ("hour", "5minute", "raw"):
            raise ValueError("History period must be hour, 5minute or raw")
    return values


def statistics_observations(mapping, rows, period="hour"):
    result = []
    minutes = 60 if period == "hour" else 5
    for row in rows:
        start = timestamp(row["start"])
        kind = mapping["kind"]
        if kind == "mean_power" or kind == "state":
            value = value_or_none(row.get("mean"))
        else:
            value = value_or_none(row.get("change"))
            kind = "interval_energy"  # Recorder change uses its reset-aware sum, not raw counters.
        result.append(
            {
                "feature": mapping["feature"],
                "source": mapping["source"],
                "epoch": mapping["epoch"],
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=minutes)).isoformat(),
                "value": value,
                "unit": mapping["unit"],
                "kind": kind,
                "boundary": mapping["boundary"],
                "quality": "valid" if value is not None else "invalid",
                "reasons": [] if value is not None else ["recorder_value_missing"],
                "coverage": 1.0,
                "revision": 0,
            }
        )
    return result
