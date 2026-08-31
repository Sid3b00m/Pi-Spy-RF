#!/usr/bin/env bash
# Release a USB/IP device imported by usbip-attach.sh.
#
# Reads the same USBIP_HOST and USBIP_BUSID as the attach script. Needs root.
set -euo pipefail

HOST=${USBIP_HOST:-}
BUSID=${USBIP_BUSID:-}

if [ -z "$HOST" ] || [ -z "$BUSID" ]; then
    echo "set USBIP_HOST and USBIP_BUSID first" >&2
    exit 2
fi

# "usbip detach" wants a local port number, which appears nowhere else. In
# "usbip port" output the port heading comes first and the remote endpoint two
# lines later, so keep the most recent heading and print it once the endpoint
# matches:
#
#     Port 00: <Port in Use> at High Speed(480Mbps)
#            OpenMoko, Inc. : Great Scott Gadgets HackRF One SDR (1d50:6089)
#            1-1 -> usbip://192.168.0.10:3240/1-11
port=$(usbip port 2>/dev/null | awk -v want="usbip://$HOST:3240/$BUSID" '
    /^Port [0-9]+:/  { p = $2; sub(":", "", p) }
    index($0, want)  { print p; exit }
')

if [ -n "$port" ]; then
    usbip detach -p "$port"
    echo "detached port $port"
else
    echo "not attached: $HOST busid $BUSID"
fi
