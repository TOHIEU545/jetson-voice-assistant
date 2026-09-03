#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

RUNNER="$SCRIPT_DIR/benchmark_noise_snr.py"
LOOPBACK_HELPER="$REPO_ROOT/scripts/prepare_alsa_loopback.sh"
DATASET_DIR="$REPO_ROOT/data/stt/ms_snsd/mixed/voicebank_prepared_15/airconditioner"
OUTPUT_ROOT="$REPO_ROOT/logs/benchmarks/stt/M03_noise_snr_stress"
RUN_ID="$(date +%Y-%m-%d_%H-%M-%S)"
OUT_DIR="$OUTPUT_ROOT/$RUN_ID"

LOOPBACK_WAS_LOADED=0
if grep -q '^snd_aloop ' /proc/modules 2>/dev/null; then
    LOOPBACK_WAS_LOADED=1
fi

cleanup() {
    local rc=$?
    if [[ "$LOOPBACK_WAS_LOADED" -eq 0 ]] && grep -q '^snd_aloop ' /proc/modules 2>/dev/null; then
        "$LOOPBACK_HELPER" unload >/dev/null 2>&1 || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

cd "$REPO_ROOT"

echo "=========================================="
echo " M03 Controlled SNR Noise Stress"
echo "=========================================="
echo "Dataset : $DATASET_DIR"
echo "Output  : $OUT_DIR"
echo

for cmd in python3 aplay arecord; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "[ERROR] Missing command: $cmd"
        exit 1
    fi
done

if [[ ! -x "$LOOPBACK_HELPER" ]]; then
    echo "[ERROR] Missing executable loopback helper: $LOOPBACK_HELPER"
    exit 1
fi
if [[ ! -f "$RUNNER" ]]; then
    echo "[ERROR] Missing M03 runner: $RUNNER"
    exit 1
fi
if [[ ! -f "$DATASET_DIR/manifest.tsv" ]]; then
    echo "[ERROR] Missing prepared M03 manifest: $DATASET_DIR/manifest.tsv"
    echo "[ERROR] Prepare the fixed dataset with: python3 $SCRIPT_DIR/prepare_snr_dataset.py"
    exit 1
fi

echo "[INFO] Validating the prepared 20/10/5/0 dB dataset..."
python3 "$RUNNER" --dataset-dir "$DATASET_DIR" --validate-dataset

VOICE_ASSISTANT_STT=zipformer_2023_06_21 \
VOICE_ASSISTANT_GTCRN=1 \
VOICE_ASSISTANT_SMART_TURN=0 \
VOICE_ASSISTANT_SPECULATIVE=0 \
python3 - <<'PY'
import os
import sys
from pathlib import Path

from app.config import build_speech_command

command = build_speech_command()
required = [Path(command[0])]
for argument in command[1:]:
    value = argument.split("=", 1)[1] if "=" in argument else ""
    if value.endswith((".onnx", ".txt")):
        required.append(Path(value))
missing = [str(path) for path in required if not path.is_file()]
if missing:
    print("[ERROR] Missing M03 runtime/model files:", file=sys.stderr)
    for path in missing:
        print("  {}".format(path), file=sys.stderr)
    raise SystemExit(1)
if not os.access(str(required[0]), os.X_OK):
    print("[ERROR] Runtime is not executable: {}".format(required[0]), file=sys.stderr)
    raise SystemExit(1)
print("[OK] Runtime/model files: Zipformer + GTCRN")
PY

echo "[INFO] Preparing ALSA Loopback..."
"$LOOPBACK_HELPER" load >/dev/null
echo "[OK] ALSA Loopback ready"

mkdir -p "$OUTPUT_ROOT"

echo "[INFO] Running GTCRN OFF then ON at all fixed SNR levels..."
python3 "$RUNNER" \
    --dataset-dir "$DATASET_DIR" \
    --output-root "$OUTPUT_ROOT" \
    --run-id "$RUN_ID"

echo
echo "=========================================="
echo " M03 BENCHMARK COMPLETE"
echo "=========================================="
echo "Results      : $OUT_DIR/samples.jsonl"
echo "Summary      : $OUT_DIR/summary.md"
echo "Paired effect: $OUT_DIR/paired_effect.json"
