from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

from app.core.db import get_device_roles


VALID_ROLES = ("scan", "decode", "wifi", "bluetooth", "idle")


@dataclass
class RadioDevice:
    id: str
    type: str
    name: str
    serial: str | None
    status: str
    role: str = "idle"
    detail: str = ""


def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def _detect_rtl() -> list[RadioDevice]:
    devices: list[RadioDevice] = []
    if not shutil.which("rtl_test"):
        return devices
    code, out, err = _run(["rtl_test",
        "rtl_power", "-t"], timeout=8.0)
    text = out + "\n" + err
    for m in re.finditer(r"(\d+):\s+(.+?),\s+SN:\s*(\S+)", text):
        idx, name, serial = m.group(1), m.group(2).strip(), m.group(3)
        devices.append(
            RadioDevice(
                id=f"rtl-{idx}",
                type="rtl-sdr",
                name=name,
                serial=serial,
                status="online" if code in (0, 1) else "detected",
                role="scan",
                detail="Enumerated via rtl_test",
            )
        )
    return devices


def _detect_hackrf() -> list[RadioDevice]:
    devices: list[RadioDevice] = []
    if not shutil.which("hackrf_info"):
        return devices
    code, out, err = _run(["hackrf_info"], timeout=8.0)
    text = out + "\n" + err
    if "No HackRF boards found" in text:
        return devices
    board = None
    serial = None
    for line in text.splitlines():
        if "Board ID Number" in line or "Board ID:" in line:
            board = line.split(":")[-1].strip()
        if "Serial number" in line or "Serial Number" in line:
            serial = line.split(":")[-1].strip()
    if board or serial or code == 0:
        devices.append(
            RadioDevice(
                id="hackrf-0",
                type="hackrf",
                name=f"HackRF One ({board or 'unknown board'})",
                serial=serial,
                status="online" if code == 0 else "detected",
                role="decode",
                detail="Enumerated via hackrf_info",
            )
        )
    return devices


def _detect_soapy() -> list[RadioDevice]:
    devices: list[RadioDevice] = []
    if not shutil.which("SoapySDRUtil"):
        return devices
    code, out, err = _run(["SoapySDRUtil", "--find"], timeout=10.0)
    text = out + "\n" + err
    if code != 0:
        return devices
    blocks = re.split(r"Found device\s+\d+", text)
    for i, block in enumerate(blocks[1:], start=0):
        driver = None
        label = None
        serial = None
        for line in block.splitlines():
            lower = line.lower()
            if "driver" in lower and "=" in line:
                driver = line.split("=", 1)[-1].strip()
            if "label" in lower and "=" in line:
                label = line.split("=", 1)[-1].strip()
            if "serial" in lower and "=" in line:
                serial = line.split("=", 1)[-1].strip()
        devices.append(
            RadioDevice(
                id=f"soapy-{i}",
                type=driver or "soapy",
                name=label or f"Soapy device {i}",
                serial=serial,
                status="online",
                role="idle",
                detail="Enumerated via SoapySDRUtil --find",
            )
        )
    return devices


def _demo_devices() -> list[RadioDevice]:
    """UI/dev placeholders when no SDR tools are installed (e.g. Windows build host)."""
    if os.environ.get("PI_SPY_NO_DEMO") == "1":
        return []
    if shutil.which("rtl_test") or shutil.which("hackrf_info") or shutil.which("SoapySDRUtil"):
        return []
    return [
        RadioDevice(
            id="demo-rtl-0",
            type="rtl-sdr",
            name="Demo RTL-SDR (no hardware)",
            serial="DEMO0001",
            status="simulated",
            role="scan",
            detail="Placeholder until rtl_test/hackrf_info are installed on this host",
        ),
        RadioDevice(
            id="demo-hackrf-0",
            type="hackrf",
            name="Demo HackRF One (no hardware)",
            serial="DEMO0002",
            status="simulated",
            role="decode",
            detail="Assign roles in the UI to exercise the device manager",
        ),
    ]


def list_tools() -> dict[str, bool]:
    names = [
        "rtl_test",
        "rtl_power",
        "rtl_fm",
        "hackrf_info",
        "hackrf_sweep",
        "SoapySDRUtil",
        "multimon-ng",
        "dsd",
        "op25",
        "dsd-fme",
        "kismet",
        "bluetoothctl",
        "iw",
        "nmcli",
    ]
    return {n: bool(shutil.which(n)) for n in names}


def list_radio_devices() -> list[dict[str, Any]]:
    found: list[RadioDevice] = []
    found.extend(_detect_rtl())
    found.extend(_detect_hackrf())
    found.extend(_detect_soapy())
    if not found:
        found.extend(_demo_devices())

    seen: set[str] = set()
    unique: list[RadioDevice] = []
    for d in found:
        key = d.serial or d.id
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)

    roles = get_device_roles()
    out: list[dict[str, Any]] = []
    for d in unique:
        item = asdict(d)
        if d.id in roles:
            item["role"] = roles[d.id]
        out.append(item)
    return out


def host_info() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "node": platform.node(),
    }