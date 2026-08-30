"""Receiver directory: parsers, cache behaviour and the picker endpoints.

The parsers are fed captured-shape payloads rather than the live directories, so
these stay fast and offline. `_fetch_text` is the only network seam.
"""
from __future__ import annotations

import json
import time

import pytest

from app.core import websdr

# Mirrors the real payload: a `var` assignment, a trailing comma before the
# closing bracket, and a stray semicolon.
KIWI_JS = """
// KiwiSDR.com receiver list for dyatlov map maker
// KiwiSDR.com data timestamp: Sunday, 30-Aug-2026 14:29:04 GMT

var kiwisdr_com =
[
    {
        "offline":"no","name":"Test One","url":"http://one.example:8073",
        "gps":"(51.500000, -0.120000)","loc":"(51.500000, -0.120000)","grid":"IO91WM",
        "users":"2","users_max":"8","bands":"0-30000000",
        "antenna":"Long wire","snr":"20,18"
    },
    {
        "offline":"yes","name":"Switched off","url":"http://off.example:8073",
        "gps":"(48.85, 2.35)","loc":"Paris, France"
    },
    {
        "offline":"no","name":"No position","url":"http://nogps.example:8073",
        "gps":"","loc":"Unknown"
    },
    {
        "offline":"no","name":"Null Island","url":"http://null.example:8073",
        "gps":"(0.0, 0.0)","loc":"Nowhere"
    },
    {
        "offline":"no","name":"Berlin Kiwi","url":"http://berlin.example:8073",
        "gps":"(52.52, 13.40)","loc":"Berlin, Germany","grid":"JO62QM",
        "users":"0","users_max":"4","bands":"1800000-30000000"
    },
];
"""

# Receiverbook embeds GeoJSON, longitude first, several receivers per site.
RECEIVERBOOK_HTML = """
<html><body><script>
var receivers = [
 {"label":"Bedford, England ","location":{"coordinates":[-0.45,52.117],"type":"Point"},
  "receivers":[
    {"label":"OpenWebRX Bedford","version":"1.2.122","url":"http://remote.example:8077/","type":"OpenWebRX"},
    {"label":"Barney's WebSDR","url":"http://remote.example:8073/","type":"WebSDR"},
    {"label":"Never registered a URL","type":"WebSDR"}
  ]},
 {"label":"London, England","location":{"coordinates":[-0.12,51.5],"type":"Point"},
  "receivers":[{"label":"Kiwi London","url":"http://one.example:8073","type":"KiwiSDR"}]},
 {"label":"Null Island","location":{"coordinates":[0,0],"type":"Point"},
  "receivers":[{"label":"Bad position","url":"http://nowhere.example","type":"KiwiSDR"}]}
];
</script></body></html>
"""


@pytest.fixture
def stub_directories(monkeypatch):
    """Serve both directories from the fixtures above and record every fetch."""
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        return KIWI_JS if url == websdr.KIWI_MIRROR_URL else RECEIVERBOOK_HTML

    monkeypatch.setattr(websdr, "_fetch_text", fake_fetch)
    return calls


@pytest.fixture
def dead_directories(monkeypatch):
    def boom(url, timeout):
        raise OSError("network is down")

    monkeypatch.setattr(websdr, "_fetch_text", boom)


def test_is_plausible_coordinate_rejects_null_island_and_out_of_range():
    assert websdr.is_plausible_coordinate(51.5, -0.12)
    assert not websdr.is_plausible_coordinate(0.0, 0.0)
    assert not websdr.is_plausible_coordinate(91.0, 0.5)
    assert not websdr.is_plausible_coordinate(10.0, 181.0)
    assert not websdr.is_plausible_coordinate("north", 5.0)
    assert not websdr.is_plausible_coordinate(None, None)


def test_parse_gps_pair_reads_latitude_first():
    assert websdr.parse_gps_pair("(-34.273700, 138.771000)") == (-34.2737, 138.771)
    assert websdr.parse_gps_pair("(0.0, 0.0)") is None
    assert websdr.parse_gps_pair("") is None
    assert websdr.parse_gps_pair(None) is None


def test_receiver_key_normalises_host_and_default_port():
    assert websdr.receiver_key("http://a.example:8073/") == "a.example:8073"
    assert websdr.receiver_key("HTTP://A.Example/") == "a.example:80"
    assert websdr.receiver_key("https://b.example/") == "b.example:443"
    # Anything we could not open in a browser is not a receiver.
    assert websdr.receiver_key("a.example:8073") is None
    assert websdr.receiver_key("javascript:alert(1)") is None
    assert websdr.receiver_key("") is None
    assert websdr.receiver_key(None) is None


def test_format_bands_converts_hz_to_compact_mhz():
    assert websdr.format_bands("0-30000000") == "0-30 MHz"
    assert websdr.format_bands("1800000-30000000") == "1.8-30 MHz"
    assert websdr.format_bands("not a range") is None
    assert websdr.format_bands(None) is None


def test_receiver_load_reports_occupancy_only_when_known():
    assert websdr.receiver_load({"users": 2, "users_max": 8}) == 0.25
    assert websdr.receiver_load({"users": 9, "users_max": 8}) == 1.0
    assert websdr.receiver_load({"users": None, "users_max": 4}) == 0.0
    assert websdr.receiver_load({"users": 3, "users_max": None}) is None
    assert websdr.receiver_load({}) is None


def test_parse_kiwi_list_skips_offline_and_positionless_receivers():
    rows = websdr.parse_kiwi_list(KIWI_JS)
    urls = {r["url"] for r in rows}
    assert urls == {"http://one.example:8073", "http://berlin.example:8073"}

    berlin = next(r for r in rows if "berlin" in r["url"])
    assert berlin["type"] == "KiwiSDR"
    assert berlin["location"] == "Berlin, Germany"
    assert berlin["label"] == "Berlin, Germany"
    assert berlin["bands"] == "1.8-30 MHz"
    assert (berlin["users"], berlin["users_max"]) == (0, 4)
    assert (berlin["lat"], berlin["lon"]) == (52.52, 13.40)
    assert berlin["source"] == "kiwisdr-mirror"


def test_parse_kiwi_list_drops_a_location_that_is_only_coordinates():
    row = next(r for r in websdr.parse_kiwi_list(KIWI_JS) if "one.example" in r["url"])
    assert row["location"] is None
    # The label has to fall back to something a human can read in a dropdown.
    assert row["label"] == "Test One"
    assert row["antenna"] == "Long wire"
    assert row["snr"] == "20,18"


def test_parse_kiwi_list_tolerates_junk():
    assert websdr.parse_kiwi_list("") == []
    assert websdr.parse_kiwi_list("var kiwisdr_com = ") == []
    assert websdr.parse_kiwi_list("var x = [not json];") == []
    assert websdr.parse_kiwi_list('var x = {"a": 1};') == []


def test_parse_receiverbook_reads_lon_lat_order_and_skips_urlless_entries():
    rows = websdr.parse_receiverbook(RECEIVERBOOK_HTML)
    assert len(rows) == 3

    owrx = next(r for r in rows if r["type"] == "OpenWebRX")
    assert owrx["url"] == "http://remote.example:8077/"
    assert owrx["location"] == "Bedford, England"
    assert (owrx["lat"], owrx["lon"]) == (52.117, -0.45)
    assert owrx["version"] == "1.2.122"
    assert owrx["source"] == "receiverbook"
    # Occupancy is the mirror's contribution; Receiverbook never reports it.
    assert owrx["users"] is None and owrx["users_max"] is None

    assert "Never registered a URL" not in {r["name"] for r in rows}
    assert "http://nowhere.example" not in {r["url"] for r in rows}


def test_parse_receiverbook_tolerates_junk():
    assert websdr.parse_receiverbook("") == []
    assert websdr.parse_receiverbook("<html>no dataset</html>") == []
    assert websdr.parse_receiverbook("var receivers = [oops];") == []


def test_merge_prefers_the_mirror_but_keeps_a_receiverbook_place_name():
    merged = websdr.merge_receivers(
        websdr.parse_receiverbook(RECEIVERBOOK_HTML),
        websdr.parse_kiwi_list(KIWI_JS),
    )
    by_id = {r["id"]: r for r in merged}
    # Same host on two ports stays two receivers.
    assert set(by_id) == {
        "remote.example:8077",
        "remote.example:8073",
        "one.example:8073",
        "berlin.example:8073",
    }

    shared = by_id["one.example:8073"]
    assert shared["source"] == "kiwisdr-mirror"
    assert shared["users_max"] == 8
    # The mirror had only coordinates for this site, so Receiverbook's town wins.
    assert shared["location"] == "London, England"
    assert shared["label"] == "London, England"


def test_merge_drops_receivers_without_an_openable_url():
    merged = websdr.merge_receivers([{"url": "javascript:alert(1)"}, {"url": None}])
    assert merged == []


def test_get_catalog_fetches_once_then_serves_from_memory(stub_directories):
    first = websdr.get_catalog(force=True)
    assert sorted(stub_directories) == [websdr.KIWI_MIRROR_URL, websdr.RECEIVERBOOK_URL]
    assert first["count"] == 4
    assert first["by_type"] == {"KiwiSDR": 2, "OpenWebRX": 1, "WebSDR": 1}
    assert first["sources"] == {"kiwisdr_mirror": 2, "receiverbook": 3}
    assert first["errors"] == {}
    assert first["stale"] is False

    again = websdr.get_catalog()
    assert len(stub_directories) == 2, "a fresh catalog must not refetch"
    assert again["count"] == 4


def test_get_catalog_writes_a_disk_cache_that_survives_a_restart(stub_directories):
    websdr.get_catalog(force=True)
    assert websdr.cache_path().exists()

    # Simulate a process restart with the network gone.
    websdr._catalog = None
    websdr._fetch_text = lambda url, timeout: pytest.fail("read the disk, not the network")
    restored = websdr.get_catalog()
    assert restored["count"] == 4
    assert restored["stale"] is False


def test_get_catalog_degrades_when_one_directory_fails(monkeypatch):
    def half_dead(url, timeout):
        if url == websdr.KIWI_MIRROR_URL:
            raise OSError("mirror timed out")
        return RECEIVERBOOK_HTML

    monkeypatch.setattr(websdr, "_fetch_text", half_dead)
    catalog = websdr.get_catalog(force=True)
    assert catalog["count"] == 3
    assert catalog["sources"] == {"kiwisdr_mirror": None, "receiverbook": 3}
    assert "mirror timed out" in catalog["errors"]["kiwisdr_mirror"]
    assert catalog["stale"] is False


def test_get_catalog_raises_when_nothing_is_available(dead_directories):
    with pytest.raises(websdr.WebSdrUnavailable):
        websdr.get_catalog(force=True)


def test_get_catalog_serves_a_stale_cache_when_the_fetch_fails(stub_directories, monkeypatch):
    websdr.get_catalog(force=True)

    # Age the cache past its refresh window, then take the network away.
    stale = json.loads(websdr.cache_path().read_text(encoding="utf-8"))
    stale["updated_at"] = time.time() - 7200
    websdr.cache_path().write_text(json.dumps(stale), encoding="utf-8")
    websdr._catalog = None
    monkeypatch.setattr(websdr, "_fetch_text", lambda url, timeout: 1 / 0)

    catalog = websdr.get_catalog()
    assert catalog["stale"] is True
    assert catalog["count"] == 4
    assert catalog["degraded_reason"]
    assert catalog["age_s"] > 3600


def test_stale_cache_past_the_limit_is_not_served(stub_directories, monkeypatch):
    websdr.get_catalog(force=True)
    ancient = json.loads(websdr.cache_path().read_text(encoding="utf-8"))
    ancient["updated_at"] = time.time() - 400 * 86400
    websdr.cache_path().write_text(json.dumps(ancient), encoding="utf-8")
    websdr._catalog = None
    monkeypatch.setattr(websdr, "_fetch_text", lambda url, timeout: 1 / 0)

    with pytest.raises(websdr.WebSdrUnavailable):
        websdr.get_catalog()


def test_list_receivers_filters_by_type_and_text(stub_directories):
    kiwis = websdr.list_receivers(kind="KiwiSDR")
    assert {r["type"] for r in kiwis["receivers"]} == {"KiwiSDR"}
    assert kiwis["count"] == 2
    assert kiwis["total"] == 4

    assert websdr.list_receivers(kind="kiwisdr")["count"] == 2, "type match is case-insensitive"

    berlin = websdr.list_receivers(query="berlin")
    assert [r["label"] for r in berlin["receivers"]] == ["Berlin, Germany"]

    assert websdr.list_receivers(query="atlantis")["count"] == 0
    assert websdr.list_receivers(limit=1)["receivers"] != []
    assert len(websdr.list_receivers(limit=1)["receivers"]) == 1


def test_receivers_are_sorted_by_label(stub_directories):
    labels = [r["label"] for r in websdr.list_receivers()["receivers"]]
    assert labels == sorted(labels, key=str.casefold)


def test_api_lists_receivers(client, stub_directories):
    body = client.get("/api/websdr/receivers").json()
    assert body["total"] == 4
    assert body["by_type"]["KiwiSDR"] == 2
    assert body["stale"] is False
    row = body["receivers"][0]
    for field in ("id", "type", "label", "url", "lat", "lon", "source"):
        assert field in row
    # The picker opens these in a browser tab, so the scheme must be safe.
    assert all(r["url"].startswith(("http://", "https://")) for r in body["receivers"])


def test_api_filters_and_clamps(client, stub_directories):
    assert client.get("/api/websdr/receivers?kind=WebSDR").json()["count"] == 1
    assert client.get("/api/websdr/receivers?q=bedford").json()["count"] == 2
    assert len(client.get("/api/websdr/receivers?limit=1").json()["receivers"]) == 1
    # Out-of-range limits are clamped rather than rejected.
    assert client.get("/api/websdr/receivers?limit=99999").status_code == 200
    assert client.get("/api/websdr/receivers?limit=0").status_code == 200


def test_api_returns_503_when_no_directory_can_be_read(client, dead_directories):
    resp = client.get("/api/websdr/receivers")
    assert resp.status_code == 503
    assert "directory" in resp.json()["detail"]


def test_api_returns_404_when_disabled(client, monkeypatch, stub_directories):
    from app.core.config import get_config

    monkeypatch.setitem(get_config().websdr, "enabled", False)
    assert client.get("/api/websdr/receivers").status_code == 404
    assert client.post("/api/websdr/refresh").status_code == 404
    assert stub_directories == [], "a disabled picker must not touch the network"


def test_api_refresh_refetches_and_logs_an_event(client, stub_directories):
    client.get("/api/websdr/receivers")
    fetched = len(stub_directories)

    body = client.post("/api/websdr/refresh").json()
    assert body["ok"] is True
    assert body["count"] == 4
    assert len(stub_directories) == fetched + 2

    kinds = [e["kind"] for e in client.get("/api/events").json()["events"]]
    assert "websdr_refresh" in kinds
