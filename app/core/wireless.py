from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import ROOT, get_config
from app.core.db import add_event, get_db
from app.core.devices import list_radio_devices
from app.core.mac_db import lookup_oui, load_known_macs, save_known_macs


@dataclass
class WirelessDevice:
    mac: str
    kind: str  # wifi | bluetooth
    name: str | None = None
    ssid: str | None = None
    rssi: int | None = None
    channel: int | None = None
    vendor: str | None = None
    known_name: str | None = None
    last_seen: str | None = None
    first_seen: str | None = None
    source: str = "demo"


def init_wireless_tables() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS wireless_devices (
                mac TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT,
                ssid TEXT,
                rssi INTEGER,
                channel INTEGER,
                vendor TEXT,
                known_name TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                source TEXT,
                meta_json TEXT,
                PRIMARY KEY (mac, kind)
            );
            CREATE INDEX IF NOT EXISTS idx_wireless_last ON wireless_devices(last_seen DESC);
            """
        )


def upsert_device(dev: WirelessDevice) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        row = conn.execute(
            "SELECT first_seen FROM wireless_devices WHERE mac=? AND kind=?",
            (dev.mac.upper(), dev.kind),
        ).fetchone()
        first = row["first_seen"] if row else (dev.first_seen or now)
        conn.execute(
            """
            INSERT INTO wireless_devices(
                mac, kind, name, ssid, rssi, channel, vendor, known_name,
                first_seen, last_seen, source, meta_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(mac, kind) DO UPDATE SET
                name=excluded.name,
                ssid=excluded.ssid,
                rssi=excluded.rssi,
                channel=excluded.channel,
                vendor=excluded.vendor,
                known_name=excluded.known_name,
                last_seen=excluded.last_seen,
                source=excluded.source
            """,
            (
                dev.mac.upper(),
                dev.kind,
                dev.name,
                dev.ssid,
                dev.rssi,
                dev.channel,
                dev.vendor,
                dev.known_name,
                first,
                now,
                dev.source,
                "{}",
            ),
        )


def list_wireless(kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with get_db() as conn:
        if kind:
            rows = conn.execute(
                """
                SELECT * FROM wireless_devices
                WHERE kind=?
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM wireless_devices
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def _enrich(mac: str, kind: str, name: str | None = None) -> tuple[str | None, str | None]:
    vendor = lookup_oui(mac)
    known_name = None
    for d in load_known_macs().get("devices", []):
        if str(d.get("mac", "")).upper() == mac.upper():
            known_name = d.get("name")
            if d.get("type") and d.get("type") != kind:
                pass
            break
    return vendor, known_name


class WirelessWorker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._interval_s = 5.0
        self._error: str | None = None
        self._wifi_enabled = True
        self._bt_enabled = True
        self._last_scan: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "interval_s": self._interval_s,
                "wifi_enabled": self._wifi_enabled,
                "bt_enabled": self._bt_enabled,
                "error": self._error,
                "last_scan": self._last_scan,
                "counts": {
                    "wifi": len(list_wireless("wifi", 500)),
                    "bluetooth": len(list_wireless("bluetooth", 500)),
                },
            }

    def configure(
        self,
        *,
        interval_s: float | None = None,
        wifi_enabled: bool | None = None,
        bt_enabled: bool | None = None,
    ) -> None:
        with self._lock:
            if interval_s is not None:
                self._interval_s = max(2.0, float(interval_s))
            if wifi_enabled is not None:
                self._wifi_enabled = bool(wifi_enabled)
            if bt_enabled is not None:
                self._bt_enabled = bool(bt_enabled)

    def start(self) -> dict[str, Any]:
        init_wireless_tables()
        with self._lock:
            if self._running:
                return self.status()
            self._error = None
            self._stop.clear()
            self._running = True
            self._thread = threading.Thread(target=self._loop, name="wireless-worker", daemon=True)
            self._thread.start()
        add_event("wireless_start", "WiFi/BT discovery worker started")
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return self.status()
            self._stop.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._running = False
            self._thread = None
        add_event("wireless_stop", "WiFi/BT discovery worker stopped")
        return self.status()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                wifi_n = bt_n = 0
                if self._wifi_enabled:
                    wifi_n = self._scan_wifi()
                if self._bt_enabled:
                    bt_n = self._scan_bluetooth()
                with self._lock:
                    self._last_scan = {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "wifi": wifi_n,
                        "bluetooth": bt_n,
                    }
                    self._error = None
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._error = str(exc)
                add_event("wireless_error", str(exc))
            self._stop.wait(self._interval_s)

    def _scan_wifi(self) -> int:
        # Prefer iw/nmcli when present; else demo
        if shutil.which("nmcli"):
            return self._scan_wifi_nmcli()
        if shutil.which("iw"):
            return self._scan_wifi_iw()
        return self._scan_wifi_demo()

    def _scan_wifi_nmcli(self) -> int:
        p = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,BSSID,CHAN,SIGNAL", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if p.returncode != 0:
            return self._scan_wifi_demo()
        count = 0
        for line in p.stdout.splitlines():
            parts = line.split(":")
            if len(parts) < 4:
                continue
            ssid, bssid, chan, signal = parts[0], parts[1], parts[2], parts[3]
            mac = bssid.replace("\\:", ":").upper()
            if not re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac):
                continue
            vendor, known = _enrich(mac, "wifi")
            try:
                rssi = int(signal)
            except ValueError:
                rssi = None
            try:
                channel = int(chan) if chan else None
            except ValueError:
                channel = None
            upsert_device(
                WirelessDevice(
                    mac=mac,
                    kind="wifi",
                    name=known or ssid or None,
                    ssid=ssid or None,
                    rssi=rssi,
                    channel=channel,
                    vendor=vendor,
                    known_name=known,
                    source="nmcli",
                )
            )
            count += 1
        return count

    def _scan_wifi_iw(self) -> int:
        cfg = get_config()
        raw_iface = (cfg.wifi or {}).get("interface") or "wlan0"
        try:
            iface = validate_iface(str(raw_iface))
        except ValueError:
            return self._scan_wifi_demo()
        p = subprocess.run(
            ["iw", "dev", iface, "scan"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if p.returncode != 0:
            return self._scan_wifi_demo()
        count = 0
        mac = ssid = None
        rssi = channel = None
        for line in p.stdout.splitlines():
            line = line.strip()
            if line.startswith("BSS "):
                if mac:
                    vendor, known = _enrich(mac, "wifi")
                    upsert_device(
                        WirelessDevice(
                            mac=mac,
                            kind="wifi",
                            name=known or ssid,
                            ssid=ssid,
                            rssi=rssi,
                            channel=channel,
                            vendor=vendor,
                            known_name=known,
                            source="iw",
                        )
                    )
                    count += 1
                m = re.search(r"BSS\s+([0-9a-f:]{17})", line, re.I)
                mac = m.group(1).upper() if m else None
                ssid = None
                rssi = channel = None
            elif "SSID:" in line:
                ssid = line.split("SSID:", 1)[-1].strip() or None
            elif "signal:" in line:
                m = re.search(r"([-\d.]+)\s*dBm", line)
                rssi = int(float(m.group(1))) if m else None
            elif "primary channel:" in line or line.startswith("freq:"):
                m = re.search(r"(\d+)", line)
                if m and "freq:" in line:
                    # rough map common 2.4GHz
                    freq = int(m.group(1))
                    if 2412 <= freq <= 2484:
                        channel = (freq - 2407) // 5
                elif m and "channel" in line:
                    channel = int(m.group(1))
        if mac:
            vendor, known = _enrich(mac, "wifi")
            upsert_device(
                WirelessDevice(
                    mac=mac,
                    kind="wifi",
                    name=known or ssid,
                    ssid=ssid,
                    rssi=rssi,
                    channel=channel,
                    vendor=vendor,
                    known_name=known,
                    source="iw",
                )
            )
            count += 1
        return count

    def _scan_wifi_demo(self) -> int:
        samples = [
            ("62:45:B1:10:22:AA", "CafeGuest", -52, 6),
            ("B8:27:EB:DE:AD:01", "Pi-LAN", -40, 1),
            ("F0:9F:C2:11:22:33", "Office-AP", -61, 11),
            ("00:11:22:33:44:55", "Hidden", -70, 36),
        ]
        for mac, ssid, rssi, ch in samples:
            # jitter rssi
            rssi = rssi + random.randint(-3, 3)
            vendor, known = _enrich(mac, "wifi")
            upsert_device(
                WirelessDevice(
                    mac=mac,
                    kind="wifi",
                    name=known or ssid,
                    ssid=ssid,
                    rssi=rssi,
                    channel=ch,
                    vendor=vendor or self._fake_vendor(mac),
                    known_name=known,
                    source="demo",
                )
            )
        return len(samples)

    def _scan_bluetooth(self) -> int:
        if shutil.which("bluetoothctl"):
            return self._scan_bluetooth_ctl()
        return self._scan_bluetooth_demo()

    def _scan_bluetooth_ctl(self) -> int:
        # Best-effort: bluetoothctl devices + info
        subprocess.run(
            ["bluetoothctl", "--timeout", "5", "scan", "on"],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        p = subprocess.run(
            ["bluetoothctl", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if p.returncode != 0:
            return self._scan_bluetooth_demo()
        count = 0
        for line in p.stdout.splitlines():
            # Device AA:BB:... Name
            m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.*)", line)
            if not m:
                continue
            mac, name = m.group(1).upper(), m.group(2).strip() or None
            vendor, known = _enrich(mac, "bluetooth")
            upsert_device(
                WirelessDevice(
                    mac=mac,
                    kind="bluetooth",
                    name=known or name,
                    rssi=None,
                    vendor=vendor,
                    known_name=known,
                    source="bluetoothctl",
                )
            )
            count += 1
        return count if count else self._scan_bluetooth_demo()

    def _scan_bluetooth_demo(self) -> int:
        samples = [
            ("AA:BB:CC:DD:EE:FF", "Example phone", -55),
            ("11:22:33:44:55:66", "Galaxy Buds", -62),
            ("DE:AD:BE:EF:00:01", "Tile Tracker", -78),
            ("A4:C1:38:12:34:56", "BLE Sensor", -69),
        ]
        for mac, name, rssi in samples:
            vendor, known = _enrich(mac, "bluetooth")
            upsert_device(
                WirelessDevice(
                    mac=mac,
                    kind="bluetooth",
                    name=known or name,
                    rssi=rssi + random.randint(-2, 2),
                    vendor=vendor or self._fake_vendor(mac),
                    known_name=known,
                    source="demo",
                )
            )
        return len(samples)

    def _fake_vendor(self, mac: str) -> str:
        oui = mac.upper()[0:8]
        table = {
            "B8:27:EB": "Raspberry Pi Foundation",
            "DC:A6:32": "Raspberry Pi Trading",
            "F0:9F:C2": "Ubiquiti",
            "A4:C1:38": "Espressif / BLE module",
            "AA:BB:CC": "Local known demo OUI",
        }
        return table.get(oui, f"Unknown OUI {oui}")


wireless_worker = WirelessWorker()