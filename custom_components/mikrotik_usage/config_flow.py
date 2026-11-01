"""Config & options flow: pick the devices to track, then the periods."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (SelectOptionDict, SelectSelector,
                                            SelectSelectorConfig, SelectSelectorMode)

from .const import (CONF_DEVICES, CONF_ESTIMATE, CONF_HA_HOST, CONF_PERIODS, CONF_SWAP,
                    DOMAIN, PERIODS)
from .discovery import discover, find_ip


class _FlowMixin:
    """Shared two-step logic for onboarding and options."""

    _candidates: dict[str, dict[str, Any]]
    _selected: list[dict[str, Any]]

    def _current(self) -> dict[str, Any]:
        return {}

    def _devices_schema(self) -> vol.Schema:
        cur = self._current()
        options = [
            SelectOptionDict(
                value=k,
                label=f"{c['name']}  ·  {c['platform']}"
                      f"{'' if c['rx'] and c['tx'] else '  (one direction only)'}")
            for k, c in self._candidates.items()
        ]
        default = [d["key"] for d in cur.get(CONF_DEVICES, []) if d["key"] in self._candidates]
        return vol.Schema({vol.Required(CONF_DEVICES, default=default): SelectSelector(
            SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST))})

    def _settings_schema(self) -> vol.Schema:
        cur = self._current()
        host_opts = [SelectOptionDict(value=d["key"], label=d["name"]) for d in self._selected]
        host_default = cur.get(CONF_HA_HOST)
        host_key = (vol.Optional(CONF_HA_HOST, description={"suggested_value": host_default}))
        return vol.Schema({
            vol.Required(CONF_PERIODS, default=cur.get(CONF_PERIODS, list(PERIODS))): SelectSelector(
                SelectSelectorConfig(options=list(PERIODS), multiple=True,
                                     translation_key="periods", mode=SelectSelectorMode.LIST)),
            vol.Required(CONF_SWAP, default=cur.get(CONF_SWAP, False)): bool,
            vol.Required(CONF_ESTIMATE, default=cur.get(CONF_ESTIMATE, True)): bool,
            host_key: SelectSelector(SelectSelectorConfig(
                options=host_opts, mode=SelectSelectorMode.DROPDOWN)),
        })

    def _resolve(self, keys: list[str]) -> list[dict[str, Any]]:
        out = []
        for k in keys:
            c = self._candidates[k]
            out.append({"key": k, "name": c["name"], "rx": c["rx"], "tx": c["tx"],
                        "ip": find_ip(self.hass, c["rx"] or c["tx"])})
        return out


class MikrotikUsageConfigFlow(_FlowMixin, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._candidates = discover(self.hass)
        if not self._candidates:
            return self.async_abort(reason="no_candidates")
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_DEVICES]:
                errors["base"] = "no_devices"
            else:
                self._selected = self._resolve(user_input[CONF_DEVICES])
                return await self.async_step_settings()
        return self.async_show_form(step_id="user", data_schema=self._devices_schema(), errors=errors)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Mikrotik Data Usage",
                                           data={CONF_DEVICES: self._selected, **user_input})
        return self.async_show_form(step_id="settings", data_schema=self._settings_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return MikrotikUsageOptionsFlow()


class MikrotikUsageOptionsFlow(_FlowMixin, OptionsFlow):
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        self._candidates = discover(self.hass)
        # keep already-tracked devices selectable even if their sensors are temporarily gone
        for d in self._current().get(CONF_DEVICES, []):
            self._candidates.setdefault(d["key"], {**d, "platform": "saved", "mikrotik": False})
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_DEVICES]:
                errors["base"] = "no_devices"
            else:
                self._selected = self._resolve(user_input[CONF_DEVICES])
                return await self.async_step_settings()
        return self.async_show_form(step_id="init", data_schema=self._devices_schema(), errors=errors)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_DEVICES: self._selected, **user_input})
        return self.async_show_form(step_id="settings", data_schema=self._settings_schema())
