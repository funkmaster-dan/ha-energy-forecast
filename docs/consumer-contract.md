# Advisory consumer contract

The alpha publishes zero permitted battery export while operating confidence is unvalidated. Shadow candidate energy is a diagnostic; do not feed it to a control automation.

A future ready consumer needs all of these at the same time: readiness binary sensor on, budget/power available and nonnegative, matching forecast generation/configuration, unexpired `valid_until`, fresh input SoC, reserve headroom, healthy battery/inverter, confirmed current limits, and any conditional charging assumption actually fulfilled. Budget updates replace prior authorizations and share the complete horizon energy balance across windows.

An illustrative read-only HA guard (adapt entity IDs after checking your installation):

```jinja
{% set plan = 'sensor.energy_forecast_battery_export_remaining' %}
{% set until = state_attr(plan, 'valid_until') %}
{{ is_state('binary_sensor.energy_forecast_export_plan_ready', 'on')
   and states(plan) not in ['unknown', 'unavailable']
   and until is not none
   and as_timestamp(until, 0) > as_timestamp(now())
   and states(plan) | float(0) > 0 }}
```

This guard is incomplete for hardware control: add independent actual-state/alarm/limit checks in your own automation. Stop discretionary export on expiry, communication failure, unavailable/invalid values, reduced replacement budget, reserve breach or an unfulfilled charging assumption. Physical fast protection stays with HA/inverter protections. Neither package executes this guard or calls a device control service.

Do not multiply a cumulative kWh window budget into unrestricted instantaneous power. `safe_battery_export_now_kwh` applies only to its stated short interval; use the current leased advisory power/interval contract. Never keep exporting simply because an old positive budget remains visible as a diagnostic.
