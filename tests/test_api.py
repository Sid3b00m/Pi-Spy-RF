"""HTTP contract: status codes, validation, and error mapping."""
from __future__ import annotations

import pytest


def test_health(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["service"] == "pi-spy-rf"


def test_health_version_matches_app_version(client):
    from app.main import app

    assert client.get("/api/health").json()["version"] == app.version


def test_dashboard_renders(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Pi-Spy-RF" in resp.text


def test_security_headers_applied(client):
    headers = client.get("/api/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "script-src 'self'" in headers["Content-Security-Policy"]


def test_devices_and_roles(client):
    body = client.get("/api/devices").json()
    assert body["devices"]
    assert "scan" in body["roles"] and "decode" in body["roles"]


def test_set_role_valid(client):
    device_id = client.get("/api/devices").json()["devices"][0]["id"]
    resp = client.put(f"/api/devices/{device_id}/role", json={"role": "decode"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "decode"


def test_set_role_invalid_is_400(client):
    device_id = client.get("/api/devices").json()["devices"][0]["id"]
    resp = client.put(f"/api/devices/{device_id}/role", json={"role": "hack-the-planet"})
    assert resp.status_code == 400


def test_set_role_unknown_device_is_404(client):
    resp = client.put("/api/devices/nope-0/role", json={"role": "scan"})
    assert resp.status_code == 404


def test_balance_endpoints(client):
    assert client.get("/api/devices/balance").status_code == 200
    applied = client.post("/api/devices/balance")
    assert applied.status_code == 200
    assert "busy" in applied.json()


@pytest.mark.parametrize(
    "payload",
    [
        {"start_mhz": 500, "end_mhz": 100},
        {"start_mhz": 100, "end_mhz": 900},
        {"start_mhz": 0.0001, "end_mhz": 2},
        {"start_mhz": 100, "end_mhz": 100},
    ],
)
def test_spectrum_config_invalid_is_400(client, payload):
    """Invalid config must be a client error, never a 500."""
    assert client.post("/api/spectrum/config", json=payload).status_code == 400


def test_spectrum_config_valid(client):
    resp = client.post(
        "/api/spectrum/config",
        json={"start_mhz": 160, "end_mhz": 170, "interval_s": 2, "threshold_db": -50},
    )
    assert resp.status_code == 200
    assert resp.json()["range_mhz"] == [160.0, 170.0]


def test_spectrum_start_with_bad_body_is_400(client):
    assert client.post("/api/spectrum/start", json={"start_mhz": 900, "end_mhz": 100}).status_code == 400


def test_spectrum_config_rejects_bad_device_id(client):
    resp = client.post("/api/spectrum/config", json={"device_id": "rtl 0; id"})
    assert resp.status_code == 400


def test_decode_modes_catalog(client):
    modes = client.get("/api/decode/modes").json()["modes"]
    ids = {m["id"] for m in modes}
    assert {"pocsag", "dmr", "p25", "nxdn", "eas"} <= ids


def test_decode_enqueue_invalid_mode_is_400(client):
    resp = client.post("/api/decode/enqueue", json={"freq_mhz": 162.4, "mode": "nope"})
    assert resp.status_code == 400


def test_decode_enqueue_out_of_range_freq_is_400(client):
    resp = client.post("/api/decode/enqueue", json={"freq_mhz": 99999, "mode": "pocsag"})
    assert resp.status_code == 400


def test_decode_enqueue_accepts_valid_job(client):
    resp = client.post("/api/decode/enqueue", json={"freq_mhz": 162.4, "mode": "eas"})
    assert resp.status_code == 200
    assert resp.json()["job"]["status"] == "queued"


def test_decode_queue_full_returns_429(client):
    from app.core.decode import decode_worker

    codes = []
    for _ in range(decode_worker.MAX_QUEUE + 5):
        codes.append(
            client.post("/api/decode/enqueue", json={"freq_mhz": 162.4, "mode": "eas"}).status_code
        )
    assert 429 in codes, "queue overflow should surface as 429, not 400/500"
    assert codes.count(200) == decode_worker.MAX_QUEUE


def test_wireless_devices_bad_kind_is_400(client):
    assert client.get("/api/wireless/devices?kind=bogus").status_code == 400


def test_wireless_devices_valid_kind(client):
    assert client.get("/api/wireless/devices?kind=wifi").status_code == 200


def test_events_limit_clamped(client):
    for i in range(5):
        client.post("/api/events", json={"kind": "t", "summary": f"s{i}"})
    assert client.get("/api/events?limit=99999").status_code == 200
    assert client.get("/api/events?limit=-5").status_code == 200


def test_create_event_requires_fields(client):
    assert client.post("/api/events", json={"kind": "", "summary": ""}).status_code == 400
    assert client.post("/api/events", json={"kind": "k", "summary": ""}).status_code == 400


def test_create_event_truncates_long_input(client):
    resp = client.post("/api/events", json={"kind": "k" * 500, "summary": "s" * 5000})
    assert resp.status_code == 200
    newest = client.get("/api/events?limit=1").json()["events"][0]
    assert len(newest["kind"]) <= 64
    assert len(newest["summary"]) <= 500


def test_mac_crud_via_api(client):
    resp = client.post("/api/macs/known", json={"mac": "AA:BB:CC:DD:EE:07", "name": "Test"})
    assert resp.status_code == 200
    assert any(d["mac"] == "AA:BB:CC:DD:EE:07" for d in client.get("/api/macs/known").json()["devices"])
    assert client.delete("/api/macs/known/AA:BB:CC:DD:EE:07").status_code == 200


def test_mac_invalid_is_400(client):
    assert client.post("/api/macs/known", json={"mac": "nope", "name": "x"}).status_code == 400


def test_mac_oversized_fields_rejected(client):
    resp = client.post(
        "/api/macs/known",
        json={"mac": "AA:BB:CC:DD:EE:08", "name": "n" * 5000},
    )
    assert resp.status_code == 422


def test_bands_classify(client):
    resp = client.post("/api/bands/classify", json={"freq_mhz": 930.0})
    assert resp.status_code == 200
    assert resp.json()["mode_hint"] == "pocsag"


def test_openapi_schema_builds(client):
    """A broken response model or annotation would surface here."""
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "Pi-Spy-RF"
