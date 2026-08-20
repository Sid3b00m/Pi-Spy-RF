# Pi-Spy-RF — Install Guide

Step-by-step setup for **Raspberry Pi 3 / 4 / 5** running Raspberry Pi OS (Bookworm or newer).

Estimated time: **15–30 minutes** (plus optional DSD build time).

> **Not only for Pi:** the same app runs on **Linux, macOS, and Windows** (demo mode without SDR). See [docs/platforms.md](docs/platforms.md) and [SECURITY.md](SECURITY.md).

---

## What you need

| Item | Notes |
|------|--------|
| Raspberry Pi 3/4/5 | 2 GB RAM minimum; 4 GB+ recommended with multiple SDRs |
| microSD (16 GB+) | Raspberry Pi OS (64-bit recommended) |
| Network | Ethernet or WiFi — dashboard is LAN-accessible |
| RTL-SDR dongle | Primary spectrum scanner (required for real RF) |
| HackRF (optional) | Better for wideband decode / second channel |
| USB hub (optional) | Powered hub if running 2+ SDR sticks |

Software (installed automatically by `install.sh`):

- Python 3, rtl-sdr, multimon-ng, hackrf tools, bluez, iw, NetworkManager

---

## Quick install (recommended)

On your Pi, after flashing Raspberry Pi OS and completing first-boot setup:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
chmod +x install.sh run.sh
sudo ./install.sh
```

When finished, open in any browser on your network:

```text
http://<pi-ip-address>:8080
```

Find your Pi IP with `hostname -I`.

The installer will:

1. Install system RF/wireless packages
2. Blacklist the RTL DVB TV driver (so SDR mode works)
3. Create a Python virtualenv and install dependencies
4. Copy `config/config.example.yaml` → `config/config.yaml`
5. Enable the `pi-spy-rf` systemd service (auto-start on boot)

---

## Step-by-step (manual)

Use this if you prefer to understand each step, or if the one-shot installer fails.

### Step 1 — Flash Raspberry Pi OS

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Choose **Raspberry Pi OS (64-bit)**
3. Enable SSH and set username/password in imager **Advanced options** (recommended)
4. Boot the Pi and connect to your network

### Step 2 — Update the system

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### Step 3 — Clone Pi-Spy-RF

```bash
cd ~
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
```

### Step 4 — Install system packages

```bash
sudo apt install -y \
  python3 python3-venv python3-pip git \
  rtl-sdr hackrf sox multimon-ng \
  bluez bluetooth iw wireless-tools network-manager \
  libusb-1.0-0
```

### Step 5 — Fix RTL-SDR driver conflict

The stock DVB driver grabs RTL dongles before SDR software can use them.

```bash
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/rtl-sdr-blacklist.conf
sudo modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
```

Unplug and replug the RTL dongle, then verify:

```bash
rtl_test -t
```

You should see a real device (not "Failed to open rtlsdr device").

### Step 6 — Python app setup

```bash
cd ~/Pi-Spy-RF
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
```

### Step 7 — First run

```bash
./run.sh
```

Open `http://127.0.0.1:8080` on the Pi, or `http://<pi-ip>:8080` from your phone/laptop.

### Step 8 — Auto-start on boot (optional)

```bash
sudo cp scripts/pi-spy-rf.service /etc/systemd/system/
# Edit paths/user if you did not install under /home/pi/Pi-Spy-RF
sudo nano /etc/systemd/system/pi-spy-rf.service
sudo systemctl daemon-reload
sudo systemctl enable --now pi-spy-rf
sudo systemctl status pi-spy-rf
```

---

## First-run checklist (dashboard)

After the web UI loads:

1. **Devices** — Confirm RTL-SDR / HackRF appear (not just demo devices)
2. **SDR load balance** — Click **Auto-assign** (RTL → scan, HackRF → decode)
3. **Spectrum** — Start spectrum worker; watch live canvas / waterfall
4. **Decode** — Start decode worker; POCSAG/FLEX need `multimon-ng` (installed by default)
5. **WiFi / Bluetooth** — Start wireless scan; edit known MACs as needed

API health check:

```bash
curl -s http://127.0.0.1:8080/api/health | python3 -m json.tool
```

---

## Configuration

Edit `config/config.yaml`:

```yaml
server:
  host: "0.0.0.0"   # listen on all interfaces
  port: 8080

auth:
  enabled: true     # recommended on shared LANs
  username: "ops"
  # password via env: export PI_SPY_PASSWORD='your-secret'
```

Restart after changes:

```bash
sudo systemctl restart pi-spy-rf
# or Ctrl+C and ./run.sh for manual runs
```

---

## Digital voice decode (DSD)

Paging (POCSAG/FLEX) works out of the box via **multimon-ng**.

For **DMR, P25, NXDN, D-STAR**, install **dsd-fme** (not bundled — build varies by Pi model):

```bash
sudo apt install -y build-essential cmake git libitpp-dev libpulse-dev
git clone https://github.com/lwvmobile/dsd_fme.git
cd dsd_fme
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo cp dsd_fme /usr/local/bin/
```

Verify:

```bash
dsd_fme -h
```

Pi-Spy-RF auto-detects `dsd_fme` or legacy `dsd` on PATH.

---

## WiFi monitor mode (advanced)

Default WiFi scanning uses **nmcli** / **iw** in managed mode (nearby APs and clients).

Monitor mode for deeper packet capture requires a compatible USB adapter and manual setup — not automated by this installer. Set `wifi.interface` in config to your dongle (e.g. `wlan1`).

---

## Windows development (no SDR)

For UI/API development on Windows without hardware:

```bat
git clone https://github.com/Sid3b00m/Pi-Spy-RF.git
cd Pi-Spy-RF
run.bat
```

Demo SDR devices and simulated spectrum/decode data are used when no sticks are found.

---

## Troubleshooting

### RTL dongle not detected

```bash
lsusb | grep -i realtek
rtl_test -t
dmesg | tail -20
```

Ensure DVB driver is blacklisted (Step 5) and reboot if needed.

### Permission denied on `/dev/bus/usb`

```bash
sudo usermod -aG plugdev $USER
# log out and back in
```

### Port 8080 already in use

Change `server.port` in `config/config.yaml` or stop the conflicting service.

### Service fails after install

```bash
journalctl -u pi-spy-rf -n 50 --no-pager
```

Check `WorkingDirectory` and `User` in `/etc/systemd/system/pi-spy-rf.service` match your install path.

### Only demo devices in UI

- Confirm SDR is plugged in before starting the app
- Run `rtl_test -t` outside the app
- Restart: `sudo systemctl restart pi-spy-rf`

---

## Uninstall

```bash
sudo systemctl disable --now pi-spy-rf
sudo rm /etc/systemd/system/pi-spy-rf.service
sudo systemctl daemon-reload
rm -rf ~/Pi-Spy-RF
sudo rm -f /etc/modprobe.d/rtl-sdr-blacklist.conf
```

---

## Support

- GitHub: https://github.com/Sid3b00m/Pi-Spy-RF
- Roadmap: [ROADMAP.md](ROADMAP.md)
