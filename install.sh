#!/usr/bin/env bash
# Pi-Spy-RF installer.
#
# Supports Raspberry Pi OS, Debian, Ubuntu, Mint, Fedora, RHEL/Rocky/Alma,
# Arch, openSUSE, Alpine, Void and Gentoo, with systemd or OpenRC auto-start.
# On an unrecognised system it still sets up the Python app and tells you which
# system packages to install by hand.
#
# Useful overrides:
#   INSTALL_RF_TOOLS=0   skip system packages, set up the Python app only
#   ENABLE_SERVICE=0     do not install an auto-start service
#   SERVICE_USER=name    run the service as this user (default: the sudo caller)
#   SDR_GROUP=name       group granted USB access (default: plugdev)
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
  for pm in apt-get dnf yum pacman zypper apk xbps-install emerge; do
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
      xbps-install) xbps-install -y "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p" ;;
      emerge)  emerge --quiet --noreplace "$p" >/dev/null 2>&1 || warn "optional package unavailable: $p" ;;
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
      # musl builds of uvicorn[standard]'s extras are not always published as
      # wheels, so pip has to compile them and needs a toolchain present.
      install_optional build-base python3-dev linux-headers libffi-dev
      install_optional rtl-sdr hackrf networkmanager multimon-ng
      ;;
    xbps-install)
      log "Detected xbps (Void). Installing packages..."
      xbps-install -Sy python3 python3-pip git sox bluez iw NetworkManager libusb
      install_optional rtl-sdr hackrf multimon-ng
      ;;
    emerge)
      log "Detected emerge (Gentoo). Installing packages..."
      warn "Gentoo builds from source - this step can take a long time."
      emerge --quiet --noreplace \
        dev-lang/python dev-vcs/git media-sound/sox net-wireless/bluez net-wireless/iw
      install_optional net-wireless/rtl-sdr net-wireless/hackrf-tools \
        net-wireless/multimon-ng net-misc/networkmanager
      ;;
    none)
      warn "No supported package manager found."
      warn "Tried: apt-get, dnf, yum, pacman, zypper, apk, xbps-install, emerge."
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

# Reading the SDR over USB needs group membership rather than root. Only Debian
# ships a plugdev group and matching rtl-sdr udev rules; elsewhere the group is
# absent and the packaged rules rely on uaccess, which covers an interactive
# login but not the system user a service runs as. So create the group, install
# our own rules, and join the group regardless of distro.
SDR_GROUP="${SDR_GROUP:-plugdev}"

group_exists() {
  getent group "$1" >/dev/null 2>&1 || grep -q "^$1:" /etc/group 2>/dev/null
}

setup_usb_access() {
  if ! group_exists "$SDR_GROUP"; then
    log "Creating the $SDR_GROUP group for SDR access..."
    groupadd -f "$SDR_GROUP" 2>/dev/null ||
      addgroup "$SDR_GROUP" 2>/dev/null ||
      warn "could not create the $SDR_GROUP group"
  fi

  if group_exists "$SDR_GROUP"; then
    usermod -aG "$SDR_GROUP" "$SERVICE_USER" 2>/dev/null ||
      addgroup "$SERVICE_USER" "$SDR_GROUP" 2>/dev/null ||
      warn "could not add $SERVICE_USER to $SDR_GROUP; SDR access may need root"
  fi

  local rules_src="$INSTALL_DIR/scripts/60-pi-spy-rf-sdr.rules"
  if [[ -d /etc/udev/rules.d && -f "$rules_src" ]]; then
    log "Installing SDR udev rules..."
    sed "s|GROUP=\"plugdev\"|GROUP=\"$SDR_GROUP\"|g" \
      "$rules_src" > /etc/udev/rules.d/60-pi-spy-rf-sdr.rules
    udevadm control --reload-rules >/dev/null 2>&1 || true
    udevadm trigger >/dev/null 2>&1 || true
  fi

  log "Group changes apply at next login; replug the dongle to pick up the rules."
}

if [[ $EUID -eq 0 ]]; then
  setup_usb_access
fi

# --------------------------------------------------------------------------
# Auto-start (systemd or OpenRC)
# --------------------------------------------------------------------------

install_systemd_service() {
  log "Installing systemd service..."
  sed "s|User=pi|User=$SERVICE_USER|g; s|/home/pi/Pi-Spy-RF|$INSTALL_DIR|g" \
    "$INSTALL_DIR/scripts/pi-spy-rf.service" > /etc/systemd/system/pi-spy-rf.service
  systemctl daemon-reload
  systemctl enable pi-spy-rf.service
  systemctl restart pi-spy-rf.service || true
  log "Check status: sudo systemctl status pi-spy-rf"
}

install_openrc_service() {
  local src="$INSTALL_DIR/scripts/pi-spy-rf.openrc"
  if [[ ! -f "$src" ]]; then
    warn "scripts/pi-spy-rf.openrc missing; skipping the auto-start service."
    return 0
  fi
  log "Installing OpenRC service..."
  sed "s|pi:pi|$SERVICE_USER:$SERVICE_USER|g; s|/home/pi/Pi-Spy-RF|$INSTALL_DIR|g" \
    "$src" > /etc/init.d/pi-spy-rf
  chmod +x /etc/init.d/pi-spy-rf
  rc-update add pi-spy-rf default >/dev/null 2>&1 || warn "could not enable the service at boot"
  rc-service pi-spy-rf restart >/dev/null 2>&1 || true
  log "Check status: rc-service pi-spy-rf status"
}

if [[ "$ENABLE_SERVICE" == "1" && $EUID -eq 0 ]]; then
  if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    install_systemd_service
  elif command -v rc-update >/dev/null 2>&1; then
    install_openrc_service
  else
    warn "No systemd or OpenRC found; skipping the auto-start service."
    warn "Start manually with ./run.sh, or wire it into your init system"
    warn "(runit, s6, dinit) using scripts/pi-spy-rf.openrc as a reference."
  fi
fi

# busybox hostname (Alpine, Void's minimal images) has no -I.
IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
if [[ -z "$IP" ]] && command -v ip >/dev/null 2>&1; then
  IP=$(ip -4 route get 1.1.1.1 2>/dev/null |
    awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}' || true)
fi
log "Done."
log "Default bind is 127.0.0.1 (see config). Local: http://127.0.0.1:8080"
log "For LAN access: set server.host=0.0.0.0, enable auth, then open http://${IP:-<host-ip>}:8080"
log "Manual start: cd $INSTALL_DIR && ./run.sh"
log "Full guide: $INSTALL_DIR/INSTALL.md"
