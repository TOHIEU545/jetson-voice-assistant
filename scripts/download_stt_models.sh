#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_ROOT="$ROOT/models/stt"
SHA_FILE="$ROOT/deps/models.sha256"
DOWNLOAD_ROOT="$ROOT/models/.downloads/stt"

BASE_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"

mkdir -p "$MODEL_ROOT" "$DOWNLOAD_ROOT"

expected_sha() {
    local model_rel="$1"

    awk -v p="models/stt/$model_rel" '
        $2 == p {
            print $1
            found = 1
            exit
        }
        END {
            if (!found) exit 1
        }
    ' "$SHA_FILE"
}

verify_file() {
    local file="$1"
    local model_rel="$2"

    local expected
    local actual

    expected="$(expected_sha "$model_rel")"
    actual="$(sha256sum "$file" | awk '{print $1}')"

    if [[ "$actual" != "$expected" ]]; then
        echo "[FAIL] SHA256 mismatch: $model_rel" >&2
        echo "       expected: $expected" >&2
        echo "       actual  : $actual" >&2
        return 1
    fi

    echo "[OK] $model_rel"
}

verify_model() {
    local target_name="$1"
    shift

    local target="$MODEL_ROOT/$target_name"
    local file

    [[ -d "$target" ]] || return 1

    for file in "$@"; do
        [[ -f "$target/$file" ]] || return 1
        verify_file \
            "$target/$file" \
            "$target_name/$file" \
            >/dev/null
    done

    return 0
}

install_model() {
    local target_name="$1"
    local archive_name="$2"
    local extracted_name="$3"
    shift 3

    local files=("$@")
    local target="$MODEL_ROOT/$target_name"
    local archive="$DOWNLOAD_ROOT/$archive_name"
    local stage="$DOWNLOAD_ROOT/stage-$target_name"
    local source
    local file

    echo
    echo "============================================================"
    echo "$target_name"
    echo "============================================================"

    if verify_model "$target_name" "${files[@]}"; then
        echo "Already installed and checksums verified."
        return 0
    fi

    rm -rf "$stage"
    mkdir -p "$stage"

    echo "Downloading official sherpa-onnx archive..."
    wget -O "$archive" "$BASE_URL/$archive_name"

    echo "Extracting..."
    tar -xjf "$archive" -C "$stage"

    source="$stage/$extracted_name"

    if [[ ! -d "$source" ]]; then
        echo "[FAIL] Expected extracted directory not found:" >&2
        echo "       $source" >&2
        exit 1
    fi

    echo "Verifying staged model..."
    for file in "${files[@]}"; do
        verify_file \
            "$source/$file" \
            "$target_name/$file"
    done

    echo "Installing..."
    rm -rf "$target"
    mv "$source" "$target"

    echo "Verifying installed model..."
    for file in "${files[@]}"; do
        verify_file \
            "$target/$file" \
            "$target_name/$file"
    done

    rm -rf "$stage" "$archive"

    echo "[DONE] $target_name"
}

install_whisper() {
    install_model \
        "whisper-tiny.en" \
        "sherpa-onnx-whisper-tiny.en.tar.bz2" \
        "sherpa-onnx-whisper-tiny.en" \
        "tiny.en-encoder.onnx" \
        "tiny.en-decoder.onnx" \
        "tiny.en-tokens.txt"
}

install_zip20() {
    install_model \
        "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17" \
        "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17.tar.bz2" \
        "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17" \
        "encoder-epoch-99-avg-1.onnx" \
        "decoder-epoch-99-avg-1.onnx" \
        "joiner-epoch-99-avg-1.onnx" \
        "tokens.txt"
}

install_ziplarge() {
    install_model \
        "sherpa-onnx-streaming-zipformer-en-2023-06-21" \
        "sherpa-onnx-streaming-zipformer-en-2023-06-21.tar.bz2" \
        "sherpa-onnx-streaming-zipformer-en-2023-06-21" \
        "encoder-epoch-99-avg-1.onnx" \
        "decoder-epoch-99-avg-1.onnx" \
        "joiner-epoch-99-avg-1.onnx" \
        "tokens.txt"
}

usage() {
    cat <<USAGE
Usage:
  $0 all
  $0 whisper
  $0 zipformer_20m
  $0 zipformer_2023_06_21

Default:
  all
USAGE
}

case "${1:-all}" in
    all)
        install_whisper
        install_zip20
        install_ziplarge
        ;;
    whisper)
        install_whisper
        ;;
    zipformer_20m)
        install_zip20
        ;;
    zipformer_2023_06_21)
        install_ziplarge
        ;;
    -h|--help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
