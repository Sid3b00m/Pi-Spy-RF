#!/usr/bin/env bash
# Claim a USB SDR that a remote usbip server exports.
#
# For hosts where the radio is plugged into a different machine than the one
# running Pi-Spy-RF: a Windows box running usbipd-win, or another Linux host
# running usbipd. Hyper-V has no generic USB passthrough, so for a Hyper-V
# guest USB/IP is the only way to reach a dongle at all.
#
# Configure with USBIP_HOST and USBIP_BUSID, normally through the
# EnvironmentFile named by scripts/pi-spy-rf-usbip.service:
#
#     USBIP_HOST=192.168.0.10
#     USBIP_BUSID=1-11
#
# Find the busid on the machine holding the radio with "usbipd list" (Windows)
# or "usbip list -l" (Linux), and share it there first:
#
#     usbipd bind --busid 1-11
#
# Needs root for modprobe and for the attach itself.
set -euo pipefail

HOST=${USBIP_HOST:-}
BUSID=${USBIP_BUSID:-}
ATTEMPTS=${USBIP_ATTEMPTS:-30}
DELAY=${USBIP_RETRY_SECONDS:-4}

if [ -z "$HOST" ] || [ -z "$BUSID" ]; then
    echo "set USBIP_HOST and USBIP_BUSID first (see the comments in this script)" >&2
    exit 2
fi

# vhci-hcd is the virtual host controller an imported device lands on. Kernels
# built for cloud or virtual guests often drop it, and some omit USB entirely:
# Debian's cloud kernel has no /sys/bus/usb at all.
if ! modprobe vhci-hcd 2>/dev/null; then
    echo "cannot load vhci-hcd; this kernel may lack USB/IP support" >&2
fi

# Idempotent so the unit can be restarted without detaching first.
if usbip port 2>/dev/null | grep -qF "usbip://$HOST:3240/$BUSID"; then
    echo "already attached: $HOST busid $BUSID"
    exit 0
fi

# The server is frequently not serving yet when a guest boots, and a host that
# has just released the device needs a moment before it re-exports it, so retry
# instead of failing the unit.
for attempt in $(seq 1 "$ATTEMPTS"); do
    if usbip attach -r "$HOST" -b "$BUSID"; then
        echo "attached $HOST busid $BUSID on attempt $attempt"
        exit 0
    fi
    sleep "$DELAY"
done

echo "could not attach $HOST busid $BUSID after $ATTEMPTS attempts" >&2
exit 1
