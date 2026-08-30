from __future__ import annotations

import shutil

import pytest

from app.core import devices


# Real output from a HackRF One (firmware v2.1.0) reached over usbip.
HACKRF_INFO = """hackrf_info version: 2026.01.3
libhackrf version: 2026.01.3 (0.9.2)
Found HackRF
Index: 0
Serial number: 0000000000000000909864c82d4d69cf
Board ID Number: 2 (HackRF One)
Firmware Version: v2.1.0 (API:1.08)
Part ID Number: 0xa000cb3c 0x005c475f
Hardware Revision: older than r6
"""


def _fake_hackrf(monkeypatch: pytest.MonkeyPatch, output: str, code: int = 0) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda n: "/usr/bin/hackrf_info" if n == "hackrf_info" else None
    )
    monkeypatch.setattr(devices, "_run", lambda cmd, timeout=5.0: (code, output, ""))


def test_board_name_is_not_repeated(monkeypatch: pytest.MonkeyPatch) -> None:
    """hackrf_info says "2 (HackRF One)"; the label must not become
    "HackRF One (2 (HackRF One))"."""
    _fake_hackrf(monkeypatch, HACKRF_INFO)
    found = devices._detect_hackrf()
    assert len(found) == 1
    assert found[0].name == "HackRF One"
    assert found[0].serial == "0000000000000000909864c82d4d69cf"
    assert found[0].status == "online"
    assert found[0].id == "hackrf-0"


@pytest.mark.parametrize(
    ("board_line", "expected"),
    [
        ("Board ID Number: 2 (HackRF One)", "HackRF One"),
        ("Board ID Number: 4 (Jawbreaker)", "HackRF One (Jawbreaker)"),
        ("Board ID Number: 2", "HackRF One (2)"),
        ("Board ID Number:", "HackRF One (unknown board)"),
        ("Board ID Number: 9 ()", "HackRF One (unknown board)"),
    ],
)
def test_board_label_variants(
    monkeypatch: pytest.MonkeyPatch, board_line: str, expected: str
) -> None:
    _fake_hackrf(monkeypatch, f"Found HackRF\nSerial number: abc123\n{board_line}\n")
    found = devices._detect_hackrf()
    assert len(found) == 1
    assert found[0].name == expected


def test_serial_with_colons_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_hackrf(monkeypatch, "Serial number: a:b:c\nBoard ID Number: 2 (HackRF One)\n")
    assert devices._detect_hackrf()[0].serial == "a:b:c"


def test_no_board_found_returns_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_hackrf(monkeypatch, "No HackRF boards found.\n", code=1)
    assert devices._detect_hackrf() == []


def test_missing_tool_returns_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda n: None)
    assert devices._detect_hackrf() == []


def test_nonzero_exit_is_reported_as_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_hackrf(monkeypatch, HACKRF_INFO, code=1)
    found = devices._detect_hackrf()
    assert len(found) == 1
    assert found[0].status == "detected"
