"""Band plan classification and the spectrum-hint -> decode-mode chain."""
from __future__ import annotations

import pytest

from app.core.bandplan import BANDS, classify_mhz, list_bands
from app.core.modes import MODE_BY_ID, hint_to_mode, resolve_mode


def test_known_bands_classify():
    assert classify_mhz(98.5)["mode_hint"] == "analog_fm"
    assert classify_mhz(121.5)["mode_hint"] == "analog_am"
    assert classify_mhz(930.5)["mode_hint"] == "pocsag"
    assert classify_mhz(800.0)["mode_hint"] == "p25"


def test_outside_plan_is_unknown():
    got = classify_mhz(70.0)
    assert got["mode_hint"] == "unknown"
    assert got["bands"] == []


def test_noaa_weather_window():
    assert classify_mhz(162.44)["mode_hint"] == "noaa_wx"
    # Edges are inclusive.
    assert classify_mhz(162.4)["mode_hint"] == "noaa_wx"
    assert classify_mhz(162.55)["mode_hint"] == "noaa_wx"


def test_every_band_hint_is_routable_or_deliberately_analog():
    """Each band hint should either map to a real mode or be a known analog hint."""
    analog = {
        "analog_fm", "analog_am", "noaa_apt", "marine",
        "ham_vhf", "ham_uhf", "gmrs", "ism", "mil_air",
    }
    for band in BANDS:
        mode = hint_to_mode(band.mode_hint, band.start_mhz + 0.01)
        assert mode is None or mode in MODE_BY_ID, band
        if mode is None:
            assert band.mode_hint in analog, (
                f"band {band.name!r} has hint {band.mode_hint!r} that routes nowhere"
            )


@pytest.mark.parametrize("freq", [144.5, 146.52, 147.9])
def test_2m_digital_hint_band_is_reachable(freq):
    """The '2m DMR / YSF / D-STAR (hint)' band should be able to win a match.

    It has the same width as '2m Ham', so min(width) tie-breaks to whichever
    entry appears first in BANDS and the digital hint is never selected.
    """
    assert classify_mhz(freq)["mode_hint"] == "dmr"


@pytest.mark.parametrize("freq", [421.0, 435.0, 449.0])
def test_70cm_digital_hint_band_is_reachable(freq):
    assert classify_mhz(freq)["mode_hint"] == "dmr"


@pytest.mark.parametrize("freq", [463.0, 466.0])
def test_uhf_business_digital_band_is_reachable(freq):
    """GMRS (462-467, width 5) fully shadows UHF business NXDN (450-470)."""
    assert classify_mhz(freq)["mode_hint"] == "nxdn"


def test_auto_decode_triggers_on_ham_digital_bands():
    """End-to-end: a peak on 2m/70cm should produce an auto-decode mode."""
    for freq in (146.52, 435.0):
        hint = classify_mhz(freq)["mode_hint"]
        assert hint_to_mode(hint, freq) is not None, (
            f"no auto-decode queued for a peak at {freq} MHz (hint={hint})"
        )


def test_resolve_mode_explicit_and_auto():
    assert resolve_mode("pocsag") == "pocsag"
    assert resolve_mode("nonsense") == "auto"
    assert resolve_mode("auto", 930.0) == "pocsag"
    assert resolve_mode("auto", 162.45) == "eas"
    assert resolve_mode("auto", 800.0) == "p25"


def test_resolve_mode_and_bandplan_agree_on_noaa():
    """modes.resolve_mode and bandplan must not disagree about the same freq."""
    for freq in (162.40, 162.45, 162.55):
        assert resolve_mode("auto", freq) == "eas"
        assert classify_mhz(freq)["mode_hint"] == "noaa_wx"


def test_list_bands_serialisable():
    bands = list_bands()
    assert bands and all(
        {"name", "start_mhz", "end_mhz", "mode_hint"} <= set(b) for b in bands
    )
    for b in bands:
        assert b["start_mhz"] < b["end_mhz"], b
