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

| OS | Command |
|----|---------|
| **Raspberry Pi / Linux** | `chmod +x install.sh run.sh && sudo ./install.sh` |
| **macOS** | `chmod +x run.sh && ./run.sh` |
| **Windows** | `run.bat` |

Dashboard: **http://127.0.0.1:8080** (or `http://<host-ip>:8080` if LAN-bound with auth).

## Guides

- [Platforms — Mac / Windows / Linux / Pi](platforms.md)
- [Installation (Pi detailed)](installation.md)
- [Security hardening](security.md)
- [GitHub repository](https://github.com/Sid3b00m/Pi-Spy-RF)

## First-run checklist

1. Confirm devices (or demo placeholders) in the dashboard
2. Enable **auth** before binding to `0.0.0.0`
3. Auto-assign SDR roles, then start Spectrum / Decode
