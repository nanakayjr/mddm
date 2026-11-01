"""Per-add-on (app) network usage, measured from Supervisor container stats.

The Supervisor reports cumulative network_rx / network_tx bytes per add-on container
(since the container started).  We turn those counters into daily/monthly/yearly totals.

Caveat: add-ons that run with `host_network: true` report the counters of the whole
host, so they cannot be attributed and are listed separately, not ranked.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .engine import Engine

_LOGGER = logging.getLogger(__name__)
_LIST_REFRESH_S = 300
_BASE = "http://supervisor"


def supervisor_available() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN"))


class AddonTracker:
    def __init__(self, hass: HomeAssistant, engine: Engine) -> None:
        self.engine = engine
        self._session = async_get_clientsession(hass)
        self._headers = {"Authorization": f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}"}
        self.info: dict[str, dict[str, Any]] = {}
        self._list_ts = 0.0
        self._warned = False

    async def _get(self, path: str) -> Any:
        async with self._session.get(f"{_BASE}{path}", headers=self._headers,
                                     timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            return (await resp.json()).get("data", {})

    async def _refresh_list(self) -> None:
        data = await self._get("/addons")
        current = {a["slug"]: a for a in data.get("addons", [])}
        for slug in [s for s in self.info if s not in current]:
            del self.info[slug]
        for slug, a in current.items():
            known = self.info.get(slug)
            if known is None or known.get("version") != a.get("version"):
                try:
                    inf = await self._get(f"/addons/{slug}/info")
                except Exception:  # noqa: BLE001
                    inf = {}
                host_net = bool(inf.get("host_network"))
            else:
                host_net = known["host_network"]
            self.info[slug] = {"name": a.get("name") or slug, "host_network": host_net,
                               "state": a.get("state"), "version": a.get("version")}
        self._list_ts = time.monotonic()

    async def _one(self, slug: str, now, sem: asyncio.Semaphore) -> None:
        async with sem:
            stats = await self._get(f"/addons/{slug}/stats")
        meta = self.info[slug]
        rx, tx = stats.get("network_rx"), stats.get("network_tx")
        self.engine.ensure(slug, meta["name"])
        for direction, val in (("rx", rx), ("tx", tx)):
            if not isinstance(val, (int, float)):
                continue
            delta = self.engine.sample_counter(f"{slug}:{direction}", float(val), now)
            if delta and not meta["host_network"]:
                self.engine.add(slug, direction, delta, now)

    async def async_update(self, now) -> None:
        try:
            if time.monotonic() - self._list_ts > _LIST_REFRESH_S or not self.info:
                await self._refresh_list()
            sem = asyncio.Semaphore(4)
            running = [s for s, m in self.info.items() if m["state"] == "started"]
            results = await asyncio.gather(*(self._one(s, now, sem) for s in running),
                                           return_exceptions=True)
            for slug, res in zip(running, results):
                if isinstance(res, Exception):
                    _LOGGER.debug("No stats for add-on %s: %s", slug, res)
        except Exception as err:  # noqa: BLE001
            if not self._warned:
                self._warned = True
                _LOGGER.warning("Supervisor add-on stats unavailable: %s", err)

    @property
    def excluded(self) -> list[str]:
        """Running add-ons that share the host network (cannot be attributed)."""
        return sorted(m["name"] for m in self.info.values()
                      if m["host_network"] and m["state"] == "started")
