"""Pure accounting engine (no Home Assistant imports, unit-testable).

All volumes are stored in BYTES.  Two source types are supported:

* "rate"    – a throughput sensor (bps, kbps, Mbps, B/s ...).  Integrated over time
              with the trapezoid rule.
* "counter" – a cumulative data sensor (B, MB, GB ...).  Deltas are accumulated;
              a decrease is treated as a counter reset (new value == usage since reset).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .const import (BACKUP_ACK_OVERHEAD, BACKUP_ADDON_NAMES, CORE_KEY, CORE_NAME,
                    LOCAL_ADDON_NAMES, PROFILE_BACKUP, PROFILE_LOCAL, PROFILE_STANDARD,
                    PROFILE_TUNNEL, TUNNEL_ADDON_NAMES, TUNNEL_WAN_SHARE, WAN_HINT_NAMES)

PERIODS = ("day", "month", "year")
# rx/tx are the volumes that really crossed the WAN; the internal_bridge_* metrics hold
# container traffic that stayed on the internal Docker bridge.
METRICS = ("rx", "tx", "internal_bridge_rx", "internal_bridge_tx")
MAX_GAP_S = 600  # do not integrate rates across gaps longer than this
HISTORY_DAYS = 400

_PREFIX = {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9, "t": 1e12, "p": 1e15}
_UNIT_RE = re.compile(r"^([kKmMgGtTpP]?)(i?)(bits?|bytes?|b|B)\s*(/s|ps|/sec|/second)?$")


def classify_unit(unit: str | None) -> tuple[str, float] | None:
    """Parse any reasonable data unit -> ("rate"|"counter", bytes factor).

    Handles bit/byte via case (kbps, Kb/s, kbit/s = bits; kB/s, KBps, MB = bytes),
    SI and IEC prefixes, and "per second" suffixes.  Returns None if not a data unit.
    """
    if not unit:
        return None
    m = _UNIT_RE.match(unit.strip())
    if not m:
        return None
    pre, iec, base, per_s = m.groups()
    mult = _PREFIX[pre.lower()]
    if iec:
        mult = 1024.0 ** "kmgtp".index(pre.lower()) * 1024.0 if pre else 1.0
    is_bytes = base[0] == "B" or base.lower().startswith("byte")
    factor = mult * (1.0 if is_bytes else 1 / 8)
    return ("rate" if per_s else "counter"), factor


_DIR = {"tx": "tx", "rx": "rx", "transmit": "tx", "transmitted": "tx", "upload": "tx",
        "uploaded": "tx", "receive": "rx", "received": "rx", "download": "rx",
        "downloaded": "rx"}
_NOISE = {"total", "rate", "speed", "traffic", "bandwidth", "throughput", "usage", "bytes", "kbps",
          "mbps", "bps", "data"}
_SPLIT = re.compile(r"[\s_\-./]+")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def split_direction(text: str | None) -> tuple[str, str] | None:
    """"John iPhone TX rate" -> ("tx", "John iPhone").  None if no direction word."""
    if not text:
        return None
    for candidate in (text, _CAMEL.sub(" ", text)):
        toks = [t for t in _SPLIT.split(candidate) if t]
        for i in range(len(toks) - 1, -1, -1):
            d = _DIR.get(toks[i].lower())
            if d:
                rest = toks[:i] + [t for t in toks[i + 1:] if t.lower() not in _NOISE]
                return d, " ".join(rest).strip()
    return None


def period_keys(now: datetime) -> dict[str, str]:
    return {
        "day": now.strftime("%Y-%m-%d"),
        "month": now.strftime("%Y-%m"),
        "year": now.strftime("%Y"),
    }


class Engine:
    """Holds per-device accumulators and per-source last samples."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        data = data or {}
        self.devices: dict[str, dict[str, Any]] = data.get("devices", {})
        self.last: dict[str, dict[str, float]] = data.get("last", {})

    # ---------------------------------------------------------------- persistence
    def to_dict(self) -> dict[str, Any]:
        return {"devices": self.devices, "last": self.last}

    # ---------------------------------------------------------------- accumulators
    def ensure(self, key: str, name: str, profile: str | None = None) -> dict[str, Any]:
        dev = self.devices.setdefault(key, {"history": {}})
        dev["name"] = name
        if profile:
            dev["profile"] = profile
        dev.setdefault("history", {})
        return dev

    def _roll(self, dev: dict[str, Any], now: datetime) -> None:
        for period, k in period_keys(now).items():
            cur = dev.get(period)
            if cur is None:
                dev[period] = {"key": k, **dict.fromkeys(METRICS, 0.0)}
            elif cur["key"] != k:
                if period == "day":
                    hist = dev["history"]
                    hist[cur["key"]] = [cur["rx"], cur["tx"]]
                    for old in sorted(hist)[:-HISTORY_DAYS]:
                        del hist[old]
                dev[period] = {"key": k, **dict.fromkeys(METRICS, 0.0)}

    def add(self, key: str, direction: str, nbytes: float, now: datetime) -> None:
        dev = self.devices[key]
        self._roll(dev, now)
        for period in PERIODS:
            dev[period][direction] = dev[period].get(direction, 0.0) + nbytes

    def totals(self, key: str, period: str, now: datetime) -> tuple[float, float]:
        dev = self.devices[key]
        self._roll(dev, now)
        return dev[period]["rx"], dev[period]["tx"]

    def internal_totals(self, key: str, period: str, now: datetime) -> tuple[float, float]:
        dev = self.devices[key]
        self._roll(dev, now)
        cur = dev[period]
        return cur.get("internal_bridge_rx", 0.0), cur.get("internal_bridge_tx", 0.0)

    def ranking(self, period: str, now: datetime) -> list[dict[str, Any]]:
        rows = []
        for key, dev in self.devices.items():
            rx, tx = self.totals(key, period, now)
            irx, itx = self.internal_totals(key, period, now)
            rows.append({"key": key, "name": dev["name"], "rx": rx, "tx": tx, "total": rx + tx,
                         "internal_bridge_rx": irx, "internal_bridge_tx": itx,
                         "internal_total": irx + itx, **({"profile": dev["profile"]}
                                                         if "profile" in dev else {})})
        rows.sort(key=lambda r: (r["total"], r["internal_total"]), reverse=True)
        _set_shares(rows)
        return rows

    def history(self, now: datetime, days: int) -> dict[str, Any]:
        """Daily history (bytes) for the last `days` days incl. today."""
        from datetime import timedelta

        dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)]
        today = now.strftime("%Y-%m-%d")
        out_dev: dict[str, Any] = {}
        network = {d: [0.0, 0.0] for d in dates}
        for key, dev in self.devices.items():
            self._roll(dev, now)
            series = []
            for d in dates:
                if d == today:
                    rx, tx = dev["day"]["rx"], dev["day"]["tx"]
                else:
                    rx, tx = dev["history"].get(d, [0.0, 0.0])
                series.append({"date": d, "rx": rx, "tx": tx})
                network[d][0] += rx
                network[d][1] += tx
            out_dev[key] = {"name": dev["name"], "days": series}
        return {
            "network": [{"date": d, "rx": v[0], "tx": v[1]} for d, v in network.items()],
            "devices": out_dev,
        }

    # ---------------------------------------------------------------- sampling
    def sample_counter(self, source: str, value_bytes: float, now: datetime) -> float:
        prev = self.last.get(source)
        self.last[source] = {"v": value_bytes, "t": now.timestamp()}
        if prev is None:
            return 0.0
        delta = value_bytes - prev["v"]
        if delta < 0:  # counter reset
            delta = value_bytes
        return delta

    def sample_rate(self, source: str, bytes_per_s: float, now: datetime) -> float:
        ts = now.timestamp()
        prev = self.last.get(source)
        if prev is not None and ts <= prev["t"]:
            return 0.0
        self.last[source] = {"v": bytes_per_s, "t": ts}
        if prev is None:
            return 0.0
        dt = ts - prev["t"]
        if dt > MAX_GAP_S:
            return 0.0
        return (prev["v"] + bytes_per_s) / 2 * dt


# ---------------------------------------------------------------- add-on WAN attribution
def _set_shares(rows: list[dict[str, Any]]) -> None:
    grand = sum(r["total"] for r in rows) or 1.0
    igrand = sum(r.get("internal_total", 0.0) for r in rows) or 1.0
    for r in rows:
        r["share"] = round(r["total"] / grand * 100, 1)
        r["internal_share"] = round(r.get("internal_total", 0.0) / igrand * 100, 1)


def _exposed_ports(info: dict[str, Any]) -> int:
    ports = info.get("ports") or info.get("network") or {}
    return sum(1 for v in ports.values() if v) if isinstance(ports, dict) else 0


def classify_addon(slug: str, info: dict[str, Any] | None = None) -> str:
    """Network profile of an add-on from its slug, then its Supervisor /info metadata."""
    base = re.sub(r"^(core|[0-9a-f]{8})_", "", slug.lower())
    if base in BACKUP_ADDON_NAMES or "backup" in base and base not in LOCAL_ADDON_NAMES:
        return PROFILE_BACKUP
    if base in TUNNEL_ADDON_NAMES:
        return PROFILE_TUNNEL
    if base in LOCAL_ADDON_NAMES:
        return PROFILE_LOCAL
    info = info or {}
    ingress_only = bool(info.get("ingress_only")) or (
        bool(info.get("ingress")) and info.get("ingress_only") is None)
    if (ingress_only and not info.get("host_network") and not _exposed_ports(info)
            and base not in WAN_HINT_NAMES):
        return PROFILE_LOCAL
    return PROFILE_STANDARD


def split_addon_traffic(profile: str, rx: float, tx: float) -> dict[str, float]:
    """Split a container's raw veth byte deltas into real WAN bytes and internal bridge bytes."""
    if profile == PROFILE_LOCAL:
        wan_rx = wan_tx = 0.0
    elif profile == PROFILE_BACKUP:
        # Only the upload is internet; RX beyond the ACKs of that upload is the snapshot pull
        # from the Supervisor over 172.30.32.x.
        wan_tx = tx
        wan_rx = min(rx, tx * BACKUP_ACK_OVERHEAD)
    elif profile == PROFILE_TUNNEL:
        # Each proxied byte crosses the veth twice: once on the WAN hop, once towards HA Core.
        wan_rx, wan_tx = rx * TUNNEL_WAN_SHARE, tx * TUNNEL_WAN_SHARE
    else:
        wan_rx, wan_tx = rx, tx
    return {"rx": wan_rx, "tx": wan_tx,
            "internal_bridge_rx": rx - wan_rx, "internal_bridge_tx": tx - wan_tx}


def attribute_wan(rows: list[dict[str, Any]],
                  host: tuple[float, float] | None) -> list[dict[str, Any]]:
    """Add the Home Assistant Core row and reconcile add-on WAN with the router's host total.

    `rows` are add-on ranking rows (WAN rx/tx already separated from internal bridge bytes),
    `host` is the MikroTik RX/TX of the Home Assistant host for the same period (or None).
    Add-on WAN can never exceed what the router saw, so if it does it is scaled down using
    the WAN weights only (local bridge traffic has weight 0).  What the add-ons do not
    explain is attributed to Core (cloud integrations, HACS, streams, voice) and the
    Supervisor (OS / container updates).
    """
    out = [dict(r) for r in rows]
    core = {"key": CORE_KEY, "name": CORE_NAME, "rx": 0.0, "tx": 0.0, "total": 0.0,
            "internal_bridge_rx": 0.0, "internal_bridge_tx": 0.0, "internal_total": 0.0,
            "derived": True, "host_known": host is not None}
    if host is not None:
        for d, host_bytes in zip(("rx", "tx"), host):
            addon_sum = sum(r[d] for r in out)
            if addon_sum > host_bytes:
                for r in out:
                    r[d] *= host_bytes / addon_sum
                    r["scaled"] = True
            core[d] = max(0.0, host_bytes - sum(r[d] for r in out))
        core["total"] = core["rx"] + core["tx"]
    for r in out:
        r["total"] = r["rx"] + r["tx"]
    out.append(core)
    out.sort(key=lambda r: (r["total"], r["internal_total"]), reverse=True)
    _set_shares(out)
    return out
