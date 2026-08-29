#!/usr/bin/env bash
# Pi-Spy-RF installer.
#
# Supports Raspberry Pi OS, Debian, Ubuntu, Mint, Fedora, RHEL/Rocky/Alma,
# Arch, openSUSE and Alpine. On an unrecognised system it still sets up the
# Python app and tells you which system packages to install by hand.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "$0")" && pwd)}"
SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-$(id -un)}}"
ENABLE_SERVICE="${ENABLE_SERVICE:-1}"
INSTALL_RF_TOOLS="${INSTALL_RF_TOOLS:-1}"

log() { echo "[Pi-Spy-RF] $*"; }
warn() { echo "[Pi-Spy-RF] warning: $*" >&2; }

log "Install directory: $INSTALL_DIR"
cd "$INSTALL_DIR"

# --------------------------------------------------------------------------
# System packages
# --------------------------------------------------------------------------

detect_pm() {
  local pm
  for pm in apt-get dnf yum pacman zypper apk; do
    if command -v "$pm" >/dev/null 2>&1; then
      echo "$pm"
      return 0
    fi
  done
  echo "none"
}

PM="$(detect_pm)"

# Optional packages are installed one at a time: several are absent or live in
# a third-party repo on some distros, and a single miss must not abort the run.
install_optional() {
  local p
  for p in "$@"; do
    case "$PM" in
      apt-get) DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p" ;;
      dnf)     dnf install -y -q "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p" ;;
      yum)     yum install -y -q "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p" ;;
      pacman)  pacman -S --noconfirm --needed "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p (try the AUR)" ;;
      zypper)  zypper --non-interactive install "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p" ;;
      apk)     apk add --no-cache "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p" ;;
    esac
  done
}

install_system_packages() {
  case "$PM" in
    apt-get)
      log "Detected apt (Debian / Ubuntu / Raspberry Pi OS). Installing packages..."
      apt-get update -qq
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        python3 python3-venv python3-pip git rtl-sdr sox bluez iw libusb-1.0-0
      install_optional hackrf multimon-ng bluetooth wireless-tools network-manager
      ;;
    dnf|yum)
      log "Detected $PM (Fedora / RHEL / Rocky / Alma). Installing packages..."
      # rtl-sdr and hackrf live in EPEL on the RHEL rebuilds.
      if ! grep -qi fedora /etc/os-release 2>/dev/null; then
        install_optional epel-release
      fi
      "$PM" install -y -q python3 python3-pip git sox bluez iw NetworkManager libusbx || \
        "$PM" install -y -q python3 python3-pip git sox bluez iw NetworkManager libusb1
      install_optional rtl-sdr rtl-sdr-devel hackrf multimon-ng
      ;;
    pacman)
      log "Detected pacman (Arch / Manjaro / EndeavourOS). Installing packages..."
      pacman -Sy --noconfirm --needed python python-pip git rtl-sdr sox bluez bluez-utils iw libusb
      install_optional hackrf networkmanager wireless_tools multimon-ng
      ;;
    zypper)
      log "Detected zypper (openSUSE). Installing packages..."
      zypper --non-interactive refresh
      zypper --non-interactive install python3 python3-pip git sox bluez iw NetworkManager
      install_optional rtl-sdr hackrf multimon-ng libusb-1_0-0
      ;;
    apk)
      log "Detected apk (Alpine). Installing packages..."
      apk add --no-cache python3 py3-pip git sox bluez iw libusb
      install_optional rtl-sdr hackrf networkmanager multimon-ng
      ;;
    none)
      warn "No supported package manager found (apt/dnf/yum/pacman/zypper/apk)."
      warn "Install these yourself, then re-run: python3 + venv, rtl-sdr, hackrf,"
      warn "multimon-ng, sox, bluez, iw, NetworkManager, libusb."
      ;;
  esac
}

if [[ "$INSTALL_RF_TOOLS" == "1" && $EUID -eq 0 ]]; then
  install_system_packages

  # The kernel DVB television driver claims RTL dongles before SDR tools can.
  if [[ -d /etc/modprobe.d ]]; then
    log "Blacklisting the RTL-SDR DVB driver..."
    echo 'blacklist dvb_usb_rtl28xxu' > /etc/modprobe.d/rtl-sdr-blacklist.conf
    modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
  fi

  log "Optional: install dsd-fme for DMR/P25/NXDN live decode"
  log "  See INSTALL.md - Digital voice decode (DSD)"
elif [[ "$INSTALL_RF_TOOLS" == "1" && $EUID -ne 0 ]]; then
  log "Skipping system packages (not root). Re-run as: sudo ./install.sh"
fi

# --------------------------------------------------------------------------
# Python application
# --------------------------------------------------------------------------

run_as_user() {
  if [[ $EUID -eq 0 ]]; then
    sudo -u "$SERVICE_USER" "$@"
  else
    "$@"
  fi
}

PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  warn "Python 3 not found. Install Python 3.11+ and re-run this script."
  exit 1
fi

log "Creating Python virtual environment..."
if [[ ! -d "$INSTALL_DIR/.venv" ]]; then
  run_as_user "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
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

# Reading the SDR over USB normally needs group membership rather than root.
if [[ $EUID -eq 0 ]] && getent group plugdev >/dev/null 2>&1; then
  usermod -aG plugdev "$SERVICE_USER" 2>/dev/null || true
fi

# --------------------------------------------------------------------------
# Auto-start (systemd only)
# --------------------------------------------------------------------------

if [[ "$ENABLE_SERVICE" == "1" && $EUID -eq 0 ]]; then
  if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    log "Installing systemd service..."
    sed "s|User=pi|User=$SERVICE_USER|g; s|/home/pi/Pi-Spy-RF|$INSTALL_DIR|g" \
      "$INSTALL_DIR/scripts/pi-spy-rf.service" > /etc/systemd/system/pi-spy-rf.service
    systemctl daemon-reload
    systemctl enable pi-spy-rf.service
    systemctl restart pi-spy-rf.service || true
    log "Check status: sudo systemctl status pi-spy-rf"
  else
    warn "systemd not present; skipping the auto-start service."
    warn "Start manually with ./run.sh, or use your init system (OpenRC, runit, launchd)."
  fi
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
log "Done."
log "Default bind is 127.0.0.1 (see config). Local: http://127.0.0.1:8080"
log "For LAN access: set server.host=0.0.0.0, enable auth, then open http://${IP:-<host-ip>}:8080"
log "Manual start: cd $INSTALL_DIR && ./run.sh"
log "Full guide: $INSTALL_DIR/INSTALL.md"
