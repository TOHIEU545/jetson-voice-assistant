# Nguồn Runtime

File này ghi provenance và quan hệ build của dependency runtime đã được project chấp nhận. Binary/model thực tế nằm dưới `runtime/` và `models/`, không commit vào Git.

## llama.cpp

Runtime Jetson Nano được cài từ:

- Project: `kreier/llama.cpp-jetson`
- Installer: `https://kreier.github.io/llama.cpp-jetson.nano/install.sh`

Lệnh provisioning đã dùng:

```bash
curl -fsSL https://kreier.github.io/llama.cpp-jetson.nano/install.sh | bash
```

Các binary quan trọng là `llama-cli`, `llama-server` và `llama-bench`. Exact `llama-server` đã validate được ghi trong `deps/llama-server.manifest`, gồm version 5050/commit `23106f94`, target aarch64, CUDA device và SHA256.

## sherpa-onnx

Upstream base:

```text
remote: deps/sherpa-onnx.remote
commit: deps/sherpa-onnx.commit
```

Giá trị hiện tại:

```text
https://github.com/k2-fsa/sherpa-onnx.git
3e409338959097c6518998c9b72757db257f5f6f
```

Ordered project delta phải apply trên clean tree đúng commit:

1. `patches/sherpa-onnx/latency-instrumentation.patch`
2. `patches/sherpa-onnx/vad-stt-decoupling.patch`
3. `patches/sherpa-onnx/gtcrn-enhancement-integration.patch`
4. `patches/sherpa-onnx/smart-turn-integration.patch`
5. `patches/sherpa-onnx/speculative-turn-integration.patch`
6. `patches/sherpa-onnx/barge-in-speech-started.patch`
7. `patches/sherpa-onnx/streaming-asr-integration.patch`
8. `patches/sherpa-onnx/streaming-asr-speech-gating.patch`
9. `patches/sherpa-onnx/speech-runtime-readiness.patch`
10. `patches/sherpa-onnx/alsa-capture-retry.patch`

Không bỏ qua hoặc đổi thứ tự nếu chưa rebase và verify lại patch stack. Responsibility/verification chi tiết của từng patch nằm trong `docs/SOFTWARE_REFERENCE.md`.

## Policy EXPERIMENT và OFFICIAL

```text
EXPERIMENT
→ download vào ignored models/ hoặc runtime/
→ benchmark local/Jetson
→ chưa sửa manifest/checksum/provisioning

OFFICIAL
→ benchmark PASS
→ project quyết định adopt
→ cập nhật deps/, checksum, download/build script và documentation
```

Không coi model/runtime mới là official chỉ vì file đã tồn tại cục bộ.

## Model metadata

- Path và byte size: `deps/models.manifest`.
- Integrity SHA256: `deps/models.sha256`.
- STT provisioning/verification: `scripts/download_stt_models.sh`.
- GTCRN provisioning/verification: `scripts/download_enhancement_models.sh`.

### GTCRN Simple

- File: `models/enhancement/gtcrn_simple.onnx`
- Source: `https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/gtcrn_simple.onnx`
- Sample rate: 16 kHz
- Size: 535638 bytes
- SHA256: `e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534`
- Vai trò: optional streaming enhancement trước VAD/STT.

Standalone Jetson benchmark đã ghi RTF offline 0.254, online 0.356, peak RSS khoảng 26.8 MiB và gần một CPU core ở online mode. GTCRN hiện đã được tích hợp vào cả Whisper offline runtime và Zipformer streaming runtime qua patch stack; flag runtime vẫn default OFF.

### Silero VAD

- File: `models/vad/silero_vad.onnx`
- Size: 643854 bytes
- SHA256 nằm trong `deps/models.sha256`.
- Vai trò: speech start/endpoint cho cả hai runtime; chạy liên tục kể cả khi streaming ASR đang gated.

### Whisper Tiny.en

- Backend: `whisper`
- Runtime: sherpa-onnx offline recognizer
- Path: `models/stt/whisper-tiny.en`
- Official archive: `https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-whisper-tiny.en.tar.bz2`
- Vai trò: stable accuracy baseline/fallback và runtime default hiện tại.

Runtime files: `tiny.en-encoder.onnx`, `tiny.en-decoder.onnx`, `tiny.en-tokens.txt`.

Benchmark 9 mẫu: exact 6/9, average WER 6.06%, average RTF 0.668, maximum RSS 355.4 MB.

### Streaming Zipformer 20M — 2023-02-17

- Backend: `zipformer_20m`
- Runtime: sherpa-onnx online recognizer
- Path: `models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17`
- Vai trò: experimental lightweight/speed baseline, không phải selected primary backend.

Runtime files: encoder, decoder, joiner `epoch-99-avg-1.onnx` và `tokens.txt`.

Benchmark 9 mẫu: exact 0/9, average WER 52.41%, average RTF 0.267, maximum RSS 218.8 MB.

### Streaming Zipformer — 2023-06-21

- Backend: `zipformer_2023_06_21`
- Runtime: sherpa-onnx online recognizer
- Path: `models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-21`
- Vai trò: benchmark-selected primary streaming backend; chưa là launcher/runtime default.

Runtime files: encoder, decoder, joiner `epoch-99-avg-1.onnx` và `tokens.txt`.

Benchmark 9 mẫu: exact 5/9, average WER 6.88%, average RTF 0.613, maximum RSS 760.8 MB.

Streaming architecture được chấp nhận dùng Silero VAD gating và rolling pre-roll 480 ms; report chi tiết ở `docs/stt-models/BENCHMARK.md`.

## Khi cập nhật file này

Chỉ cập nhật sau khi xác minh source/version/commit, build command, runtime config và hardware validation. Nếu bytes model hoặc binary đổi, phải cập nhật manifest/checksum tương ứng trong cùng thay đổi.
