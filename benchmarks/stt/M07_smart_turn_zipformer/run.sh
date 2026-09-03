#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

MANIFEST="$REPO_ROOT/data/stt/eot_bench/prepared_en_20/manifest.jsonl"
LOOPBACK_HELPER="$REPO_ROOT/scripts/prepare_alsa_loopback.sh"
RUNNER="$SCRIPT_DIR/run_benchmark.py"
SUMMARIZER="$SCRIPT_DIR/summarize_results.py"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$REPO_ROOT/logs/benchmarks/stt/M07_smart_turn_zipformer/$STAMP"

PLAYBACK_DEVICE="${M07_PLAYBACK_DEVICE:-plughw:Loopback,0,0}"
CAPTURE_DEVICE="${M07_CAPTURE_DEVICE:-plughw:Loopback,1,0}"

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
echo " M07 Smart Turn + Zipformer Benchmark"
echo "=========================================="
echo "Repo      : $REPO_ROOT"
echo "Manifest  : $MANIFEST"
echo "Playback  : $PLAYBACK_DEVICE"
echo "Capture   : $CAPTURE_DEVICE"
echo "Output    : $OUT_DIR"
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
if [[ ! -f "$MANIFEST" ]]; then
    echo "[ERROR] Missing M07 manifest: $MANIFEST"
    exit 1
fi
if [[ ! -f "$RUNNER" || ! -f "$SUMMARIZER" ]]; then
    echo "[ERROR] M07 benchmark runner files are incomplete."
    exit 1
fi

WAV_COUNT="$(python3 - "$MANIFEST" <<'PY'
import json, sys
from pathlib import Path
manifest = Path(sys.argv[1])
count = 0
with manifest.open() as f:
    for line in f:
        if not line.strip():
            continue
        row = json.loads(line)
        wav = manifest.parent / row["audio"]
        if not wav.is_file():
            print("[ERROR] Missing WAV: {}".format(wav), file=sys.stderr)
            raise SystemExit(2)
        count += 1
print(count)
PY
)"

if [[ "$WAV_COUNT" -ne 20 ]]; then
    echo "[ERROR] M07 requires exactly 20 prepared WAV files; found $WAV_COUNT."
    exit 1
fi

echo "[OK] Dataset: 20 WAV files"
echo "[INFO] Preparing ALSA Loopback..."
"$LOOPBACK_HELPER" load >/dev/null
echo "[OK] ALSA Loopback ready"

if pgrep -f 'sherpa-onnx-vad-alsa-streaming-asr.*plughw:Loopback,1,0' >/dev/null 2>&1; then
    echo "[INFO] Stopping stale loopback speech runtime..."
    pkill -INT -f 'sherpa-onnx-vad-alsa-streaming-asr.*plughw:Loopback,1,0' || true
    sleep 2
fi

mkdir -p "$OUT_DIR"

echo
echo "[INFO] Running OFF vs ON on the same 20 WAV files..."
python3 "$RUNNER" \
    --manifest "$MANIFEST" \
    --output-dir "$OUT_DIR" \
    --playback-device "$PLAYBACK_DEVICE" \
    --capture-device "$CAPTURE_DEVICE"

echo
echo "[INFO] Summarizing..."
python3 "$SUMMARIZER" \
    --results "$OUT_DIR/results.jsonl" \
    --summary-json "$OUT_DIR/summary.json" \
    --summary-md "$OUT_DIR/SUMMARY.md"

echo
echo "=========================================="
echo " M07 BENCHMARK COMPLETE"
echo "=========================================="
echo "Results : $OUT_DIR/results.jsonl"
echo "Summary : $OUT_DIR/SUMMARY.md"
echo "Raw logs: $OUT_DIR/cases/"
