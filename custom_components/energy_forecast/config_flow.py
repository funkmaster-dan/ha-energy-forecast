import json

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.recorder import get_instance, statistics
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import AuthenticationError, Client, ServiceError
from .const import DOMAIN
from .protocol import is_output, valid_url, validate_inputs


def output_ids(hass):
    registry = er.async_get(hass)
    return {entry.entity_id for entry in registry.entities.values() if entry.platform == DOMAIN}


def connection_schema(defaults=None):
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required("url", default=defaults.get("url", "http://192.168.1.10:18080")): str,
            vol.Required("token"): str,
            vol.Required("site_id", default="home"): str,
        }
    )


class EnergyForecastFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                user_input["url"] = valid_url(user_input["url"])
                client = Client(async_get_clientsession(self.hass), **user_input)
                await client.latest()
                await self.async_set_unique_id(f"{user_input['url']}:{user_input['site_id']}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Energy Forecast", data=user_input)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (ServiceError, ValueError):
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user", data_schema=connection_schema(user_input), errors=errors
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()
        if user_input:
            try:
                client = Client(
                    async_get_clientsession(self.hass),
                    entry.data["url"],
                    user_input["token"],
                    entry.data["site_id"],
                )
                await client.latest()
                return self.async_update_reload_and_abort(
                    entry, data_updates={"token": user_input["token"]}
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ServiceError:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("token"): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return EnergyForecastOptions()


class EnergyForecastOptions(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                values = validate_inputs(json.loads(user_input["inputs"]), output_ids(self.hass))
                from datetime import datetime

                datetime.fromisoformat(user_input["history_start"])
                self.draft = {**user_input, "inputs": values}
                add_source = self.draft.pop("add_source", False)
                if add_source:
                    return await self.async_step_discover()
                return self.async_create_entry(title="", data=self.draft)
            except (ValueError, TypeError):
                errors["base"] = "invalid_inputs"
        defaults = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    "inputs", default=json.dumps(defaults.get("inputs", []), indent=2)
                ): str,
                vol.Required(
                    "history_start", default=defaults.get("history_start", "2022-01-01")
                ): str,
                vol.Optional(
                    "enable_backfill", default=defaults.get("enable_backfill", True)
                ): bool,
                vol.Optional("add_source", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "guide": "https://github.com/funkmaster-dan/ha-energy-forecast#source-mappings"
            },
        )

    async def async_step_discover(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                values = validate_inputs(self.draft["inputs"] + [user_input], output_ids(self.hass))
                return self.async_create_entry(title="", data={**self.draft, "inputs": values})
            except (ValueError, TypeError):
                errors["base"] = "invalid_inputs"
        from functools import partial

        metadata = await get_instance(self.hass).async_add_executor_job(
            partial(statistics.list_statistic_ids, self.hass)
        )
        outputs = output_ids(self.hass)
        labels = {
            m[
                "statistic_id"
            ]: f"{m.get('name') or m['statistic_id']} · {m.get('unit_of_measurement') or 'unknown unit'} (Recorder)"
            for m in metadata
            if not is_output(m["statistic_id"], outputs)
        }
        for entity in self.hass.states.async_all("sensor"):
            if not is_output(entity.entity_id, outputs):
                labels.setdefault(
                    entity.entity_id,
                    f"{entity.name} · {entity.attributes.get('unit_of_measurement', 'unknown unit')}",
                )
        options = [{"value": key, "label": value} for key, value in sorted(labels.items())]
        schema = vol.Schema(
            {
                vol.Required("source"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required("feature", default="household_load"): str,
                vol.Required("unit", default="W"): vol.In(
                    ["W", "kW", "Wh", "kWh", "%", "°C", "W/m²"]
                ),
                vol.Required("kind", default="mean_power"): vol.In(
                    ["mean_power", "counter", "interval_energy", "state"]
                ),
                vol.Required("boundary", default="AC"): vol.In(
                    ["AC", "DC", "stored", "environment"]
                ),
                vol.Required("epoch", default="commissioned-v1"): str,
                vol.Optional("history", default=True): bool,
                vol.Optional("history_period", default="hour"): vol.In(["hour", "5minute", "raw"]),
                vol.Optional("interval_seconds", default=60): int,
            }
        )
        return self.async_show_form(step_id="discover", data_schema=schema, errors=errors)
