# Setup and Deployment

Tài liệu này mô tả cách dựng lại project trên HOST/Jetson và giữ runtime reproducible.

---

## 1. Workflow chuẩn

```text
HOST
  │
  ├── edit / build / test
  └── commit + push
        │
        ▼
      GitHub
        │
        ▼
      Jetson
        │
        ├── git pull
        ├── rebuild nếu cần
        └── hardware test
```

GitHub là source of truth.

## 2. Target

```text
Jetson Nano 4GB
JetPack 4.6.1
L4T 32.x
CUDA 10.2
Python 3.6.9
Maxwell cc 5.3
```

## 3. Clone

```bash
git clone <project-repository>
cd jetson-voice-assistant
git checkout dev
```

## 4. Sherpa source

Source metadata:

```text
deps/sherpa-onnx.remote
deps/sherpa-onnx.commit
```

Pinned commit:

```text
3e409338959097c6518998c9b72757db257f5f6f
```

HOST dev tree:

```text
~/jetson-voice-assistant-runtime-dev/sherpa-onnx
```

Jetson runtime:

```text
~/jetson-voice-assistant/runtime/sherpa-onnx
```

## 5. Apply patches

Từ clean pinned tree:

```bash
PATCH_DIR=~/jetson-voice-assistant/patches/sherpa-onnx

git apply "$PATCH_DIR/latency-instrumentation.patch"
git apply "$PATCH_DIR/vad-stt-decoupling.patch"
git apply "$PATCH_DIR/gtcrn-enhancement-integration.patch"
git apply "$PATCH_DIR/smart-turn-integration.patch"
git apply "$PATCH_DIR/speculative-turn-integration.patch"
git apply "$PATCH_DIR/barge-in-speech-started.patch"

git diff --check
```

Không apply lại patch đã có trên Jetson. Luôn dùng `git apply --check` trước patch mới.

## 6. Build sherpa target

Ubuntu HOST dependencies đã dùng:

```bash
sudo apt update
sudo apt install -y \
    build-essential \
    cmake \
    git \
    pkg-config \
    libasound2-dev
```

Configure:

```bash
cmake -S . -B build \
    -DSHERPA_ONNX_ENABLE_ALSA=ON
```

Build:

```bash
cmake --build build \
    --target sherpa-onnx-vad-alsa-offline-asr \
    -j2
```

## 7. Models

Runtime tối thiểu:

```text
Silero VAD
Whisper Tiny.en encoder/decoder/tokens
Gemma GGUF
```

Optional:

```text
GTCRN
Smart Turn
```

Model weights không nằm trong Git.

Source/version/checksum chính thức nên được ghi tại:

```text
deps/models.manifest
deps/models.sha256
deps/runtime-sources.md
```

Nếu repo có download/conversion script thì script là cách provisioning ưu tiên.

## 8. Experiment vs official

```text
new model
   ↓
EXPERIMENT
   ↓
models/ (ignored)
   ↓
benchmark RAM / CPU / latency / quality
   ↓
PASS?
 /   \
NO   YES
│     │
remove officialize
      ↓
manifest + SHA256 + source + deterministic script
```

Không đưa candidate chưa benchmark vào dependency chính thức.

## 9. llama.cpp

Local backend cần OpenAI-compatible server tại:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Current model:

```text
Gemma 3 1B Q4_K_M
```

llama.cpp trên Nano phải build phù hợp CUDA 10.2 / compute capability 5.3.

## 10. Run

Stable config:

```bash
cd ~/jetson-voice-assistant

VOICE_ASSISTANT_GTCRN=1 \
VOICE_ASSISTANT_SMART_TURN=0 \
VOICE_ASSISTANT_SPECULATIVE=0 \
LLM_MODE=local \
python3 app/voice_assistant.py
```

## 11. Validation

Kiểm tra lần lượt:

```text
[ ] microphone hoạt động
[ ] VAD nhận speech
[ ] Whisper có transcript
[ ] LLM stream response
[ ] nhiều turn không crash
[ ] barge-in dừng generation cũ
[ ] turn mới vẫn được xử lý
```

Logs:

```text
logs/conversations/
logs/benchmarks/python_llm_latency/
logs/benchmarks/full_pipeline_latency/
```

## 12. Definition of reproducible

Một dependency/runtime chỉ nên coi là chính thức khi biết:

```text
source
version / commit
checksum nếu là model
build command
runtime config
hardware validation result
```
