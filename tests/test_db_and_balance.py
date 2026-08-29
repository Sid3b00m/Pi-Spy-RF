"""Event log, device-role persistence, and exclusive SDR role arbitration."""
from __future__ import annotations

import threading

import pytest

from app.core.balance import assign_exclusive, assignments, auto_balance, require_role
from app.core.db import add_event, get_device_roles, list_events, set_device_role


def test_add_and_list_event_round_trip():
    add_event("unit_test", "hello", source="rtl-0", freq_hz=162.4e6, mode="eas", meta={"a": 1})
    events = list_events(10)
    assert events[0]["kind"] == "unit_test"
    assert events[0]["meta"] == {"a": 1}
    assert events[0]["freq_hz"] == pytest.approx(162.4e6)


def test_events_ordered_newest_first():
    for i in range(5):
        add_event("seq", f"event-{i}")
    summaries = [e["summary"] for e in list_events(5)]
    assert summaries == [f"event-{i}" for i in reversed(range(5))]


def test_event_meta_defaults_to_empty_dict():
    add_event("no_meta", "x")
    assert list_events(1)[0]["meta"] == {}


def test_list_events_respects_limit():
    for i in range(30):
        add_event("bulk", str(i))
    assert len(list_events(7)) == 7


def test_set_device_role_upserts():
    set_device_role("rtl-0", "scan")
    set_device_role("rtl-0", "decode")
    roles = get_device_roles()
    assert roles["rtl-0"] == "decode"
    assert list(roles).count("rtl-0") == 1


def test_concurrent_event_writes_do_not_lose_rows():
    """WAL + busy_timeout should absorb concurrent writers from the workers."""
    errors: list[Exception] = []

    def writer(n: int):
        try:
            for i in range(20):
                add_event("concurrent", f"w{n}-{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"concurrent writes raised: {errors[:3]}"
    got = [e for e in list_events(200) if e["kind"] == "concurrent"]
    assert len(got) == 120


def test_demo_devices_present_without_hardware():
    plan = assignments()
    assert plan["devices"], "expected demo placeholders when no SDR tools exist"


def test_assign_exclusive_preempts_previous_holder():
    devices = assignments()["devices"]
    assert len(devices) >= 2
    a, b = devices[0]["id"], devices[1]["id"]

    assign_exclusive(a, "scan")
    assert require_role("scan")["id"] == a

    plan = assign_exclusive(b, "scan")
    assert require_role("scan")["id"] == b
    assert len(plan["scan"]) == 1, "scan must stay exclusive"
    assert plan["ok"]


def test_assign_exclusive_unknown_device_raises():
    with pytest.raises(KeyError):
        assign_exclusive("no-such-device", "scan")


def test_auto_balance_separates_scan_and_decode():
    plan = auto_balance()
    scan_ids = {d["id"] for d in plan["scan"]}
    decode_ids = {d["id"] for d in plan["decode"]}
    assert scan_ids and decode_ids
    assert not (scan_ids & decode_ids), "one stick cannot hold both roles"
    assert plan["ok"]


def test_auto_balance_prefers_rtl_for_scan_hackrf_for_decode():
    plan = auto_balance()
    assert any("rtl" in d["id"] for d in plan["scan"])
    assert any("hackrf" in d["id"] for d in plan["decode"])


def test_auto_balance_is_idempotent():
    first = auto_balance()
    second = auto_balance()
    assert [d["id"] for d in first["scan"]] == [d["id"] for d in second["scan"]]
    assert [d["id"] for d in first["decode"]] == [d["id"] for d in second["decode"]]


def test_require_role_none_when_unassigned():
    for d in assignments()["devices"]:
        set_device_role(d["id"], "idle")
    from app.core import devices as dev_mod

    dev_mod._device_cache_at = 0.0
    assert require_role("scan") is None
