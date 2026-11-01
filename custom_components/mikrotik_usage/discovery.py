"""Find traffic sensors already present in Home Assistant.

Accepts both cumulative counters (GB...) and throughput sensors (kb/s...), groups
them by device/port name and direction.  Disabled registry entries are reported so the
user knows to enable them.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import MIKROTIK_PLATFORMS
from .engine import classify_unit, split_direction

_IP_ATTRS = ("ip", "ip_address", "ipaddress", "ip_addr", "address")


def find_ip(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Best effort: look for an IP attribute on the sensor or its sibling entities."""
    if not entity_id:
        return None
    reg = er.async_get(hass)
    ids = [entity_id]
    entry = reg.async_get(entity_id)
    if entry and entry.device_id:
        ids += [e.entity_id for e in er.async_entries_for_device(reg, entry.device_id)]
    for eid in ids:
        st = hass.states.get(eid)
        if not st:
            continue
        for attr in _IP_ATTRS:
            val = st.attributes.get(attr)
            if isinstance(val, str) and re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", val):
                return val
    return None


def _device_name(hass: HomeAssistant, entry: er.RegistryEntry | None) -> str | None:
    if entry and entry.device_id:
        dev = dr.async_get(hass).async_get(entry.device_id)
        if dev:
            return dev.name_by_user or dev.name
    return None


def _parse(hass, st, entry) -> tuple[str, str] | None:
    """Return (direction, base name) for a sensor state, or None."""
    obj = st.entity_id.split(".", 1)[1]
    friendly = st.attributes.get("friendly_name")
    for text in (friendly, obj):
        res = split_direction(text)
        if res:
            d, base = res
            return d, (base or _device_name(hass, entry) or "").strip() or None  # type: ignore[return-value]
    if entry:
        for text in (entry.original_name, entry.translation_key, entry.unique_id):
            res = split_direction(text if isinstance(text, str) else None)
            if res:
                base = _device_name(hass, entry) or res[1] or friendly
                if base:
                    return res[0], base
    return None


def discover(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """{key: {key,name,platform,mikrotik, rx:{rate,counter}, tx:{rate,counter}}}"""
    reg = er.async_get(hass)
    found: dict[str, dict[str, Any]] = {}
    for st in hass.states.async_all("sensor"):
        entry = reg.async_get(st.entity_id)
        unit = st.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or (entry.unit_of_measurement if entry else None)
        cls = classify_unit(unit)
        if cls is None:
            continue
        parsed = _parse(hass, st, entry)
        if not parsed or not parsed[1]:
            continue
        direction, base = parsed
        platform = entry.platform if entry else "unknown"
        cand = found.setdefault(slugify(base), {
            "key": slugify(base), "name": base, "platform": platform,
            "mikrotik": platform in MIKROTIK_PLATFORMS, "rx": {}, "tx": {}})
        cand[direction].setdefault(cls[0], st.entity_id)
    return dict(sorted(found.items(), key=lambda kv: (not kv[1]["mikrotik"], kv[1]["name"].lower())))


def disabled_traffic_sensors(hass: HomeAssistant) -> int:
    """Count disabled MikroTik sensors that look like TX/RX traffic."""
    n = 0
    for e in er.async_get(hass).entities.values():
        if e.domain != "sensor" or e.platform not in MIKROTIK_PLATFORMS or not e.disabled_by:
            continue
        if any(split_direction(t) for t in (e.original_name, e.entity_id.split(".", 1)[1], e.unique_id)
               if isinstance(t, str)):
            n += 1
    return n


def pick(cand: dict[str, Any], direction: str, prefer_rate: bool) -> str | None:
    slot = cand.get(direction) or {}
    order = ("rate", "counter", "manual") if prefer_rate else ("counter", "rate", "manual")
    for mode in order:
        if slot.get(mode):
            return slot[mode]
    return None
