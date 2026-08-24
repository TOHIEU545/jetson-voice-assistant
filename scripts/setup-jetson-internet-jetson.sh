#!/usr/bin/env bash
set -euo pipefail

LAPTOP_USB_IP="${LAPTOP_USB_IP:-192.168.55.100}"
JETSON_USB_IP="${JETSON_USB_IP:-192.168.55.1}"

echo "=== Jetson Internet Sharing - Jetson Setup ==="

sudo -v

# Confirm that the USB network is present.
if ! ip -o -4 addr show | grep -q "${JETSON_USB_IP}/"; then
    echo "[WARN] ${JETSON_USB_IP} is not currently assigned on this Jetson."
    echo "Current IPv4 addresses:"
    ip -4 addr
    echo
    echo "Continuing anyway in case the USB interface uses a different prefix..."
fi

echo "[1/3] Checking laptop USB gateway..."
if ! ping -c 1 -W 2 "${LAPTOP_USB_IP}" >/dev/null 2>&1; then
    echo "[ERROR] Cannot reach laptop gateway ${LAPTOP_USB_IP}."
    echo "Run the laptop setup script first."
    exit 1
fi

echo "[2/3] Setting default route via laptop..."
sudo ip route replace default via "${LAPTOP_USB_IP}"

echo "[3/3] Testing Internet and DNS..."

if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
    echo "[OK] Internet access works."
else
    echo "[ERROR] Cannot reach 8.8.8.8."
    echo
    echo "Current routes:"
    ip route
    exit 1
fi

if ping -c 1 -W 3 google.com >/dev/null 2>&1; then
    echo "[OK] DNS works."
else
    echo "[WARN] Internet works, but DNS lookup failed."
    echo "Current resolver configuration:"
    cat /etc/resolv.conf || true
    exit 1
fi

echo
echo "======================================"
echo " Jetson Internet is READY"
echo "======================================"
echo
ip route
