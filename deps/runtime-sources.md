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
