# Pi-Spy-RF

Web-based multi-SDR RF suite for **Raspberry Pi** — spectrum scanning, digital decode, WiFi/Bluetooth catalog, and a browser dashboard reachable from any device on your LAN.

**Version:** 0.7.0

---

## Documentation

| Guide | Description |
|-------|-------------|
| **[Install Guide (INSTALL.md)](INSTALL.md)** | Full step-by-step Pi setup, troubleshooting, DSD, auth |
| **[Online docs](https://sid3b00m.github.io/Pi-Spy-RF/)** | Install guide on GitHub Pages |
| **[ROADMAP.md](ROADMAP.md)** | Planned features |

---

## Quick install (Raspberry Pi)

Copy and paste on a fresh **Raspberry Pi OS** system:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
chmod +x install.sh run.sh
sudo ./install.sh
```

Open the dashboard from any device on your network:

```text
http://<your-pi-ip>:8080
```

Find your Pi IP: `hostname -I`

The installer sets up rtl-sdr, multimon-ng, Python dependencies, config, and a **systemd service** so Pi-Spy-RF starts on boot.

**Need more detail?** See [INSTALL.md](INSTALL.md) or [docs/installation.md](docs/installation.md).

---

## Quick start (Windows dev)

```bat
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
run.bat
```

Open http://127.0.0.1:8080 — demo mode runs without SDR hardware.

---

## Features

- **Multi-SDR management** — RTL-SDR, HackRF, Soapy; role assignment (scan / decode / idle)
- **Live spectrum** — waterfall, peak detect, band classification, event log
- **Digital decode** — POCSAG, FLEX, DMR, P25, NXDN, and more
- **Load balancing** — auto-assign sticks (RTL scan, HackRF decode)
- **Wireless catalog** — WiFi + Bluetooth observation, OUI lookup, known MAC tagging
- **Optional LAN auth** — password gate for shared networks

---

## Hardware

| Device | Role |
|--------|------|
| RTL-SDR v3/v4 | Spectrum scan, paging decode |
| HackRF One | Wideband decode, second channel |
| Pi built-in WiFi/BT | Wireless catalog |
| USB WiFi dongle (optional) | Dedicated monitor interface |

---

## After install

1. Confirm SDR sticks appear under **Devices**
2. Click **Auto-assign** in the load balance panel
3. Start **Spectrum** and **Decode** workers
4. Optional: enable auth in `config/config.yaml` and set `PI_SPY_PASSWORD`

Service commands:

```bash
sudo systemctl status pi-spy-rf
sudo systemctl restart pi-spy-rf
journalctl -u pi-spy-rf -f
```

---

## Project layout

```text
Pi-Spy-RF/
  app/              FastAPI backend + dashboard UI
  config/           config.example.yaml -> config.yaml
  data/             SQLite DB, OUI seed, known MACs
  docs/             GitHub Pages documentation
  install.sh        One-shot Pi installer
  INSTALL.md        Detailed install guide
  run.sh / run.bat  Manual start scripts
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
