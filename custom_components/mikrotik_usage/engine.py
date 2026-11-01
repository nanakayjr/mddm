"""Pure accounting engine (no Home Assistant imports, unit-testable).

All volumes are stored in BYTES.  Two source types are supported:

* "rate"    – a throughput sensor (bps, kbps, Mbps, B/s ...).  Integrated over time
              with the trapezoid rule.
* "counter" – a cumulative data sensor (B, MB, GB ...).  Deltas are accumulated;
              a decrease is treated as a counter reset (new value == usage since reset).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

PERIODS = ("day", "month", "year")
MAX_GAP_S = 600  # do not integrate rates across gaps longer than this
HISTORY_DAYS = 400

DATA_UNITS: dict[str, float] = {
    "bit": 1 / 8, "kbit": 125.0, "Mbit": 125e3, "Gbit": 125e6,
    "B": 1.0, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "PB": 1e15,
    "KiB": 1024.0, "MiB": 1024.0**2, "GiB": 1024.0**3, "TiB": 1024.0**4,
}
RATE_UNITS: dict[str, float] = {
    "bit/s": 1 / 8, "kbit/s": 125.0, "Mbit/s": 125e3, "Gbit/s": 125e6,
    "bps": 1 / 8, "kbps": 125.0, "Kbps": 125.0, "Mbps": 125e3, "Gbps": 125e6,
    "kb/s": 125.0, "Mb/s": 125e3, "Gb/s": 125e6,
    "B/s": 1.0, "kB/s": 1e3, "KB/s": 1e3, "MB/s": 1e6, "GB/s": 1e9,
    "KiB/s": 1024.0, "MiB/s": 1024.0**2, "GiB/s": 1024.0**3,
}


def classify_unit(unit: str | None) -> tuple[str, float] | None:
    """Return ("rate"|"counter", bytes-factor) for a unit string, else None."""
    if not unit:
        return None
    u = unit.strip()
    if u in RATE_UNITS:
        return "rate", RATE_UNITS[u]
    if u in DATA_UNITS:
        return "counter", DATA_UNITS[u]
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
    def ensure(self, key: str, name: str) -> dict[str, Any]:
        dev = self.devices.setdefault(key, {"history": {}})
        dev["name"] = name
        dev.setdefault("history", {})
        return dev

    def _roll(self, dev: dict[str, Any], now: datetime) -> None:
        for period, k in period_keys(now).items():
            cur = dev.get(period)
            if cur is None:
                dev[period] = {"key": k, "rx": 0.0, "tx": 0.0}
            elif cur["key"] != k:
                if period == "day":
                    hist = dev["history"]
                    hist[cur["key"]] = [cur["rx"], cur["tx"]]
                    for old in sorted(hist)[:-HISTORY_DAYS]:
                        del hist[old]
                dev[period] = {"key": k, "rx": 0.0, "tx": 0.0}

    def add(self, key: str, direction: str, nbytes: float, now: datetime) -> None:
        dev = self.devices[key]
        self._roll(dev, now)
        for period in PERIODS:
            dev[period][direction] += nbytes

    def totals(self, key: str, period: str, now: datetime) -> tuple[float, float]:
        dev = self.devices[key]
        self._roll(dev, now)
        return dev[period]["rx"], dev[period]["tx"]

    def ranking(self, period: str, now: datetime) -> list[dict[str, Any]]:
        rows = []
        for key, dev in self.devices.items():
            rx, tx = self.totals(key, period, now)
            rows.append({"key": key, "name": dev["name"], "rx": rx, "tx": tx, "total": rx + tx})
        rows.sort(key=lambda r: r["total"], reverse=True)
        grand = sum(r["total"] for r in rows) or 1.0
        for r in rows:
            r["share"] = round(r["total"] / grand * 100, 1)
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
