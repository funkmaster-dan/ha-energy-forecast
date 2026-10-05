from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .protocol import ready


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PlanReady(entry)])


class PlanReady(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Export plan ready"
    _attr_icon = "mdi:shield-check-outline"

    def __init__(self, entry):
        super().__init__(entry.runtime_data.coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{entry.data['site_id']}_export_plan_ready"
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
        return True  # A failed service must publish false, even with a cached ready response.

    @property
    def is_on(self):
        return self.coordinator.last_update_success and ready(self.coordinator.data or {})
