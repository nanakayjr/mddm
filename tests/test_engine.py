import importlib.util, pathlib
from datetime import datetime, timedelta, timezone

spec = importlib.util.spec_from_file_location(
    "engine", pathlib.Path(__file__).parents[1] / "custom_components/mikrotik_usage/engine.py")
engine = importlib.util.module_from_spec(spec); spec.loader.exec_module(engine)
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
