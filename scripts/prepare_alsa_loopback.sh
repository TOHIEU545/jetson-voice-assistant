#!/usr/bin/env bash
set -euo pipefail

# ALSA Loopback helper for STT pipeline benchmarks.
#
# Tracked on HOST under:
#   scripts/prepare_alsa_loopback.sh
#
# Executed on Jetson before fixed-WAV pipeline benchmarks.
#
# Usage:
#   ./scripts/prepare_alsa_loopback.sh load     # default
#   ./scripts/prepare_alsa_loopback.sh status
#   ./scripts/prepare_alsa_loopback.sh unload
#
# Expected benchmark devices:
#   playback -> plughw:Loopback,0,0
#   capture  -> plughw:Loopback,1,0
#
# Normal microphone demo does NOT require snd-aloop.

ACTION="${1:-load}"

module_loaded() {
    grep -q '^snd_aloop ' /proc/modules 2>/dev/null
}

show_status() {
    echo "=========================================="
    echo " ALSA Loopback Status"
    echo "=========================================="

    if module_loaded; then
        echo "[OK] snd-aloop module is loaded."
    else
        echo "[OFF] snd-aloop module is not loaded."
    fi

    echo
    echo "=== ALSA CARDS ==="
    if [[ -r /proc/asound/cards ]]; then
        cat /proc/asound/cards
    else
        echo "[WARN] /proc/asound/cards is unavailable."
    fi

    echo
    echo "=== LOOPBACK PLAYBACK ==="
    aplay -l 2>/dev/null | grep -A12 -i 'Loopback' || true

    echo
    echo "=== LOOPBACK CAPTURE ==="
    arecord -l 2>/dev/null | grep -A12 -i 'Loopback' || true

    echo
    echo "Benchmark devices:"
    echo "  playback : plughw:Loopback,0,0"
    echo "  capture  : plughw:Loopback,1,0"
}

case "$ACTION" in
    load)
        if ! command -v modinfo >/dev/null 2>&1; then
            echo "[ERROR] modinfo not found."
            exit 1
        fi

        if ! modinfo snd-aloop >/dev/null 2>&1; then
            echo "[ERROR] snd-aloop kernel module is not available."
            exit 1
        fi

        if module_loaded; then
            echo "[OK] snd-aloop is already loaded."
        else
            echo "[INFO] Loading snd-aloop..."
            sudo modprobe snd-aloop
        fi

        sleep 0.2

        if ! module_loaded; then
            echo "[ERROR] snd-aloop failed to load."
            exit 1
        fi

        if ! grep -q 'Loopback' /proc/asound/cards 2>/dev/null; then
            echo "[ERROR] snd-aloop is loaded but ALSA Loopback card was not found."
            exit 1
        fi

        echo "[OK] ALSA Loopback is ready."
        show_status
        ;;

    status)
        show_status
        ;;

    unload)
        if module_loaded; then
            echo "[INFO] Unloading snd-aloop..."
            sudo modprobe -r snd-aloop
            echo "[OK] snd-aloop unloaded."
        else
            echo "[OK] snd-aloop is already unloaded."
        fi
        ;;

    *)
        echo "Usage: $0 [load|status|unload]"
        exit 2
        ;;
esac
