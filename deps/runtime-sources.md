# Runtime Sources

## llama.cpp

Runtime llama.cpp for Jetson Nano is installed from:

- Project: `kreier/llama.cpp-jetson`
- Installer: `https://kreier.github.io/llama.cpp-jetson.nano/install.sh`

Install command:

    curl -fsSL https://kreier.github.io/llama.cpp-jetson.nano/install.sh | bash

Important binaries:

- `llama-cli`
- `llama-server`
- `llama-bench`

The exact `llama-server` version and SHA256 used by this project are recorded in:

- `deps/llama-server.manifest`

## sherpa-onnx

The exact sherpa-onnx upstream repository and commit are recorded in:

- `deps/sherpa-onnx.remote`
- `deps/sherpa-onnx.commit`

Local latency instrumentation is stored in:

- `patches/sherpa-onnx/latency-instrumentation.patch`

## Models

Model filenames and sizes:

- `deps/models.manifest`

Model SHA256 checksums:

- `deps/models.sha256`

## GTCRN Simple Speech Enhancement

- Model: GTCRN Simple
- Purpose: streaming speech enhancement / denoising
- Model variant: `gtcrn_simple.onnx`
- Format: ONNX
- Sample rate: 16 kHz
- Runtime: sherpa-onnx + ONNX Runtime
- Runtime binary: `sherpa-onnx-online-denoiser`
- Provider: CPU
- Threads benchmarked: 1
- Streaming chunk duration: 10 ms
- Installed path: `models/enhancement/gtcrn_simple.onnx`
- File size: 535638 bytes
- SHA256: `e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534`
- Official source: https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx

### Jetson Nano standalone benchmark

Configuration:

    provider       = cpu
    num_threads    = 1
    sample_rate    = 16000 Hz
    chunk_duration = 10 ms

Results:

    Model size         : 535638 bytes (~524 KiB)
    Offline RTF        : 0.254
    Online RTF         : 0.356
    Online peak RSS    : ~26.8 MiB
    Online CPU usage   : ~99% of one CPU core
    Clean speech test  : PASS
    Noisy speech test  : PASS

Observed Whisper comparison with fan noise:

    Raw audio   : "When is a microcontroller?"
    GTCRN audio : "What is a microcontroller?"

GTCRN passed the Phase 2 standalone resource and basic speech-quality
evaluation. It is retained as the project's speech-enhancement dependency.

Note: GTCRN is not integrated into the production voice pipeline by this
dependency update.

## Speech-to-Text Models

All STT model weights are runtime dependencies and are stored under
`models/stt/`. Model weights are intentionally excluded from Git.

The exact installed file sizes are recorded in:

- `deps/models.manifest`

The exact installed file SHA256 values are recorded in:

- `deps/models.sha256`

### Whisper Tiny.en

- Backend name: `whisper`
- Model: Whisper Tiny.en
- Runtime: sherpa-onnx offline recognizer
- Mode: non-streaming / offline
- Provider: CPU
- Project role: stable accuracy baseline / fallback
- Installed path: `models/stt/whisper-tiny.en`
- Official archive:
  `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-tiny.en.tar.bz2`

Runtime files:

- `tiny.en-encoder.onnx`
- `tiny.en-decoder.onnx`
- `tiny.en-tokens.txt`

Benchmark status:

- Exact matches: 6 / 9
- Average WER: 6.06%
- Average RTF: 0.668
- Maximum RSS: 355.4 MB

### Streaming Zipformer 20M — 2023-02-17

- Backend name: `zipformer_20m`
- Model: `sherpa-onnx-streaming-zipformer-en-20M-2023-02-17`
- Runtime: sherpa-onnx online recognizer
- Mode: streaming transducer
- Provider: CPU
- Project role: experimental lightweight / speed baseline
- Installed path:
  `models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17`
- Official archive:
  `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17.tar.bz2`

Runtime files:

- `encoder-epoch-99-avg-1.onnx`
- `decoder-epoch-99-avg-1.onnx`
- `joiner-epoch-99-avg-1.onnx`
- `tokens.txt`

Benchmark status:

- Exact matches: 0 / 9
- Average WER: 52.41%
- Average RTF: 0.267
- Maximum RSS: 218.8 MB

The model is retained because it provides a useful lightweight and
latency/resource reference, but it is not the selected primary STT backend.

### Streaming Zipformer — 2023-06-21

- Backend name: `zipformer_2023_06_21`
- Model: `sherpa-onnx-streaming-zipformer-en-2023-06-21`
- Runtime: sherpa-onnx online recognizer
- Mode: streaming transducer
- Provider: CPU
- Project role: selected primary streaming STT candidate
- Installed path:
  `models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-21`
- Official archive:
  `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-en-2023-06-21.tar.bz2`

Runtime files:

- `encoder-epoch-99-avg-1.onnx`
- `decoder-epoch-99-avg-1.onnx`
- `joiner-epoch-99-avg-1.onnx`
- `tokens.txt`

Benchmark status:

- Exact matches: 5 / 9
- Average WER: 6.88%
- Average RTF: 0.613
- Maximum RSS: 760.8 MB

This model is the selected streaming candidate for the next architecture
iteration. Whisper Tiny.en remains available as the stable fallback.

Full benchmark details:

- `docs/benchmarks/STT_BENCHMARK_REPORT_2026-08-26.md`
