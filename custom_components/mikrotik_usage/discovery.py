"""Find traffic sensors already present in Home Assistant."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import MIKROTIK_PLATFORMS
from .engine import classify_unit

_DIR_RE = re.compile(r"^(?P<base>.*?)[\s_\-]*(?P<dir>tx|rx)$", re.IGNORECASE)
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


def discover(hass: HomeAssistant) -> dict[str, dict[str, Any]]:
    """Return candidates {key: {key,name,rx,tx,platform,mikrotik}}."""
    reg = er.async_get(hass)
    found: dict[str, dict[str, Any]] = {}
    for st in hass.states.async_all("sensor"):
        if classify_unit(st.attributes.get(ATTR_UNIT_OF_MEASUREMENT)) is None:
            continue
        label = st.attributes.get("friendly_name") or st.entity_id.split(".", 1)[1]
        m = _DIR_RE.match(label.strip()) or _DIR_RE.match(st.entity_id.split(".", 1)[1])
        if not m or not m.group("base").strip():
            continue
        base = m.group("base").strip().replace("_", " ")
        key = slugify(base)
        entry = reg.async_get(st.entity_id)
        platform = entry.platform if entry else "unknown"
        cand = found.setdefault(
            key,
            {"key": key, "name": base, "rx": None, "tx": None,
             "platform": platform, "mikrotik": platform in MIKROTIK_PLATFORMS},
        )
        cand[m.group("dir").lower()] = st.entity_id
    return dict(
        sorted(found.items(), key=lambda kv: (not kv[1]["mikrotik"], kv[1]["name"].lower()))
    )
