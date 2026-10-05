"""Input forwarding is independent of output entity subscriptions."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from functools import partial

from homeassistant.components.recorder import get_instance, history, statistics
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, INPUT_SECONDS
from .protocol import (
    UNITS,
    compatible_units,
    is_output,
    sensor_contexts,
    statistics_observations,
    timestamp,
    value_or_none,
)

_LOGGER = logging.getLogger(__name__)


class Bridge:
    def __init__(self, hass, entry, client):
        self.hass, self.entry, self.client = hass, entry, client
        self.storage = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.bridge")
        self.state = {"checkpoints": {}, "pending": None}
        self.lock = asyncio.Lock()
        self.last_poll = None
        self.last_values = {}
        self.last_reported = {}
        self.last_error = None
        self.remote_inputs = None
        self.metadata_at = None

    async def load(self):
        self.state = await self.storage.async_load() or self.state
        signature = hashlib.sha256(
            json.dumps(self.entry.options.get("inputs", []), sort_keys=True).encode()
        ).hexdigest()
        if self.state.get("mapping_signature") not in (None, signature) and self.state.get(
            "pending"
        ):
            quarantined = self.state.get("quarantined", [])
            quarantined.append({"reason": "options_changed", "pending": self.state["pending"]})
            self.state["quarantined"] = quarantined[-3:]
            self.state["pending"] = None
        self.state["mapping_signature"] = signature
        await self.storage.async_save(self.state)

    def mappings(self):
        outputs = {
            e.entity_id for e in er.async_get(self.hass).entities.values() if e.platform == DOMAIN
        }
        return [
            m
            for m in (
                self.remote_inputs
                if self.remote_inputs is not None
                else self.entry.options.get("inputs", [])
            )
            if not is_output(m["source"], outputs)
            and not is_output(m.get("entity_id", ""), outputs)
        ]

    async def publish_metadata(self):
        outputs = {
            e.entity_id for e in er.async_get(self.hass).entities.values() if e.platform == DOMAIN
        }
        sources = {}
        for entity in self.hass.states.async_all("sensor"):
            unit = entity.attributes.get("unit_of_measurement")
            if is_output(entity.entity_id, outputs) or unit not in UNITS:
                continue
            if unit in ("Wh", "kWh") and entity.attributes.get("state_class") not in (
                "total",
                "total_increasing",
            ):
                continue
            sources[entity.entity_id] = {
                "source": entity.entity_id,
                "name": entity.name,
                "unit": unit,
                "kind": "mean_power"
                if unit in ("W", "kW")
                else "counter"
                if unit in ("Wh", "kWh")
                else "state",
                "inactive": False,
                "device_class": entity.attributes.get("device_class"),
                "state_class": entity.attributes.get("state_class"),
            }
        metadata = await get_instance(self.hass).async_add_executor_job(
            partial(statistics.list_statistic_ids, self.hass)
        )
        for source in metadata:
            identifier = source["statistic_id"]
            unit = (
                source.get("statistics_unit_of_measurement")
                or source.get("unit_of_measurement")
                or source.get("display_unit_of_measurement")
            )
            if (
                identifier not in sources
                and unit in UNITS
                and not is_output(identifier, outputs)
                and (unit not in ("Wh", "kWh") or source.get("has_sum"))
            ):
                sources[identifier] = {
                    "source": identifier,
                    "name": source.get("name") or identifier,
                    "unit": unit,
                    "kind": "mean_power"
                    if unit in ("W", "kW")
                    else "counter"
                    if unit in ("Wh", "kWh")
                    else "state",
                    "inactive": True,
                }
        for metadata in sources.values():
            metadata["contexts"] = sensor_contexts(
                metadata["source"], metadata["name"], metadata["unit"], metadata.get("device_class")
            )
        from homeassistant.const import __version__

        await self.client.request(
            "POST",
            "/bridge/metadata",
            {
                "home": {
                    "name": self.hass.config.location_name,
                    "latitude": self.hass.config.latitude,
                    "longitude": self.hass.config.longitude,
                    "timezone": self.hass.config.time_zone,
                },
                "sources": list(sources.values()),
                "ha_version": __version__,
            },
        )
        self.metadata_at = dt_util.utcnow()

    async def send(self, observations, checkpoint=None):
        if not observations:
            if checkpoint:
                self.state["checkpoints"].update(checkpoint)
                await self.storage.async_save(self.state)
            return
        batch = {
            "schema_version": "1.0",
            "batch_id": hashlib.sha256(
                json.dumps(observations, sort_keys=True).encode()
            ).hexdigest(),
            "observations": observations,
        }
        self.state["pending"] = {"batch": batch, "checkpoint": checkpoint}
        await self.storage.async_save(self.state)
        await self.retry_pending()

    async def retry_pending(self):
        pending = self.state.get("pending")
        if pending:
            await self.client.observations(pending["batch"])
            if pending.get("checkpoint"):
                self.state["checkpoints"].update(pending["checkpoint"])
            self.state["pending"] = None
            await self.storage.async_save(self.state)

    async def tick(self, _now=None):
        if self.lock.locked():
            return
        async with self.lock:
            try:
                if (
                    not self.metadata_at
                    or (dt_util.utcnow() - self.metadata_at).total_seconds() >= 300
                ):
                    await self.publish_metadata()
                if (await self.client.diagnostics()).get("data_access") == "direct_api":
                    return  # Optional integration publishes forecasts; service owns ingestion.
                selected = await self.client.request("GET", "/bridge/inputs")
                from .protocol import validate_inputs

                chosen = validate_inputs(selected) or self.entry.options.get("inputs", [])
                if chosen != self.remote_inputs:
                    self.remote_inputs = chosen
                    self.state["mapping_signature"] = hashlib.sha256(
                        json.dumps(chosen, sort_keys=True).encode()
                    ).hexdigest()
                await self.retry_pending()
                current = dt_util.utcnow()
                start = self.last_poll or current - timedelta(seconds=INPUT_SECONDS)
                self.last_poll = current
                observations = []
                for mapping in self.mappings():
                    entity_id = mapping.get("entity_id", mapping["source"])
                    state = self.hass.states.get(entity_id)
                    if not state:
                        continue
                    value = value_or_none(state.state)
                    reported = state.last_reported
                    if (
                        mapping["kind"] in ("state", "interval_energy")
                        and self.last_reported.get(entity_id) == reported
                    ):
                        continue
                    self.last_reported[entity_id] = reported
                    age = (current - reported).total_seconds()
                    quality = (
                        "valid" if value is not None and age <= INPUT_SECONDS * 2 else "invalid"
                    )
                    reasons = [] if quality == "valid" else ["source_stale_or_missing"]
                    reported_unit = state.attributes.get("unit_of_measurement")
                    if not compatible_units(reported_unit, mapping["unit"]):
                        quality, reasons = (
                            "invalid",
                            ["source_unit_changed", f"reported_unit:{str(reported_unit)[:32]}"],
                        )
                    end = current
                    first = start
                    if mapping["kind"] == "state":
                        # Preserve source timestamp, do not freshen stale SoC by polling it.
                        end = reported
                        first = reported - timedelta(seconds=1)
                    elif mapping["kind"] == "interval_energy":
                        end = reported
                        first = reported - timedelta(seconds=mapping["interval_seconds"])
                    elif mapping["kind"] == "mean_power":
                        previous = self.last_values.get(entity_id)
                        if previous and previous[0] is not None and value is not None:
                            value = (previous[0] + value) / 2
                        else:
                            quality, reasons = "invalid", ["power_integration_start"]
                        if (end - first).total_seconds() > INPUT_SECONDS * 2:
                            quality, reasons = "invalid", ["power_gap"]
                    self.last_values[entity_id] = (value_or_none(state.state), current)
                    observations.append(
                        {
                            "feature": mapping["feature"],
                            "source": mapping["source"],
                            "epoch": mapping["epoch"],
                            "start": first.isoformat(),
                            "end": end.isoformat(),
                            "value": value,
                            "unit": reported_unit if reported_unit in UNITS else mapping["unit"],
                            "kind": mapping["kind"],
                            "boundary": mapping["boundary"],
                            "quality": quality,
                            "reasons": reasons,
                            "coverage": 1.0,
                            "revision": 0,
                            "provenance": "live",
                        }
                    )
                await self.send(observations)
                if self.entry.options.get("enable_backfill", True):
                    await self.backfill_page(current)
                self.last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.last_error = type(error).__name__
                _LOGGER.warning("Energy Forecast input forwarding paused: %s", self.last_error)

    async def backfill_page(self, current):
        start_default = datetime.fromisoformat(
            self.entry.options.get("history_start", "2022-01-01")
        ).replace(tzinfo=timezone.utc)
        for mapping in self.mappings():
            if not mapping.get("history", True):
                continue
            period = mapping.get("history_period", "hour")
            key = f"{mapping['source']}:{mapping['feature']}:{mapping['epoch']}:{period}"
            start = timestamp(self.state["checkpoints"].get(key, start_default.isoformat()))
            # Do not request incomplete current statistics or count future targets.
            limit = current.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
            end = min(start + timedelta(days=1), limit)
            if end <= start:
                continue
            recorder = get_instance(self.hass)
            if period == "raw":
                entity_id = mapping.get("entity_id", mapping["source"])
                rows = await recorder.async_add_executor_job(
                    partial(
                        history.state_changes_during_period,
                        self.hass,
                        start,
                        end,
                        entity_id,
                        False,
                        False,
                        2000,
                        True,
                    )
                )
                raw = rows.get(entity_id, [])
                observations = []
                for previous, next_state in zip(raw, raw[1:]):
                    first, last = previous.last_updated, next_state.last_updated
                    if first < start or last > end or last <= first:
                        continue
                    value = value_or_none(previous.state)
                    gap = (last - first).total_seconds()
                    observations.append(
                        {
                            "feature": mapping["feature"],
                            "source": mapping["source"],
                            "epoch": mapping["epoch"],
                            "start": first.isoformat(),
                            "end": last.isoformat(),
                            "value": value,
                            "unit": mapping["unit"],
                            "kind": mapping["kind"],
                            "boundary": mapping["boundary"],
                            "quality": "valid" if value is not None and gap <= 120 else "invalid",
                            "reasons": []
                            if value is not None and gap <= 120
                            else ["raw_gap_or_missing"],
                            "coverage": 1.0,
                            "revision": 0,
                            "provenance": "raw_history",
                        }
                    )
                # A bounded raw query that hit its cap must resume, never skip the remainder.
                if len(raw) >= 2000:
                    end = raw[-1].last_updated
            else:
                # Inactive statistic IDs remain selectable; Recorder supplies metadata units.
                metadata = await recorder.async_add_executor_job(
                    partial(statistics.list_statistic_ids, self.hass, {mapping["source"]})
                )
                meta = next((m for m in metadata if m["statistic_id"] == mapping["source"]), None)
                if meta and not compatible_units(meta.get("unit_of_measurement"), mapping["unit"]):
                    raise ValueError(
                        "Statistic unit differs from selected source; review source epoch"
                    )
                # Recorder converts the requested unit family; raw response units are explicit.
                unit_family = (
                    "power"
                    if mapping["unit"] in ("W", "kW")
                    else "energy"
                    if mapping["unit"] in ("Wh", "kWh")
                    else None
                )
                requested_units = {unit_family: mapping["unit"]} if unit_family else None
                values = await recorder.async_add_executor_job(
                    partial(
                        statistics.statistics_during_period,
                        self.hass,
                        start,
                        end,
                        {mapping["source"]},
                        period,
                        requested_units,
                        {"mean", "change"},
                    )
                )
                observations = statistics_observations(
                    mapping, values.get(mapping["source"], []), period
                )
            # Keep each request bounded. Hour/5-minute day <= 288 records; raw <= 1999.
            await self.send(observations, {key: end.isoformat()})
            return  # One day/source per tick; resumable and throttled.
