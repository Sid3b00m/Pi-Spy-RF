"""Known-MAC storage, normalisation, and OUI vendor lookup."""
from __future__ import annotations

import json

import pytest

from app.core.mac_db import (
    delete_known_mac,
    ensure_mini_oui,
    load_known_macs,
    lookup_oui,
    save_known_macs,
    upsert_known_mac,
)


def test_known_file_seeded_on_first_read():
    data = load_known_macs()
    assert "devices" in data and isinstance(data["devices"], list)


def test_upsert_normalises_case_and_separators():
    upsert_known_mac("aa-bb-cc-dd-ee-01", "Phone", "bluetooth", "note")
    devices = load_known_macs()["devices"]
    entry = next(d for d in devices if d["name"] == "Phone")
    assert entry["mac"] == "AA:BB:CC:DD:EE:01"


def test_upsert_is_idempotent_not_duplicating():
    upsert_known_mac("AA:BB:CC:DD:EE:02", "First", "wifi")
    upsert_known_mac("aa:bb:cc:dd:ee:02", "Renamed", "wifi")
    devices = load_known_macs()["devices"]
    hits = [d for d in devices if d["mac"] == "AA:BB:CC:DD:EE:02"]
    assert len(hits) == 1
    assert hits[0]["name"] == "Renamed"


@pytest.mark.parametrize(
    "bad",
    ["nope", "", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:FF:11", "ZZ:BB:CC:DD:EE:FF", "AABBCCDDEEFF"],
)
def test_upsert_rejects_invalid_mac(bad):
    with pytest.raises(ValueError):
        upsert_known_mac(bad, "x")


def test_delete_removes_entry():
    upsert_known_mac("AA:BB:CC:DD:EE:03", "Doomed", "wifi")
    assert any(d["mac"] == "AA:BB:CC:DD:EE:03" for d in load_known_macs()["devices"])
    delete_known_mac("aa-bb-cc-dd-ee-03")
    assert not any(d["mac"] == "AA:BB:CC:DD:EE:03" for d in load_known_macs()["devices"])


def test_delete_unknown_mac_is_noop():
    before = len(load_known_macs()["devices"])
    delete_known_mac("AA:BB:CC:DD:EE:99")
    assert len(load_known_macs()["devices"]) == before


def test_save_rejects_non_list_devices():
    with pytest.raises(ValueError):
        save_known_macs({"devices": {"not": "a list"}})


def test_save_survives_round_trip(isolated_state):
    save_known_macs({"devices": [{"mac": "B8:27:EB:00:00:01", "name": "Pi"}]})
    raw = json.loads((isolated_state / "data" / "known_macs.json").read_text(encoding="utf-8"))
    assert raw["devices"][0]["mac"] == "B8:27:EB:00:00:01"


def test_oui_seed_and_lookup():
    ensure_mini_oui()
    assert "Raspberry Pi" in (lookup_oui("B8:27:EB:11:22:33") or "")


def test_oui_lookup_unknown_prefix_returns_none():
    ensure_mini_oui()
    assert lookup_oui("02:00:00:11:22:33") is None


def test_oui_lookup_handles_dash_separator():
    ensure_mini_oui()
    assert lookup_oui("B8-27-EB-11-22-33") is not None


def test_oui_lookup_missing_file_returns_none(isolated_state):
    (isolated_state / "data" / "oui.txt").unlink(missing_ok=True)
    assert lookup_oui("B8:27:EB:11:22:33") is None


def test_oui_lookup_does_not_rescan_file_per_call(isolated_state, monkeypatch):
    """A full Wireshark manuf table is ~50k lines; enrichment calls this per
    device per scan cycle, so the table must not be re-read every time."""
    ensure_mini_oui()
    path = isolated_state / "data" / "oui.txt"
    opens = {"n": 0}
    real_open = type(path).open

    def counting_open(self, *a, **kw):
        if self == path:
            opens["n"] += 1
        return real_open(self, *a, **kw)

    monkeypatch.setattr(type(path), "open", counting_open)
    for _ in range(25):
        lookup_oui("B8:27:EB:11:22:33")
    assert opens["n"] <= 1, f"OUI table re-opened {opens['n']} times for 25 lookups"
