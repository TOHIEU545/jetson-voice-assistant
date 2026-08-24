#!/usr/bin/env bash
set -euo pipefail

JETSON_NET="${JETSON_NET:-192.168.55.0/24}"
LAPTOP_USB_IP="${LAPTOP_USB_IP:-192.168.55.100}"

echo "=== Jetson Internet Sharing - Laptop Setup ==="

sudo -v

# Detect the interface currently used to reach the Internet.
INTERNET_IF="$(
    ip route get 8.8.8.8 2>/dev/null |
    awk '{
        for (i = 1; i <= NF; i++) {
            if ($i == "dev") {
                print $(i+1)
                exit
            }
        }
    }'
)"

if [[ -z "${INTERNET_IF}" ]]; then
    echo "[ERROR] Cannot detect the laptop Internet interface."
    exit 1
fi

# Detect the USB network interface that owns 192.168.55.100.
USB_IF="$(
    ip -o -4 addr show |
    awk -v ip="${LAPTOP_USB_IP}" '
        $4 ~ ("^" ip "/") {
            print $2
            exit
        }
    '
)"

if [[ -z "${USB_IF}" ]]; then
    echo "[ERROR] Cannot find an interface with ${LAPTOP_USB_IP}."
    echo "Check the Jetson USB connection with:"
    echo "  ip -4 addr"
    exit 1
fi

echo "[INFO] Internet interface : ${INTERNET_IF}"
echo "[INFO] Jetson USB interface: ${USB_IF}"
echo "[INFO] Laptop USB IP       : ${LAPTOP_USB_IP}"

echo
echo "[1/3] Enabling IPv4 forwarding..."
sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

echo "[2/3] Configuring NAT..."
sudo iptables -t nat -C POSTROUTING \
    -s "${JETSON_NET}" \
    -o "${INTERNET_IF}" \
    -j MASQUERADE 2>/dev/null || \
sudo iptables -t nat -A POSTROUTING \
    -s "${JETSON_NET}" \
    -o "${INTERNET_IF}" \
    -j MASQUERADE

echo "[3/3] Configuring forwarding rules..."
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

echo
echo "======================================"
echo " Laptop network sharing is READY"
echo "======================================"
echo "Internet interface : ${INTERNET_IF}"
echo "Jetson USB interface: ${USB_IF}"
echo "Laptop USB IP       : ${LAPTOP_USB_IP}"
echo
echo "Next:"
echo "  1. SSH to the Jetson manually."
echo "  2. Run setup-jetson-internet-jetson.sh on the Jetson."
