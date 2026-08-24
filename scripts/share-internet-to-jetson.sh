#!/usr/bin/env bash
set -euo pipefail

JETSON_USER="${1:-ptit}"
JETSON_IP="${2:-192.168.55.1}"
JETSON_NET="192.168.55.0/24"
LAPTOP_USB_IP="192.168.55.100"

echo "=== Jetson Internet Sharing Setup ==="

# Ask sudo once at the beginning
sudo -v

# Detect interface used by laptop to reach the Internet
INTERNET_IF="$(ip route get 8.8.8.8 2>/dev/null | awk '
{
    for (i = 1; i <= NF; i++) {
        if ($i == "dev") {
            print $(i+1)
            exit
        }
    }
}')"

if [[ -z "${INTERNET_IF}" ]]; then
    echo "[ERROR] Cannot detect laptop Internet interface."
    exit 1
fi

# Detect USB interface that owns 192.168.55.100
USB_IF="$(ip -o -4 addr show | awk -v ip="${LAPTOP_USB_IP}" '
$4 ~ ("^" ip "/") {
    print $2
    exit
}')"

if [[ -z "${USB_IF}" ]]; then
    echo "[ERROR] Cannot find interface with ${LAPTOP_USB_IP}."
    echo "Check Jetson USB connection with:"
    echo "  ip -4 addr"
    exit 1
fi

echo "[INFO] Internet interface : ${INTERNET_IF}"
echo "[INFO] Jetson USB interface: ${USB_IF}"
echo "[INFO] Jetson IP           : ${JETSON_IP}"

echo
echo "[1/4] Enabling IPv4 forwarding..."
sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

echo "[2/4] Configuring NAT..."

sudo iptables -t nat -C POSTROUTING \
    -s "${JETSON_NET}" \
    -o "${INTERNET_IF}" \
    -j MASQUERADE 2>/dev/null || \
sudo iptables -t nat -A POSTROUTING \
    -s "${JETSON_NET}" \
    -o "${INTERNET_IF}" \
    -j MASQUERADE

sudo iptables -C FORWARD \
    -i "${USB_IF}" \
    -o "${INTERNET_IF}" \
    -j ACCEPT 2>/dev/null || \
sudo iptables -I FORWARD 1 \
    -i "${USB_IF}" \
    -o "${INTERNET_IF}" \
    -j ACCEPT

sudo iptables -C FORWARD \
    -i "${INTERNET_IF}" \
    -o "${USB_IF}" \
    -m conntrack \
    --ctstate RELATED,ESTABLISHED \
    -j ACCEPT 2>/dev/null || \
sudo iptables -I FORWARD 1 \
    -i "${INTERNET_IF}" \
    -o "${USB_IF}" \
    -m conntrack \
    --ctstate RELATED,ESTABLISHED \
    -j ACCEPT

echo "[3/4] Configuring Jetson default gateway..."

if ! ping -c 1 -W 2 "${JETSON_IP}" >/dev/null 2>&1; then
    echo "[ERROR] Jetson ${JETSON_IP} is not reachable."
    exit 1
fi

ssh "${JETSON_USER}@${JETSON_IP}" \
    "sudo ip route replace default via ${LAPTOP_USB_IP}"

echo "[4/4] Testing Jetson Internet..."

if ssh "${JETSON_USER}@${JETSON_IP}" "ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1"; then
    echo "[OK] Internet access works."
else
    echo "[WARN] Jetson cannot reach 8.8.8.8."
    exit 1
fi

if ssh "${JETSON_USER}@${JETSON_IP}" "ping -c 1 -W 3 google.com >/dev/null 2>&1"; then
    echo "[OK] DNS works."
else
    echo "[WARN] Internet works, but DNS test failed."
    exit 1
fi

echo
echo "======================================"
echo " Jetson Internet sharing is READY"
echo "======================================"
echo "Laptop Internet : ${INTERNET_IF}"
echo "Laptop USB      : ${USB_IF}"
echo "Jetson          : ${JETSON_USER}@${JETSON_IP}"
