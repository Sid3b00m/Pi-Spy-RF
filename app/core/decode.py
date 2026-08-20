from __future__ import annotations

import random
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.db import add_event
from app.core.balance import require_role
from app.core.devices import list_radio_devices
from app.core.security import clamp_duration_s, clamp_freq_mhz, validate_device_id
from app.core.modes import (
    MODE_BY_ID,
    SUPPORTED_MODES,
    hint_to_mode,
    list_modes,
    resolve_mode,
)


@dataclass
class DecodeResult:
    mode: str
    text: str | None = None
    color_code: int | None = None
    timeslot: int | None = None
    talkgroup: int | None = None
    radio_id: int | None = None
    nac: str | None = None
    ran: int | None = None
    callsign: str | None = None
    dgid: int | None = None
    capcode: str | None = None
    encrypted: bool = False
    raw: str | None = None


@dataclass
class DecodeJob:
    id: str
    freq_mhz: float
    mode: str
    status: str  # queued | running | done | error
    device_id: str | None = None
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: DecodeResult | None = None
    duration_s: float = 8.0


class DecodeWorker:
    """Background decode queue bound to role=decode SDR (or demo)."""

    MAX_QUEUE = 200

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._queue: list[DecodeJob] = []
        self._history: list[DecodeJob] = []
        self._current: DecodeJob | None = None
        self._device_id: str | None = None
        self._error: str | None = None
        self._auto_from_spectrum = True

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "device_id": self._device_id,
            "auto_from_spectrum": self._auto_from_spectrum,
            "supported_modes": list(SUPPORTED_MODES),
            "mode_catalog": list_modes(),
            "queue_len": len(self._queue),
            "error": self._error,
            "current": self._job_dict(self._current) if self._current else None,
            "queue": [self._job_dict(j) for j in self._queue[:20]],
            "recent": [self._job_dict(j) for j in self._history[:30]],
        }

    def _job_dict(self, job: DecodeJob) -> dict[str, Any]:
        d = asdict(job)
        return d

    def configure(self, *, auto_from_spectrum: bool | None = None, device_id: str | None = None) -> None:
        with self._lock:
            if auto_from_spectrum is not None:
                self._auto_from_spectrum = bool(auto_from_spectrum)
            if device_id is not None:
                self._device_id = validate_device_id(device_id)

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return self._status_unlocked()
            device = self._pick_decode_device_unlocked()
            if not device:
                self._error = "No device with role=decode"
                return self._status_unlocked()
            self._device_id = device["id"]
            self._error = None
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="decode-worker", daemon=True)
            self._thread.start()
            device_id = self._device_id
        add_event(
            "decode_start",
            f"Decode worker started on {device_id}",
            source=device_id,
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
            if thread is not None and thread.is_alive():
                self._error = "Decode worker still stopping (SDR tool busy)"
            else:
                self._running = False
                self._thread = None
        add_event("decode_stop", f"Decode worker stopped ({device_id})", source=device_id)
        return self.status()

    def enqueue(
        self,
        freq_mhz: float,
        mode: str = "auto",
        *,
        duration_s: float = 8.0,
        device_id: str | None = None,
    ) -> DecodeJob:
        mode = (mode or "auto").lower().strip()
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"mode must be one of {SUPPORTED_MODES}")
        freq_mhz = clamp_freq_mhz(freq_mhz)
        duration_s = clamp_duration_s(duration_s)
        device_id = validate_device_id(device_id)
        job = DecodeJob(
            id=str(uuid.uuid4())[:8],
            freq_mhz=freq_mhz,
            mode=mode,
            status="queued",
            device_id=device_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            duration_s=duration_s,
        )
        with self._lock:
            if len(self._queue) >= self.MAX_QUEUE:
                raise ValueError(f"decode queue full (max {self.MAX_QUEUE})")
            self._queue.append(job)
        add_event(
            "decode_queued",
            f"Queued {mode} decode @ {freq_mhz} MHz",
            source=device_id or self._device_id,
            freq_hz=freq_mhz * 1e6,
            mode=mode,
            meta={"job_id": job.id},
        )
        return job

    def maybe_queue_from_peak(self, freq_mhz: float, mode_hint: str) -> None:
        if not self._auto_from_spectrum:
            return
        with self._lock:
            if not self._running:
                return
            # Avoid duplicates already queued/running for nearby freq
            for j in self._queue + ([self._current] if self._current else []):
                if j and abs(j.freq_mhz - freq_mhz) < 0.05 and j.status in ("queued", "running"):
                    return
        mode = hint_to_mode(mode_hint, freq_mhz)
        if not mode:
            return
        self.enqueue(freq_mhz, mode=mode, duration_s=6.0)

    def _pick_decode_device_unlocked(self) -> dict[str, Any] | None:
        dedicated = require_role("decode")
        if dedicated:
            self._device_id = dedicated["id"]
            return dedicated
        return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = None
            with self._lock:
                if self._queue:
                    job = self._queue.pop(0)
                    job.status = "running"
                    job.started_at = datetime.now(timezone.utc).isoformat()
                    job.device_id = job.device_id or self._device_id
                    self._current = job
            if not job:
                self._stop.wait(0.5)
                continue
            try:
                result = self._run_job(job)
                with self._lock:
                    job.result = result
                    job.status = "done"
                    job.finished_at = datetime.now(timezone.utc).isoformat()
                    job.error = None
                    self._history.insert(0, job)
                    self._history = self._history[:100]
                    self._current = None
                self._log_result(job)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    job.status = "error"
                    job.error = str(exc)
                    job.finished_at = datetime.now(timezone.utc).isoformat()
                    self._history.insert(0, job)
                    self._history = self._history[:100]
                    self._current = None
                    self._error = str(exc)
                add_event(
                    "decode_error",
                    f"{job.mode} @ {job.freq_mhz} MHz failed: {exc}",
                    source=job.device_id,
                    freq_hz=job.freq_mhz * 1e6,
                    mode=job.mode,
                    meta={"job_id": job.id},
                )

    def _run_job(self, job: DecodeJob) -> DecodeResult:
        device = None
        devices = list_radio_devices()
        for d in devices:
            if d["id"] == (job.device_id or self._device_id):
                device = d
                break
        mode = resolve_mode(job.mode, job.freq_mhz)
        spec = MODE_BY_ID.get(mode)

        simulated = (
            not device
            or device["id"].startswith("demo-")
            or device.get("status") == "simulated"
        )
        if simulated:
            time.sleep(min(job.duration_s, 1.6))
            return self._demo_result(mode, job.freq_mhz)

        backend = spec.backend if spec else "demo"
        if backend == "multimon":
            return self._run_multimon(job, mode)
        if backend == "dsd":
            return self._run_dsd(job, mode)
        time.sleep(min(job.duration_s, 1.2))
        return self._demo_result(mode, job.freq_mhz)

    def _demo_result(self, mode: str, freq_mhz: float) -> DecodeResult:
        if mode in ("pocsag", "flex"):
            return DecodeResult(
                mode=mode,
                text=random.choice(["TEST PAGE - Pi-Spy-RF", "ALPHA: GATE 3", "STATUS OK"]),
                capcode=str(random.randint(100000, 999999)),
                raw=f"DEMO {mode.upper()}",
            )
        if mode in ("eas", "afsk1200", "morse", "dtmf"):
            samples = {
                "eas": "ZCZC-WXR-SVR-022019+0100-1012000-Kxxx-",
                "afsk1200": "N0CALL>APRS:!3012.00N/09312.00W-",
                "morse": "CQ CQ DE N0CALL",
                "dtmf": "1 2 3 #",
            }
            return DecodeResult(mode=mode, text=samples.get(mode, "demo"), raw="demo "+mode)
        if mode == "dmr":
            return DecodeResult(
                mode="dmr",
                color_code=random.randint(1, 15),
                timeslot=random.choice([1, 2]),
                talkgroup=random.choice([9, 91, 3100, 31000]),
                radio_id=random.randint(1000001, 1999999),
                text="Demo DMR grant",
                encrypted=False,
            )
        if mode in ("p25", "p25p2"):
            return DecodeResult(
                mode=mode,
                nac=f"0x{random.randint(0x293, 0x6F0):03X}",
                timeslot=1 if mode == "p25p2" else None,
                talkgroup=random.choice([1, 100, 2001]),
                radio_id=random.randint(10000, 99999),
                text="Demo P25 group voice",
            )
        if mode in ("nxdn", "nxdn48", "nxdn96"):
            return DecodeResult(
                mode=mode,
                ran=random.randint(1, 15),
                talkgroup=random.randint(1, 200),
                radio_id=random.randint(1000, 9999),
                text="Demo NXDN",
            )
        if mode == "dstar":
            return DecodeResult(mode=mode, callsign="N0CALL", text="Demo D-STAR header")
        if mode == "ysf":
            return DecodeResult(mode=mode, callsign="N0CALL", dgid=random.randint(0, 99), text="Demo YSF")
        if mode == "dpmr":
            return DecodeResult(mode=mode, radio_id=random.randint(1, 999), talkgroup=1, text="Demo dPMR")
        if mode == "m17":
            return DecodeResult(mode=mode, callsign="N0CALL", text="Demo M17")
        if mode == "tetra":
            return DecodeResult(
                mode=mode,
                color_code=random.randint(1, 63),
                timeslot=random.choice([1, 2, 3, 4]),
                talkgroup=random.randint(1, 20000),
                text="Demo TETRA metadata (install osmo-tetra/telive for live decode)",
            )
        return DecodeResult(mode=mode, text="Demo decode", raw="demo")

    def _run_multimon(self, job: DecodeJob, mode: str) -> DecodeResult:
        if not shutil.which("rtl_fm") or not shutil.which("multimon-ng"):
            return self._demo_result(mode, job.freq_mhz)
        freq_hz = int(job.freq_mhz * 1e6)
        demod = {
            "pocsag": "POCSAG512",
            "flex": "FLEX",
            "eas": "EAS",
            "afsk1200": "AFSK1200",
            "morse": "MORSE_CW",
            "dtmf": "DTMF",
        }.get(mode, "POCSAG512")
        rtl = subprocess.Popen(
            ["rtl_fm", "-f", str(freq_hz), "-s", "22050", "-g", "20"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            mm = subprocess.run(
                ["multimon-ng", "-a", demod, "-t", "raw", "-q", "-"],
                stdin=rtl.stdout,
                capture_output=True,
                text=True,
                timeout=job.duration_s,
                check=False,
            )
            text = (mm.stdout or "").strip() or None
            return DecodeResult(mode=mode, text=text, raw=(mm.stdout or "")[:4000])
        except subprocess.TimeoutExpired as exc:
            out = ""
            if exc.stdout:
                out = exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="ignore")
            return DecodeResult(mode=mode, text=out.strip() or None, raw=out[:4000])
        finally:
            rtl.kill()
            try:
                rtl.wait(timeout=2)
            except Exception:
                pass

    def _run_dsd(self, job: DecodeJob, mode: str) -> DecodeResult:
        """Live path when dsd-fme/dsd + rtl_fm exist. Encrypted frames are flagged only."""
        bin_name = shutil.which("dsd-fme") or shutil.which("dsd")
        if not bin_name or not shutil.which("rtl_fm"):
            return self._demo_result(mode, job.freq_mhz)
        freq_hz = int(job.freq_mhz * 1e6)
        rtl = subprocess.Popen(
            ["rtl_fm", "-f", str(freq_hz), "-s", "48000", "-g", "20"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        args = [bin_name, "-i", "-", "-n"]
        try:
            proc = subprocess.run(
                args,
                stdin=rtl.stdout,
                capture_output=True,
                text=True,
                timeout=job.duration_s,
                check=False,
            )
            raw = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[:4000]
            return self._parse_dsd_text(mode, raw)
        except subprocess.TimeoutExpired as exc:
            raw = ""
            if exc.stdout:
                raw = exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode(errors="ignore")
            return self._parse_dsd_text(mode, raw)
        finally:
            rtl.kill()
            try:
                rtl.wait(timeout=2)
            except Exception:
                pass

    def _parse_dsd_text(self, mode: str, raw: str) -> DecodeResult:
        import re

        low = raw.lower()
        enc = bool(
            re.search(r"(?m)^\s*(encrypted|encryption|enc\s*[:=])", low)
            or "encrypted" in low
            or "privacy" in low and "on" in low
        )
        def grab(patterns):
            for pat in patterns:
                m = re.search(pat, raw, re.I)
                if m:
                    return m.group(1)
            return None

        cc = grab([r"CC[:\s]+(\d+)", r"color code[:\s]+(\d+)"])
        ts = grab([r"TS[:\s]+(\d)", r"slot[:\s]+(\d)"])
        tg = grab([r"TG[:\s]+(\d+)", r"talkgroup[:\s]+(\d+)"])
        rid = grab([r"RID[:\s]+(\d+)", r"src[:\s]+(\d+)", r"radio[:\s]+(\d+)"])
        nac = grab([r"NAC[:\s]+([0-9A-Fx]+)"])
        ran = grab([r"RAN[:\s]+(\d+)"])
        call = grab([r"([A-Z0-9]{3,7}/[A-Z0-9]{3,7})", r"callsign[:\s]+([A-Z0-9/]+)"])
        return DecodeResult(
            mode=mode,
            color_code=int(cc) if cc and cc.isdigit() else None,
            timeslot=int(ts) if ts and ts.isdigit() else None,
            talkgroup=int(tg) if tg and tg.isdigit() else None,
            radio_id=int(rid) if rid and rid.isdigit() else None,
            nac=nac,
            ran=int(ran) if ran and ran.isdigit() else None,
            callsign=call,
            encrypted=enc,
            text=("ENCRYPTED — not decoded" if enc else (raw.strip()[:200] or None)),
            raw=raw,
        )

    def _log_result(self, job: DecodeJob) -> None:
        r = job.result
        if not r:
            return
        bits = [f"{r.mode.upper()} @ {job.freq_mhz} MHz"]
        if r.encrypted:
            bits.append("ENCRYPTED")
        if r.color_code is not None:
            bits.append(f"CC={r.color_code}")
        if r.timeslot is not None:
            bits.append(f"TS={r.timeslot}")
        if r.talkgroup is not None:
            bits.append(f"TG={r.talkgroup}")
        if r.radio_id is not None:
            bits.append(f"RID={r.radio_id}")
        if r.nac:
            bits.append(f"NAC={r.nac}")
        if r.ran is not None:
            bits.append(f"RAN={r.ran}")
        if r.callsign:
            bits.append(r.callsign)
        if r.dgid is not None:
            bits.append(f"DGID={r.dgid}")
        if r.text and r.mode not in ("dmr", "p25", "p25p2", "nxdn"):
            bits.append(r.text[:60])
        summary = " ".join(bits)
        add_event(
            "decode_hit",
            summary,
            source=job.device_id,
            freq_hz=job.freq_mhz * 1e6,
            mode=r.mode,
            meta=asdict(r) | {"job_id": job.id},
        )


decode_worker = DecodeWorker()