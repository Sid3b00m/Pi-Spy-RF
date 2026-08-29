---
title: Platforms
---

# Install on Raspberry Pi, macOS, Windows, and Linux

Pi-Spy-RF is a **Python FastAPI** app, so the dashboard runs on any OS with Python 3.11+. The RF features shell out to SDR command-line tools (`rtl_power`, `rtl_fm`, `multimon-ng`, `dsd-fme`), so how much *real* radio you get depends on which of those your platform can install.

**Without any hardware or tools the app still runs in demo mode**, serving simulated spectrum, decodes, and WiFi/BT data. That makes it safe to install anywhere first and add hardware later.

Jump to: [Raspberry Pi](#raspberry-pi) · [macOS](#macos) · [Windows](#windows) · [Debian/Ubuntu](#debian-ubuntu-and-derivatives) · [Fedora](#fedora) · [RHEL/Rocky/Alma](#rhel-rocky-alma-centos-stream) · [Arch](#arch-manjaro-endeavouros) · [openSUSE](#opensuse) · [Alpine](#alpine) · [Other distros](#other-distributions) · [Auto-start](#auto-start-on-boot) · [Troubleshooting](#troubleshooting-by-platform)

---

## Before you start

### Python version

The suite is tested on **Python 3.11 and 3.12**. This trips people up on older long-term-support releases, which often ship something older as `python3`:

| OS release | Default `python3` | Action |
|---|---|---|
| Raspberry Pi OS Bookworm | 3.11 | Ready to go |
| Debian 12 Bookworm | 3.11 | Ready to go |
| Debian 11 Bullseye | 3.9 | Too old — upgrade or install 3.11+ |
| Ubuntu 24.04 LTS | 3.12 | Ready to go |
| Ubuntu 22.04 LTS | 3.10 | Below tested floor — install 3.11+ |
| Fedora 39+ | 3.12 | Ready to go |
| RHEL / Rocky / Alma 9 | 3.9 | Install the `python3.12` package |
| Arch / Manjaro | current | Ready to go |
| openSUSE Tumbleweed | current | Ready to go |
| Alpine 3.19+ | 3.11+ | Ready to go |

Check yours with `python3 --version`.

### Clone once

Every platform starts the same way:

```bash
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
```

### What the SDR tools give you

| Tool | Enables | Without it |
|---|---|---|
| `rtl_test` / `rtl_power` | RTL-SDR detection and live spectrum | Simulated spectrum |
| `rtl_fm` | Audio piping into decoders | No live decode |
| `multimon-ng` | POCSAG, FLEX, EAS, AFSK, CW, DTMF | Demo decode results |
| `dsd-fme` or `dsd` | DMR, P25, NXDN, D-STAR, YSF | Demo decode results |
| `hackrf_info` | HackRF detection | RTL only |
| `nmcli` or `iw` | Real WiFi scanning | Demo WiFi list |
| `bluetoothctl` | Real Bluetooth discovery | Demo BT list |

---

## Raspberry Pi

The one-shot installer is the recommended path and handles packages, the DVB driver conflict, the virtualenv, config, and a systemd service:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
chmod +x install.sh run.sh
sudo ./install.sh
```

Then open `http://<pi-ip>:8080` from any device on your LAN (`hostname -I` shows the address).

For the full walkthrough with hardware notes and DSD build steps, see the **[Install Guide](installation.md)**.

### Supported Pi models

| Model | Suitability |
|---|---|
| Pi 5 | Best. Handles two SDRs plus decode comfortably |
| Pi 4 (2 GB+) | Recommended. The reference target |
| Pi 400 | Same silicon as Pi 4; fine |
| Pi 3 / 3B+ | Works. Use one SDR; expect slower waterfall refresh |
| Pi Zero 2 W | Works for single-stick scanning; avoid live DSD |
| Pi Zero / Pi 1 (armv6) | Not recommended — too slow for FastAPI plus decode |

Use a **powered USB hub** for two or more SDR sticks. RTL dongles draw enough current to cause brownouts and USB resets on Pi ports alone.

### Pi OS variants

- **Raspberry Pi OS 64-bit (Bookworm)** — recommended.
- **Raspberry Pi OS 32-bit** — works; all packages exist for armhf.
- **Raspberry Pi OS Lite** — ideal for a headless receiver. Nothing here needs a desktop.
- **Ubuntu Server for Pi** — `install.sh` works, but Ubuntu Server uses netplan and may not have `nmcli`. The app falls back to `iw` automatically; install `network-manager` if you want richer WiFi data.
- **DietPi** — apt-based, so `install.sh` works. Install `git` first.

---

## macOS

Works on both Apple Silicon and Intel. Dashboard, spectrum, and decode all run; the **WiFi/Bluetooth catalog stays in demo mode** because macOS has no `nmcli`, `iw`, or `bluetoothctl`.

### App only

```bash
cd Pi-Spy-RF
chmod +x run.sh
./run.sh
```

Open <http://127.0.0.1:8080>.

If macOS Python is too old or missing, install it with [Homebrew](https://brew.sh):

```bash
brew install python@3.12
```

### With SDR hardware

```bash
brew install rtl-sdr hackrf sox
brew install multimon-ng   # for POCSAG / FLEX / EAS paging
```

Then re-run `./run.sh`, plug in the dongle, and press **Refresh** on the Devices panel.

### Apple Silicon PATH note

Homebrew installs to `/opt/homebrew` on Apple Silicon but `/usr/local` on Intel. If the app reports no tools even after `brew install`, your shell probably isn't picking up the Homebrew prefix:

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"   # Apple Silicon
eval "$(/usr/local/bin/brew shellenv)"      # Intel
```

Add that line to `~/.zprofile` to make it permanent, then verify with `which rtl_test`.

### Other macOS notes

- macOS may prompt for USB access the first time an SDR is opened — approve it.
- `dsd-fme` has no Homebrew formula; build from source if you need DMR/P25 decode.
- Apple Silicon Macs need no Rosetta; everything here is native.

---

## Windows

Two options: run natively (simplest), or use WSL2 (better tool availability, but USB passthrough is extra work).

### Native Windows

1. Install [Python 3.12](https://www.python.org/downloads/) and tick **Add python.exe to PATH**. Or use winget:

```powershell
winget install Python.Python.3.12
winget install Git.Git
```

2. Start the app:

```bat
cd Pi-Spy-RF
run.bat
```

`run.bat` creates the virtualenv, installs dependencies, copies the config, and starts the server on <http://127.0.0.1:8080>.

### Native Windows with an RTL-SDR

1. Install [Zadig](https://zadig.akeo.ie/).
2. In Zadig choose **Options → List All Devices**, select your dongle (shows as *Bulk-In, Interface (Interface 0)* or *RTL2838*), pick the **WinUSB** driver, and click **Replace Driver**.
3. Download Windows `rtl-sdr` binaries and put the folder containing `rtl_test.exe`, `rtl_power.exe`, and `rtl_fm.exe` on your `PATH`.
4. Confirm from a new terminal:

```powershell
rtl_test -t
```

5. Restart the app. Real devices replace the demo placeholders.

Windows builds of `multimon-ng` exist and work once on `PATH`. Enabling WinUSB means SDR# and other WinUSB apps can use the dongle, but the Windows TV/DVB driver no longer will.

### WSL2

WSL2 gives you the full Linux toolchain, which is handy for `multimon-ng` and `dsd-fme`:

```bash
wsl --install -d Ubuntu
```

Then follow the [Debian/Ubuntu](#debian-ubuntu-and-derivatives) steps inside WSL.

Two important limits:

- **USB is not passed through by default.** Install [usbipd-win](https://github.com/dorssel/usbipd-win) on Windows and attach the dongle to WSL, or the SDR stays invisible.
- **WiFi and Bluetooth scanning will not see your real adapters.** WSL2 has no direct radio access, so that panel stays in demo mode regardless of `nmcli` being installed.

Reach the dashboard from Windows at <http://127.0.0.1:8080> — WSL2 forwards localhost automatically.

### LAN access and firewall

To reach the dashboard from other devices, enable auth first, then allow the port:

```powershell
$env:PI_SPY_PASSWORD = "your-password"
New-NetFirewallRule -DisplayName "Pi-Spy-RF" -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow
```

Set `server.host: "0.0.0.0"` and `auth.enabled: true` in `config/config.yaml`. The app **refuses to bind a LAN address with auth disabled** unless you set `PI_SPY_ALLOW_INSECURE_LAN=1`.

---

## Linux

`install.sh` detects apt, dnf, yum, pacman, zypper, and apk, installs what it can, warns about anything unavailable, and skips the systemd step on systems without it:

```bash
chmod +x install.sh run.sh
sudo ./install.sh
```

Prefer to do it yourself, or on a distro not listed? The per-distro commands below install the same things. Everything except Python is optional — missing tools only reduce the app to demo mode for that feature.

### Debian, Ubuntu, and derivatives

Covers Debian, Ubuntu, Linux Mint, Pop!\_OS, Kali, Raspberry Pi OS, and other apt-based systems.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git \
  rtl-sdr hackrf sox multimon-ng \
  bluez bluetooth iw wireless-tools network-manager libusb-1.0-0
```

### Fedora

```bash
sudo dnf install -y python3 python3-pip git \
  rtl-sdr rtl-sdr-devel hackrf sox multimon-ng \
  bluez iw NetworkManager libusbx
```

### RHEL, Rocky, Alma, CentOS Stream

The SDR packages come from EPEL, and the default Python is too old:

```bash
sudo dnf install -y epel-release
sudo dnf install -y python3.12 python3.12-pip git \
  sox bluez iw NetworkManager libusbx
sudo dnf install -y rtl-sdr hackrf      # from EPEL
```

Then point the virtualenv at the newer interpreter:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.main
```

`multimon-ng` is often unpackaged here — build it from source if you need paging decode.

### Arch, Manjaro, EndeavourOS

```bash
sudo pacman -Syu --needed python python-pip git \
  rtl-sdr hackrf sox \
  bluez bluez-utils iw wireless_tools networkmanager libusb
```

`multimon-ng` lives in the AUR:

```bash
yay -S multimon-ng      # or: paru -S multimon-ng
```

### openSUSE

```bash
sudo zypper refresh
sudo zypper install python3 python3-pip git \
  rtl-sdr hackrf sox bluez iw NetworkManager libusb-1_0-0
```

If `rtl-sdr` or `multimon-ng` aren't found, add the Packman repository or search with `zypper se -s rtl`.

### Alpine

```bash
doas apk add python3 py3-pip git rtl-sdr sox bluez iw networkmanager libusb
```

Alpine is musl-based, so some RF tools are unpackaged; `multimon-ng` and `dsd-fme` usually need building. There is no systemd — use OpenRC or run `./run.sh` under a supervisor.

### Other distributions

Void, Gentoo, Slackware, NixOS and friends aren't auto-detected, but nothing here is distro-specific. Install the equivalents of: **Python 3.11+ with venv, rtl-sdr, hackrf, multimon-ng, sox, bluez, iw, NetworkManager, libusb**, then run `./run.sh`. Search your package manager for the names, for example:

```bash
apt-cache search rtl-sdr        # Debian family
dnf search rtl-sdr             # Fedora family
pacman -Ss rtl-sdr             # Arch family
zypper se rtl-sdr              # openSUSE
apk search rtl-sdr             # Alpine
xbps-query -Rs rtl-sdr         # Void
emerge --search rtl-sdr        # Gentoo
```

### RTL-SDR driver conflict (all Linux)

The kernel's DVB television driver claims RTL dongles before SDR software can. `install.sh` does this for you; manually it is:

```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
sudo modprobe -r dvb_usb_rtl28xxu
```

Unplug and replug the dongle, then confirm with `rtl_test -t`.

### USB permissions (all Linux)

Reading an SDR as a normal user needs group membership rather than root:

```bash
sudo usermod -aG plugdev $USER
# log out and back in
```

---

## Auto-start on boot

### Linux and Raspberry Pi (systemd)

`install.sh` does this automatically. Manually:

```bash
sudo cp scripts/pi-spy-rf.service /etc/systemd/system/
sudo nano /etc/systemd/system/pi-spy-rf.service   # fix User= and paths
sudo systemctl daemon-reload
sudo systemctl enable --now pi-spy-rf
sudo systemctl status pi-spy-rf
```

Logs: `journalctl -u pi-spy-rf -f`

### macOS (launchd)

Save as `~/Library/LaunchAgents/com.pi-spy-rf.plist`, correcting both paths:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.pi-spy-rf</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/Pi-Spy-RF/.venv/bin/python</string>
    <string>-m</string>
    <string>app.main</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/YOU/Pi-Spy-RF</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.pi-spy-rf.plist
```

### Windows (Task Scheduler)

```powershell
$action  = New-ScheduledTaskAction -Execute "C:\Path\To\Pi-Spy-RF\.venv\Scripts\python.exe" `
                                   -Argument "-m app.main" `
                                   -WorkingDirectory "C:\Path\To\Pi-Spy-RF"
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "Pi-Spy-RF" -Action $action -Trigger $trigger -RunLevel Highest
```

For a proper Windows service with restart-on-failure, wrap it with [NSSM](https://nssm.cc/).

---

## Environment variables

| Variable | Purpose |
|---|---|
| `PI_SPY_PASSWORD` | Auth password (preferred over storing it in YAML) |
| `PI_SPY_SECURE_COOKIE=1` | Mark the session cookie `Secure` (behind HTTPS) |
| `PI_SPY_NO_DEMO=1` | Never invent placeholder SDR devices |
| `PI_SPY_ALLOW_INSECURE_LAN=1` | Permit binding a LAN address with auth off (not advised) |
| `INSTALL_DIR` | Override the install path used by `install.sh` |
| `SERVICE_USER` | User the systemd service runs as |
| `ENABLE_SERVICE=0` | Skip systemd setup during install |
| `INSTALL_RF_TOOLS=0` | Skip system packages during install |

---

## Verify the install

```bash
curl -s http://127.0.0.1:8080/api/health
# {"ok":true,"service":"pi-spy-rf","version":"0.8.1"}
```

Check which tools were found:

```bash
curl -s http://127.0.0.1:8080/api/tools
```

Any `false` entry means that feature falls back to demo data. Interactive API docs: <http://127.0.0.1:8080/docs>

---

## Feature matrix by platform

| Feature | Pi / Linux | macOS | Windows native | WSL2 |
|---|---|---|---|---|
| Web dashboard | Yes | Yes | Yes | Yes |
| Demo spectrum and decode | Yes | Yes | Yes | Yes |
| RTL-SDR spectrum (`rtl_power`) | Yes | Yes | Yes, with Zadig | With usbipd |
| HackRF | Yes | Yes | Yes, with Zadig | With usbipd |
| Paging decode (`multimon-ng`) | Yes | Yes (brew) | If on PATH | Yes |
| Digital voice (`dsd-fme`) | Build | Build | Rare | Build |
| WiFi scan (`nmcli` / `iw`) | Yes | Demo | Demo | Demo |
| Bluetooth (`bluetoothctl`) | Yes | Demo | Demo | Demo |
| Auto-start on boot | systemd | launchd | Task Scheduler | Manual |

---

## Troubleshooting by platform

### All platforms — only demo devices appear

Plug the SDR in *before* starting the app, confirm `rtl_test -t` works outside the app, then restart. Check `/api/tools` to see what the app can actually find; a tool installed but not on the service's `PATH` is the usual culprit.

### Linux — `usb_claim_interface error -6`

Another process holds the dongle, or the DVB driver grabbed it. Blacklist the driver as shown above, and make sure two workers aren't assigned the same stick (the dashboard's **Auto-assign** keeps scan and decode on separate radios).

### Linux — port 8080 in use

Change `server.port` in `config/config.yaml`, or find the conflict with `sudo ss -tulpn | grep 8080`.

### Linux — service fails right after install

```bash
journalctl -u pi-spy-rf -n 50 --no-pager
```

Confirm `User=`, `WorkingDirectory=`, and `ReadWritePaths=` in the unit file match your actual install path.

### macOS — tools installed but not detected

A Homebrew PATH problem nearly every time. Run `which rtl_test`; if empty, apply the `brew shellenv` line above and restart the app from that shell.

### Windows — `rtl_test` not recognised

The binaries aren't on `PATH`. Add the folder holding `rtl_test.exe`, then open a **new** terminal — `PATH` changes don't reach already-running shells.

### Windows — dongle visible but fails to open

The WinUSB driver replacement in Zadig either didn't complete or was applied to the wrong interface. Re-run Zadig with **List All Devices** enabled and target *Interface 0*.

### WSL2 — no SDR devices

Expected without USB passthrough. Set up usbipd-win, then `usbipd attach --wsl --busid <id>`.

---

## Security reminder

SDR reception and wireless scanning are regulated in many places. Only monitor frequencies and networks you are authorised to. **Enable `auth.enabled` and set `PI_SPY_PASSWORD` before exposing the dashboard on any network you do not fully control.** See [SECURITY.md](../SECURITY.md) / [security.md](security.md).
