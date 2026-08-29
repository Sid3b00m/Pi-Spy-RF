"""Input clamps, identifier validation, and the login rate limiter."""
from __future__ import annotations

import pytest

from app.core.security import (
    DECODE_DURATION_MAX,
    DECODE_DURATION_MIN,
    INTERVAL_S_MAX,
    INTERVAL_S_MIN,
    SPECTRUM_SPAN_MAX_MHZ,
    LoginRateLimiter,
    clamp_duration_s,
    clamp_freq_mhz,
    clamp_interval_s,
    clamp_spectrum_range,
    validate_device_id,
    validate_iface,
)


def test_freq_in_range_passes():
    assert clamp_freq_mhz(162.4) == 162.4


@pytest.mark.parametrize("bad", [0.0, 0.999, 6000.1, 1e9, -5])
def test_freq_out_of_range_rejected(bad):
    with pytest.raises(ValueError):
        clamp_freq_mhz(bad)


def test_duration_clamps_rather_than_raises():
    assert clamp_duration_s(0.1) == DECODE_DURATION_MIN
    assert clamp_duration_s(9999) == DECODE_DURATION_MAX
    assert clamp_duration_s(8.0) == 8.0


def test_interval_clamps():
    assert clamp_interval_s(0) == INTERVAL_S_MIN
    assert clamp_interval_s(99999) == INTERVAL_S_MAX


def test_spectrum_range_ok():
    assert clamp_spectrum_range(140.0, 170.0) == (140.0, 170.0)


def test_spectrum_range_rejects_inverted():
    with pytest.raises(ValueError):
        clamp_spectrum_range(170.0, 140.0)
    with pytest.raises(ValueError):
        clamp_spectrum_range(150.0, 150.0)


def test_spectrum_range_rejects_oversized_span():
    with pytest.raises(ValueError):
        clamp_spectrum_range(100.0, 100.0 + SPECTRUM_SPAN_MAX_MHZ + 1)


def test_spectrum_range_at_exact_span_limit_allowed():
    start, end = clamp_spectrum_range(100.0, 100.0 + SPECTRUM_SPAN_MAX_MHZ)
    assert end - start == SPECTRUM_SPAN_MAX_MHZ


@pytest.mark.parametrize("good", ["wlan0", "eth0", "wlp2s0", "wlan0.10"])
def test_iface_accepts_real_names(good):
    assert validate_iface(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "  ",
        "0wlan",
        "wlan0; rm -rf /",
        "wlan0 && id",
        "$(id)",
        "../../etc/passwd",
        "a" * 40,
        "wlan0|cat",
    ],
)
def test_iface_rejects_injection_and_junk(bad):
    """iface is interpolated into an `iw dev <iface> scan` argv."""
    with pytest.raises(ValueError):
        validate_iface(bad)


@pytest.mark.parametrize("good", ["rtl-0", "hackrf-0", "soapy-1", "demo-rtl-0", "a:b.c_1"])
def test_device_id_accepts_generated_ids(good):
    assert validate_device_id(good) == good


def test_device_id_empty_is_none():
    assert validate_device_id(None) is None
    assert validate_device_id("") is None


@pytest.mark.parametrize("bad", ["rtl 0", "rtl;0", "../x", "a" * 65, "rtl/0", "rtl$0"])
def test_device_id_rejects_junk(bad):
    with pytest.raises(ValueError):
        validate_device_id(bad)


def test_rate_limiter_blocks_after_max_attempts():
    rl = LoginRateLimiter(max_attempts=3, window_s=300.0)
    assert rl.allow("1.2.3.4")
    assert rl.allow("1.2.3.4")
    assert rl.allow("1.2.3.4")
    assert not rl.allow("1.2.3.4")


def test_rate_limiter_is_per_key():
    rl = LoginRateLimiter(max_attempts=2, window_s=300.0)
    assert rl.allow("a") and rl.allow("a") and not rl.allow("a")
    assert rl.allow("b"), "one client must not exhaust another client's budget"


def test_rate_limiter_window_expiry(monkeypatch):
    import app.core.security as sec

    now = [1000.0]
    monkeypatch.setattr(sec.time, "time", lambda: now[0])
    rl = sec.LoginRateLimiter(max_attempts=2, window_s=60.0)
    assert rl.allow("k") and rl.allow("k")
    assert not rl.allow("k")
    now[0] += 61.0
    assert rl.allow("k"), "attempts should age out of the window"
