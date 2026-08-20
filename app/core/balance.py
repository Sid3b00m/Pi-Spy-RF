from __future__ import annotations

from typing import Any

from app.core.db import add_event, set_device_role
from app.core.devices import list_radio_devices

# One SDR owns wide scan; another owns parked decode. WiFi/BT are not SDR-exclusive.
EXCLUSIVE_ROLES = ("scan", "decode")


def assignments() -> dict[str, Any]:
    devices = list_radio_devices()
    by_role: dict[str, list[dict[str, Any]]] = {"scan": [], "decode": [], "wifi": [], "bluetooth": [], "idle": []}
    for d in devices:
        role = d.get("role") or "idle"
        by_role.setdefault(role, []).append(d)
    conflicts = {
        role: [d["id"] for d in by_role.get(role, [])]
        for role in EXCLUSIVE_ROLES
        if len(by_role.get(role, [])) > 1
    }
    return {
        "devices": devices,
        "scan": by_role.get("scan") or [],
        "decode": by_role.get("decode") or [],
        "idle": by_role.get("idle") or [],
        "ok": not conflicts,
        "conflicts": conflicts,
        "hint": "Use one stick for scan and a different stick for decode.",
    }


def assign_exclusive(device_id: str, role: str) -> dict[str, Any]:
    role = role.strip().lower()
    devices = list_radio_devices()
    ids = {d["id"] for d in devices}
    if device_id not in ids:
        raise KeyError(device_id)
    if role in EXCLUSIVE_ROLES:
        for d in devices:
            if d.get("role") == role and d["id"] != device_id:
                set_device_role(d["id"], "idle")
                add_event(
                    "device_role",
                    f"Preempted {d['id']} from {role} -> idle",
                    source=d["id"],
                    meta={"role": "idle", "reason": "exclusive"},
                )
    set_device_role(device_id, role)
    add_event("device_role", f"Set {device_id} role to {role}", source=device_id, meta={"role": role})
    return assignments()


def auto_balance() -> dict[str, Any]:
    """Prefer RTL for scan, HackRF for decode; otherwise first two unique sticks."""
    devices = list_radio_devices()
    if not devices:
        return {"ok": False, "error": "No radios detected", **assignments()}

    def pick(pred, exclude: set[str]) -> dict[str, Any] | None:
        for d in devices:
            if d["id"] in exclude:
                continue
            if pred(d):
                return d
        for d in devices:
            if d["id"] not in exclude:
                return d
        return None

    scan = pick(lambda d: "rtl" in (d.get("type") or "").lower() or "rtl" in d["id"], set())
    exclude = {scan["id"]} if scan else set()
    decode = pick(lambda d: "hackrf" in (d.get("type") or "").lower() or "hackrf" in d["id"], exclude)

    if scan:
        assign_exclusive(scan["id"], "scan")
    if decode and (not scan or decode["id"] != scan["id"]):
        assign_exclusive(decode["id"], "decode")
    elif scan and len(devices) == 1:
        # Single stick: scan only; decode stays idle until a second radio appears
        pass

    result = assignments()
    add_event(
        "sdr_balance",
        f"Auto-balance scan={[d['id'] for d in result['scan']]} decode={[d['id'] for d in result['decode']]}",
        meta={"scan": [d["id"] for d in result["scan"]], "decode": [d["id"] for d in result["decode"]]},
    )
    return result


def require_role(role: str) -> dict[str, Any] | None:
    devices = list_radio_devices()
    hits = [d for d in devices if d.get("role") == role]
    return hits[0] if hits else None
