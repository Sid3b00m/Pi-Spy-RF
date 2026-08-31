"""Input validation, rate limits, and HTTP hardening helpers."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from threading import Lock

# Typical SDR / HF-UHF-SHF practical bounds for this suite
FREQ_MHZ_MIN = 1.0
FREQ_MHZ_MAX = 6000.0
DECODE_DURATION_MIN = 2.0
DECODE_DURATION_MAX = 60.0
SPECTRUM_SPAN_MAX_MHZ = 200.0
INTERVAL_S_MIN = 1.0
INTERVAL_S_MAX = 300.0

_IFACE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,31}$")
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def clamp_freq_mhz(value: float) -> float:
    v = float(value)
    if v < FREQ_MHZ_MIN or v > FREQ_MHZ_MAX:
        raise ValueError(f"freq_mhz must be between {FREQ_MHZ_MIN} and {FREQ_MHZ_MAX}")
    return v


def clamp_duration_s(value: float) -> float:
    v = float(value)
    return max(DECODE_DURATION_MIN, min(DECODE_DURATION_MAX, v))


def clamp_spectrum_range(start_mhz: float, end_mhz: float) -> tuple[float, float]:
    start = clamp_freq_mhz(start_mhz)
    end = clamp_freq_mhz(end_mhz)
    if end <= start:
        raise ValueError("end_mhz must be greater than start_mhz")
    if (end - start) > SPECTRUM_SPAN_MAX_MHZ:
        raise ValueError(f"spectrum span must be <= {SPECTRUM_SPAN_MAX_MHZ} MHz")
    return start, end


def clamp_interval_s(value: float) -> float:
    return max(INTERVAL_S_MIN, min(INTERVAL_S_MAX, float(value)))


def validate_iface(name: str) -> str:
    iface = (name or "").strip()
    if not _IFACE_RE.match(iface):
        raise ValueError("invalid wifi interface name")
    return iface


def validate_device_id(device_id: str | None) -> str | None:
    if device_id is None or device_id == "":
        return None
    if not _DEVICE_ID_RE.match(device_id):
        raise ValueError("invalid device_id")
    return device_id


class LoginRateLimiter:
    """Simple in-memory login attempt limiter (per process)."""

    def __init__(self, max_attempts: int = 8, window_s: float = 300.0) -> None:
        self.max_attempts = max_attempts
        self.window_s = window_s
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            bucket = [t for t in self._hits[key] if now - t < self.window_s]
            self._hits[key] = bucket
            if len(bucket) >= self.max_attempts:
                return False
            bucket.append(now)
            self._hits[key] = bucket
            return True


login_limiter = LoginRateLimiter()


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        # The live audio stream is same-origin; no third-party media is ever loaded.
        "media-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}
