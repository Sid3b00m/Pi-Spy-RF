---
title: Pi-Spy-RF Documentation
---

# Pi-Spy-RF Documentation

Web-based multi-SDR RF suite for **Raspberry Pi, Linux, macOS, and Windows**.

## Start here

```bash
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
```

| OS | Command | Notes |
|----|---------|-------|
| **Raspberry Pi** | `chmod +x install.sh run.sh && sudo ./install.sh` | Installs SDR tools + systemd service |
| **Linux** (Debian, Ubuntu, Fedora, RHEL, Arch, openSUSE, Alpine) | `chmod +x install.sh run.sh && sudo ./install.sh` | Auto-detects your package manager |
| **macOS** (Apple Silicon or Intel) | `chmod +x run.sh && ./run.sh` | Add SDR tools with `brew install rtl-sdr hackrf sox` |
| **Windows** | `run.bat` | RTL-SDR needs the Zadig WinUSB driver |

Dashboard: **http://127.0.0.1:8080** (or `http://<host-ip>:8080` if LAN-bound with auth).

No SDR hardware? Everything still runs in **demo mode** with simulated data, on every platform.

## Guides

- [**Install on any platform**](platforms.md) — Pi, macOS, Windows, and every Linux variant, with auto-start and per-platform troubleshooting
- [Installation (Raspberry Pi, detailed)](installation.md)
- [Security hardening](security.md)
- [GitHub repository](https://github.com/Sid3b00m/Pi-Spy-RF)

## First-run checklist

1. Confirm devices (or demo placeholders) in the dashboard
2. Enable **auth** before binding to `0.0.0.0`
3. Auto-assign SDR roles, then start Spectrum / Decode
4. Compare against a distant receiver from the **Public WebSDR receivers** panel (set
   `websdr.enabled: false` if the host must make no outbound requests)
