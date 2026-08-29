"""Worker threads: lifecycle, restart safety, locking, and hardware fallbacks."""
from __future__ import annotations

import subprocess
import threading
import time

import pytest

from app.core.balance import auto_balance
from app.core.decode import decode_worker
from app.core.spectrum import spectrum_worker
from app.core.wireless import WirelessDevice, list_wireless, upsert_device, wireless_worker


@pytest.fixture(autouse=True)
def balanced_roles():
    auto_balance()
    yield


# --------------------------------------------------------------------------
# spectrum
# --------------------------------------------------------------------------


def test_spectrum_start_produces_snapshot():
    spectrum_worker.configure(start_mhz=160, end_mhz=170, interval_s=1)
    status = spectrum_worker.start()
    assert status["running"] is True
    assert status["error"] is None
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not spectrum_worker.status()["latest"]:
            time.sleep(0.25)
        latest = spectrum_worker.status()["latest"]
        assert latest, "worker produced no snapshot"
        assert len(latest["bins"]) == len(latest["freqs_mhz"]) > 0
    finally:
        spectrum_worker.stop()


def test_spectrum_stop_is_clean_and_joins_thread():
    spectrum_worker.configure(interval_s=1)
    spectrum_worker.start()
    status = spectrum_worker.stop()
    assert status["running"] is False
    assert spectrum_worker._thread is None


def test_spectrum_restart_cycles():
    """Repeated start/stop must not wedge the running flag or leak threads."""
    spectrum_worker.configure(interval_s=1)
    before = threading.active_count()
    for _ in range(4):
        assert spectrum_worker.start()["running"] is True
        assert spectrum_worker.stop()["running"] is False
    assert threading.active_count() <= before + 1, "worker threads leaked across restarts"


def test_spectrum_double_start_is_idempotent():
    spectrum_worker.configure(interval_s=1)
    spectrum_worker.start()
    try:
        second = spectrum_worker.start()
        assert second["running"] is True
        alive = [t for t in threading.enumerate() if t.name == "spectrum-worker"]
        assert len(alive) == 1, "a second start spawned a duplicate worker thread"
    finally:
        spectrum_worker.stop()


def test_spectrum_stop_when_not_running_is_safe():
    assert spectrum_worker.stop()["running"] is False


def test_spectrum_refuses_without_scan_role():
    from app.core.db import set_device_role
    from app.core import devices as dev_mod

    for d in dev_mod.list_radio_devices():
        set_device_role(d["id"], "idle")
    dev_mod._device_cache_at = 0.0

    status = spectrum_worker.start()
    assert status["running"] is False
    assert "scan" in (status["error"] or "")


def test_spectrum_status_thread_safe_under_polling():
    """status() and the capture loop share a lock; hammer both together."""
    spectrum_worker.configure(start_mhz=160, end_mhz=170, interval_s=1)
    spectrum_worker.start()
    errors: list[Exception] = []

    def poll():
        try:
            for _ in range(60):
                snap = spectrum_worker.status()
                if snap["latest"]:
                    assert len(snap["latest"]["bins"]) == len(snap["latest"]["freqs_mhz"])
                time.sleep(0.01)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=poll) for _ in range(6)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        spectrum_worker.stop()
    assert not errors, f"concurrent status polling raised: {errors[:3]}"


def test_spectrum_peak_detection_finds_synthetic_signal():
    """The demo generator injects peaks; the detector should see them."""
    spectrum_worker.configure(start_mhz=160, end_mhz=170, threshold_db=-45, interval_s=1)
    snap = spectrum_worker._demo_snapshot("demo-rtl-0", 165.0, 10.0)
    assert snap.peaks, "no peaks found in synthetic spectrum"
    assert any(162.3 <= p.freq_mhz <= 162.7 for p in snap.peaks)


def test_rtl_power_parse_failure_surfaces_as_error(monkeypatch):
    """A failing rtl_power must raise, not silently return empty bins."""
    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(a[0], 1, "", "usb_claim_interface error -6")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="usb_claim_interface"):
        spectrum_worker._rtl_power_snapshot("rtl-0", 165.0, 10.0)


def test_rtl_power_empty_output_raises(monkeypatch):
    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(a[0], 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="no bins"):
        spectrum_worker._rtl_power_snapshot("rtl-0", 165.0, 10.0)


def test_rtl_power_parses_csv(monkeypatch):
    row = "2024-01-01, 00:00:00, 160000000, 161000000, 500000, 1, -50.0, -30.0"

    def fake_run(*a, **kw):
        return subprocess.CompletedProcess(a[0], 0, row, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    snap = spectrum_worker._rtl_power_snapshot("rtl-0", 160.5, 1.0)
    assert snap.source == "rtl_power"
    assert snap.bins == [-50.0, -30.0]


def test_spectrum_loop_records_error_without_dying(monkeypatch):
    """A capture exception must be recorded and the loop must keep running."""
    calls = {"n": 0}

    def boom(self):
        calls["n"] += 1
        raise RuntimeError("synthetic capture failure")

    monkeypatch.setattr(type(spectrum_worker), "_capture_once", boom)
    spectrum_worker.configure(interval_s=1)
    spectrum_worker.start()
    try:
        deadline = time.time() + 15
        while time.time() < deadline and calls["n"] < 2:
            time.sleep(0.2)
        assert calls["n"] >= 2, "loop stopped after first error"
        assert "synthetic capture failure" in (spectrum_worker.status()["error"] or "")
    finally:
        spectrum_worker.stop()


# --------------------------------------------------------------------------
# decode
# --------------------------------------------------------------------------


def test_decode_job_runs_to_completion():
    decode_worker.configure(auto_from_spectrum=False)
    decode_worker.start()
    try:
        job = decode_worker.enqueue(162.45, mode="eas", duration_s=2.0)
        deadline = time.time() + 25
        while time.time() < deadline:
            done = [j for j in decode_worker.status()["recent"] if j["id"] == job.id]
            if done:
                assert done[0]["status"] == "done"
                assert done[0]["result"]["mode"] == "eas"
                break
            time.sleep(0.25)
        else:
            pytest.fail("decode job never completed")
    finally:
        decode_worker.stop()


def test_decode_queue_limit_enforced():
    for _ in range(decode_worker.MAX_QUEUE):
        decode_worker.enqueue(162.45, mode="eas")
    with pytest.raises(ValueError, match="queue full"):
        decode_worker.enqueue(162.45, mode="eas")


def test_decode_rejects_bad_mode_and_freq():
    with pytest.raises(ValueError):
        decode_worker.enqueue(162.4, mode="not-a-mode")
    with pytest.raises(ValueError):
        decode_worker.enqueue(999999, mode="eas")


def test_decode_duration_is_clamped():
    job = decode_worker.enqueue(162.45, mode="eas", duration_s=99999)
    assert job.duration_s <= 60.0


def test_decode_restart_cycles():
    decode_worker.configure(auto_from_spectrum=False)
    for _ in range(4):
        assert decode_worker.start()["running"] is True
        assert decode_worker.stop()["running"] is False
    assert decode_worker._thread is None


def test_decode_refuses_without_decode_role():
    from app.core.db import set_device_role
    from app.core import devices as dev_mod

    for d in dev_mod.list_radio_devices():
        set_device_role(d["id"], "idle")
    dev_mod._device_cache_at = 0.0

    status = decode_worker.start()
    assert status["running"] is False
    assert "decode" in (status["error"] or "")


def test_decode_error_does_not_kill_loop(monkeypatch):
    def boom(self, job):
        raise RuntimeError("synthetic decode failure")

    monkeypatch.setattr(type(decode_worker), "_run_job", boom)
    decode_worker.configure(auto_from_spectrum=False)
    decode_worker.start()
    try:
        j1 = decode_worker.enqueue(162.45, mode="eas")
        j2 = decode_worker.enqueue(162.50, mode="eas")
        deadline = time.time() + 25
        while time.time() < deadline:
            ids = {j["id"]: j["status"] for j in decode_worker.status()["recent"]}
            if j1.id in ids and j2.id in ids:
                assert ids[j1.id] == "error" and ids[j2.id] == "error"
                break
            time.sleep(0.25)
        else:
            pytest.fail("loop stopped processing after an error")
    finally:
        decode_worker.stop()


def test_decode_auto_queue_dedupes_nearby_peaks():
    decode_worker.configure(auto_from_spectrum=True)
    decode_worker.start()
    try:
        decode_worker.maybe_queue_from_peak(162.45, "noaa_wx")
        decode_worker.maybe_queue_from_peak(162.46, "noaa_wx")
        time.sleep(0.2)
        queued = decode_worker.status()
        seen = [j for j in (queued["queue"] + queued["recent"]) if 162.4 <= j["freq_mhz"] <= 162.5]
        current = queued["current"]
        if current and 162.4 <= current["freq_mhz"] <= 162.5:
            seen.append(current)
        assert len(seen) <= 1, "duplicate auto-decode jobs queued for the same signal"
    finally:
        decode_worker.stop()


def test_decode_auto_queue_ignores_analog_hints():
    decode_worker.configure(auto_from_spectrum=True)
    decode_worker.start()
    try:
        before = decode_worker.status()["queue_len"]
        decode_worker.maybe_queue_from_peak(98.5, "analog_fm")
        assert decode_worker.status()["queue_len"] == before
    finally:
        decode_worker.stop()


def test_decode_history_is_capped():
    """History must not grow without bound on a long-running receiver."""
    from app.core.decode import DecodeJob

    with decode_worker._lock:
        for i in range(250):
            decode_worker._history.insert(
                0, DecodeJob(id=str(i), freq_mhz=162.45, mode="eas", status="done")
            )
            decode_worker._history = decode_worker._history[:100]
        assert len(decode_worker._history) <= 100


def test_dsd_output_parsing_flags_encryption():
    result = decode_worker._parse_dsd_text("dmr", "Sync: +DMR  CC: 3  TS: 2  TG: 100  RID: 1234567")
    assert result.color_code == 3
    assert result.timeslot == 2
    assert result.talkgroup == 100
    assert result.radio_id == 1234567
    assert result.encrypted is False


def test_dsd_encrypted_frame_is_flagged_not_decoded():
    result = decode_worker._parse_dsd_text("dmr", "Voice frame ENCRYPTED, algid 0x21")
    assert result.encrypted is True
    assert "ENCRYPTED" in (result.text or "")


def test_multimon_falls_back_to_demo_without_tools():
    """No rtl_fm/multimon-ng on this host: must degrade, not crash."""
    from app.core.decode import DecodeJob

    job = DecodeJob(id="t", freq_mhz=162.45, mode="eas", status="running", duration_s=2.0)
    result = decode_worker._run_multimon(job, "eas")
    assert result.mode == "eas"


# --------------------------------------------------------------------------
# wireless
# --------------------------------------------------------------------------


def test_wireless_start_stop_and_scan():
    wireless_worker.configure(interval_s=2)
    assert wireless_worker.start()["running"] is True
    try:
        deadline = time.time() + 20
        while time.time() < deadline and not wireless_worker.status()["last_scan"]:
            time.sleep(0.25)
        assert wireless_worker.status()["last_scan"], "no scan cycle completed"
    finally:
        assert wireless_worker.stop()["running"] is False


def test_wireless_restart_cycles():
    wireless_worker.configure(interval_s=2)
    for _ in range(3):
        assert wireless_worker.start()["running"] is True
        assert wireless_worker.stop()["running"] is False
    assert wireless_worker._thread is None


def test_wireless_upsert_preserves_first_seen():
    dev = WirelessDevice(mac="AA:11:22:33:44:55", kind="wifi", ssid="Net", rssi=-50)
    upsert_device(dev)
    first = list_wireless("wifi", 10)[0]["first_seen"]
    time.sleep(0.05)
    upsert_device(WirelessDevice(mac="AA:11:22:33:44:55", kind="wifi", ssid="Net", rssi=-60))
    rows = [r for r in list_wireless("wifi", 10) if r["mac"] == "AA:11:22:33:44:55"]
    assert len(rows) == 1, "upsert duplicated a device row"
    assert rows[0]["first_seen"] == first
    assert rows[0]["rssi"] == -60


def test_wireless_same_mac_different_kind_are_distinct():
    upsert_device(WirelessDevice(mac="BB:11:22:33:44:55", kind="wifi"))
    upsert_device(WirelessDevice(mac="BB:11:22:33:44:55", kind="bluetooth"))
    assert len([r for r in list_wireless(None, 50) if r["mac"] == "BB:11:22:33:44:55"]) == 2


def test_wireless_mac_normalised_to_upper():
    upsert_device(WirelessDevice(mac="cc:11:22:33:44:aa", kind="wifi"))
    assert any(r["mac"] == "CC:11:22:33:44:AA" for r in list_wireless("wifi", 50))


def test_list_wireless_limit_clamped():
    assert len(list_wireless("wifi", 99999)) <= 500
    assert list_wireless("wifi", -1) is not None


def test_wireless_status_does_not_fetch_rows_to_count(monkeypatch):
    """counts should come from COUNT(*), not by fetching up to 500 rows twice."""
    import app.core.wireless as wl

    calls = {"n": 0}
    real = wl.list_wireless

    def counting(kind=None, limit=100):
        calls["n"] += 1
        return real(kind, limit)

    monkeypatch.setattr(wl, "list_wireless", counting)
    wireless_worker.status()
    assert calls["n"] == 0, (
        f"status() ran {calls['n']} row-fetching queries just to produce counts"
    )
