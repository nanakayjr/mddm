import importlib, pathlib, sys, types
from datetime import datetime, timedelta, timezone

# Import engine/const as a submodule without running the package __init__ (needs Home Assistant).
_pkg_dir = pathlib.Path(__file__).parents[1] / "custom_components/mikrotik_usage"
_pkg = types.ModuleType("mikrotik_usage"); _pkg.__path__ = [str(_pkg_dir)]
sys.modules["mikrotik_usage"] = _pkg
engine = importlib.import_module("mikrotik_usage.engine")
const = importlib.import_module("mikrotik_usage.const")
E = engine.Engine
T0 = datetime(2026, 10, 31, 22, 0, tzinfo=timezone.utc)


def test_units():
    assert engine.classify_unit("Mbps") == ("rate", 125e3)
    assert engine.classify_unit("GB") == ("counter", 1e9)
    assert engine.classify_unit("%") is None and engine.classify_unit(None) is None


def test_counter_delta_and_reset():
    e = E(); e.ensure("a", "A")
    assert e.sample_counter("s", 1e9, T0) == 0
    assert e.sample_counter("s", 1.5e9, T0 + timedelta(hours=1)) == 0.5e9
    assert e.sample_counter("s", 0.2e9, T0 + timedelta(hours=2)) == 0.2e9  # reset


def test_rate_trapezoid_and_gap():
    e = E()
    e.sample_rate("s", 1e6, T0)
    assert e.sample_rate("s", 3e6, T0 + timedelta(seconds=30)) == 2e6 * 30
    assert e.sample_rate("s", 3e6, T0 + timedelta(seconds=30 + 3600)) == 0  # gap ignored
    assert e.sample_rate("s", 3e6, T0 + timedelta(seconds=30 + 3600)) == 0  # same ts


def test_rollover_history_and_ranking():
    e = E(); e.ensure("a", "A"); e.ensure("b", "B")
    e.add("a", "rx", 100, T0); e.add("a", "tx", 50, T0); e.add("b", "rx", 500, T0)
    nxt = T0 + timedelta(hours=3)  # crosses midnight AND month AND year? (31 Oct -> 1 Nov)
    e.add("a", "rx", 10, nxt)
    assert e.totals("a", "day", nxt) == (10, 0)
    assert e.totals("a", "month", nxt) == (10, 0)
    assert e.totals("a", "year", nxt) == (110, 50)
    assert e.devices["a"]["history"]["2026-10-31"] == [100, 50]
    r = e.ranking("year", nxt)
    assert [x["key"] for x in r] == ["b", "a"] and r[0]["share"] > 70
    h = e.history(nxt, 3)
    assert h["network"][-1]["rx"] == 10 and h["network"][-2]["rx"] == 600


def test_persistence_roundtrip():
    import json
    e = E(); e.ensure("a", "A"); e.add("a", "rx", 5, T0)
    e2 = E(json.loads(json.dumps(e.to_dict())))
    assert e2.totals("a", "day", T0) == (5, 0)


def test_unit_parser_variants():
    c = engine.classify_unit
    assert c("kbps") == ("rate", 125.0) and c("kb/s") == ("rate", 125.0)
    assert c("kbit/s") == ("rate", 125.0) and c("Kbit/s") == ("rate", 125.0)
    assert c("Mb/s") == ("rate", 125e3) and c("Mbps") == ("rate", 125e3)
    assert c("kB/s") == ("rate", 1e3) and c("KBps") == ("rate", 1e3) and c("MB/s") == ("rate", 1e6)
    assert c("B") == ("counter", 1.0) and c("GB") == ("counter", 1e9) and c("MiB") == ("counter", 1048576.0)
    assert c("GiB/s") == ("rate", 1024.0**3)
    assert c("°C") is None and c("%") is None and c("min") is None and c("") is None


def test_split_direction():
    s = engine.split_direction
    assert s("John iPhone TX") == ("tx", "John iPhone")
    assert s("ether1 RX total") == ("rx", "ether1 total") or s("ether1 RX total")[0] == "rx"
    assert s("laptop_rx_rate") == ("rx", "laptop")
    assert s("Living room TV Download") == ("rx", "Living room TV")
    assert s("Temperature") is None


# ---------------------------------------------------------------- add-on WAN attribution
GB = 1e9
MB = 1e6


def _feed(e, slug, name, rx, tx, now=T0, info=None):
    """Mimic AddonTracker._one for one sampling interval."""
    profile = engine.classify_addon(slug, info)
    e.ensure(slug, name, profile)
    for metric, nbytes in engine.split_addon_traffic(profile, rx, tx).items():
        if nbytes:
            e.add(slug, metric, nbytes, now)


def test_classify_addon():
    c = engine.classify_addon
    for slug in ("core_configurator", "a0d7b954_influxdb", "core_mosquitto", "a0d7b954_grafana",
                 "core_ssh", "a0d7b954_vscode", "a0d7b954_sqlite-web", "core_chrony",
                 "45df7312_zigbee2mqtt", "a0d7b954_tasmoadmin"):
        assert c(slug) == const.PROFILE_LOCAL, slug
    assert c("cebe7a76_hassio_google_drive_backup") == const.PROFILE_BACKUP
    for slug in ("9074a9ba_cloudflared", "a0d7b954_tailscale", "core_wireguard", "core_nginx_proxy"):
        assert c(slug) == const.PROFILE_TUNNEL, slug
    assert c("a0d7b954_firefox", {"ingress": True, "ingress_only": True}) == const.PROFILE_STANDARD
    assert c("abcd1234_plexmediaserver") == const.PROFILE_STANDARD


def test_classify_addon_from_metadata():
    c = engine.classify_addon
    assert c("abc12345_notes", {"ingress": True, "ingress_only": True, "ports": {}}) == const.PROFILE_LOCAL
    assert c("abc12345_notes", {"ingress": True, "ingress_only": True,
                                "ports": {"80/tcp": None}}) == const.PROFILE_LOCAL
    assert c("abc12345_notes", {"ingress": True, "ingress_only": True,
                                "ports": {"80/tcp": 8080}}) == const.PROFILE_STANDARD
    assert c("abc12345_notes", {"ingress": True, "ingress_only": True,
                                "host_network": True}) == const.PROFILE_STANDARD
    assert c("abc12345_notes", {"ingress": False}) == const.PROFILE_STANDARD
    assert c("abc12345_notes") == const.PROFILE_STANDARD


def test_local_addons_have_zero_wan_and_keep_bridge_traffic():
    e = E()
    _feed(e, "core_configurator", "File editor", 2.70 * GB, 5 * MB)
    _feed(e, "a0d7b954_influxdb", "InfluxDB", 441 * MB, 20 * MB)
    for slug in ("core_configurator", "a0d7b954_influxdb"):
        assert e.totals(slug, "month", T0) == (0, 0)
    assert e.internal_totals("core_configurator", "month", T0) == (2.70 * GB, 5 * MB)
    assert e.internal_totals("a0d7b954_influxdb", "day", T0) == (441 * MB, 20 * MB)
    r = {x["key"]: x for x in e.ranking("month", T0)}
    assert r["core_configurator"]["total"] == 0 and r["core_configurator"]["internal_total"] > 2.7 * GB


def test_backup_discounts_local_snapshot_pull():
    s = engine.split_addon_traffic(const.PROFILE_BACKUP, 2.65 * GB, 2.65 * GB)
    assert s["tx"] == 2.65 * GB
    assert s["rx"] == 2.65 * GB * const.BACKUP_ACK_OVERHEAD  # only ACK overhead counts as WAN RX
    assert abs(s["rx"] + s["internal_bridge_rx"] - 2.65 * GB) < 1 and s["internal_bridge_tx"] == 0
    # little RX (no snapshot pull): never more WAN RX than was received
    assert engine.split_addon_traffic(const.PROFILE_BACKUP, 1e3, 1e9)["rx"] == 1e3


def test_tunnel_does_not_double_count():
    s = engine.split_addon_traffic(const.PROFILE_TUNNEL, 600 * MB, 400 * MB)
    assert (s["rx"], s["tx"]) == (300 * MB, 200 * MB)
    assert (s["internal_bridge_rx"], s["internal_bridge_tx"]) == (300 * MB, 200 * MB)
    s = engine.split_addon_traffic(const.PROFILE_STANDARD, 7, 9)
    assert (s["rx"], s["tx"], s["internal_bridge_rx"], s["internal_bridge_tx"]) == (7, 9, 0, 0)


def _wan_scenario(local_rx):
    e = E()
    _feed(e, "core_configurator", "File editor", local_rx, 0)
    _feed(e, "a0d7b954_influxdb", "InfluxDB", local_rx / 6, 0)
    _feed(e, "cebe7a76_hassio_google_drive_backup", "Google Drive Backup", 2.65 * GB, 2.65 * GB)
    _feed(e, "9074a9ba_cloudflared", "Cloudflared", 100 * MB, 100 * MB)
    return engine.attribute_wan(e.ranking("day", T0), (10 * GB, 4 * GB))


def test_local_chatter_does_not_skew_wan_attribution():
    quiet, noisy = _wan_scenario(0), _wan_scenario(50 * GB)
    for rows in (quiet, noisy):
        by = {r["key"]: r for r in rows}
        assert by["core_configurator"]["total"] == 0 and by["a0d7b954_influxdb"]["total"] == 0
    # Google Drive Backup and Cloudflared get identical WAN numbers regardless of local noise.
    for key in ("cebe7a76_hassio_google_drive_backup", "9074a9ba_cloudflared"):
        q = next(r for r in quiet if r["key"] == key); n = next(r for r in noisy if r["key"] == key)
        assert (q["rx"], q["tx"], q["share"]) == (n["rx"], n["tx"], n["share"])
    by = {r["key"]: r for r in noisy}
    assert by["cebe7a76_hassio_google_drive_backup"]["tx"] == 2.65 * GB
    assert by["9074a9ba_cloudflared"]["rx"] == 50 * MB and by["9074a9ba_cloudflared"]["tx"] == 50 * MB
    assert by["core_configurator"]["internal_total"] == 50 * GB


def test_remainder_goes_to_core_and_totals_match_router():
    rows = _wan_scenario(5 * GB)
    core = next(r for r in rows if r["key"] == const.CORE_KEY)
    assert core["derived"] and core["name"] == const.CORE_NAME
    addons_rx = sum(r["rx"] for r in rows if r["key"] != const.CORE_KEY)
    addons_tx = sum(r["tx"] for r in rows if r["key"] != const.CORE_KEY)
    assert abs(core["rx"] + addons_rx - 10 * GB) < 1 and abs(core["tx"] + addons_tx - 4 * GB) < 1
    assert core["rx"] > 0 and core["tx"] > 0
    assert rows[0]["key"] == const.CORE_KEY  # largest WAN consumer


def test_addon_wan_is_capped_by_router_total_and_core_without_host():
    e = E()
    _feed(e, "cebe7a76_hassio_google_drive_backup", "Google Drive Backup", 0, 3 * GB)
    _feed(e, "a0d7b954_firefox", "Firefox", 0, 1 * GB)
    rows = engine.attribute_wan(e.ranking("day", T0), (0, 2 * GB))
    by = {r["key"]: r for r in rows}
    assert abs(by["cebe7a76_hassio_google_drive_backup"]["tx"] - 1.5 * GB) < 1  # 3:1 weights
    assert abs(by["a0d7b954_firefox"]["tx"] - 0.5 * GB) < 1
    assert by[const.CORE_KEY]["tx"] == 0 and by["a0d7b954_firefox"]["scaled"]
    unknown = engine.attribute_wan(e.ranking("day", T0), None)
    core = next(r for r in unknown if r["key"] == const.CORE_KEY)
    assert core["total"] == 0 and core["host_known"] is False
    assert next(r for r in unknown if r["key"] == "a0d7b954_firefox")["tx"] == 1 * GB


def test_legacy_period_data_without_internal_metrics():
    e = E({"devices": {"a": {"name": "A", "history": {}, "day": {"key": "2026-10-31", "rx": 5.0, "tx": 1.0},
                              "month": {"key": "2026-10", "rx": 5.0, "tx": 1.0},
                              "year": {"key": "2026", "rx": 5.0, "tx": 1.0}}}})
    assert e.internal_totals("a", "day", T0) == (0.0, 0.0)
    e.add("a", "internal_bridge_rx", 7, T0)
    assert e.internal_totals("a", "year", T0) == (7, 0.0) and e.totals("a", "year", T0) == (5, 1)
