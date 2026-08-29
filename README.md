# Pi-Spy-RF

Web-based multi-SDR RF suite for **Raspberry Pi** — spectrum scanning, digital decode, WiFi/Bluetooth catalog, and a browser dashboard reachable from any device on your LAN.

**Version:** 0.8.1

---

## Documentation

| Guide | Description |
|-------|-------------|
| **[Install on any platform](docs/platforms.md)** | Pi, macOS, Windows, WSL2, and every Linux distro — plus auto-start and troubleshooting |
| **[Install Guide (INSTALL.md)](INSTALL.md)** | Full step-by-step Pi setup, troubleshooting, DSD, auth |
| **[Online docs](https://sid3b00m.github.io/Pi-Spy-RF/)** | Install guide on GitHub Pages |
| **[SECURITY.md](SECURITY.md)** | Hardening notes and LAN advice |
| **[ROADMAP.md](ROADMAP.md)** | Planned features |

---

## Install

Requires **Python 3.11+**. No SDR hardware? Every platform still runs in **demo mode** with simulated data.

```bash
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
```

### Raspberry Pi

```bash
sudo apt update && sudo apt install -y git
chmod +x install.sh run.sh
sudo ./install.sh
```

Installs rtl-sdr, multimon-ng, Python dependencies, config, and a **systemd service** so it starts on boot. Open `http://<your-pi-ip>:8080` from any device on your network (`hostname -I` shows the address).

Supported: Pi 5, Pi 4, Pi 400, Pi 3/3B+, Pi Zero 2 W. Works on Pi OS 64-bit, 32-bit, and Lite.

### Linux (any distro)

```bash
chmod +x install.sh run.sh
sudo ./install.sh
```

The installer detects **apt, dnf, yum, pacman, zypper, apk, xbps, and emerge**, covering Debian, Ubuntu, Mint, Pop!\_OS, Kali, Fedora, RHEL, Rocky, Alma, Arch, Manjaro, openSUSE, Alpine, Void and Gentoo. It also:

- installs **systemd or OpenRC** auto-start, whichever the system uses
- installs **udev rules** and creates the SDR group, so non-root USB access works on distros that have no `plugdev`
- adds a **build toolchain on musl** systems where Python wheels must be compiled
- **warns instead of failing** when an optional package is missing from your repos

On an unrecognised distro it still sets up the Python app and prints the packages to install by hand.

App only, no system packages or root:

```bash
./run.sh
```

### macOS (Apple Silicon or Intel)

```bash
chmod +x run.sh && ./run.sh
```

Add SDR support with Homebrew:

```bash
brew install rtl-sdr hackrf sox multimon-ng
```

### Windows

```bat
run.bat
```

Opens on http://127.0.0.1:8080. For a real RTL-SDR, install the WinUSB driver with [Zadig](https://zadig.akeo.ie/) and put the `rtl-sdr` binaries on `PATH`. WSL2 also works, with [usbipd-win](https://github.com/dorssel/usbipd-win) for USB passthrough.

---

**Full instructions for every platform**, including per-distro package lists, auto-start (systemd / launchd / Task Scheduler), and troubleshooting: **[docs/platforms.md](docs/platforms.md)**

Detailed Pi walkthrough: [INSTALL.md](INSTALL.md) · Hardening: [SECURITY.md](SECURITY.md)

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
