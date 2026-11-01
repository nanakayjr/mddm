"""Estimate the network data demand of Home Assistant integrations.

Home Assistant exposes no per-integration byte counters, so this is explicit about
how each number is obtained:

* measured   – the integration talks to a LAN host that is one of the devices
               you track; the router's real counters are used.
* estimated  – a cloud/polling integration: polls/day x typical payload.
* lan        – LAN integration whose host is not tracked: same estimate, flagged.
* unmodelled – streaming / media / camera style integrations: not estimable.
"""

from __future__ import annotations

import ipaddress
import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# domain -> (bytes per poll incl. TLS/HTTP overhead, default interval seconds)
PROFILES: dict[str, tuple[int, int]] = {
    "met": (12_000, 3600), "openweathermap": (10_000, 600), "accuweather": (8_000, 1800),
    "pirateweather": (10_000, 600), "ipma": (8_000, 1800), "nws": (15_000, 600),
    "github": (6_000, 300), "speedtestdotnet": (0, 3600), "hacs": (30_000, 1800),
    "google_travel_time": (5_000, 300), "waze_travel_time": (5_000, 300),
    "nordpool": (20_000, 3600), "tibber": (8_000, 300), "octopus_energy": (10_000, 1800),
    "ecobee": (4_000, 180), "nest": (4_000, 60), "myq": (3_000, 60), "tuya": (3_000, 30),
    "smartthings": (4_000, 60), "withings": (5_000, 1800), "fitbit": (5_000, 900),
    "todoist": (4_000, 900), "google_calendar": (6_000, 900), "caldav": (6_000, 900),
    "adguard": (2_000, 10), "pi_hole": (2_000, 120), "unifi": (3_000, 30),
}
DEFAULT_PROFILE = (4_000, 60)

UNMODELLED = {
    "cast", "spotify", "plex", "jellyfin", "roku", "sonos", "camera", "generic", "ffmpeg",
    "stream", "onvif", "reolink", "nabucasa", "cloud", "tts", "google_translate",
    "wyoming", "voip", "mjpeg", "frigate", "androidtv_remote", "apple_tv",
}
# Local-push protocols with negligible/unknown network cost.
LOCAL_PUSH = {"zha", "zwave_js", "matter", "mqtt", "esphome", "homekit_controller", "thread",
              "bluetooth", "ble_monitor", "govee_ble", "xiaomi_ble", "otbr", "isy994"}
SKIP = {DOMAIN, "sun", "backup", "hassio", "analytics", "go2rtc", "mobile_app", "person",
        "zone", "homeassistant_alerts", "radio_browser", "shopping_list", "met_eireann",
        "mikrotik_extended", "mikrotik_router", "mikrotik"}
_HOST_KEYS = ("host", "ip_address", "ip", "address", "url", "base_url", "hostname", "server")


def _host_of(entry) -> str | None:
    for src in (entry.data, entry.options):
        for k in _HOST_KEYS:
            v = src.get(k)
            if isinstance(v, str) and v:
                if "://" in v:
                    return urlparse(v).hostname
                return v.split(":")[0]
    return None


def _is_lan(host: str | None) -> bool:
    if not host:
        return False
    if host.endswith((".local", ".lan", ".home", ".internal")) or "." not in host:
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _find_interval(obj: Any, depth: int = 0) -> float | None:
    """Best-effort search for a coordinator update_interval below a runtime object."""
    if obj is None or depth > 2:
        return None
    iv = getattr(obj, "update_interval", None)
    if isinstance(iv, timedelta) and iv.total_seconds() > 0:
        return iv.total_seconds()
    children: list[Any] = []
    if isinstance(obj, dict):
        children = list(obj.values())
    elif isinstance(obj, (list, tuple, set)):
        children = list(obj)
    else:
        try:
            children = list(vars(obj).values())
        except TypeError:
            pass
    for child in children[:25]:
        found = _find_interval(child, depth + 1)
        if found:
            return found
    return None


def estimate_services(hass: HomeAssistant, tracked: list[dict[str, Any]],
                      measured: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """Return one row per integration config entry.

    `tracked`  – tracked devices (with optional `ip`).
    `measured` – {device_key: {"day": bytes, "month": bytes}} real router numbers.
    """
    by_ip = {d["ip"]: d for d in tracked if d.get("ip")}
    by_name = {d["key"]: d for d in tracked}
    rows: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = {}

    for entry in hass.config_entries.async_entries():
        if entry.domain in SKIP:
            continue
        host = _host_of(entry)
        row: dict[str, Any] = {
            "domain": entry.domain, "title": entry.title or entry.domain, "host": host,
            "mode": "estimated", "device": None, "day": 0.0, "month": 0.0, "polls_per_day": None,
        }
        match = None
        if host:
            match = by_ip.get(host) or by_name.get(host.split(".")[0].lower())
        if match:
            row["mode"], row["device"] = "measured", match["key"]
            groups.setdefault(match["key"], []).append(row)
        elif entry.domain in UNMODELLED:
            row["mode"], row["day"], row["month"] = "unmodelled", None, None
        elif entry.domain in LOCAL_PUSH:
            row["mode"], row["day"], row["month"] = "lan", 0.0, 0.0
        else:
            payload, default_iv = PROFILES.get(entry.domain, DEFAULT_PROFILE)
            interval = _find_interval(getattr(entry, "runtime_data", None)) or \
                _find_interval(hass.data.get(entry.domain)) or default_iv
            polls = 86400 / max(interval, 1)
            row["polls_per_day"] = round(polls)
            row["day"] = payload * polls
            row["month"] = row["day"] * 30
            if _is_lan(host):
                row["mode"] = "lan"
        rows.append(row)

    # measured: split a device's real traffic evenly between integrations sharing it
    for key, members in groups.items():
        m = measured.get(key, {})
        for row in members:
            row["day"] = m.get("day", 0.0) / len(members)
            row["month"] = m.get("month", 0.0) / len(members)

    rows.sort(key=lambda r: (r["month"] is None, -(r["month"] or 0)))
    return rows
