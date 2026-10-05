# Energy Forecast for Home Assistant

A HACS custom integration for the [Energy Forecast service](https://github.com/funkmaster-dan/energy-forecast). It forwards selected measured inputs and Recorder history, polls one atomic forecast snapshot, and publishes advisory sensors. Forecasting/training runs outside HA. **No battery controls are provided.**

The service's 0.1.0 alpha keeps discretionary export authorization disabled pending source/parameter/tail validation. Forecast totals and shadow diagnostics are still useful. See the service's [delivery status](https://github.com/funkmaster-dan/energy-forecast/blob/main/docs/status.md).

## Installation and pairing

1. In HACS → Custom repositories, add `https://github.com/funkmaster-dan/ha-energy-forecast` as type **Integration**. Download the alpha release and restart HA.
2. Complete site/battery/tariff/source configuration in the service GUI and create an **integration** token.
3. In HA → Settings → Devices & services → Add integration, select **Energy Forecast**. Enter the service's reachable HTTP(S) origin, token and site ID `home`.
4. Open integration options to select input sources and history. The optional discovery form includes current sensors and inactive Recorder statistic IDs. Advanced JSON can express multiple aliases/disjoint inputs.

The HA machine cannot use the service host's `127.0.0.1` address. Use a trusted reachable LAN URL or HTTPS reverse proxy. Tokens are stored in the HA config entry and redacted from diagnostics. Reauthentication accepts a replacement token; unloading cancels forwarding/output timers, and options edits reload the entry.

Tested in an isolated HA Core **2026.9.4** runtime. The actual household instance has not been commissioned. The HACS package requires 2026.9.4 or newer; compatibility should be rechecked on upgrades.

## Source mappings

Example options JSON:

```json
[
  {"source":"sensor.household_load", "feature":"household_load", "unit":"W", "kind":"mean_power", "boundary":"AC", "epoch":"meter-v1", "history":true, "history_period":"hour"},
  {"source":"sensor.pv_ac", "feature":"pv_generation", "unit":"W", "kind":"mean_power", "boundary":"AC", "epoch":"pv-v1", "history":true},
  {"source":"sensor.battery_soc", "feature":"battery_soc", "unit":"%", "kind":"state", "boundary":"stored", "epoch":"battery-v1", "history":false}
]
```

`source` is the entity/statistic ID configured in the service profile. An optional `entity_id` can provide the live entity for an inactive/alternate statistic mapping. Units and boundaries must be verified; gross household load excludes battery charging. DC PV is converted explicitly by the service mapping. Do not map vendor percentage capacity as kWh.

Kinds: `mean_power` (W/kW), `counter` (Wh/kWh cumulative), `interval_energy` (Wh/kWh, requires actual `interval_seconds`) or `state` (SoC/temperature/limits). Change `epoch` when a meter, sign, unit or boundary changes. Missing/unavailable/nonfinite state is forwarded as invalid/null, never zero. Source `last_reported` is retained for state freshness; repeatedly polling an old SoC does not make it fresh.

Historical periods: `hour` long-term statistics, `5minute` short-term statistics, or bounded `raw` Recorder state history. Recorder reset-aware `change` is forwarded as interval energy; mean metadata does not depend on deprecated `has_mean`. Raw integration is gap-limited and does not claim coverage across a long unchanged interval. The bridge performs one bounded source/day page per input tick, persists a pending batch before transmission, and advances its checkpoint only after acknowledgement. Inactive statistic IDs can be selected manually or through discovery.

The service owns stitch/fallback/sum/derived composition. Never add old and new whole-home meters together. Configure disjoint components explicitly before summing phases/banks. Output entities from this integration, including renamed ones, are excluded from input discovery/forwarding.

## Entities and expiry

Ten initial entities publish PV/load 48-hour totals, remaining/now battery export, reserve kWh/SoC, advisory power, readiness, issue time, and `binary_sensor.energy_forecast_export_plan_ready`. Rolling forecast energy has **no** `total_increasing` state class and does not replace measured Energy Dashboard meters. Forecast arrays remain in the service.

All actionable budgets are **replacement** budgets: never add successive runs. Every snapshot has a forecast ID, configuration hash, issuance time and short expiry. Only `ready` with an unexpired generation permits discretionary export. Communication failure immediately makes readiness false; local five-second timers expire cached readiness even when no HTTP update succeeds. Energy/power sensors become unavailable after expiry. Ingestion continues independently of whether output entities are enabled.

User automations must also check actual SoC, hardware alarms, physical reserve, current network limits and execution assumptions. This integration never operates your inverter. A generic consumer guard is in [the contract guide](docs/consumer-contract.md); there is no runnable charge/discharge automation supplied.

## Development

```sh
uv sync
uv run ruff check .
uv run pytest
```

The lightweight tests exercise v1 expiry, schema safety, output feedback prevention, URL/NaN rejection, reset-aware statistics and retry/checkpoint acknowledgement. Pinned source contracts are in `contracts/`; regenerate them from the service's export script when coordinating API changes. A full isolated-runtime smoke script is in `tests/manual_ha_smoke.py` and requires the documented test environment in [validation](docs/validation.md).

Public contents contain only synthetic fixtures/general documentation. Never commit config-entry tokens, HA exports, household telemetry or installation-specific commissioning records. MIT licensed.
