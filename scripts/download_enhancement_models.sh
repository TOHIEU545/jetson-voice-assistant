#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

MODEL_DIR="${ROOT_DIR}/models/enhancement"
MODEL_NAME="gtcrn_simple.onnx"
MODEL_PATH="${MODEL_DIR}/${MODEL_NAME}"
TMP_PATH="${MODEL_PATH}.tmp"

MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx"
EXPECTED_SIZE="535638"
EXPECTED_SHA256="e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534"

verify_model() {
    local path="$1"

    [[ -f "${path}" ]] || return 1

    local actual_size
    local actual_sha256

    actual_size="$(stat -c '%s' "${path}")"
    actual_sha256="$(sha256sum "${path}" | awk '{print $1}')"

    if [[ "${actual_size}" != "${EXPECTED_SIZE}" ]]; then
        echo "ERROR: model size mismatch"
        echo "Expected: ${EXPECTED_SIZE}"
        echo "Actual:   ${actual_size}"
        return 1
    fi

    if [[ "${actual_sha256}" != "${EXPECTED_SHA256}" ]]; then
        echo "ERROR: model SHA256 mismatch"
        echo "Expected: ${EXPECTED_SHA256}"
        echo "Actual:   ${actual_sha256}"
        return 1
    fi

    return 0
}

mkdir -p "${MODEL_DIR}"

if verify_model "${MODEL_PATH}"; then
    echo "GTCRN model already exists and is valid:"
    echo "  ${MODEL_PATH}"
    exit 0
fi

rm -f "${TMP_PATH}"

cleanup() {
    rm -f "${TMP_PATH}"
}
trap cleanup EXIT

echo "Downloading GTCRN Simple..."
echo "  ${MODEL_URL}"

wget \
    --progress=bar:force \
    -O "${TMP_PATH}" \
    "${MODEL_URL}"

echo "Verifying model..."

if ! verify_model "${TMP_PATH}"; then
    echo "ERROR: downloaded GTCRN model failed verification."
    exit 1
fi

mv "${TMP_PATH}" "${MODEL_PATH}"
trap - EXIT

echo "GTCRN model downloaded and verified:"
echo "  ${MODEL_PATH}"

stat -c 'Size: %s bytes' "${MODEL_PATH}"
sha256sum "${MODEL_PATH}"
