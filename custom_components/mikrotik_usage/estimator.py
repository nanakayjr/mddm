"""Estimate the network data demand of Home Assistant integrations.

Home Assistant exposes no per-integration byte counters, so this is explicit about
how each number is obtained.  Scope comes from the integration's own manifest
(`iot_class`), not from guesswork:

* internet – cloud_polling / cloud_push: estimated as polls/day x typical payload.
* lan      – local_*: stays inside your network.  Measured if its host is a device you
             track (real router counters), otherwise a polling estimate (local_polling)
             or "no estimate" (local_push, which only sends on change).
* hidden   – radio protocols (Zigbee, Z-Wave, Bluetooth, Thread), helpers, calculated
             and system integrations: they generate no IP traffic.

One row per integration (all its config entries merged), named by the integration,
never by the user's account/device name.
"""

from __future__ import annotations

import ipaddress
import logging
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

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
# Radio / serial protocols: no IP traffic worth reporting.
RADIO = {"zha", "zwave_js", "zwave_me", "bluetooth", "bluetooth_adapters", "thread", "otbr",
         "enocean", "insteon", "ble_monitor", "govee_ble", "xiaomi_ble", "switchbot_bluetooth",
         "ibeacon", "bthome", "led_ble", "improv_ble", "ruuvitag_ble", "inkbird", "sensorpush"}
HIDDEN_TYPES = {"helper", "system", "hardware", "virtual", "entity"}
SKIP = {DOMAIN, "sun", "backup", "hassio", "analytics", "go2rtc", "mobile_app", "person",
        "zone", "homeassistant_alerts", "radio_browser", "shopping_list",
        "mikrotik_extended", "mikrotik_router", "mikrotik", "hacs"}
CLOUD_PUSH_PROFILE = (3_000, 300)  # keepalive-ish
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


_PRIORITY = ["unmodelled", "estimated", "lan", "lan_push", "measured"]


async def async_estimate_services(hass: HomeAssistant, tracked: list[dict[str, Any]],
                                  measured: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """Return one row per integration (entries merged)."""
    by_ip = {d["ip"]: d for d in tracked if d.get("ip")}
    by_key = {d["key"]: d for d in tracked}
    merged: dict[str, dict[str, Any]] = {}
    shares: dict[str, list[dict[str, Any]]] = {}

    for entry in hass.config_entries.async_entries():
        dom = entry.domain
        if dom in SKIP or dom in RADIO:
            continue
        try:
            integ = await async_get_integration(hass, dom)
        except Exception:  # noqa: BLE001
            continue
        iot = getattr(integ, "iot_class", None) or ""
        itype = getattr(integ, "integration_type", None) or ""
        if itype in HIDDEN_TYPES or iot == "calculated":
            continue
        scope = "internet" if iot.startswith("cloud") else "lan"
        host = _host_of(entry)
        match = by_ip.get(host) or by_key.get(host.split(".")[0].lower()) if host else None
        e: dict[str, Any] = {"mode": "estimated", "device": None, "day": None, "month": None,
                             "polls": None}
        if match:
            e["mode"], e["device"] = "measured", match["key"]
        elif dom in UNMODELLED:
            e["mode"] = "unmodelled"
        elif iot == "local_push":
            e["mode"] = "lan_push"
        else:
            if iot == "cloud_push":
                payload, default_iv = CLOUD_PUSH_PROFILE
            else:
                payload, default_iv = PROFILES.get(dom, DEFAULT_PROFILE)
            interval = _find_interval(getattr(entry, "runtime_data", None)) or \
                _find_interval(hass.data.get(dom)) or default_iv
            polls = 86400 / max(interval, 1)
            e.update(polls=polls, day=payload * polls, month=payload * polls * 30)
            if scope == "lan":
                e["mode"] = "lan"
        row = merged.setdefault(dom, {
            "domain": dom, "name": integ.name or dom, "scope": scope, "entries": 0,
            "modes": [], "day": None, "month": None, "polls_per_day": None})
        row["entries"] += 1
        row["modes"].append(e["mode"])
        for f, src in (("day", "day"), ("month", "month")):
            if e[src] is not None:
                row[f] = (row[f] or 0.0) + e[src]
        if e["polls"] is not None:
            row["polls_per_day"] = (row["polls_per_day"] or 0) + round(e["polls"])
        if e["mode"] == "measured":
            shares.setdefault(e["device"], []).append(row)

    # measured: split a device's real traffic evenly between entries sharing it
    for key, rows in shares.items():
        m = measured.get(key, {})
        for row in rows:
            row["day"] = (row["day"] or 0.0) + m.get("day", 0.0) / len(rows)
            row["month"] = (row["month"] or 0.0) + m.get("month", 0.0) / len(rows)

    out = []
    for row in merged.values():
        row["mode"] = next(m for m in _PRIORITY if m in row["modes"])
        del row["modes"]
        out.append(row)
    out.sort(key=lambda r: (r["scope"] != "internet", r["month"] is None, -(r["month"] or 0)))
    return out
