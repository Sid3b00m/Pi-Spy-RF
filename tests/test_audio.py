"""Live audio: backend choice, worker lifecycle, fan-out and the stream endpoint.

No SDR is touched. Backend selection takes an injected `which`, and the worker
runs its demo tone, so every path here is exercisable on a build host and in CI.
"""
from __future__ import annotations

import struct
import threading
import time

import pytest

from app.core import audio as audio_mod
from app.core.audio import (
    AUDIO_MODES,
    Listener,
    audio_worker,
    clamp_gain,
    clamp_squelch,
    if_decimation,
    select_backend,
    soft_audio_rate,
    wav_header,
)

RTL = {"id": "rtl-0", "type": "rtl-sdr", "status": "online"}
HACKRF = {"id": "hackrf-0", "type": "hackrf", "status": "online"}
SOAPY_HACKRF = {"id": "soapy-0", "type": "hackrf", "status": "online"}
SIMULATED = {"id": "demo-hackrf-0", "type": "hackrf", "status": "simulated"}


def only(*present: str):
    """A stand-in for shutil.which that finds exactly the named tools."""
    return lambda name: f"/usr/bin/{name}" if name in present else None


@pytest.fixture
def audio_device(monkeypatch):
    """One simulated radio already holding role=audio."""
    device = {
        "id": "demo-hackrf-0",
        "type": "hackrf",
        "name": "Demo HackRF One (no hardware)",
        "serial": "DEMO0002",
        "status": "simulated",
        "role": "audio",
        "detail": "",
    }
    from app.core import balance as balance_mod

    monkeypatch.setattr(balance_mod, "list_radio_devices", lambda **kw: [device])
    return device


@pytest.fixture
def running_audio(audio_device):
    status = audio_worker.start()
    assert status["running"] is True, status.get("error")
    yield status
    audio_worker.stop()


class TestWavHeader:
    def test_is_a_44_byte_pcm_header(self):
        header = wav_header(48_000)
        assert len(header) == 44
        assert header[:4] == b"RIFF"
        assert header[8:12] == b"WAVE"
        assert header[12:16] == b"fmt "
        assert header[36:40] == b"data"

    def test_declares_the_requested_rate_and_derived_fields(self):
        header = wav_header(22_050, channels=1, bits=16)
        (size, fmt, channels, rate, byte_rate, align, bits) = struct.unpack(
            "<IHHIIHH", header[16:36]
        )
        assert (size, fmt, channels, bits) == (16, 1, 1, 16)
        assert rate == 22_050
        assert byte_rate == 22_050 * 2
        assert align == 2

    def test_length_stays_a_positive_int32(self):
        """A negative or wrapped size makes browsers stop the stream early."""
        header = wav_header(48_000)
        assert 0 < struct.unpack("<I", header[4:8])[0] <= 0x7FFFFFFF
        assert 0 < struct.unpack("<I", header[40:44])[0] <= 0x7FFFFFFF


class TestClampsAndRates:
    def test_gain_is_clamped_to_a_usable_span(self):
        assert clamp_gain(0.0) == 0.1
        assert clamp_gain(99) == 8.0
        assert clamp_gain(2.5) == 2.5

    def test_squelch_is_a_percentage(self):
        assert clamp_squelch(-5) == 0
        assert clamp_squelch(500) == 100
        assert clamp_squelch(42.4) == 42

    def test_if_decimation_targets_a_250_khz_if(self):
        assert if_decimation(2_000_000) == 8
        assert if_decimation(8_000_000) == 32
        assert if_decimation(240_000) == 1

    def test_soft_audio_rate_follows_the_capture_rate(self):
        assert soft_audio_rate(2_000_000) == 50_000
        assert soft_audio_rate(8_000_000) == 50_000


class TestBackendSelection:
    def test_rtl_dongles_go_through_rtl_fm(self):
        backend, reason = select_backend(RTL, "nbfm", which=only("rtl_fm", "rx_fm"))
        assert backend == "rtl_fm"
        assert "rtl_fm" in reason

    def test_rx_fm_covers_anything_soapy_can_open(self):
        backend, _ = select_backend(HACKRF, "nbfm", which=only("rx_fm", "hackrf_transfer"))
        assert backend == "rx_fm"

    def test_rtl_falls_back_to_rx_fm_when_rtl_fm_is_absent(self):
        backend, _ = select_backend(RTL, "nbfm", which=only("rx_fm"))
        assert backend == "rx_fm"

    def test_hackrf_without_rx_tools_uses_software_demodulation(self):
        backend, reason = select_backend(HACKRF, "nbfm", which=only("hackrf_transfer"))
        assert backend == "hackrf_soft"
        assert "software demodulator" in reason

    def test_soapy_reported_hackrf_is_recognised_by_driver_name(self):
        backend, _ = select_backend(SOAPY_HACKRF, "am", which=only("hackrf_transfer"))
        assert backend == "hackrf_soft"

    def test_software_demodulation_declines_ssb_and_says_why(self):
        backend, reason = select_backend(HACKRF, "usb", which=only("hackrf_transfer"))
        assert backend == "demo"
        assert "rx_tools" in reason

    def test_a_simulated_device_gets_the_demo_tone(self):
        backend, reason = select_backend(SIMULATED, "nbfm", which=only("rtl_fm", "rx_fm"))
        assert backend == "demo"
        assert "simulated" in reason

    def test_no_assigned_device_is_demo(self):
        backend, reason = select_backend(None, "nbfm", which=only("rtl_fm"))
        assert backend == "demo"
        assert "no device" in reason

    def test_a_host_with_no_sdr_tooling_is_demo(self):
        backend, reason = select_backend(HACKRF, "nbfm", which=only())
        assert backend == "demo"
        assert "PATH" in reason


class TestListener:
    def test_drops_the_oldest_chunk_rather_than_blocking(self):
        """A stalled browser must not back up the radio."""
        listener = Listener(48_000, maxsize=2)
        for i in range(5):
            listener.put(bytes([i]))
        assert listener.dropped == 3
        assert listener.get(timeout=0.1) == bytes([3])
        assert listener.get(timeout=0.1) == bytes([4])

    def test_carries_the_stop_sentinel(self):
        listener = Listener(48_000, maxsize=2)
        listener.put(None)
        assert listener.get(timeout=0.1) is None


class TestConfigure:
    def test_rejects_a_mode_that_is_not_offered(self):
        with pytest.raises(ValueError, match="mode must be one of"):
            audio_worker.configure(mode="morse")

    def test_accepts_every_advertised_mode(self):
        for mode in AUDIO_MODES:
            audio_worker.configure(mode=mode)
            assert audio_worker.status()["mode"] == mode

    def test_rejects_a_frequency_outside_the_sdr_range(self):
        with pytest.raises(ValueError, match="freq_mhz"):
            audio_worker.configure(freq_mhz=99_999)

    def test_clamps_gain_and_squelch(self):
        audio_worker.configure(gain=99, squelch=-4)
        status = audio_worker.status()
        assert status["gain"] == 8.0
        assert status["squelch"] == 0

    def test_sample_rate_is_held_to_what_a_hackrf_accepts(self):
        audio_worker.configure(sample_rate=100)
        assert audio_worker.status()["sample_rate"] == audio_mod.HACKRF_MIN_RATE
        audio_worker.configure(sample_rate=99_000_000)
        assert audio_worker.status()["sample_rate"] == audio_mod.HACKRF_MAX_RATE

    def test_rejects_a_malformed_device_id(self):
        with pytest.raises(ValueError, match="device_id"):
            audio_worker.configure(device_id="../../etc/passwd")


class TestCommands:
    def test_rtl_fm_command_carries_frequency_mode_and_rate(self):
        audio_worker.configure(freq_mhz=162.55, mode="nbfm", squelch=0)
        audio_worker._backend = "rtl_fm"
        cmd = audio_worker.cli_command()
        assert cmd[0] == "rtl_fm"
        assert cmd[cmd.index("-f") + 1] == "162550000"
        # rtl_fm spells narrowband FM plain "fm".
        assert cmd[cmd.index("-M") + 1] == "fm"
        assert cmd[-1] == "-"
        assert "-l" not in cmd

    def test_squelch_is_passed_through_when_set(self):
        audio_worker.configure(squelch=20)
        audio_worker._backend = "rtl_fm"
        cmd = audio_worker.cli_command()
        assert "-l" in cmd
        audio_worker.configure(squelch=0)

    def test_wide_fm_keeps_its_own_mode_name(self):
        audio_worker.configure(mode="wbfm")
        audio_worker._backend = "rtl_fm"
        assert audio_worker.cli_command()[audio_worker.cli_command().index("-M") + 1] == "wbfm"
        audio_worker.configure(mode="nbfm")

    def test_hackrf_command_requests_iq_on_stdout(self):
        audio_worker.configure(freq_mhz=144.8, sample_rate=2_000_000)
        cmd = audio_worker.hackrf_command()
        assert cmd[0] == "hackrf_transfer"
        assert cmd[cmd.index("-r") + 1] == "-"
        assert cmd[cmd.index("-f") + 1] == "144800000"
        assert cmd[cmd.index("-s") + 1] == "2000000"


class TestWorkerLifecycle:
    def test_refuses_to_start_without_a_radio_in_the_audio_role(self, monkeypatch):
        from app.core import balance as balance_mod

        monkeypatch.setattr(balance_mod, "list_radio_devices", lambda **kw: [])
        status = audio_worker.start()
        assert status["running"] is False
        assert "role=audio" in status["error"]

    def test_start_stop_cycle(self, audio_device):
        assert audio_worker.start()["running"] is True
        assert audio_worker.status()["backend"] == "demo"
        assert audio_worker.stop()["running"] is False

    def test_double_start_is_idempotent(self, running_audio):
        assert audio_worker.start()["running"] is True
        assert audio_worker.status()["listeners"] == 0

    def test_stop_when_idle_is_safe(self):
        assert audio_worker.stop()["running"] is False

    def test_restart_cycles_cleanly(self, audio_device):
        for _ in range(3):
            assert audio_worker.start()["running"] is True
            assert audio_worker.stop()["running"] is False

    def test_disabled_in_config_refuses_to_start(self, audio_device, monkeypatch):
        from app.core.config import get_config

        monkeypatch.setitem(get_config().audio, "enabled", False)
        status = audio_worker.start()
        assert status["running"] is False
        assert "disabled" in status["error"]

    def test_retune_restarts_only_when_already_running(self, audio_device):
        idle = audio_worker.retune(freq_mhz=155.0)
        assert idle["running"] is False
        assert idle["freq_mhz"] == 155.0

        audio_worker.start()
        try:
            running = audio_worker.retune(freq_mhz=156.0)
            assert running["running"] is True
            assert running["freq_mhz"] == 156.0
        finally:
            audio_worker.stop()


class TestFanOut:
    def test_a_listener_receives_audio(self, running_audio):
        listener = audio_worker.subscribe()
        try:
            chunk = listener.get(timeout=5.0)
            assert chunk and len(chunk) % 2 == 0
        finally:
            audio_worker.unsubscribe(listener)

    def test_retune_keeps_the_browser_listening(self, running_audio):
        """Changing frequency restarts the radio; the <audio> element must survive."""
        listener = audio_worker.subscribe()
        try:
            assert listener.get(timeout=5.0)
            status = audio_worker.retune(freq_mhz=155.4)
            assert status["freq_mhz"] == 155.4
            assert status["running"] is True
            after = listener.get(timeout=8.0)
            assert after is not None, "retune ended the stream"
            assert len(after) % 2 == 0
        finally:
            audio_worker.unsubscribe(listener)

    def test_retune_ends_the_stream_when_the_sample_rate_changes(self, running_audio):
        """The header the browser already parsed names a rate, so it cannot change."""
        listener = audio_worker.subscribe()
        try:
            assert listener.get(timeout=5.0)
            before = audio_worker.status()["audio_rate"]
            audio_worker._audio_rate = before + 1000
            audio_worker.retune(freq_mhz=155.4)
            # Drain whatever was already queued; the sentinel must arrive.
            for _ in range(40):
                if listener.get(timeout=5.0) is None:
                    break
            else:
                pytest.fail("stream was not ended after a rate change")
        finally:
            audio_worker.unsubscribe(listener)

    def test_retune_while_stopped_does_not_start_the_radio(self, audio_device):
        assert audio_worker.status()["running"] is False
        status = audio_worker.retune(freq_mhz=155.4, mode="nbfm")
        assert status["running"] is False
        assert status["freq_mhz"] == 155.4
        assert status["retuning"] is False

    def test_stop_still_ends_every_stream(self, running_audio):
        listener = audio_worker.subscribe()
        try:
            assert listener.get(timeout=5.0)
            audio_worker.stop()
            for _ in range(40):
                if listener.get(timeout=5.0) is None:
                    break
            else:
                pytest.fail("stop did not end the stream")
        finally:
            audio_worker.unsubscribe(listener)

    def test_one_radio_feeds_several_listeners(self, running_audio):
        first = audio_worker.subscribe()
        second = audio_worker.subscribe()
        try:
            assert first.get(timeout=5.0)
            assert second.get(timeout=5.0)
            assert audio_worker.status()["listeners"] == 2
        finally:
            audio_worker.unsubscribe(first)
            audio_worker.unsubscribe(second)

    def test_listener_count_is_capped(self, running_audio, monkeypatch):
        from app.core.config import get_config

        monkeypatch.setitem(get_config().audio, "max_listeners", 1)
        held = audio_worker.subscribe()
        try:
            with pytest.raises(RuntimeError, match="too many listeners"):
                audio_worker.subscribe()
        finally:
            audio_worker.unsubscribe(held)

    def test_stream_starts_with_a_wav_header(self, running_audio):
        listener = audio_worker.subscribe()
        stream = audio_worker.stream(listener)
        try:
            assert next(stream)[:4] == b"RIFF"
            assert next(stream)
        finally:
            stream.close()

    def test_stopping_ends_every_open_stream(self, audio_device):
        audio_worker.start()
        listener = audio_worker.subscribe()
        stream = audio_worker.stream(listener)
        next(stream)

        audio_worker.stop()
        # The sentinel queued by stop() has to terminate the generator.
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                next(stream)
            except StopIteration:
                break
        else:
            pytest.fail("stream did not end after the worker stopped")

    def test_unsubscribe_is_idempotent(self, running_audio):
        listener = audio_worker.subscribe()
        audio_worker.unsubscribe(listener)
        audio_worker.unsubscribe(listener)
        assert audio_worker.status()["listeners"] == 0


class TestApi:
    def test_status_endpoint_describes_the_worker(self, client):
        body = client.get("/api/audio").json()
        assert body["running"] is False
        assert body["modes"] == list(AUDIO_MODES)
        assert "backend" in body

    def test_audio_is_an_assignable_role(self, client):
        assert "audio" in client.get("/api/devices").json()["roles"]

    def test_balance_reports_the_audio_slot(self, client, audio_device):
        body = client.get("/api/devices/balance").json()
        assert [d["id"] for d in body["audio"]] == ["demo-hackrf-0"]
        assert body["busy"]["audio"] is None

    def test_balance_marks_the_slot_busy_while_listening(self, client, running_audio):
        assert client.get("/api/devices/balance").json()["busy"]["audio"] == "demo-hackrf-0"

    def test_start_and_stop_over_http(self, client, audio_device):
        started = client.post("/api/audio/start", json={"freq_mhz": 162.55, "mode": "nbfm"})
        assert started.status_code == 200
        assert started.json()["running"] is True
        assert client.post("/api/audio/stop").json()["running"] is False

    def test_start_rejects_a_bad_mode(self, client, audio_device):
        resp = client.post("/api/audio/start", json={"mode": "definitely-not-a-mode"})
        assert resp.status_code == 400
        assert "mode must be one of" in resp.json()["detail"]

    def test_config_rejects_a_bad_frequency(self, client):
        resp = client.post("/api/audio/config", json={"freq_mhz": 99_999})
        assert resp.status_code == 400

    def test_stream_refuses_while_the_radio_is_off(self, client):
        resp = client.get("/api/audio/stream")
        assert resp.status_code == 409
        assert "not running" in resp.json()["detail"]

    def test_stream_serves_wav_and_is_never_compressed(self, client, running_audio):
        # TestClient runs the whole app call before handing back a response, so an
        # endless stream never returns. Stop the radio to close it from the far end.
        closer = threading.Timer(0.6, audio_worker.stop)
        closer.start()
        try:
            resp = client.get("/api/audio/stream", headers={"Accept-Encoding": "gzip"})
        finally:
            closer.cancel()
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("audio/wav")
        # Gzipping a live stream would buffer it into silence.
        assert resp.headers["content-encoding"] == "identity"
        assert resp.headers["x-accel-buffering"] == "no"
        body = resp.content
        assert body[:4] == b"RIFF"
        assert body[8:12] == b"WAVE"
        assert len(body) > 44

    def test_stream_turns_a_full_house_away(self, client, running_audio, monkeypatch):
        from app.core.config import get_config

        monkeypatch.setitem(get_config().audio, "max_listeners", 1)
        held = audio_worker.subscribe()
        try:
            assert client.get("/api/audio/stream").status_code == 429
        finally:
            audio_worker.unsubscribe(held)

    def test_endpoints_are_404_when_audio_is_disabled(self, client, monkeypatch):
        from app.core.config import get_config

        monkeypatch.setitem(get_config().audio, "enabled", False)
        assert client.post("/api/audio/start").status_code == 404
        assert client.get("/api/audio/stream").status_code == 404

    def test_starting_logs_an_event(self, client, audio_device):
        client.post("/api/audio/start", json={"freq_mhz": 145.5})
        try:
            kinds = [e["kind"] for e in client.get("/api/events").json()["events"]]
            assert "audio_start" in kinds
        finally:
            client.post("/api/audio/stop")
