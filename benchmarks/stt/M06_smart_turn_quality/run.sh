#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

RUNNER="$SCRIPT_DIR/benchmark_smart_turn.py"
BUILD_HELPER="$SCRIPT_DIR/build_probe.sh"
PROBE="$SCRIPT_DIR/build/smart_turn_probe"
MANIFEST="$REPO_ROOT/data/stt/smart_turn_v3_2_test/source/hf_selected_60/manifest.tsv"
MODEL="$REPO_ROOT/models/turn/smart-turn-v3.2-cpu-opset16-ir8-clean.onnx"
OUTPUT_ROOT="$REPO_ROOT/logs/benchmarks/stt/M06_smart_turn_quality"
RUN_ID="$(date +%Y-%m-%d_%H-%M-%S)"
OUT_DIR="$OUTPUT_ROOT/$RUN_ID"

if [[ -n "${SHERPA_ONNX_SRC:-}" ]]; then
    SHERPA_ONNX_SRC="$SHERPA_ONNX_SRC"
elif [[ -d "$HOME/jetson-voice-assistant-runtime-dev/sherpa-onnx" ]]; then
    SHERPA_ONNX_SRC="$HOME/jetson-voice-assistant-runtime-dev/sherpa-onnx"
elif [[ -d "$REPO_ROOT/runtime/sherpa-onnx" ]]; then
    SHERPA_ONNX_SRC="$REPO_ROOT/runtime/sherpa-onnx"
else
    echo "[ERROR] Cannot locate sherpa-onnx source/build tree."
    echo "[ERROR] Set SHERPA_ONNX_SRC if it is outside the standard project paths."
    exit 1
fi
ORT_LIB_DIR="$SHERPA_ONNX_SRC/build/_deps/onnxruntime-src/lib"
export SHERPA_ONNX_SRC

cd "$REPO_ROOT"

echo "=========================================="
echo " M06 Smart Turn v3.2 Quality"
echo "=========================================="
echo "Manifest: $MANIFEST"
echo "Model   : $MODEL"
echo "Runtime : $SHERPA_ONNX_SRC"
echo "Output  : $OUT_DIR"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Missing command: python3"
    exit 1
fi

if [[ ! -f "$RUNNER" || ! -x "$BUILD_HELPER" ]]; then
    echo "[ERROR] M06 runner or executable build helper is missing."
    exit 1
fi
if [[ ! -f "$MANIFEST" ]]; then
    echo "[ERROR] Missing prepared M06 manifest: $MANIFEST"
    echo "[ERROR] Dataset preparation is a developer-only step; see $SCRIPT_DIR/README.md"
    exit 1
fi
if [[ ! -f "$MODEL" ]]; then
    echo "[ERROR] Missing Smart Turn v3.2 model: $MODEL"
    exit 1
fi
if [[ ! -d "$SHERPA_ONNX_SRC/build" ]]; then
    echo "[ERROR] Missing sherpa-onnx build tree: $SHERPA_ONNX_SRC/build"
    exit 1
fi

if [[ ! -x "$PROBE" || "$SCRIPT_DIR/smart_turn_probe.cc" -nt "$PROBE" || "$BUILD_HELPER" -nt "$PROBE" ]]; then
    if [[ ! -x /usr/bin/c++ ]]; then
        echo "[ERROR] Missing compiler required to build probe: /usr/bin/c++"
        exit 1
    fi
    echo "[INFO] Building Smart Turn probe..."
    "$BUILD_HELPER"
else
    echo "[OK] Smart Turn probe is up to date: $PROBE"
fi

if [[ -f "$ORT_LIB_DIR/libonnxruntime.so" ]]; then
    export LD_LIBRARY_PATH="$ORT_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    echo "[OK] ONNX Runtime library path configured: $ORT_LIB_DIR"
elif [[ ! -f "$ORT_LIB_DIR/libonnxruntime.a" ]]; then
    echo "[ERROR] ONNX Runtime library not found under: $ORT_LIB_DIR"
    exit 1
fi

echo "[INFO] Validating fixed 30 COMPLETE + 30 INCOMPLETE dataset..."
python3 "$RUNNER" --manifest "$MANIFEST" --validate-dataset

mkdir -p "$OUTPUT_ROOT"

echo "[INFO] Running Smart Turn standalone quality benchmark..."
python3 "$RUNNER" \
    --manifest "$MANIFEST" \
    --probe "$PROBE" \
    --model "$MODEL" \
    --output-root "$OUTPUT_ROOT" \
    --run-id "$RUN_ID"

echo
echo "=========================================="
echo " M06 BENCHMARK COMPLETE"
echo "=========================================="
echo "Results : $OUT_DIR/samples.jsonl"
echo "Summary : $OUT_DIR/summary.md"
echo "Metadata: $OUT_DIR/smart_turn_v3_2/config_metadata.json"
