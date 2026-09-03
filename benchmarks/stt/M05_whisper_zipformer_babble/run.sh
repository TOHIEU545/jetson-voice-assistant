#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

RUNNER="$SCRIPT_DIR/benchmark_model_noise.py"
LOOPBACK_HELPER="$REPO_ROOT/scripts/prepare_alsa_loopback.sh"
DATASET_DIR="$REPO_ROOT/data/stt/ms_snsd/mixed/voicebank_prepared_15/babble"
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
OUT_DIR="$REPO_ROOT/logs/benchmarks/stt/M05_whisper_zipformer_babble/$STAMP"

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
echo " M05 Whisper vs Zipformer under Babble"
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
    echo "[ERROR] Missing M05 runner: $RUNNER"
    exit 1
fi
if [[ ! -f "$DATASET_DIR/manifest.tsv" ]]; then
    echo "[ERROR] Missing prepared M04/M05 manifest: $DATASET_DIR/manifest.tsv"
    exit 1
fi

echo "[INFO] Validating the prepared 5/0 dB Babble dataset..."
python3 "$RUNNER" --dataset-dir "$DATASET_DIR" --validate-dataset

validate_runtime() {
    local backend=$1

    VOICE_ASSISTANT_STT="$backend" \
    VOICE_ASSISTANT_GTCRN=0 \
    VOICE_ASSISTANT_SMART_TURN=0 \
    VOICE_ASSISTANT_SPECULATIVE=0 \
    python3 - "$backend" <<'PY'
import os
import sys
from pathlib import Path

from app.config import build_speech_command

backend = sys.argv[1]
command = build_speech_command()
required = [Path(command[0])]
for argument in command[1:]:
    value = argument.split("=", 1)[1] if "=" in argument else ""
    if value.endswith((".onnx", ".txt")):
        required.append(Path(value))
missing = [str(path) for path in required if not path.is_file()]
if missing:
    print("[ERROR] Missing runtime/model files for {}:".format(backend), file=sys.stderr)
    for path in missing:
        print("  {}".format(path), file=sys.stderr)
    raise SystemExit(1)
if not os.access(str(required[0]), os.X_OK):
    print("[ERROR] Runtime is not executable: {}".format(required[0]), file=sys.stderr)
    raise SystemExit(1)
print("[OK] Runtime/model files: {}".format(backend))
PY
}

validate_runtime whisper
validate_runtime zipformer_2023_06_21

echo "[INFO] Preparing ALSA Loopback..."
"$LOOPBACK_HELPER" load >/dev/null
echo "[OK] ALSA Loopback ready"

mkdir -p "$OUT_DIR"

run_comparison() {
    local run_id=$1
    local order=$2

    echo
    echo "[INFO] $run_id: $order"
    python3 "$RUNNER" \
        --dataset-dir "$DATASET_DIR" \
        --output-root "$OUT_DIR" \
        --run-id "$run_id" \
        --order "$order"
}

run_comparison "run_1_whisper_first" "whisper,zipformer_2023_06_21"
run_comparison "run_2_zipformer_first" "zipformer_2023_06_21,whisper"
run_comparison "run_3_whisper_first" "whisper,zipformer_2023_06_21"

echo
echo "=========================================="
echo " M05 BENCHMARK COMPLETE"
echo "=========================================="
echo "Run 1 summary: $OUT_DIR/run_1_whisper_first/summary.md"
echo "Run 2 summary: $OUT_DIR/run_2_zipformer_first/summary.md"
echo "Run 3 summary: $OUT_DIR/run_3_whisper_first/summary.md"
echo "All results  : $OUT_DIR"
