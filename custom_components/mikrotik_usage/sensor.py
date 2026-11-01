"""Sensors: per-device usage, network totals, rankings and the HA services estimate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity, SensorStateClass)
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PERIOD_LABEL
from .coordinator import UsageConfigEntry, UsageCoordinator, period_start

_UNREC = frozenset({"items", "mu_kind", "mu_entry", "rows", "note"})
_PERIOD_ICON = {"day": "mdi:calendar-today", "month": "mdi:calendar-month", "year": "mdi:calendar"}


def _mb(nbytes: float | None) -> float | None:
    return None if nbytes is None else round(nbytes / 1e6, 2)


async def async_setup_entry(hass: HomeAssistant, entry: UsageConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    c = entry.runtime_data
    ents: list[SensorEntity] = []
    for dev in c.devices:
        for p in c.periods:
            for kind in ("rx", "tx", "total"):
                ents.append(DeviceUsageSensor(c, dev, p, kind))
    for p in c.periods:
        ents.append(NetworkTotalSensor(c, p))
        ents.append(RankingSensor(c, p))
    if c.estimate_enabled:
        ents.append(ServicesSensor(c))
    async_add_entities(ents)


class _Base(CoordinatorEntity[UsageCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_suggested_unit_of_measurement = UnitOfInformation.GIGABYTES
    _attr_suggested_display_precision = 2
    _unrecorded_attributes = _UNREC

    def __init__(self, coordinator: UsageCoordinator) -> None:
        super().__init__(coordinator)
        self._entry_id = coordinator.config_entry.entry_id

    @property
    def _network_device(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"{self._entry_id}_network")},
                          name="Network data usage", manufacturer="MikroTik",
                          model="Usage summary")


class DeviceUsageSensor(_Base):
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, c: UsageCoordinator, dev: dict[str, Any], period: str, kind: str) -> None:
        super().__init__(c)
        self._key, self._period, self._kind = dev["key"], period, kind
        self._attr_unique_id = f"{self._entry_id}_{dev['key']}_{period}_{kind}"
        self._attr_name = f"{PERIOD_LABEL[period]} {kind.upper() if kind != 'total' else 'total'}"
        self._attr_icon = {"rx": "mdi:download", "tx": "mdi:upload", "total": _PERIOD_ICON[period]}[kind]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}_{dev['key']}")}, name=dev["name"],
            manufacturer="MikroTik", model="Tracked network client")

    @property
    def native_value(self) -> float | None:
        rx, tx = self.coordinator.totals(self._key, self._period)
        return _mb({"rx": rx, "tx": tx, "total": rx + tx}[self._kind])

    @property
    def last_reset(self):
        return period_start(self._period, dt_util.now())


class NetworkTotalSensor(_Base):
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, c: UsageCoordinator, period: str) -> None:
        super().__init__(c)
        self._period = period
        self._attr_unique_id = f"{self._entry_id}_network_{period}"
        self._attr_name = f"Network {PERIOD_LABEL[period].lower()}"
        self._attr_icon = _PERIOD_ICON[period]
        self._attr_device_info = self._network_device

    def _sum(self) -> tuple[float, float]:
        rows = self.coordinator.ranking(self._period)
        return sum(r["rx"] for r in rows), sum(r["tx"] for r in rows)

    @property
    def native_value(self) -> float | None:
        return _mb(sum(self._sum()))

    @property
    def last_reset(self):
        return period_start(self._period, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rx, tx = self._sum()
        return {"mu_kind": "network", "mu_entry": self._entry_id, "period": self._period,
                "rx": rx, "tx": tx, "devices": len(self.coordinator.devices)}


class RankingSensor(_Base):
    """State = the top consumer; attributes carry the full ranking for the dashboard."""

    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_suggested_unit_of_measurement = None
    _attr_suggested_display_precision = None

    def __init__(self, c: UsageCoordinator, period: str) -> None:
        super().__init__(c)
        self._period = period
        self._attr_unique_id = f"{self._entry_id}_ranking_{period}"
        self._attr_name = f"Top consumer {PERIOD_LABEL[period].lower()}"
        self._attr_icon = "mdi:podium-gold"
        self._attr_device_info = self._network_device

    @property
    def native_value(self) -> str | None:
        rows = self.coordinator.ranking(self._period)
        return rows[0]["name"] if rows and rows[0]["total"] > 0 else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"mu_kind": "ranking", "mu_entry": self._entry_id, "period": self._period,
                "period_start": period_start(self._period, dt_util.now()).isoformat(),
                "items": self.coordinator.ranking(self._period)}


class ServicesSensor(_Base):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, c: UsageCoordinator) -> None:
        super().__init__(c)
        self._attr_unique_id = f"{self._entry_id}_services_estimate"
        self._attr_name = "Home Assistant services estimate (month)"
        self._attr_icon = "mdi:home-assistant"
        self._attr_device_info = self._network_device

    @property
    def native_value(self) -> float | None:
        return _mb(self.coordinator.services()["est_month"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.coordinator.services()
        return {"mu_kind": "services", "mu_entry": self._entry_id, "rows": s["rows"],
                "host": s["host"], "est_day": s["est_day"], "est_month": s["est_month"],
                "note": "Estimates: integrations pointing at tracked LAN devices are measured; "
                        "cloud integrations are polls/day x typical payload."}
