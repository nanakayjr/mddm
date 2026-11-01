"""Mikrotik Data Usage – per-device and per-service data accounting with a ready dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PANEL_URL, STATIC_URL
from .coordinator import UsageConfigEntry, UsageCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
VERSION = "0.1.0"
_PANEL_FLAG = f"{DOMAIN}_panel_registered"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    websocket_api.async_register_command(hass, ws_history)
    return True


@websocket_api.websocket_command({
    vol.Required("type"): "mikrotik_usage/history",
    vol.Required("entry_id"): str,
    vol.Optional("days", default=30): vol.All(int, vol.Range(min=1, max=400)),
})
@websocket_api.async_response
async def ws_history(hass: HomeAssistant, connection, msg: dict) -> None:
    entry = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None or entry.domain != DOMAIN or not hasattr(entry, "runtime_data"):
        connection.send_error(msg["id"], "not_found", "Unknown entry")
        return
    connection.send_result(msg["id"], entry.runtime_data.history(msg["days"]))


async def _register_panel(hass: HomeAssistant) -> None:
    if hass.data.get(_PANEL_FLAG):
        return
    js = Path(__file__).parent / "frontend" / "mikrotik-usage-panel.js"
    await hass.http.async_register_static_paths([StaticPathConfig(STATIC_URL, str(js), False)])
    await panel_custom.async_register_panel(
        hass, webcomponent_name="mikrotik-usage-panel", frontend_url_path=PANEL_URL,
        module_url=f"{STATIC_URL}?v={VERSION}", sidebar_title="Data Usage",
        sidebar_icon="mdi:router-network", require_admin=False, config={})
    hass.data[_PANEL_FLAG] = True


async def async_setup_entry(hass: HomeAssistant, entry: UsageConfigEntry) -> bool:
    coordinator = UsageCoordinator(hass, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await _register_panel(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload))
    return True


async def _reload(hass: HomeAssistant, entry: UsageConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: UsageConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data._store.async_save(entry.runtime_data.engine.to_dict())
        others = [e for e in hass.config_entries.async_entries(DOMAIN)
                  if e.entry_id != entry.entry_id]
        if not others and hass.data.pop(_PANEL_FLAG, None):
            frontend.async_remove_panel(hass, PANEL_URL)
    return ok
