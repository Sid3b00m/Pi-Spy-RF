"""Live listening: tune the local SDR and stream demodulated audio to browsers.

One radio feeds many listeners. A worker thread owns the SDR process, and each
connected browser gets its own bounded queue fed from that single stream, so a
tab that stalls drops chunks instead of backing up the radio.

Which backend runs depends on what is actually installed:

* `rtl_fm` for RTL dongles. Packaged everywhere and already used by the decode
  path, so it stays the preferred route.
* `rx_fm` from rx_tools, the SoapySDR-flavoured rtl_fm, when it is present.
* `hackrf_transfer` piped through the software demodulator in app.core.dsp. No
  distro packages an rtl_fm equivalent for HackRF, so this is what makes the
  board usable for audio at all.
* A synthesised tone otherwise, matching how the rest of the app degrades on a
  host with no SDR tooling.

Audio is served as a WAV stream because it needs no encoder dependency and every
browser plays it from a plain <audio> element.
"""
from __future__ import annotations

import math
import shutil
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from queue import Empty, Full, Queue
from typing import Any, Callable, Iterator

import numpy as np

from app.core.balance import require_role
from app.core.config import get_config
from app.core.db import add_event
from app.core.dsp import AUDIO_DECIM, SOFT_MODES, SoftDemodulator, to_pcm16
from app.core.security import clamp_freq_mhz, validate_device_id

# rtl_fm and rx_fm share a command line; these are our names for their -M values.
AUDIO_MODES = ("nbfm", "wbfm", "am", "usb", "lsb")
_CLI_MODE = {"nbfm": "fm", "wbfm": "wbfm", "am": "am", "usb": "usb", "lsb": "lsb"}

DEFAULT_OUTPUT_RATE = 48_000
# HackRF will not sample below 2 Msps.
HACKRF_MIN_RATE = 2_000_000
HACKRF_MAX_RATE = 20_000_000
TARGET_IF_RATE = 250_000

GAIN_MIN, GAIN_MAX = 0.1, 8.0
MAX_LISTENERS = 4
QUEUE_CHUNKS = 24

# Big enough that no browser stops early, small enough to stay a positive int32.
STREAM_DATA_SIZE = 0x7FFFFFFF


def wav_header(sample_rate: int, channels: int = 1, bits: int = 16) -> bytes:
    """44-byte PCM header declaring an open-ended stream."""
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    return b"".join(
        [
            b"RIFF",
            struct.pack("<I", STREAM_DATA_SIZE),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits),
            b"data",
            struct.pack("<I", STREAM_DATA_SIZE),
        ]
    )


def clamp_gain(value: float) -> float:
    return max(GAIN_MIN, min(GAIN_MAX, float(value)))


def clamp_squelch(value: float) -> int:
    return int(max(0, min(100, round(float(value)))))


def if_decimation(sample_rate: float) -> int:
    """Pick the first-stage decimation that lands nearest the target IF rate."""
    return max(1, int(round(float(sample_rate) / TARGET_IF_RATE)))


def soft_audio_rate(sample_rate: float) -> int:
    return int(round(sample_rate / if_decimation(sample_rate) / AUDIO_DECIM))


def _is_hackrf(device: dict[str, Any]) -> bool:
    return "hackrf" in f"{device.get('type') or ''} {device.get('id') or ''}".lower()


def _is_rtl(device: dict[str, Any]) -> bool:
    return "rtl" in f"{device.get('type') or ''} {device.get('id') or ''}".lower()


def select_backend(
    device: dict[str, Any] | None,
    mode: str,
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> tuple[str, str]:
    """Choose how to produce audio for this device. Returns (backend, reason)."""
    if not device:
        return "demo", "no device assigned"
    if str(device.get("id", "")).startswith("demo-") or device.get("status") == "simulated":
        return "demo", "device is simulated"

    if _is_rtl(device) and which("rtl_fm"):
        return "rtl_fm", "rtl_fm handles RTL dongles directly"
    if which("rx_fm"):
        return "rx_fm", "rx_fm (rx_tools) drives this device through SoapySDR"
    if _is_hackrf(device) and which("hackrf_transfer"):
        if mode not in SOFT_MODES:
            return "demo", f"software demodulation cannot do {mode}; install rx_tools for it"
        return "hackrf_soft", "hackrf_transfer piped through the software demodulator"
    return "demo", "no usable SDR audio tool found on PATH"


class Listener:
    """One browser. Bounded, and drops the oldest chunk rather than blocking."""

    def __init__(self, sample_rate: int, maxsize: int = QUEUE_CHUNKS) -> None:
        self.sample_rate = sample_rate
        self.queue: Queue[bytes | None] = Queue(maxsize=maxsize)
        self.dropped = 0

    def put(self, chunk: bytes | None) -> None:
        try:
            self.queue.put_nowait(chunk)
        except Full:
            try:
                self.queue.get_nowait()
                self.dropped += 1
                self.queue.put_nowait(chunk)
            except (Empty, Full):
                pass

    def get(self, timeout: float = 1.0) -> bytes | None:
        return self.queue.get(timeout=timeout)


@dataclass
class AudioSettings:
    freq_mhz: float = 162.55
    mode: str = "nbfm"
    gain: float = 1.0
    squelch: int = 0
    device_id: str | None = None
    sample_rate: int = HACKRF_MIN_RATE
    output_rate: int = DEFAULT_OUTPUT_RATE


class AudioWorker:
    """Owns the tuned SDR and fans its audio out to the connected browsers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._settings = AudioSettings()
        self._listeners: list[Listener] = []
        self._proc: subprocess.Popen[bytes] | None = None
        self._backend = "demo"
        self._backend_reason = "not started"
        self._audio_rate = DEFAULT_OUTPUT_RATE
        self._device_id: str | None = None
        self._error: str | None = None
        self._started_at: float | None = None
        self._bytes_out = 0
        self._squelched = False
        self._retuning = False

    # ---------------------------------------------------------------- status

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, Any]:
        s = self._settings
        return {
            "running": self._running,
            "enabled": is_enabled(),
            "device_id": self._device_id,
            "backend": self._backend,
            "backend_reason": self._backend_reason,
            "freq_mhz": s.freq_mhz,
            "mode": s.mode,
            "modes": list(AUDIO_MODES),
            "gain": s.gain,
            "squelch": s.squelch,
            "squelched": self._squelched,
            "sample_rate": s.sample_rate,
            "audio_rate": self._audio_rate,
            "listeners": len(self._listeners),
            "max_listeners": _max_listeners(),
            "dropped_chunks": sum(x.dropped for x in self._listeners),
            "bytes_out": self._bytes_out,
            "uptime_s": (time.time() - self._started_at) if self._started_at else 0.0,
            "retuning": self._retuning,
            "error": self._error,
        }

    # ------------------------------------------------------------- configure

    def configure(
        self,
        *,
        freq_mhz: float | None = None,
        mode: str | None = None,
        gain: float | None = None,
        squelch: float | None = None,
        device_id: str | None = None,
        sample_rate: int | None = None,
    ) -> None:
        with self._lock:
            if freq_mhz is not None:
                self._settings.freq_mhz = clamp_freq_mhz(freq_mhz)
            if mode is not None:
                wanted = str(mode).strip().lower()
                if wanted not in AUDIO_MODES:
                    raise ValueError(f"mode must be one of {AUDIO_MODES}")
                self._settings.mode = wanted
            if gain is not None:
                self._settings.gain = clamp_gain(gain)
            if squelch is not None:
                self._settings.squelch = clamp_squelch(squelch)
            if device_id is not None:
                self._settings.device_id = validate_device_id(device_id)
            if sample_rate is not None:
                self._settings.sample_rate = int(
                    max(HACKRF_MIN_RATE, min(HACKRF_MAX_RATE, int(sample_rate)))
                )

    # ------------------------------------------------------------ life cycle

    def start(self) -> dict[str, Any]:
        if not is_enabled():
            with self._lock:
                self._error = "audio is disabled in config"
                return self._status_unlocked()

        with self._lock:
            if self._running:
                return self._status_unlocked()
            device = require_role("audio")
            if not device:
                self._error = (
                    "No device with role=audio. Assign one under SDR devices - "
                    "a single radio can only hold one role at a time."
                )
                return self._status_unlocked()

            backend, reason = select_backend(device, self._settings.mode)
            self._device_id = device["id"]
            self._backend = backend
            self._backend_reason = reason
            self._audio_rate = (
                soft_audio_rate(self._settings.sample_rate)
                if backend == "hackrf_soft"
                else self._settings.output_rate
            )
            self._error = None
            self._bytes_out = 0
            self._squelched = False
            self._started_at = time.time()
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="audio-worker", daemon=True)
            self._thread.start()
            device_id = self._device_id
            freq = self._settings.freq_mhz
            mode = self._settings.mode

        add_event(
            "audio_start",
            f"Listening on {freq} MHz {mode} via {backend} ({device_id})",
            source=device_id,
            freq_hz=freq * 1e6,
            mode=mode,
            meta={"backend": backend},
        )
        return self.status()

    def stop(self, *, notify: bool = True) -> dict[str, Any]:
        """Release the radio. notify=False keeps listeners for a retune restart."""
        with self._lock:
            if not self._running:
                return self._status_unlocked()
            self._stop.set()
            thread = self._thread
            device_id = self._device_id
            proc = self._proc

        _terminate(proc)
        if thread and thread.is_alive():
            thread.join(timeout=5)

        with self._lock:
            self._running = False
            self._thread = None
            self._proc = None
            self._started_at = None

        if notify:
            self._end_listeners()
            add_event("audio_stop", f"Stopped listening ({device_id})", source=device_id)
        return self.status()

    def retune(self, **kwargs: Any) -> dict[str, Any]:
        """Apply settings, restarting the radio underneath anyone listening.

        Listeners are deliberately kept: the WAV stream a browser is already
        playing stays valid while the sample rate holds, so changing frequency
        is a brief buffer gap rather than a dead <audio> element. A rate change
        contradicts the header already sent, so those streams do have to end.
        """
        with self._lock:
            was_running = self._running
            old_rate = self._audio_rate
            self._retuning = was_running

        try:
            if was_running:
                self.stop(notify=False)
            self.configure(**kwargs)
            if not was_running:
                return self.status()
            status = self.start()
        finally:
            with self._lock:
                self._retuning = False

        if status["audio_rate"] != old_rate or not status["running"]:
            self._end_listeners()
        return self.status()

    def _end_listeners(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            listener.put(None)

    # ------------------------------------------------------------- listeners

    def subscribe(self) -> Listener:
        with self._lock:
            if len(self._listeners) >= _max_listeners():
                raise RuntimeError(f"too many listeners (max {_max_listeners()})")
            listener = Listener(self._audio_rate)
            self._listeners.append(listener)
            return listener

    def unsubscribe(self, listener: Listener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _broadcast(self, chunk: bytes) -> None:
        with self._lock:
            listeners = list(self._listeners)
            self._bytes_out += len(chunk)
        for listener in listeners:
            listener.put(chunk)

    # ----------------------------------------------------------------- radio

    def _loop(self) -> None:
        try:
            if self._backend == "demo":
                self._run_demo()
            elif self._backend == "hackrf_soft":
                self._run_hackrf_soft()
            else:
                self._run_cli()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._error = str(exc)
                self._running = False
            add_event("audio_error", str(exc), source=self._device_id)
            for listener in list(self._listeners):
                listener.put(None)

    def _spawn(self, cmd: list[str]) -> subprocess.Popen[bytes]:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        with self._lock:
            self._proc = proc
        return proc

    def _fail_from(self, proc: subprocess.Popen[bytes], label: str) -> None:
        detail = ""
        try:
            if proc.stderr:
                detail = proc.stderr.read(4000).decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001
            pass
        tail = detail.splitlines()[-1] if detail else f"{label} produced no audio"
        raise RuntimeError(tail)

    def cli_command(self) -> list[str]:
        """The rtl_fm / rx_fm invocation, split out so tests can assert on it."""
        s = self._settings
        binary = "rtl_fm" if self._backend == "rtl_fm" else "rx_fm"
        cmd = [
            binary,
            "-f",
            str(int(s.freq_mhz * 1e6)),
            "-M",
            _CLI_MODE.get(s.mode, "fm"),
            "-s",
            str(int(s.output_rate)),
        ]
        if s.squelch:
            # rtl_fm's squelch is a raw power threshold; this is an approximate map.
            cmd += ["-l", str(s.squelch * 3)]
        if binary == "rx_fm":
            cmd += ["-d", "driver=hackrf"] if self._device_is_hackrf() else []
        cmd.append("-")
        return cmd

    def _device_is_hackrf(self) -> bool:
        return "hackrf" in str(self._device_id or "").lower()

    def _run_cli(self) -> None:
        proc = self._spawn(self.cli_command())
        block = max(2048, int(self._audio_rate * 2 * 0.05))
        produced = False
        while not self._stop.is_set():
            chunk = proc.stdout.read(block) if proc.stdout else b""
            if not chunk:
                break
            produced = True
            self._broadcast(self._apply_gain(chunk))
        if not produced and not self._stop.is_set():
            self._fail_from(proc, self._backend)
        _terminate(proc)

    def hackrf_command(self) -> list[str]:
        """The hackrf_transfer invocation, split out so tests can assert on it."""
        s = self._settings
        return [
            "hackrf_transfer",
            "-r",
            "-",
            "-f",
            str(int(s.freq_mhz * 1e6)),
            "-s",
            str(int(s.sample_rate)),
            "-l",
            "24",
            "-g",
            "20",
        ]

    def _run_hackrf_soft(self) -> None:
        s = self._settings
        demod = SoftDemodulator(
            mode=s.mode,
            sample_rate=s.sample_rate,
            if_decim=if_decimation(s.sample_rate),
            gain=s.gain,
        )
        proc = self._spawn(self.hackrf_command())
        # Roughly 60 ms of IQ, so latency stays low without waking the loop constantly.
        block = max(65536, int(s.sample_rate * 2 * 0.06))
        produced = False
        while not self._stop.is_set():
            raw = proc.stdout.read(block) if proc.stdout else b""
            if not raw:
                break
            produced = True
            if self._squelch_closed(raw):
                continue
            pcm = demod.process(raw)
            if pcm:
                self._broadcast(pcm)
        if not produced and not self._stop.is_set():
            self._fail_from(proc, "hackrf_transfer")
        _terminate(proc)

    def _squelch_closed(self, raw: bytes) -> bool:
        """Signal-strength gate on the raw IQ, so an idle channel stays quiet."""
        level = self._settings.squelch
        if not level:
            self._squelched = False
            return False
        # Subsampled: this only needs to track the channel, not measure it.
        sample = np.frombuffer(raw, dtype=np.int8)[::128].astype(np.float32) / 128.0
        if sample.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(sample)))) or 1e-9
        threshold_db = -60.0 + (level / 100.0) * 50.0
        self._squelched = (20.0 * math.log10(rms)) < threshold_db
        return self._squelched

    def _apply_gain(self, pcm: bytes) -> bytes:
        gain = self._settings.gain
        if abs(gain - 1.0) < 1e-6:
            return pcm
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        return to_pcm16(samples, gain)

    def _run_demo(self) -> None:
        """A quiet two-tone warble, so the player and the plumbing are testable."""
        rate = self._audio_rate
        step = 0.05
        size = int(rate * step)
        phase = 0.0
        while not self._stop.is_set():
            t = np.arange(size, dtype=np.float32) / rate
            wobble = 440.0 + 40.0 * math.sin(phase)
            tone = 0.18 * np.sin(2 * np.pi * wobble * t).astype(np.float32)
            phase += 0.35
            self._broadcast(to_pcm16(tone, self._settings.gain))
            self._stop.wait(step)

    # ---------------------------------------------------------------- stream

    def _stream_alive(self) -> bool:
        with self._lock:
            return self._running or self._retuning

    def stream(self, listener: Listener) -> Iterator[bytes]:
        """WAV header then PCM, until the worker stops or the browser goes away."""
        yield wav_header(listener.sample_rate)
        try:
            while True:
                try:
                    chunk = listener.get(timeout=1.0)
                except Empty:
                    # A retune leaves a gap with no chunks and nothing running.
                    if not self._stream_alive():
                        return
                    continue
                if chunk is None:
                    return
                yield chunk
        finally:
            self.unsubscribe(listener)


def _terminate(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
    for pipe in (proc.stdout, proc.stderr):
        try:
            if pipe:
                pipe.close()
        except Exception:  # noqa: BLE001
            pass


def _settings() -> dict[str, Any]:
    return get_config().audio or {}


def is_enabled() -> bool:
    return bool(_settings().get("enabled", True))


def _max_listeners() -> int:
    try:
        return max(1, min(16, int(_settings().get("max_listeners", MAX_LISTENERS))))
    except (TypeError, ValueError):
        return MAX_LISTENERS


audio_worker = AudioWorker()
