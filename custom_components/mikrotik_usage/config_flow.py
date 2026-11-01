"""Config & options flow: pick devices to track (auto-detected or manual), then settings."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (EntitySelector, EntitySelectorConfig, SelectOptionDict,
                                            SelectSelector, SelectSelectorConfig, SelectSelectorMode)
from homeassistant.util import slugify

from .const import (CONF_DEVICES, CONF_ESTIMATE, CONF_HA_HOST, CONF_PERIODS, CONF_PREFER_RATE,
                    CONF_SWAP, DOMAIN, PERIODS)
from .discovery import disabled_traffic_sensors, discover, find_ip, pick

M_NAME, M_RX, M_TX = "manual_name", "manual_rx", "manual_tx"


class _FlowMixin:
    _candidates: dict[str, dict[str, Any]]
    _keys: list[str]

    def _current(self) -> dict[str, Any]:
        return {}

    def _hint(self) -> str:
        n = disabled_traffic_sensors(self.hass)
        return (f"{n} disabled MikroTik TX/RX sensors exist – enable them in Settings → Entities "
                f"(they are often off by default), then reopen this dialog. ") if n else ""

    @staticmethod
    def _modes(c: dict[str, Any]) -> str:
        modes = {m for d in ("rx", "tx") for m in (c.get(d) or {}) if (c.get(d) or {}).get(m)}
        names = {"rate": "throughput", "counter": "total", "manual": "manual"}
        return "+".join(names[m] for m in sorted(modes))

    def _devices_schema(self) -> vol.Schema:
        cur, fields = self._current(), {}
        if self._candidates:
            options = [SelectOptionDict(value=k, label=f"{c['name']}  ·  {self._modes(c)}  ·  {c['platform']}")
                       for k, c in self._candidates.items()]
            default = [d["key"] for d in cur.get(CONF_DEVICES, []) if d["key"] in self._candidates]
            fields[vol.Optional(CONF_DEVICES, default=default)] = SelectSelector(
                SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST))
        sel = EntitySelector(EntitySelectorConfig(domain="sensor"))
        fields[vol.Optional(M_NAME)] = str
        fields[vol.Optional(M_RX)] = sel
        fields[vol.Optional(M_TX)] = sel
        return vol.Schema(fields)

    def _placeholders(self) -> dict[str, str]:
        return {"found": str(len(self._candidates)), "hint": self._hint()}

    def _ingest(self, ui: dict[str, Any]) -> bool:
        keys = list(ui.get(CONF_DEVICES, []))
        rx, tx = ui.get(M_RX), ui.get(M_TX)
        if rx or tx:
            name = (ui.get(M_NAME) or (rx or tx).split(".", 1)[1].replace("_", " ")).strip()
            key = slugify(name)
            self._candidates[key] = {"key": key, "name": name, "platform": "manual", "mikrotik": False,
                                     "rx": {"manual": rx} if rx else {}, "tx": {"manual": tx} if tx else {}}
            keys.append(key)
        self._keys = list(dict.fromkeys(keys))
        return bool(self._keys)

    def _settings_schema(self) -> vol.Schema:
        cur = self._current()
        host_opts = [SelectOptionDict(value=k, label=self._candidates[k]["name"]) for k in self._keys]
        return vol.Schema({
            vol.Required(CONF_PERIODS, default=cur.get(CONF_PERIODS, list(PERIODS))): SelectSelector(
                SelectSelectorConfig(options=list(PERIODS), multiple=True,
                                     translation_key="periods", mode=SelectSelectorMode.LIST)),
            vol.Required(CONF_PREFER_RATE, default=cur.get(CONF_PREFER_RATE, False)): bool,
            vol.Required(CONF_SWAP, default=cur.get(CONF_SWAP, False)): bool,
            vol.Required(CONF_ESTIMATE, default=cur.get(CONF_ESTIMATE, True)): bool,
            vol.Optional(CONF_HA_HOST, description={"suggested_value": cur.get(CONF_HA_HOST)}):
                SelectSelector(SelectSelectorConfig(options=host_opts, mode=SelectSelectorMode.DROPDOWN)),
        })

    def _resolve(self, prefer_rate: bool) -> list[dict[str, Any]]:
        out = []
        for k in self._keys:
            c = self._candidates[k]
            rx, tx = pick(c, "rx", prefer_rate), pick(c, "tx", prefer_rate)
            out.append({"key": k, "name": c["name"], "rx": rx, "tx": tx,
                        "ip": find_ip(self.hass, rx or tx)})
        return out


class MikrotikUsageConfigFlow(_FlowMixin, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is None:
            self._candidates = discover(self.hass)
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._ingest(user_input):
                return await self.async_step_settings()
            errors["base"] = "no_devices"
        return self.async_show_form(step_id="user", data_schema=self._devices_schema(), errors=errors,
                                    description_placeholders=self._placeholders())

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            devices = self._resolve(user_input.get(CONF_PREFER_RATE, False))
            return self.async_create_entry(title="Mikrotik Data Usage",
                                           data={CONF_DEVICES: devices, **user_input})
        return self.async_show_form(step_id="settings", data_schema=self._settings_schema())

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return MikrotikUsageOptionsFlow()


class MikrotikUsageOptionsFlow(_FlowMixin, OptionsFlow):
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            self._candidates = discover(self.hass)
            for d in self._current().get(CONF_DEVICES, []):  # keep saved devices selectable
                self._candidates.setdefault(d["key"], {
                    "key": d["key"], "name": d["name"], "platform": "saved", "mikrotik": False,
                    "rx": {"manual": d["rx"]} if d.get("rx") else {},
                    "tx": {"manual": d["tx"]} if d.get("tx") else {}})
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._ingest(user_input):
                return await self.async_step_settings()
            errors["base"] = "no_devices"
        return self.async_show_form(step_id="init", data_schema=self._devices_schema(), errors=errors,
                                    description_placeholders=self._placeholders())

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            devices = self._resolve(user_input.get(CONF_PREFER_RATE, False))
            return self.async_create_entry(data={CONF_DEVICES: devices, **user_input})
        return self.async_show_form(step_id="settings", data_schema=self._settings_schema())
