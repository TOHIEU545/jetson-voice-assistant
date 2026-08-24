#!/usr/bin/env bash
set -e

# ============================================================
# USER CONFIG
# ============================================================

# Mỗi lần tạo Quick Tunnel mới, chỉ sửa dòng này.
# Không thêm /v1/chat/completions ở đây.
TUNNEL_URL="https://xxxxx.trycloudflare.com"

# Speech features
export VOICE_ASSISTANT_GTCRN=1
export VOICE_ASSISTANT_SMART_TURN=0
export VOICE_ASSISTANT_SPECULATIVE=0
export VOICE_ASSISTANT_BARGE_IN=1

# LLM backend
export LLM_MODE="remote"
export LLM_MODEL="ministral-3:8b"

# Quick Tunnel hiện chưa dùng API key
unset LLM_API_KEY

# ============================================================
# BUILD REMOTE ENDPOINT
# ============================================================

TUNNEL_URL="${TUNNEL_URL%/}"

if [ "$TUNNEL_URL" = "https://xxxxx.trycloudflare.com" ]; then
    echo "ERROR: Hãy sửa TUNNEL_URL trong script trước khi chạy."
    exit 1
fi

export LLM_BASE_URL="${TUNNEL_URL}/v1/chat/completions"

# ============================================================
# SHOW CONFIG
# ============================================================

echo "=========================================="
echo " Jetson Voice Assistant Runtime Config"
echo "=========================================="
echo "GTCRN       : ${VOICE_ASSISTANT_GTCRN}"
echo "SMART TURN  : ${VOICE_ASSISTANT_SMART_TURN}"
echo "SPECULATIVE : ${VOICE_ASSISTANT_SPECULATIVE}"
echo "BARGE-IN    : ${VOICE_ASSISTANT_BARGE_IN}"
echo "LLM MODE    : ${LLM_MODE}"
echo "LLM MODEL   : ${LLM_MODEL}"
echo "LLM URL     : ${LLM_BASE_URL}"
echo "=========================================="
echo

# ============================================================
# RUN
# ============================================================

cd "$(dirname "$0")/.."

exec python3 app/voice_assistant.py
