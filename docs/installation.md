---
title: Installation Guide
---

# Pi-Spy-RF — Install Guide

Step-by-step setup for **Raspberry Pi 3 / 4 / 5** running Raspberry Pi OS (Bookworm or newer).

Estimated time: **15–30 minutes** (plus optional DSD build time).

> **Not only for Pi:** the same app runs on **Linux (all major distros), macOS, and Windows** — in demo mode without SDR hardware. See [Install on any platform](platforms.md) and [Security hardening](security.md).

---

## Quick install

On your Pi, after flashing Raspberry Pi OS and completing first-boot setup:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
chmod +x install.sh run.sh
sudo ./install.sh
```

> **On another Linux distribution?** Only the first line above is Debian-specific —
> install `git` with your own package manager, then run `install.sh` unchanged. It
> detects apt, dnf, yum, pacman, zypper, apk, xbps, and emerge, and installs a
> systemd or OpenRC service to match your system. See
> [Install on any platform](platforms.md) for per-distro package lists.

When finished, open in any browser on your network:

```text
http://<pi-ip-address>:8080
```

Find your Pi IP with `hostname -I`.

The installer handles system RF packages, the RTL-SDR driver conflict, USB
permissions and udev rules, the Python environment, and the optional
`pi-spy-rf` auto-start service.

---

## Full guide

The complete walkthrough — hardware checklist, all eight manual steps, DSD build,
WiFi monitor mode, auth setup, troubleshooting, and uninstall — is maintained in
**[INSTALL.md](https://github.com/Sid3b00m/Pi-Spy-RF/blob/main/INSTALL.md)**.

It is kept in the repository root so it ships with every clone and stays readable
offline on a headless Pi, which is where you are most likely to need it. `install.sh`
prints its on-disk path when it finishes.

---

## Other platforms

For macOS (Apple Silicon and Intel), native Windows, WSL2, and every major Linux
distribution — including auto-start setup and per-platform troubleshooting — see
**[Install on any platform](platforms.md)**.

---

## Support

- GitHub: <https://github.com/Sid3b00m/Pi-Spy-RF>
- Roadmap: [ROADMAP.md](../ROADMAP.md)
- Security: [Security hardening](security.md)
