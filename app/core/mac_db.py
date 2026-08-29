from __future__ import annotations

import json
import re
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import ROOT, get_config

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}([-:])){5}[0-9A-Fa-f]{2}$")

# Wireless enrichment hits both tables once per device per scan cycle, and the
# OUI table is meant to be swapped for the full Wireshark manuf list (~50k
# lines), so both are cached and revalidated against the file's mtime/size.
_cache_lock = Lock()
_oui_cache: dict[str, Any] = {"stamp": None, "table": {}}
_known_cache: dict[str, Any] = {"stamp": None, "data": None}


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _parse_oui_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split()
    if not parts:
        return None
    # Wireshark manuf prefixes may carry a bit-mask suffix, e.g. B8:27:EB/28.
    oui = parts[0].split("/", 1)[0].upper().replace("-", ":")
    if len(oui) < 8:
        return None
    vendor = " ".join(parts[1:]) if len(parts) > 1 else oui
    return oui[:8], vendor


def _oui_table(path: Path) -> dict[str, str]:
    stamp = _stamp(path)
    if stamp is None:
        return {}
    with _cache_lock:
        if _oui_cache["stamp"] == stamp:
            return _oui_cache["table"]
    table: dict[str, str] = {}
    with path.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            parsed = _parse_oui_line(line)
            if parsed:
                table.setdefault(parsed[0], parsed[1])
    with _cache_lock:
        _oui_cache["stamp"] = stamp
        _oui_cache["table"] = table
    return table


def _invalidate_known_cache() -> None:
    with _cache_lock:
        _known_cache["stamp"] = None
        _known_cache["data"] = None


def _known_path() -> Path:
    cfg = get_config()
    rel = cfg.mac_db.get("known_path", "data/known_macs.json")
    path = Path(rel)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            json.dumps(
                {
                    "note": "Local known WiFi/Bluetooth MACs for identification. Not a global database.",
                    "devices": [
                        {
                            "mac": "AA:BB:CC:DD:EE:FF",
                            "name": "Example phone",
                            "type": "bluetooth",
                            "notes": "Replace with your devices",
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return path


def load_known_macs() -> dict[str, Any]:
    path = _known_path()
    stamp = _stamp(path)
    with _cache_lock:
        if stamp is not None and _known_cache["stamp"] == stamp:
            return _known_cache["data"]
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    with _cache_lock:
        _known_cache["stamp"] = stamp
        _known_cache["data"] = data
    return data


def save_known_macs(data: dict[str, Any]) -> dict[str, Any]:
    path = _known_path()
    devices = data.get("devices", [])
    if not isinstance(devices, list):
        raise ValueError("devices must be a list")
    cleaned = []
    for d in devices:
        mac = str(d.get("mac", "")).strip().upper().replace("-", ":")
        if not _MAC_RE.match(mac):
            raise ValueError(f"invalid mac: {d.get('mac')}")
        cleaned.append(
            {
                "mac": mac,
                "name": str(d.get("name") or "").strip() or mac,
                "type": str(d.get("type") or "unknown").strip().lower(),
                "notes": str(d.get("notes") or "").strip(),
            }
        )
    out = {
        "note": data.get("note")
        or "Local known WiFi/Bluetooth MACs for identification. Not a global database.",
        "devices": cleaned,
    }
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    _invalidate_known_cache()
    return out


def _load_known_uncached() -> dict[str, Any]:
    """Editors must not mutate the shared cached document in place."""
    with _known_path().open(encoding="utf-8") as f:
        return json.load(f)


def upsert_known_mac(mac: str, name: str, type_: str = "unknown", notes: str = "") -> dict[str, Any]:
    data = _load_known_uncached()
    mac_n = mac.strip().upper().replace("-", ":")
    if not _MAC_RE.match(mac_n):
        raise ValueError(f"invalid mac: {mac}")
    devices = data.get("devices", [])
    found = False
    for d in devices:
        if str(d.get("mac", "")).upper().replace("-", ":") == mac_n:
            d["mac"] = mac_n
            d["name"] = name
            d["type"] = type_
            d["notes"] = notes
            found = True
            break
    if not found:
        devices.append({"mac": mac_n, "name": name, "type": type_, "notes": notes})
    data["devices"] = devices
    return save_known_macs(data)


def delete_known_mac(mac: str) -> dict[str, Any]:
    data = _load_known_uncached()
    mac_n = mac.strip().upper().replace("-", ":")
    data["devices"] = [
        d
        for d in data.get("devices", [])
        if str(d.get("mac", "")).upper().replace("-", ":") != mac_n
    ]
    return save_known_macs(data)


def lookup_oui(mac: str) -> str | None:
    """Best-effort OUI vendor lookup if data/oui.txt is present (Wireshark manuf format)."""
    cfg = get_config()
    rel = cfg.mac_db.get("oui_path", "data/oui.txt")
    path = Path(rel)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return None
    clean = mac.upper().replace("-", ":")
    return _oui_table(path).get(clean[:8])


def ensure_mini_oui() -> Path:
    """Seed a tiny OUI file for demos if missing (not a full IEEE DB)."""
    cfg = get_config()
    rel = cfg.mac_db.get("oui_path", "data/oui.txt")
    path = Path(rel)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "\n".join(
                [
                    "# Mini OUI seed for Pi-Spy-RF demos. Replace with Wireshark manuf for full coverage.",
                    "B8:27:EB Raspberry Pi Foundation",
                    "DC:A6:32 Raspberry Pi Trading",
                    "E4:5F:01 Raspberry Pi Trading",
                    "F0:9F:C2 Ubiquiti Networks",
                    "A4:C1:38 Espressif Inc.",
                    "00:11:22 Cimsys / demo",
                    "AA:BB:CC Local demo OUI",
                    "62:45:B1 Randomized / locally administered",
                    "11:22:33 Locally administered demo",
                    "DE:AD:BE Demo tracker OUI",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    return path