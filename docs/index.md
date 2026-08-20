---
title: Pi-Spy-RF Documentation
---

# Pi-Spy-RF Documentation

Web-based multi-SDR RF suite for Raspberry Pi 3 / 4 / 5.

## Install on Raspberry Pi

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
chmod +x install.sh run.sh
sudo ./install.sh
```

Then open **`http://<your-pi-ip>:8080`** in a browser (`hostname -I` on the Pi).

## Guides

- [Installation guide](installation.html) — full step-by-step setup, DSD, auth, troubleshooting
- [GitHub repository](https://github.com/Sid3b00m/Pi-Spy-RF)
- [INSTALL.md on GitHub](https://github.com/Sid3b00m/Pi-Spy-RF/blob/main/INSTALL.md)

## What the installer does

1. Installs rtl-sdr, multimon-ng, hackrf, bluez, and related tools
2. Blacklists the RTL DVB TV driver
3. Creates a Python virtualenv and installs dependencies
4. Copies `config/config.example.yaml` to `config/config.yaml`
5. Enables the `pi-spy-rf` systemd service (auto-start on boot)

## First-run checklist

1. Confirm SDR devices appear in the dashboard (not demo-only)
2. Use **Auto-assign** for SDR load balancing
3. Start **Spectrum** and **Decode** workers
4. Optionally enable LAN auth in config

## Service management

```bash
sudo systemctl status pi-spy-rf
sudo systemctl restart pi-spy-rf
journalctl -u pi-spy-rf -f
```

## Windows development

```bat
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
run.bat
```

Demo mode at http://127.0.0.1:8080 — no hardware required.
