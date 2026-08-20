#!/usr/bin/env bash
# Pi-Spy-RF one-shot installer for Raspberry Pi OS (Bookworm / Debian-based)
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "$0")" && pwd)}"
SERVICE_USER="${SERVICE_USER:-$USER}"
ENABLE_SERVICE="${ENABLE_SERVICE:-1}"
INSTALL_RF_TOOLS="${INSTALL_RF_TOOLS:-1}"

log() { echo "[Pi-Spy-RF] $*"; }
log "Install directory: $INSTALL_DIR"
cd "$INSTALL_DIR"

if [[ "$INSTALL_RF_TOOLS" == "1" && $EUID -eq 0 ]]; then
  log "Updating apt and installing system packages..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3 python3-venv python3-pip git \
    rtl-sdr hackrf sox \
    multimon-ng \
    bluez bluetooth \
    iw wireless-tools network-manager \
    libusb-1.0-0

  log "Blacklisting RTL-SDR DVB driver (if not already)..."
  echo 'blacklist dvb_usb_rtl28xxu' > /etc/modprobe.d/rtl-sdr-blacklist.conf
  modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true

  log "Optional: install dsd-fme for DMR/P25/NXDN live decode"
  log "  See INSTALL.md — Digital voice decode (DSD)"
elif [[ "$INSTALL_RF_TOOLS" == "1" && $EUID -ne 0 ]]; then
  log "Skipping apt packages (not root). Run: sudo ./install.sh"
fi

run_as_user() {
  if [[ $EUID -eq 0 ]]; then
    sudo -u "$SERVICE_USER" "$@"
  else
    "$@"
  fi
}

log "Creating Python virtual environment..."
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  run_as_user python3 -m venv "$INSTALL_DIR/.venv"
fi
run_as_user "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
run_as_user "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"

if [[ ! -f "$INSTALL_DIR/config/config.yaml" ]]; then
  cp "$INSTALL_DIR/config/config.example.yaml" "$INSTALL_DIR/config/config.yaml"
  if [[ $EUID -eq 0 ]]; then
    chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/config/config.yaml"
  fi
fi

mkdir -p "$INSTALL_DIR/data"
if [[ $EUID -eq 0 ]]; then
  chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/data" "$INSTALL_DIR/config"
fi

chmod +x "$INSTALL_DIR/run.sh" "$INSTALL_DIR/install.sh"

if [[ "$ENABLE_SERVICE" == "1" && $EUID -eq 0 ]]; then
  log "Installing systemd service..."
  sed "s|User=pi|User=$SERVICE_USER|g; s|/home/pi/Pi-Spy-RF|$INSTALL_DIR|g" \
    "$INSTALL_DIR/scripts/pi-spy-rf.service" > /etc/systemd/system/pi-spy-rf.service
  systemctl daemon-reload
  systemctl enable pi-spy-rf.service
  systemctl restart pi-spy-rf.service || true
  log "Check status: sudo systemctl status pi-spy-rf"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
log "Done."
log "Dashboard: http://${IP:-127.0.0.1}:8080"
log "Manual start: cd $INSTALL_DIR && ./run.sh"
log "Full guide: $INSTALL_DIR/INSTALL.md"
