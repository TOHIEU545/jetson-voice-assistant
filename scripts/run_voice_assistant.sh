#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# USER CONFIG
# Edit this block on the Jetson before running.
# ============================================================

# STT backend:
#   whisper
#   zipformer_20m
#   zipformer_2023_06_21
VOICE_ASSISTANT_STT="whisper"

# Speech features: 1 = ON, 0 = OFF
VOICE_ASSISTANT_GTCRN=0
VOICE_ASSISTANT_SMART_TURN=0
VOICE_ASSISTANT_SPECULATIVE=0
VOICE_ASSISTANT_BARGE_IN=1

# Hardware
VOICE_ASSISTANT_MIC_DEVICE="plughw:2,0"

# LLM backend: local | remote
LLM_MODE="local"

# Remote LLM settings.
# Used ONLY when LLM_MODE="remote".
# Do not append /v1/chat/completions.
REMOTE_LLM_URL="https://xxxxx.trycloudflare.com"
REMOTE_LLM_MODEL="ministral-3:8b"
REMOTE_LLM_API_KEY=""

# ============================================================
# INTERNAL
# Normally do not edit below this line.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

validate_toggle() {
    local name="$1"
    local value="$2"

    if [[ "$value" != "0" && "$value" != "1" ]]; then
        echo "ERROR: $name must be 0 or 1 (current: $value)"
        exit 1
    fi
}

validate_toggle "VOICE_ASSISTANT_GTCRN" "$VOICE_ASSISTANT_GTCRN"
validate_toggle "VOICE_ASSISTANT_SMART_TURN" "$VOICE_ASSISTANT_SMART_TURN"
validate_toggle "VOICE_ASSISTANT_SPECULATIVE" "$VOICE_ASSISTANT_SPECULATIVE"
validate_toggle "VOICE_ASSISTANT_BARGE_IN" "$VOICE_ASSISTANT_BARGE_IN"

case "$VOICE_ASSISTANT_STT" in
    whisper|zipformer_20m|zipformer_2023_06_21)
        ;;
    *)
        echo "ERROR: Unsupported VOICE_ASSISTANT_STT: $VOICE_ASSISTANT_STT"
        echo "Supported: whisper, zipformer_20m, zipformer_2023_06_21"
        exit 1
        ;;
esac

if [[ "$VOICE_ASSISTANT_SPECULATIVE" == "1" && "$VOICE_ASSISTANT_SMART_TURN" != "1" ]]; then
    echo "ERROR: VOICE_ASSISTANT_SPECULATIVE=1 requires VOICE_ASSISTANT_SMART_TURN=1"
    exit 1
fi

if [[ "$LLM_MODE" != "local" && "$LLM_MODE" != "remote" ]]; then
    echo "ERROR: LLM_MODE must be 'local' or 'remote' (current: $LLM_MODE)"
    exit 1
fi

if [[ "$LLM_MODE" == "remote" ]]; then
    if [[ -z "$REMOTE_LLM_URL" || "$REMOTE_LLM_URL" == "https://xxxxx.trycloudflare.com" ]]; then
        echo "ERROR: Set REMOTE_LLM_URL before using LLM_MODE=remote"
        exit 1
    fi
fi

export VOICE_ASSISTANT_STT
export VOICE_ASSISTANT_GTCRN
export VOICE_ASSISTANT_SMART_TURN
export VOICE_ASSISTANT_SPECULATIVE
export VOICE_ASSISTANT_BARGE_IN
export VOICE_ASSISTANT_MIC_DEVICE

export LLM_MODE

if [[ "$LLM_MODE" == "remote" ]]; then
    export REMOTE_LLM_URL
    export REMOTE_LLM_MODEL
    export REMOTE_LLM_API_KEY
else
    unset REMOTE_LLM_URL
    unset REMOTE_LLM_MODEL
    unset REMOTE_LLM_API_KEY
fi

# ============================================================
# SHOW USER CONFIG
# ============================================================

echo "=========================================="
echo " Jetson Voice Assistant Runtime Config"
echo "=========================================="
echo "STT BACKEND : ${VOICE_ASSISTANT_STT}"
echo "GTCRN       : ${VOICE_ASSISTANT_GTCRN}"
echo "SMART TURN  : ${VOICE_ASSISTANT_SMART_TURN}"
echo "SPECULATIVE : ${VOICE_ASSISTANT_SPECULATIVE}"
echo "BARGE-IN    : ${VOICE_ASSISTANT_BARGE_IN}"
echo "MIC DEVICE  : ${VOICE_ASSISTANT_MIC_DEVICE}"
echo "LLM MODE    : ${LLM_MODE}"

if [[ "$LLM_MODE" == "remote" ]]; then
    echo "REMOTE URL   : ${REMOTE_LLM_URL}"
    echo "REMOTE MODEL : ${REMOTE_LLM_MODEL:-server-selected}"

    if [[ -n "$REMOTE_LLM_API_KEY" ]]; then
        echo "API KEY      : configured"
    else
        echo "API KEY      : none"
    fi
fi

echo "=========================================="
echo

# ============================================================
# RUN
# ============================================================

cd "$PROJECT_ROOT"
exec python3 app/voice_assistant.py
