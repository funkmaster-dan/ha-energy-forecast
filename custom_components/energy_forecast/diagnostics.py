from homeassistant.components.diagnostics import async_redact_data

TO_REDACT = {
    "token",
    "url",
    "source",
    "entity_id",
    "epoch",
    "inputs",
    "latitude",
    "longitude",
    "checkpoints",
    "pending",
}


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = entry.runtime_data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "coordinator_success": runtime.coordinator.last_update_success,
            "forwarding_error": runtime.bridge.last_error,
            "backfill_profiles": len(runtime.bridge.state["checkpoints"]),
            "pending_retry": runtime.bridge.state["pending"] is not None,
        },
        TO_REDACT,
    )
