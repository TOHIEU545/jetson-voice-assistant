#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# USER CONFIG
# Edit this block on the Jetson before running.
# ============================================================

# Speech feature models: 1 = ON, 0 = OFF
VOICE_ASSISTANT_GTCRN=0
VOICE_ASSISTANT_SMART_TURN=0
VOICE_ASSISTANT_SPECULATIVE=0
VOICE_ASSISTANT_BARGE_IN=1

# LLM backend: local | remote
LLM_MODE="local"

# Remote LLM settings.
# Used ONLY when LLM_MODE="remote".
# Do not append /v1/chat/completions.
REMOTE_LLM_URL="https://xxxxx.trycloudflare.com"
REMOTE_LLM_MODEL="ministral-3:8b"
REMOTE_LLM_API_KEY=""

# ============================================================
# INTERNAL CONFIG
# Normally do not edit below this line.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LOCAL_LLM_BASE_URL="http://127.0.0.1:8080/v1/chat/completions"

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

if [[ "$VOICE_ASSISTANT_SPECULATIVE" == "1" && "$VOICE_ASSISTANT_SMART_TURN" != "1" ]]; then
    echo "ERROR: VOICE_ASSISTANT_SPECULATIVE=1 requires VOICE_ASSISTANT_SMART_TURN=1"
    exit 1
fi

export VOICE_ASSISTANT_GTCRN
export VOICE_ASSISTANT_SMART_TURN
export VOICE_ASSISTANT_SPECULATIVE
export VOICE_ASSISTANT_BARGE_IN

case "$LLM_MODE" in
    local)
        export LLM_MODE="local"
        export LLM_BASE_URL="$LOCAL_LLM_BASE_URL"
        unset LLM_MODEL
        unset LLM_API_KEY
        ;;

    remote)
        REMOTE_LLM_URL="${REMOTE_LLM_URL%/}"

        if [[ -z "$REMOTE_LLM_URL" || "$REMOTE_LLM_URL" == "https://xxxxx.trycloudflare.com" ]]; then
            echo "ERROR: Set REMOTE_LLM_URL before using LLM_MODE=remote"
            exit 1
        fi

        export LLM_MODE="remote"
        export LLM_BASE_URL="${REMOTE_LLM_URL}/v1/chat/completions"

        if [[ -n "$REMOTE_LLM_MODEL" ]]; then
            export LLM_MODEL="$REMOTE_LLM_MODEL"
        else
            unset LLM_MODEL
        fi

        if [[ -n "$REMOTE_LLM_API_KEY" ]]; then
            export LLM_API_KEY="$REMOTE_LLM_API_KEY"
        else
            unset LLM_API_KEY
        fi
        ;;

    *)
        echo "ERROR: LLM_MODE must be 'local' or 'remote' (current: $LLM_MODE)"
        exit 1
        ;;
esac

# ============================================================
# SHOW EFFECTIVE CONFIG
# ============================================================

echo "=========================================="
echo " Jetson Voice Assistant Runtime Config"
echo "=========================================="
echo "GTCRN       : ${VOICE_ASSISTANT_GTCRN}"
echo "SMART TURN  : ${VOICE_ASSISTANT_SMART_TURN}"
echo "SPECULATIVE : ${VOICE_ASSISTANT_SPECULATIVE}"
echo "BARGE-IN    : ${VOICE_ASSISTANT_BARGE_IN}"
echo "LLM MODE    : ${LLM_MODE}"
echo "LLM MODEL   : ${LLM_MODEL:-server-selected}"
echo "LLM URL     : ${LLM_BASE_URL}"

if [[ "$LLM_MODE" == "remote" ]]; then
    if [[ -n "${LLM_API_KEY:-}" ]]; then
        echo "LLM API KEY : configured"
    else
        echo "LLM API KEY : none"
    fi
fi

echo "=========================================="
echo

# ============================================================
# RUN
# ============================================================

cd "$PROJECT_ROOT"
exec python3 app/voice_assistant.py
