from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.bandplan import classify_mhz, list_bands
from app.core.balance import assignments, assign_exclusive, auto_balance
from app.core.db import add_event, list_events
from app.core.decode import decode_worker
from app.core.modes import SUPPORTED_MODES, list_modes
from app.core.devices import VALID_ROLES, host_info, list_radio_devices, list_tools
from app.core.mac_db import (
    delete_known_mac,
    load_known_macs,
    lookup_oui,
    upsert_known_mac,
)
from app.core.spectrum import spectrum_worker
from app.core.wireless import list_wireless, wireless_worker

router = APIRouter(prefix="/api")


class RoleUpdate(BaseModel):
    role: str


class ClassifyRequest(BaseModel):
    freq_mhz: float


class EventCreate(BaseModel):
    kind: str
    summary: str
    source: str | None = None
    freq_hz: float | None = None
    mode: str | None = None
    meta: dict | None = None


class SpectrumConfig(BaseModel):
    start_mhz: float | None = None
    end_mhz: float | None = None
    step_mhz: float | None = None
    interval_s: float | None = None
    threshold_db: float | None = None
    device_id: str | None = None


class DecodeConfig(BaseModel):
    auto_from_spectrum: bool | None = None
    device_id: str | None = None


class DecodeEnqueue(BaseModel):
    freq_mhz: float
    mode: str = "auto"
    duration_s: float = 8.0


class WirelessConfig(BaseModel):
    interval_s: float | None = None
    wifi_enabled: bool | None = None
    bt_enabled: bool | None = None


class KnownMac(BaseModel):
    mac: str
    name: str
    type: str = "unknown"
    notes: str = ""


@router.get("/health")
def health():
    return {"ok": True, "service": "pi-spy-rf", "version": "0.7.0"}


@router.get("/host")
def host():
    return host_info()


@router.get("/tools")
def tools():
    return list_tools()


@router.get("/devices")
def devices():
    return {"devices": list_radio_devices(), "roles": list(VALID_ROLES)}


@router.put("/devices/{device_id}/role")
def update_device_role(device_id: str, body: RoleUpdate):
    role = body.role.strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(400, f"role must be one of {VALID_ROLES}")
    try:
        plan = assign_exclusive(device_id, role)
    except KeyError:
        raise HTTPException(404, f"unknown device_id: {device_id}") from None
    return {"ok": True, "device_id": device_id, "role": role, "plan": plan}


@router.get("/devices/balance")
def devices_balance():
    from app.core.decode import decode_worker
    from app.core.spectrum import spectrum_worker

    plan = assignments()
    spec = spectrum_worker.status()
    dec = decode_worker.status()
    plan["busy"] = {
        "scan": spec.get("device_id") if spec.get("running") else None,
        "decode": dec.get("device_id") if dec.get("running") else None,
    }
    return plan


@router.post("/devices/balance")
def devices_balance_apply():
    from app.core.decode import decode_worker
    from app.core.spectrum import spectrum_worker

    plan = auto_balance()
    spec = spectrum_worker.status()
    dec = decode_worker.status()
    plan["busy"] = {
        "scan": spec.get("device_id") if spec.get("running") else None,
        "decode": dec.get("device_id") if dec.get("running") else None,
    }
    return plan


@router.get("/bands")
def bands():
    return {"bands": list_bands()}


@router.post("/bands/classify")
def bands_classify(body: ClassifyRequest):
    return classify_mhz(body.freq_mhz)


@router.get("/spectrum")
def spectrum_status():
    return spectrum_worker.status()


@router.post("/spectrum/config")
def spectrum_config(body: SpectrumConfig):
    spectrum_worker.configure(**body.model_dump(exclude_none=True))
    return spectrum_worker.status()


@router.post("/spectrum/start")
def spectrum_start(body: SpectrumConfig | None = None):
    if body:
        spectrum_worker.configure(**body.model_dump(exclude_none=True))
    return spectrum_worker.start()


@router.post("/spectrum/stop")
def spectrum_stop():
    return spectrum_worker.stop()


@router.get("/decode/modes")
def decode_modes():
    return {"modes": list_modes()}


@router.get("/decode")
def decode_status():
    return decode_worker.status()


@router.post("/decode/config")
def decode_config(body: DecodeConfig):
    decode_worker.configure(**body.model_dump(exclude_none=True))
    return decode_worker.status()


@router.post("/decode/start")
def decode_start(body: DecodeConfig | None = None):
    if body:
        decode_worker.configure(**body.model_dump(exclude_none=True))
    return decode_worker.start()


@router.post("/decode/stop")
def decode_stop():
    return decode_worker.stop()


@router.post("/decode/enqueue")
def decode_enqueue(body: DecodeEnqueue):
    mode = body.mode.lower().strip()
    if mode not in SUPPORTED_MODES:
        raise HTTPException(400, f"mode must be one of {SUPPORTED_MODES}")
    try:
        job = decode_worker.enqueue(body.freq_mhz, mode=mode, duration_s=body.duration_s)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "job": {
            "id": job.id,
            "freq_mhz": job.freq_mhz,
            "mode": job.mode,
            "status": job.status,
            "created_at": job.created_at,
        },
    }


@router.get("/wireless")
def wireless_status():
    return wireless_worker.status()


@router.post("/wireless/config")
def wireless_config(body: WirelessConfig):
    wireless_worker.configure(**body.model_dump(exclude_none=True))
    return wireless_worker.status()


@router.post("/wireless/start")
def wireless_start(body: WirelessConfig | None = None):
    if body:
        wireless_worker.configure(**body.model_dump(exclude_none=True))
    return wireless_worker.start()


@router.post("/wireless/stop")
def wireless_stop():
    return wireless_worker.stop()


@router.get("/wireless/devices")
def wireless_devices(kind: str | None = None, limit: int = 100):
    if kind and kind not in ("wifi", "bluetooth"):
        raise HTTPException(400, "kind must be wifi or bluetooth")
    return {"devices": list_wireless(kind, limit)}


@router.get("/events")
def events(limit: int = 50):
    limit = max(1, min(limit, 200))
    return {"events": list_events(limit)}


@router.post("/events")
def create_event(body: EventCreate):
    event_id = add_event(
        body.kind,
        body.summary,
        source=body.source,
        freq_hz=body.freq_hz,
        mode=body.mode,
        meta=body.meta,
    )
    return {"ok": True, "id": event_id}


@router.get("/macs/known")
def known_macs():
    return load_known_macs()


@router.post("/macs/known")
def known_macs_upsert(body: KnownMac):
    try:
        data = upsert_known_mac(body.mac, body.name, body.type, body.notes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    add_event("mac_known_upsert", f"Known MAC {body.mac} -> {body.name}", meta=body.model_dump())
    return data


@router.delete("/macs/known/{mac}")
def known_macs_delete(mac: str):
    try:
        data = delete_known_mac(mac)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    add_event("mac_known_delete", f"Removed known MAC {mac}", meta={"mac": mac})
    return data


@router.get("/macs/lookup/{mac}")
def mac_lookup(mac: str):
    vendor = lookup_oui(mac)
    known = load_known_macs().get("devices", [])
    match = next((d for d in known if d.get("mac", "").upper() == mac.upper()), None)
    return {"mac": mac, "vendor": vendor, "known": match}