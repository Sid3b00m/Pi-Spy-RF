---
title: Platforms
---

# Run on Linux, macOS, Windows, and Raspberry Pi

Pi-Spy-RF is a **Python FastAPI** app. Hardware SDR features need OS tools (`rtl-sdr`, etc.). Without hardware, **demo mode** still runs the dashboard for UI/API development on any OS.

---

## Common prerequisites

- **Python 3.11+** (3.12 recommended)
- Git
- Network access to install pip packages

Clone once:

```bash
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
```

---

## Windows

### App only (demo / UI)

1. Install [Python 3](https://www.python.org/downloads/) and check **Add python.exe to PATH**.
2. In PowerShell or cmd:

```bat
cd Pi-Spy-RF
run.bat
```

3. Open http://127.0.0.1:8080

### Optional SDR on Windows

- Install [Zadig](https://zadig.akeo.ie/) and WinUSB driver for your RTL-SDR
- Install `rtl-sdr` / `hackrf` binaries and put them on `PATH`
- Restart the app; real devices replace demo placeholders

### Auth / LAN

Edit `config/config.yaml` (copied from example on first run). Prefer:

```yaml
server:
  host: "127.0.0.1"
```

For LAN access set `host: "0.0.0.0"`, `auth.enabled: true`, and:

```powershell
$env:PI_SPY_PASSWORD = "your-password"
.\run.bat
```

---

## macOS

### App only (demo / UI)

```bash
cd Pi-Spy-RF
chmod +x run.sh
./run.sh
```

Open http://127.0.0.1:8080

### Optional SDR tools (Homebrew)

```bash
brew install python@3.12 rtl-sdr hackrf sox multimon-ng
```

Then `./run.sh` again. Plug in the dongle and refresh **Devices**.

### Notes

- WiFi/BT catalog may stay in **demo** mode; macOS does not ship `nmcli`/`iw`/`bluetoothctl` like Linux.
- Grant USB access if macOS prompts when opening the SDR.

---

## Linux (desktop / server)

### Quick (app + optional apt tools)

Debian/Ubuntu/Raspberry Pi OS:

```bash
cd Pi-Spy-RF
chmod +x install.sh run.sh
# Full stack (SDR tools + systemd) — needs sudo:
sudo ./install.sh
```

App-only without system packages:

```bash
./run.sh
```

### Manual packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv rtl-sdr hackrf sox multimon-ng \
  bluez iw network-manager
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
```

### Firewall tip

If you bind `0.0.0.0:8080`, restrict with `ufw` / firewalld to your LAN only and enable auth.

---

## Raspberry Pi

See [INSTALL.md](../INSTALL.md) / [installation.md](installation.md). Same codebase; `install.sh` is Pi-oriented (apt + systemd).

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `PI_SPY_PASSWORD` | Auth password (preferred over YAML) |
| `PI_SPY_SECURE_COOKIE=1` | Mark session cookie Secure (HTTPS) |
| `PI_SPY_NO_DEMO=1` | Do not invent placeholder SDR devices |

---

## Verify install

```bash
curl -s http://127.0.0.1:8080/api/health
# expect: {"ok":true,"service":"pi-spy-rf","version":"0.8.0"}
```

Interactive API docs: http://127.0.0.1:8080/docs

---

## Feature matrix by OS

| Feature | Linux / Pi | macOS | Windows |
|---------|------------|-------|---------|
| Web dashboard | Yes | Yes | Yes |
| Demo spectrum / decode | Yes | Yes | Yes |
| RTL-SDR (`rtl_power` / `rtl_fm`) | Yes* | Yes* | Yes* |
| HackRF | Yes* | Yes* | Yes* |
| multimon-ng paging | Yes* | Yes* | If on PATH |
| WiFi via nmcli/iw | Yes | Demo | Demo |
| Bluetooth via bluetoothctl | Yes | Demo | Demo |
| systemd auto-start | Yes (`install.sh`) | launchd DIY | Task Scheduler DIY |

\* when vendor tools are installed and the dongle is detected.
