# Pi-Spy-RF

Web-based multi-SDR RF suite for **Raspberry Pi** — spectrum scanning, digital decode, WiFi/Bluetooth catalog, and a browser dashboard reachable from any device on your LAN.

**Version:** 0.7.0

![Python](https://img.shields.io/badge/python-3.11+-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-red)
![License](https://img.shields.io/badge/license-MIT-green)

---

## Features

- **Multi-SDR management** — RTL-SDR, HackRF, Soapy; role assignment (scan / decode / idle)
- **Live spectrum** — waterfall, peak detect, band classification, event log
- **Digital decode** — POCSAG, FLEX, DMR, P25, NXDN, and more (mode catalog in UI)
- **Load balancing** — auto-assign sticks (RTL scan, HackRF decode)
- **Wireless catalog** — WiFi + Bluetooth observation, OUI lookup, known MAC tagging
- **Optional LAN auth** — simple password gate for shared networks
- **Demo mode** — runs on Windows/macOS without hardware for development

---

## Quick start (Raspberry Pi)

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
chmod +x install.sh run.sh
sudo ./install.sh
```

Then open **`http://<your-pi-ip>:8080`** in a browser.

**Full step-by-step guide:** [INSTALL.md](INSTALL.md)

---

## Quick start (Windows dev)

```bat
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
run.bat
```

Open http://127.0.0.1:8080

---

## Hardware

| Device | Role |
|--------|------|
| RTL-SDR v3/v4 | Spectrum scan, paging decode |
| HackRF One | Wideband decode, second channel |
| Pi built-in WiFi/BT | Wireless catalog |
| USB WiFi dongle (optional) | Dedicated monitor interface |

---

## Project layout

```text
Pi-Spy-RF/
  app/              FastAPI backend + dashboard UI
  config/           config.example.yaml → config.yaml
  data/             SQLite DB, OUI seed, known MACs
  scripts/          systemd unit
  install.sh        One-shot Pi installer
  run.sh / run.bat  Manual start scripts
  INSTALL.md        Detailed install guide
  archive/          Legacy bash scanner (reference)
```

---

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Service status |
| `GET /api/devices` | SDR enumeration + roles |
| `POST /api/devices/balance` | Auto-assign SDR roles |
| `POST /api/spectrum/start` | Start spectrum worker |
| `POST /api/decode/start` | Start decode worker |
| `GET /api/decode/modes` | Supported digital modes |

Interactive docs: `http://<host>:8080/docs`

---

## Security note

SDR and wireless scanning may be regulated where you live. Use only on frequencies and networks you are authorized to monitor. Enable `auth.enabled` before exposing the dashboard on untrusted LANs.

---

## License

MIT — see [LICENSE](LICENSE).
