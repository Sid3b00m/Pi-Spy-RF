"""Public WebSDR / KiwiSDR receiver directory behind the dashboard picker.

The two source choices and the parsers are ported from the gods-ear project
(Sid3b00m/gods-ear: src/data/receiversParse.js, src/server/receivers.js).

Two directories, deliberately:
  - Receiverbook aggregates voluntarily-registered KiwiSDR, OpenWebRX and WebSDR
    sites and embeds the whole set as GeoJSON inside its map page.
  - The community KiwiSDR mirror at rx.linkfanel.net carries live user counts,
    SNR and antenna details that Receiverbook does not.

The direct WebSDR.org list is deliberately NOT fetched: its response body states
the data "may not be re-used in another website or automated system without prior
permission". WebSDR sites still reach this list through Receiverbook, where the
operator opted in.

Both are fetched here rather than from the browser for two reasons: neither sends
CORS headers, and the Kiwi mirror is plain HTTP, which a page served over HTTPS
could not load at all. The merged result is cached on disk as well as in memory,
so a receiver that is offline, or firewalled away from these hosts, still has a
usable list to show.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app import __version__
from app.core.config import ROOT, get_config

KIWI_MIRROR_URL = "http://rx.linkfanel.net/kiwisdr_com.js"
RECEIVERBOOK_URL = "https://www.receiverbook.de/map"

# Both directories refuse anything that is not browser-shaped.
USER_AGENT = f"Mozilla/5.0 (compatible; pi-spy-rf/{__version__}; RF console)"

DEFAULT_CACHE_PATH = "data/websdr_receivers.json"
DEFAULT_REFRESH_MINUTES = 60.0
# Generous, because the point of the disk cache is an offline or firewalled host.
DEFAULT_STALE_DAYS = 30.0
DEFAULT_TIMEOUT_S = 12.0
DEFAULT_MAX_RECEIVERS = 4000

_GPS_RE = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)")
# The array ends at the only "];" in the page; inner arrays close with "]}" or "],".
_RECEIVERBOOK_RE = re.compile(r"var receivers\s*=\s*(\[.*?\]);", re.DOTALL)
_BANDS_RE = re.compile(r"^(\d+)-(\d+)$")
_TRAILING_COMMA_RE = re.compile(r",(\s*)\]$")
# Plenty of operators leave the town field set to their GPS pair.
_COORD_ONLY_RE = re.compile(r"^\(\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*\)$")

# Every receiver family spells "tune here" differently, and none of them agree
# on units either. Our own mode names are the keys.
_KIWI_MODE = {"nbfm": "nbfm", "am": "am", "usb": "usb", "lsb": "lsb", "cw": "cw"}
_OWRX_MODE = {"nbfm": "nfm", "wbfm": "wfm", "am": "am", "usb": "usb", "lsb": "lsb", "cw": "cw"}
_WEBSDR_MODE = {"nbfm": "fm", "am": "am", "usb": "usb", "lsb": "lsb", "cw": "cw"}


class WebSdrUnavailable(RuntimeError):
    """No directory could be fetched and no cache is recent enough to stand in."""


def is_plausible_coordinate(lat: Any, lon: Any) -> bool:
    """Null Island and out-of-range values mean the operator never set a position."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    if lat_f != lat_f or lon_f != lon_f:  # NaN
        return False
    if abs(lat_f) > 90 or abs(lon_f) > 180:
        return False
    return abs(lat_f) > 0.01 or abs(lon_f) > 0.01


def parse_gps_pair(value: Any) -> tuple[float, float] | None:
    """`gps` arrives as the string "(-34.273700, 138.771000)", latitude first."""
    match = _GPS_RE.search(str(value or ""))
    if not match:
        return None
    lat = float(match.group(1))
    lon = float(match.group(2))
    return (lat, lon) if is_plausible_coordinate(lat, lon) else None


def receiver_key(url: Any) -> str | None:
    """Dedupe key: both directories list many of the same sites, so compare host:port."""
    try:
        parts = urlsplit(str(url or ""))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    return f"{parts.hostname.lower()}:{port}"


def _fmt_mhz(hz: Any) -> str:
    mhz = round(float(hz) / 1000.0) / 1000.0
    return f"{mhz:.3f}".rstrip("0").rstrip(".") or "0"


def format_bands(bands: Any) -> str | None:
    """Turn a "1800000-30000000" (Hz) span into a compact "1.8-30 MHz" for display."""
    match = _BANDS_RE.match(str(bands or "").strip())
    if not match:
        return None
    return f"{_fmt_mhz(match.group(1))}-{_fmt_mhz(match.group(2))} MHz"


def parse_band_range(bands: Any) -> tuple[float, float] | None:
    '''The same span as numbers in MHz, so a frequency can be matched against it.'''
    match = _BANDS_RE.match(str(bands or "").strip())
    if not match:
        return None
    lo = float(match.group(1)) / 1e6
    hi = float(match.group(2)) / 1e6
    return (lo, hi) if hi > lo else None


def tune_url(receiver: dict[str, Any], freq_mhz: float, mode: str | None = None) -> str | None:
    '''Deep-link straight to a frequency, in whichever syntax the software uses.

    An unrecognised receiver type falls back to the plain site URL rather than
    guessing at a query string the far end will not understand.
    '''
    url = str((receiver or {}).get("url") or "")
    if not url.lower().startswith(("http://", "https://")):
        return None
    kind = str((receiver or {}).get("type") or "").casefold()
    base = url.rstrip("/")
    wanted = (mode or "").strip().lower()
    khz = f"{float(freq_mhz) * 1000.0:.2f}".rstrip("0").rstrip(".")

    if "kiwi" in kind:
        return f"{base}/?f={khz}{_KIWI_MODE.get(wanted, '')}"
    if "openwebrx" in kind:
        hz = int(round(float(freq_mhz) * 1e6))
        mod = _OWRX_MODE.get(wanted)
        return f"{base}/#freq={hz}" + (f",mod={mod}" if mod else "")
    if "websdr" in kind:
        return f"{base}/?tune={khz}{_WEBSDR_MODE.get(wanted, '')}"
    return url


def _to_count(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str | None:
    """Collapse the ragged whitespace both directories are full of.

    A few Receiverbook labels arrive double-encoded, carrying a literal backslash
    in front of their quotes.
    """
    if value is None:
        return None
    text = " ".join(str(value).split()).replace('\\"', '"')
    return text or None


def _place(value: Any) -> str | None:
    """A town name, or None when the operator only filled in coordinates."""
    text = _clean(value)
    if not text or _COORD_ONLY_RE.match(text):
        return None
    return text


def parse_kiwi_list(text: str) -> list[dict[str, Any]]:
    """Parse the mirror's JS payload.

    It is JavaScript rather than JSON: it opens with `var kiwisdr_com =`, ends with
    a stray semicolon, and leaves a trailing comma before the final bracket.
    """
    source = str(text or "")
    start = source.find("[")
    end = source.rfind("]")
    if start < 0 or end <= start:
        return []
    body = _TRAILING_COMMA_RE.sub(r"\1]", source[start : end + 1])
    try:
        entries = json.loads(body)
    except ValueError:
        return []
    if not isinstance(entries, list):
        return []

    receivers: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("offline") == "yes":
            continue
        point = parse_gps_pair(entry.get("gps"))
        if not point:
            continue
        location = _place(entry.get("loc"))
        name = _clean(entry.get("name")) or location or "KiwiSDR"
        coverage = parse_band_range(entry.get("bands"))
        receivers.append(
            {
                "type": "KiwiSDR",
                "name": name,
                "label": location or name,
                "url": entry.get("url"),
                "location": location,
                "grid": _clean(entry.get("grid")),
                "users": _to_count(entry.get("users")),
                "users_max": _to_count(entry.get("users_max")),
                "bands": format_bands(entry.get("bands")),
                "band_lo_mhz": coverage[0] if coverage else None,
                "band_hi_mhz": coverage[1] if coverage else None,
                "antenna": _clean(entry.get("antenna")),
                "snr": _clean(entry.get("snr")),
                "source": "kiwisdr-mirror",
                "lat": point[0],
                "lon": point[1],
            }
        )
    return receivers


def parse_receiverbook(html: str) -> list[dict[str, Any]]:
    """Parse the inline `var receivers = [...]` dataset from the map page.

    Note the GeoJSON axis order: coordinates[0] is LONGITUDE.
    """
    match = _RECEIVERBOOK_RE.search(str(html or ""))
    if not match:
        return []
    try:
        sites = json.loads(match.group(1))
    except ValueError:
        return []
    if not isinstance(sites, list):
        return []

    receivers: list[dict[str, Any]] = []
    for site in sites:
        if not isinstance(site, dict):
            continue
        coordinates = (site.get("location") or {}).get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            continue
        lon, lat = coordinates[0], coordinates[1]
        if not is_plausible_coordinate(lat, lon):
            continue
        location = _place(site.get("label"))
        for receiver in site.get("receivers") or []:
            if not isinstance(receiver, dict) or not receiver.get("url"):
                continue
            kind = _clean(receiver.get("type")) or "Unknown"
            name = _clean(receiver.get("label")) or location or kind
            receivers.append(
                {
                    "type": kind,
                    "name": name,
                    "label": location or name,
                    "url": receiver.get("url"),
                    "location": location,
                    "grid": None,
                    "users": None,
                    "users_max": None,
                    "bands": None,
                    "band_lo_mhz": None,
                    "band_hi_mhz": None,
                    "antenna": None,
                    "snr": None,
                    "version": _clean(receiver.get("version")),
                    "source": "receiverbook",
                    "lat": float(lat),
                    "lon": float(lon),
                }
            )
    return receivers


def merge_receivers(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the directories.

    The Kiwi mirror wins on collision because it carries live occupancy and SNR,
    which Receiverbook omits. Its town field is the weaker of the two though, so
    a Receiverbook place name is kept when the mirror has none.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for group in lists:
        for receiver in group:
            key = receiver_key(receiver.get("url"))
            if not key:
                continue
            existing = by_key.get(key)
            if existing is None or (
                existing.get("source") != "kiwisdr-mirror"
                and receiver.get("source") == "kiwisdr-mirror"
            ):
                merged = {**receiver, "id": key}
                if existing and not merged.get("location") and existing.get("location"):
                    merged["location"] = existing["location"]
                    merged["label"] = existing["location"]
                by_key[key] = merged
    return list(by_key.values())


def receiver_load(receiver: dict[str, Any]) -> float | None:
    """Occupancy in [0, 1], or None when the directory does not report it."""
    limit = (receiver or {}).get("users_max")
    if not limit:
        return None
    users = (receiver or {}).get("users") or 0
    return max(0.0, min(1.0, users / limit))


def _sort_key(receiver: dict[str, Any]) -> tuple[str, str]:
    return (
        str(receiver.get("label") or "").casefold(),
        str(receiver.get("name") or "").casefold(),
    )


_lock = Lock()
_catalog: dict[str, Any] | None = None


def _settings() -> dict[str, Any]:
    return get_config().websdr or {}


def is_enabled() -> bool:
    """False keeps the dashboard offline: no outbound request is ever made."""
    return bool(_settings().get("enabled", True))


def _setting_float(key: str, default: float) -> float:
    try:
        return float(_settings().get(key, default))
    except (TypeError, ValueError):
        return default


def cache_path() -> Path:
    raw = str(_settings().get("cache_path") or DEFAULT_CACHE_PATH)
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _describe(exc: BaseException, url: str) -> str:
    host = urlsplit(url).hostname or url
    if isinstance(exc, HTTPError):
        return f"{host} HTTP {exc.code}"
    if isinstance(exc, URLError):
        return f"{host} unreachable: {exc.reason}"
    return f"{host}: {exc}"


def _fetch_text(url: str, timeout: float) -> str:
    """Fetch one directory. Split out so tests can stub the network."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _read_disk_cache() -> dict[str, Any] | None:
    path = cache_path()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("receivers"), list):
        return None
    return data


def _write_disk_cache(catalog: dict[str, Any]) -> None:
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(catalog, f)
        tmp.replace(path)
    except OSError:
        # A read-only data dir is not a reason to fail the request.
        pass


def _build(timeout: float) -> dict[str, Any]:
    # One directory failing should degrade coverage, not empty the list.
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {
            "kiwisdr_mirror": (
                KIWI_MIRROR_URL,
                pool.submit(_fetch_text, KIWI_MIRROR_URL, timeout),
                parse_kiwi_list,
            ),
            "receiverbook": (
                RECEIVERBOOK_URL,
                pool.submit(_fetch_text, RECEIVERBOOK_URL, timeout),
                parse_receiverbook,
            ),
        }
        parsed: dict[str, list[dict[str, Any]]] = {}
        sources: dict[str, int | None] = {}
        errors: dict[str, str] = {}
        for name, (url, future, parse) in jobs.items():
            try:
                parsed[name] = parse(future.result())
                sources[name] = len(parsed[name])
            except Exception as exc:  # noqa: BLE001
                parsed[name] = []
                sources[name] = None
                errors[name] = _describe(exc, url)

    # Receiverbook first so the Kiwi mirror overwrites it where both list a site.
    receivers = merge_receivers(parsed["receiverbook"], parsed["kiwisdr_mirror"])
    if not receivers:
        detail = "; ".join(errors.values()) or "nothing parsed"
        raise WebSdrUnavailable(f"no receiver directory could be read ({detail})")

    receivers.sort(key=_sort_key)
    limit = int(_settings().get("max_receivers") or DEFAULT_MAX_RECEIVERS)
    receivers = receivers[:limit]

    by_type: dict[str, int] = {}
    for receiver in receivers:
        kind = str(receiver.get("type") or "Unknown")
        by_type[kind] = by_type.get(kind, 0) + 1

    return {
        "receivers": receivers,
        "count": len(receivers),
        "by_type": dict(sorted(by_type.items())),
        "sources": sources,
        "errors": errors,
        "updated_at": time.time(),
    }


def get_catalog(*, force: bool = False) -> dict[str, Any]:
    """Return the merged directory.

    Prefers a fresh fetch, but never fails while a usable cache exists. Raises
    WebSdrUnavailable only when there is nothing at all to show.
    """
    global _catalog
    ttl = _setting_float("refresh_minutes", DEFAULT_REFRESH_MINUTES) * 60.0
    stale_limit = _setting_float("stale_days", DEFAULT_STALE_DAYS) * 86400.0
    timeout = _setting_float("timeout_s", DEFAULT_TIMEOUT_S)

    with _lock:
        if _catalog is None:
            _catalog = _read_disk_cache()
        cached = _catalog
        age = time.time() - float((cached or {}).get("updated_at") or 0)
        if cached and not force and age < ttl:
            return {**cached, "stale": False, "age_s": age, "degraded_reason": None}

        try:
            _catalog = _build(timeout)
            _write_disk_cache(_catalog)
            return {**_catalog, "stale": False, "age_s": 0.0, "degraded_reason": None}
        except Exception as exc:  # noqa: BLE001
            if cached and age <= stale_limit:
                return {
                    **cached,
                    "stale": True,
                    "age_s": age,
                    "degraded_reason": str(exc),
                }
            raise WebSdrUnavailable(str(exc)) from exc


def covers_frequency(receiver: dict[str, Any], freq_mhz: float) -> bool | None:
    """True, False, or None when the directory never published a coverage range."""
    lo = (receiver or {}).get("band_lo_mhz")
    hi = (receiver or {}).get("band_hi_mhz")
    if lo is None or hi is None:
        return None
    return float(lo) <= float(freq_mhz) <= float(hi)


def list_receivers(
    *,
    kind: str | None = None,
    query: str | None = None,
    limit: int = 500,
    force: bool = False,
    freq_mhz: float | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Catalog filtered down for the dashboard picker."""
    catalog = get_catalog(force=force)
    receivers = catalog["receivers"]

    if kind:
        wanted = kind.casefold()
        receivers = [r for r in receivers if str(r.get("type") or "").casefold() == wanted]
    if query:
        needle = query.casefold()
        receivers = [
            r
            for r in receivers
            if needle in str(r.get("label") or "").casefold()
            or needle in str(r.get("name") or "").casefold()
        ]

    # Only the Kiwi mirror publishes coverage, and a cache written before this
    # existed has none at all, so the count is reported rather than hidden.
    unknown_coverage = 0
    if freq_mhz is not None:
        covering = []
        for receiver in receivers:
            verdict = covers_frequency(receiver, freq_mhz)
            if verdict is None:
                unknown_coverage += 1
            elif verdict:
                covering.append(receiver)
        receivers = covering

    page = receivers[:limit]
    if freq_mhz is not None:
        page = [{**r, "tune_url": tune_url(r, freq_mhz, mode)} for r in page]

    return {
        "receivers": page,
        "count": len(receivers),
        "unknown_coverage": unknown_coverage,
        "total": catalog["count"],
        "by_type": catalog["by_type"],
        "sources": catalog["sources"],
        "errors": catalog.get("errors") or {},
        "updated_at": catalog["updated_at"],
        "age_s": catalog["age_s"],
        "stale": catalog["stale"],
        "degraded_reason": catalog["degraded_reason"],
    }
