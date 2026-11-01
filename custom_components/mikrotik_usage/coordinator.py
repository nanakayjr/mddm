"""Coordinator: samples source sensors, keeps the engine, persists it."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (CONF_DEVICES, CONF_ESTIMATE, CONF_HA_HOST, CONF_PERIODS, CONF_SWAP,
                    DOMAIN, ESTIMATE_REFRESH_S, PERIODS, SCAN_SECONDS)
from .addons import AddonTracker, supervisor_available
from .engine import Engine, classify_unit
from .estimator import async_estimate_services

_LOGGER = logging.getLogger(__name__)

type UsageConfigEntry = ConfigEntry["UsageCoordinator"]


def period_start(period: str, now: datetime) -> datetime:
    if period == "day":
        return dt_util.start_of_local_day(now)
    if period == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


class UsageCoordinator(DataUpdateCoordinator[None]):
    """Owns accounting for all tracked devices."""

    config_entry: UsageConfigEntry

    def __init__(self, hass: HomeAssistant, entry: UsageConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=timedelta(seconds=SCAN_SECONDS))
        cfg = {**entry.data, **entry.options}
        self.devices: list[dict[str, Any]] = cfg.get(CONF_DEVICES, [])
        self.periods: list[str] = [p for p in PERIODS if p in cfg.get(CONF_PERIODS, PERIODS)]
        self.swap: bool = cfg.get(CONF_SWAP, False)
        self.ha_host: str | None = cfg.get(CONF_HA_HOST)
        self.estimate_enabled: bool = cfg.get(CONF_ESTIMATE, True)
        self.engine = Engine()
        self._store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._est_rows: list[dict[str, Any]] = []
        self._est_ts = 0.0
        self._warned: set[str] = set()
        self.addon_engine = Engine()
        self._addon_store: Store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.addons")
        self.addons: AddonTracker | None = None
        self._addon_ts = 0.0

    # ------------------------------------------------------------------ lifecycle
    async def async_setup(self) -> None:
        self.engine = Engine(await self._store.async_load())
        for dev in self.devices:
            self.engine.ensure(dev["key"], dev["name"])
        entity_ids = [e for d in self.devices for e in (d.get("rx"), d.get("tx")) if e]
        if entity_ids:
            self.config_entry.async_on_unload(
                async_track_state_change_event(self.hass, entity_ids, self._on_event))
        if supervisor_available():
            self.addon_engine = Engine(await self._addon_store.async_load())
            self.addons = AddonTracker(self.hass, self.addon_engine)
        self._sample()

    @callback
    def _on_event(self, _event: Event) -> None:
        self._sample()

    async def _async_update_data(self) -> None:
        self._sample()
        self._store.async_delay_save(self.engine.to_dict, SCAN_SECONDS // 2)
        if self.estimate_enabled and time.monotonic() - self._est_ts > ESTIMATE_REFRESH_S:
            measured = {d["key"]: {"day": sum(self.totals(d["key"], "day")),
                                   "month": sum(self.totals(d["key"], "month"))} for d in self.devices}
            self._est_rows = await async_estimate_services(self.hass, self.devices, measured)
            self._est_ts = time.monotonic()
        if self.addons is not None and time.monotonic() - self._addon_ts >= 55:
            self._addon_ts = time.monotonic()
            await self.addons.async_update(dt_util.now())
            self._addon_store.async_delay_save(self.addon_engine.to_dict, SCAN_SECONDS // 2)

    async def async_save(self) -> None:
        await self._store.async_save(self.engine.to_dict())
        if self.addons is not None:
            await self._addon_store.async_save(self.addon_engine.to_dict())

    def addon_ranking(self, period: str) -> list[dict[str, Any]]:
        return self.addon_engine.ranking(period, dt_util.now())

    # ------------------------------------------------------------------ sampling
    def _sample(self) -> None:
        now = dt_util.now()
        for dev in self.devices:
            for direction in ("rx", "tx"):
                eid = dev.get(direction)
                if not eid:
                    continue
                st = self.hass.states.get(eid)
                if st is None or st.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                    continue
                try:
                    value = float(st.state)
                except ValueError:
                    continue
                cls = classify_unit(st.attributes.get(ATTR_UNIT_OF_MEASUREMENT))
                if cls is None:
                    if eid not in self._warned:
                        self._warned.add(eid)
                        _LOGGER.warning("%s has no recognised unit, assuming a GB counter", eid)
                    cls = ("counter", 1e9)
                mode, factor = cls
                if mode == "rate":
                    nbytes = self.engine.sample_rate(eid, value * factor, now)
                else:
                    nbytes = self.engine.sample_counter(eid, value * factor, now)
                if nbytes:
                    target = ("tx" if direction == "rx" else "rx") if self.swap else direction
                    self.engine.add(dev["key"], target, nbytes, now)

    # ------------------------------------------------------------------ read API
    def totals(self, key: str, period: str) -> tuple[float, float]:
        return self.engine.totals(key, period, dt_util.now())

    def ranking(self, period: str) -> list[dict[str, Any]]:
        return self.engine.ranking(period, dt_util.now())

    def history(self, days: int) -> dict[str, Any]:
        return self.engine.history(dt_util.now(), days)

    def services(self) -> dict[str, Any]:
        now = dt_util.now()
        host = None
        if self.ha_host and self.ha_host in self.engine.devices:
            host = {"name": self.engine.devices[self.ha_host]["name"],
                    "day": sum(self.totals(self.ha_host, "day")),
                    "month": sum(self.totals(self.ha_host, "month"))}
        addon_day = sum(r["total"] for r in self.addon_ranking("day")) if self.addons else 0.0
        addon_month = sum(r["total"] for r in self.addon_ranking("month")) if self.addons else 0.0
        internet = [r for r in self._est_rows if r["scope"] == "internet" and r["mode"] != "measured"]
        est_day = sum(r["day"] or 0 for r in internet)
        est_month = sum(r["month"] or 0 for r in internet)
        return {"rows": self._est_rows, "host": host, "est_day": est_day,
                "est_month": est_month, "addon_day": addon_day,
                "addon_month": addon_month, "as_of": now.isoformat()}
