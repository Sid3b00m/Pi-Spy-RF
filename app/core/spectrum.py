from __future__ import annotations

import random
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.bandplan import classify_mhz
from app.core.db import add_event
from app.core.balance import require_role
from app.core.decode import decode_worker
from app.core.security import clamp_interval_s, clamp_spectrum_range, validate_device_id


def _is_hackrf(device: dict[str, Any]) -> bool:
    """hackrf_info reports type 'hackrf'; via SoapySDR the driver name is the type."""
    return "hackrf" in f"{device.get('type') or ''} {device.get('id') or ''}".lower()


def parse_sweep_csv(
    text: str, start_mhz: float, end_mhz: float
) -> tuple[list[float], list[float]]:
    """Parse hackrf_sweep CSV into (freqs_mhz, powers), trimmed and in order.

    Rows are `date, time, hz_low, hz_high, bin_width, samples, dB...`. The sweep
    tunes in 20 MHz steps, so it overshoots whatever range was asked for, and the
    segments come back in tuning order rather than frequency order.
    """
    points: list[tuple[float, float]] = []
    for line in text.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 7:
            continue
        try:
            hz_low = float(parts[2])
            bin_width = float(parts[4])
            powers = [float(x) for x in parts[6:]]
        except ValueError:
            continue
        if bin_width <= 0:
            continue
        for i, power in enumerate(powers):
            mhz = (hz_low + bin_width * (i + 0.5)) / 1e6
            if start_mhz <= mhz <= end_mhz:
                points.append((mhz, power))
    points.sort(key=lambda p: p[0])
    return [p[0] for p in points], [p[1] for p in points]


@dataclass
class Peak:
    freq_mhz: float
    power_db: float
    label: str
    mode_hint: str


@dataclass
class SpectrumSnapshot:
    ts: str
    device_id: str
    center_mhz: float
    span_mhz: float
    bins: list[float]
    freqs_mhz: list[float]
    peaks: list[Peak] = field(default_factory=list)
    source: str = "demo"
    note: str = ""


class SpectrumWorker:
    """Background spectrum scanner for the device assigned role=scan."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._latest: SpectrumSnapshot | None = None
        self._interval_s = 3.0
        self._threshold_db = -45.0
        self._start_mhz = 140.0
        self._end_mhz = 170.0
        self._step_mhz = 2.0
        self._device_id: str | None = None
        self._error: str | None = None
        self._last_peak_log: dict[str, float] = {}

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = None
            if self._latest:
                latest = {
                    "ts": self._latest.ts,
                    "device_id": self._latest.device_id,
                    "center_mhz": self._latest.center_mhz,
                    "span_mhz": self._latest.span_mhz,
                    "bins": self._latest.bins,
                    "freqs_mhz": self._latest.freqs_mhz,
                    "peaks": [asdict(p) for p in self._latest.peaks],
                    "source": self._latest.source,
                    "note": self._latest.note,
                }
            return {
                "running": self._running,
                "device_id": self._device_id,
                "interval_s": self._interval_s,
                "threshold_db": self._threshold_db,
                "range_mhz": [self._start_mhz, self._end_mhz],
                "step_mhz": self._step_mhz,
                "error": self._error,
                "latest": latest,
            }

    def configure(
        self,
        *,
        start_mhz: float | None = None,
        end_mhz: float | None = None,
        step_mhz: float | None = None,
        interval_s: float | None = None,
        threshold_db: float | None = None,
        device_id: str | None = None,
    ) -> None:
        with self._lock:
            start = self._start_mhz if start_mhz is None else float(start_mhz)
            end = self._end_mhz if end_mhz is None else float(end_mhz)
            if start_mhz is not None or end_mhz is not None:
                start, end = clamp_spectrum_range(start, end)
                self._start_mhz = start
                self._end_mhz = end
            if step_mhz is not None:
                self._step_mhz = max(0.1, min(50.0, float(step_mhz)))
            if interval_s is not None:
                self._interval_s = clamp_interval_s(interval_s)
            if threshold_db is not None:
                self._threshold_db = max(-120.0, min(0.0, float(threshold_db)))
            if device_id is not None:
                self._device_id = validate_device_id(device_id)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return {"running": True, "device_id": self._device_id, "note": "already running"}
            device = self._pick_scan_device_unlocked()
            if not device:
                self._error = "No device with role=scan"
                return self._status_unlocked()
            self._device_id = device["id"]
            self._error = None
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="spectrum-worker", daemon=True)
            self._thread.start()
        add_event(
            "spectrum_start",
            f"Spectrum worker started on {self._device_id}",
            source=self._device_id,
            meta={"range_mhz": [self._start_mhz, self._end_mhz]},
        )
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return self._status_unlocked()
            self._stop.set()
            thread = self._thread
            device_id = self._device_id
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._running = False
            self._thread = None
        add_event("spectrum_stop", f"Spectrum worker stopped ({device_id})", source=device_id)
        return self.status()

    def _status_unlocked(self) -> dict[str, Any]:
        latest = None
        if self._latest:
            latest = {
                "ts": self._latest.ts,
                "device_id": self._latest.device_id,
                "center_mhz": self._latest.center_mhz,
                "span_mhz": self._latest.span_mhz,
                "bins": self._latest.bins,
                "freqs_mhz": self._latest.freqs_mhz,
                "peaks": [asdict(p) for p in self._latest.peaks],
                "source": self._latest.source,
                "note": self._latest.note,
            }
        return {
            "running": self._running,
            "device_id": self._device_id,
            "interval_s": self._interval_s,
            "threshold_db": self._threshold_db,
            "range_mhz": [self._start_mhz, self._end_mhz],
            "step_mhz": self._step_mhz,
            "error": self._error,
            "latest": latest,
        }

    def _pick_scan_device_unlocked(self) -> dict[str, Any] | None:
        # Never steal the decode stick.
        dedicated = require_role("scan")
        if dedicated:
            self._device_id = dedicated["id"]
            return dedicated
        return None

    def _pick_scan_device(self) -> dict[str, Any] | None:
        with self._lock:
            return self._pick_scan_device_unlocked()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap = self._capture_once()
                with self._lock:
                    self._latest = snap
                    self._error = None
                self._emit_peaks(snap)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._error = str(exc)
                add_event("spectrum_error", str(exc), source=self._device_id)
            self._stop.wait(self._interval_s)

    def _capture_once(self) -> SpectrumSnapshot:
        device = self._pick_scan_device()
        if not device:
            raise RuntimeError("No scan device available")
        device_id = device["id"]
        center = (self._start_mhz + self._end_mhz) / 2.0
        span = max(0.1, self._end_mhz - self._start_mhz)

        if device_id.startswith("demo-") or device.get("status") == "simulated":
            return self._demo_snapshot(device_id, center, span)

        if device.get("type") == "rtl-sdr" and shutil.which("rtl_power"):
            return self._rtl_power_snapshot(device_id, center, span)

        if _is_hackrf(device) and shutil.which("hackrf_sweep"):
            return self._hackrf_sweep_snapshot(device_id, center, span)

        snap = self._demo_snapshot(device_id, center, span)
        snap.source = "fallback-demo"
        snap.note = "No rtl_power/hackrf_sweep path available; using simulated spectrum"
        return snap

    def _demo_snapshot(self, device_id: str, center: float, span: float) -> SpectrumSnapshot:
        n = 128
        freqs = [self._start_mhz + (span * i / (n - 1)) for i in range(n)]
        bins: list[float] = []
        synthetic = [162.4, 162.55, 146.52, 156.8, 929.662]
        for f in freqs:
            noise = -65.0 + random.uniform(-3, 3)
            for p in synthetic:
                if abs(f - p) < 0.05:
                    noise = max(noise, -30.0 + random.uniform(-2, 2))
            bins.append(noise)
        peaks = self._find_peaks(freqs, bins)
        return SpectrumSnapshot(
            ts=datetime.now(timezone.utc).isoformat(),
            device_id=device_id,
            center_mhz=center,
            span_mhz=span,
            bins=bins,
            freqs_mhz=freqs,
            peaks=peaks,
            source="demo",
            note="Simulated spectrum for UI/dev without SDR hardware",
        )

    def _rtl_power_snapshot(self, device_id: str, center: float, span: float) -> SpectrumSnapshot:
        start = self._start_mhz
        end = self._end_mhz
        bin_hz = int(max(10000, (self._step_mhz * 1e6) / 4))
        cmd = [
            "rtl_power",
            "-f",
            f"{start}M:{end}M:{bin_hz}",
            "-i",
            "1",
            "-1",
            "-",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or "rtl_power failed")
        freqs: list[float] = []
        bins: list[float] = []
        for line in p.stdout.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 7:
                continue
            try:
                f0 = float(parts[2]) / 1e6
                step = float(parts[4]) / 1e6
                powers = [float(x) for x in parts[6:]]
            except ValueError:
                continue
            for i, power in enumerate(powers):
                freqs.append(f0 + i * step)
                bins.append(power)
        if not freqs:
            raise RuntimeError("rtl_power returned no bins")
        peaks = self._find_peaks(freqs, bins)
        return SpectrumSnapshot(
            ts=datetime.now(timezone.utc).isoformat(),
            device_id=device_id,
            center_mhz=center,
            span_mhz=span,
            bins=bins,
            freqs_mhz=freqs,
            peaks=peaks,
            source="rtl_power",
            note="Captured via rtl_power",
        )

    def _hackrf_sweep_snapshot(self, device_id: str, center: float, span: float) -> SpectrumSnapshot:
        start = self._start_mhz
        end = self._end_mhz
        # hackrf_sweep takes whole MHz, and refuses a bin width outside this range.
        bin_hz = int(max(2445, min(5_000_000, (self._step_mhz * 1e6) / 4)))
        cmd = [
            "hackrf_sweep",
            "-f",
            f"{int(start)}:{int(end) + 1}",
            "-w",
            str(bin_hz),
            "-1",
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        freqs, bins = parse_sweep_csv(p.stdout, start, end)
        if not freqs:
            detail = p.stderr.strip().splitlines()
            raise RuntimeError(detail[-1] if detail else "hackrf_sweep returned no bins")
        peaks = self._find_peaks(freqs, bins)
        return SpectrumSnapshot(
            ts=datetime.now(timezone.utc).isoformat(),
            device_id=device_id,
            center_mhz=center,
            span_mhz=span,
            bins=bins,
            freqs_mhz=freqs,
            peaks=peaks,
            source="hackrf_sweep",
            note="Captured via hackrf_sweep",
        )

    def _find_peaks(self, freqs: list[float], bins: list[float]) -> list[Peak]:
        peaks: list[Peak] = []
        if len(bins) < 3:
            return peaks
        for i in range(1, len(bins) - 1):
            if bins[i] < self._threshold_db:
                continue
            if bins[i] >= bins[i - 1] and bins[i] >= bins[i + 1]:
                info = classify_mhz(freqs[i])
                peaks.append(
                    Peak(
                        freq_mhz=round(freqs[i], 4),
                        power_db=round(bins[i], 2),
                        label=info["label"],
                        mode_hint=info["mode_hint"],
                    )
                )
        peaks.sort(key=lambda p: p.power_db, reverse=True)
        filtered: list[Peak] = []
        for peak in peaks:
            if any(abs(peak.freq_mhz - x.freq_mhz) < 0.05 for x in filtered):
                continue
            filtered.append(peak)
            if len(filtered) >= 12:
                break
        return filtered

    def _emit_peaks(self, snap: SpectrumSnapshot) -> None:
        now = time.time()
        for peak in snap.peaks:
            if peak.mode_hint == "unknown" and peak.power_db < self._threshold_db + 10:
                continue
            key = f"{round(peak.freq_mhz, 2)}:{peak.mode_hint}"
            last = self._last_peak_log.get(key, 0.0)
            if now - last < 30:
                continue
            self._last_peak_log[key] = now
            add_event(
                "spectrum_peak",
                f"{peak.label} @ {peak.freq_mhz} MHz ({peak.power_db} dB)",
                source=snap.device_id,
                freq_hz=peak.freq_mhz * 1e6,
                mode=peak.mode_hint,
                meta={"power_db": peak.power_db, "source": snap.source},
            )
            try:
                decode_worker.maybe_queue_from_peak(peak.freq_mhz, peak.mode_hint)
            except Exception:
                pass


spectrum_worker = SpectrumWorker()