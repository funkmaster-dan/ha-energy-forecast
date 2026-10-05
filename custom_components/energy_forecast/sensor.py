from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .protocol import ready, unexpired

DESCRIPTIONS = (
    SensorEntityDescription(
        key="pv_48h_kwh",
        name="PV forecast 48 hours",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
    ),
    SensorEntityDescription(
        key="load_48h_kwh",
        name="Load forecast 48 hours",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
    ),
    SensorEntityDescription(
        key="safe_battery_export_remaining_kwh",
        name="Battery export remaining",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
    ),
    SensorEntityDescription(
        key="safe_battery_export_now_kwh",
        name="Battery export now",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
    ),
    SensorEntityDescription(
        key="required_reserve_kwh",
        name="Required battery reserve",
        native_unit_of_measurement="kWh",
        device_class=SensorDeviceClass.ENERGY,
    ),
    SensorEntityDescription(
        key="required_reserve_soc_pct",
        name="Required battery reserve SoC",
        native_unit_of_measurement="%",
    ),
    SensorEntityDescription(
        key="advisory_export_power_kw",
        name="Advisory battery export power",
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
    ),
    SensorEntityDescription(key="status", name="Forecast readiness"),
    SensorEntityDescription(
        key="issued_at", name="Forecast issued", device_class=SensorDeviceClass.TIMESTAMP
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(ForecastSensor(entry, description) for description in DESCRIPTIONS)


class ForecastSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    # Rolling forecast totals are not measured meters: intentionally no state_class.
    def __init__(self, entry, description):
        super().__init__(entry.runtime_data.coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{entry.data['site_id']}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Energy Forecast",
            manufacturer="Energy Forecast",
            model="Advisory service",
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(self.hass, self.expire, timedelta(seconds=5))
        )

    @callback
    def expire(self, _now):
        self.async_write_ha_state()

    @property
    def available(self):
        if self.entity_description.key in ("status", "issued_at"):
            return super().available
        return super().available and unexpired(self.coordinator.data or {})

    @property
    def native_value(self):
        snapshot = self.coordinator.data or {}
        key = self.entity_description.key
        if key == "status":
            return snapshot.get("status") if unexpired(snapshot) else "stale"
        if key == "issued_at":
            from .protocol import timestamp

            return timestamp(snapshot[key]) if snapshot.get(key) else None
        if key in (
            "safe_battery_export_remaining_kwh",
            "safe_battery_export_now_kwh",
            "advisory_export_power_kw",
        ) and not ready(snapshot):
            return 0
        return (
            snapshot.get("totals", {}).get(key)
            if key in ("pv_48h_kwh", "load_48h_kwh")
            else snapshot.get("export_plan", {}).get(key)
        )

    @property
    def extra_state_attributes(self):
        snapshot = self.coordinator.data or {}
        return {
            key: snapshot.get(key)
            for key in ("forecast_id", "issued_at", "valid_until", "configuration_hash")
        } | {
            "replacement_budget": True,
            "reason_codes": snapshot.get("export_plan", {}).get("reason_codes", []),
            "source_soc_at": snapshot.get("export_plan", {}).get("source_soc_at"),
        }
