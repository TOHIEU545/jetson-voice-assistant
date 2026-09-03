#!/usr/bin/env bash
set -euo pipefail

LAPTOP_USB_IP="${LAPTOP_USB_IP:-192.168.55.100}"
JETSON_USB_IP="${JETSON_USB_IP:-192.168.55.1}"

DNS_PRIMARY="${DNS_PRIMARY:-8.8.8.8}"
DNS_SECONDARY="${DNS_SECONDARY:-1.1.1.1}"

echo "=== Jetson Internet Sharing - Jetson Setup ==="

sudo -v

# Detect the Jetson USB/bridge interface that owns 192.168.55.1.
USB_IF="$(
    ip -o -4 addr show |
    awk -v ip="${JETSON_USB_IP}" '
        $4 ~ ("^" ip "/") {
            print $2
            exit
        }
    '
)"

if [[ -z "${USB_IF}" ]]; then
    echo "[ERROR] Cannot find an interface with ${JETSON_USB_IP}."
    echo
    echo "Current IPv4 addresses:"
    ip -4 addr
    exit 1
fi

echo "[INFO] Laptop USB gateway  : ${LAPTOP_USB_IP}"
echo "[INFO] Jetson USB IP       : ${JETSON_USB_IP}"
echo "[INFO] Jetson USB interface: ${USB_IF}"
echo "[INFO] DNS primary         : ${DNS_PRIMARY}"
echo "[INFO] DNS secondary       : ${DNS_SECONDARY}"
echo

echo "[1/4] Checking laptop USB gateway..."
if ! ping -c 1 -W 2 "${LAPTOP_USB_IP}" >/dev/null 2>&1; then
    echo "[ERROR] Cannot reach laptop gateway ${LAPTOP_USB_IP}."
    echo "Run setup-jetson-internet-laptop.sh on the laptop first."
    exit 1
fi

echo "[2/4] Setting default route via laptop..."
sudo ip route replace default via "${LAPTOP_USB_IP}"

echo "[3/4] Configuring DNS on ${USB_IF}..."

if command -v systemd-resolve >/dev/null 2>&1; then
    sudo systemd-resolve         --interface="${USB_IF}"         --set-dns="${DNS_PRIMARY}"         --set-dns="${DNS_SECONDARY}"

    sudo systemd-resolve --flush-caches || true

elif command -v resolvectl >/dev/null 2>&1; then
    sudo resolvectl dns         "${USB_IF}"         "${DNS_PRIMARY}"         "${DNS_SECONDARY}"

    sudo resolvectl flush-caches || true

else
    echo "[ERROR] Neither systemd-resolve nor resolvectl is available."
    echo "Cannot configure DNS safely because /etc/resolv.conf is managed dynamically."
    exit 1
fi

echo "[4/4] Testing Internet and DNS..."

if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
    echo "[OK] Internet access works."
else
    echo "[ERROR] Cannot reach 8.8.8.8."
    echo
    echo "Current routes:"
    ip route
    exit 1
fi

if getent hosts github.com >/dev/null 2>&1; then
    echo "[OK] DNS works."
else
    echo "[ERROR] Internet works, but DNS lookup failed."
    echo
    echo "Current resolver configuration:"
    cat /etc/resolv.conf || true
    echo

    if command -v systemd-resolve >/dev/null 2>&1; then
        systemd-resolve --status "${USB_IF}" || true
    elif command -v resolvectl >/dev/null 2>&1; then
        resolvectl status "${USB_IF}" || true
    fi

    exit 1
fi

echo
echo "======================================"
echo " Jetson Internet is READY"
echo "======================================"
echo "Laptop USB gateway  : ${LAPTOP_USB_IP}"
echo "Jetson USB interface: ${USB_IF}"
echo "DNS                 : ${DNS_PRIMARY}, ${DNS_SECONDARY}"
echo
ip route
