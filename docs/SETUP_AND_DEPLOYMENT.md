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
git apply "$PATCH_DIR/streaming-asr-integration.patch"
git apply "$PATCH_DIR/streaming-asr-speech-gating.patch"
git apply "$PATCH_DIR/speech-runtime-readiness.patch"
git apply "$PATCH_DIR/alsa-capture-retry.patch"

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

Build cả offline và streaming target:

```bash
cmake --build build \
    --target \
      sherpa-onnx-vad-alsa-offline-asr \
      sherpa-onnx-vad-alsa-streaming-asr \
    -j2
```

## 7. Models

Runtime mặc định tối thiểu:

```text
Silero VAD
Whisper Tiny.en encoder/decoder/tokens
Gemma GGUF
```

Optional:

```text
GTCRN
Smart Turn
Zipformer 20M / Zipformer 2023-06-21 khi chạy streaming backend
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

Cấu hình mặc định hiện tại:

```bash
cd ~/jetson-voice-assistant

VOICE_ASSISTANT_STT=whisper \
VOICE_ASSISTANT_GTCRN=0 \
VOICE_ASSISTANT_SMART_TURN=0 \
VOICE_ASSISTANT_SPECULATIVE=0 \
VOICE_ASSISTANT_BARGE_IN=1 \
LLM_MODE=local \
python3 app/voice_assistant.py
```

## 11. Validation

Kiểm tra lần lượt:

```text
[ ] microphone hoạt động
[ ] VAD nhận speech
[ ] `[READY]` xuất hiện trước lời nhắc `Speak...`
[ ] backend STT được chọn có transcript
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

Các path trên là runtime-generated và không commit. Benchmark implementation phải nằm dưới `benchmarks/`; xem `benchmarks/README.md`.

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

---

## 13. Remote LLM trên Windows — Ollama + Cloudflare Tunnel

> Đây là **deployment thử nghiệm**, không phải architecture LLM cuối cùng của project.
> Jetson vẫn dùng cùng `RemoteOpenAICompatibleBackend`; Windows chỉ cung cấp một OpenAI-compatible endpoint từ xa.

Cấu hình đã từng dùng:

```text
Windows GPU : RTX 5090
Runtime     : Ollama
Model       : ministral-3:8b
Tunnel      : Cloudflare Quick Tunnel
Jetson mode : LLM_MODE=remote
```

### 1. Trước khi chạy trên Windows

Mở **PowerShell**.

#### Kiểm tra GPU

```powershell
nvidia-smi
```

Quan sát:

- GPU Util
- Memory-Usage
- process nào đang dùng GPU

Nếu GPU đang bị dùng nặng thì không nên chạy thêm model.

#### Kiểm tra runtime/process AI đang chạy

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "ollama|llama|lmstudio|python|vllm|sglang" } |
    Select-Object ProcessId,Name,CommandLine
```

Không tự ý kill process lạ.

#### Kiểm tra các model Ollama đã có

```powershell
ollama list
```

Model chat đang dùng:

```text
ministral-3:8b
```

#### Kiểm tra model nào đang được Ollama load để suy luận

```powershell
ollama ps
```

Nếu đang có model khác được load thì cần chú ý vì có thể đang dùng GPU chung.

#### Kiểm tra Ollama server

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "ollama" } |
    Select-Object ProcessId,Name,CommandLine
```

Kiểm tra port:

```powershell
Get-NetTCPConnection -LocalPort 11434 |
    Select-Object LocalAddress,LocalPort,State,OwningProcess
```

---

### 2. Chạy Cloudflare Tunnel trên Windows

`cloudflared.exe` hiện nằm tại:

```text
C:\Users\PC\llm-tunnel-test\cloudflared.exe
```

Chạy:

```powershell
$DIR="$env:USERPROFILE\llm-tunnel-test"

& "$DIR\cloudflared.exe" tunnel `
  --url http://127.0.0.1:11434 `
  --no-autoupdate
```

Cloudflare sẽ tạo URL dạng:

```text
https://xxxxx.trycloudflare.com
```

Copy đúng URL nằm trong dòng:

```text
Your quick Tunnel has been created!
```

Giữ nguyên cửa sổ PowerShell đang chạy `cloudflared`.

Luồng:

```text
Jetson
  ↓ HTTPS
Cloudflare public endpoint
  ↓
Cloudflare Tunnel
  ↓
cloudflared trên Windows
  ↓
127.0.0.1:11434
  ↓
Ollama
  ↓
ministral-3:8b
  ↓
RTX 5090
```

---

### 3. Chạy Voice Assistant trên Jetson

Trên Jetson:

```bash
cd ~/jetson-voice-assistant
```

Cấu hình speech pipeline:

```bash
export VOICE_ASSISTANT_GTCRN=1
export VOICE_ASSISTANT_SMART_TURN=0
export VOICE_ASSISTANT_SPECULATIVE=0
```

Cấu hình remote LLM:

```bash
export LLM_MODE=remote
export REMOTE_LLM_URL="https://xxxxx.trycloudflare.com"
export REMOTE_LLM_MODEL="ministral-3:8b"
unset REMOTE_LLM_API_KEY
```

Thay:

```text
https://xxxxx.trycloudflare.com
```

bằng URL Quick Tunnel mới vừa tạo.

Kiểm tra URL trước khi chạy:

```bash
echo "$REMOTE_LLM_URL"
```

Phải có dạng:

```text
https://xxxxx.trycloudflare.com
```

Sau đó chạy:

```bash
python3 app/voice_assistant.py
```

---

### 4. Khi dùng xong

#### Trên Jetson

Dừng Voice Assistant:

```text
Ctrl+C
```

Không sửa tracked source trên Jetson. Sau khi dừng, `git status --short` phải không có thay đổi tracked ngoài những gì đã pull từ GitHub.

---

#### Trên Windows

Dừng Cloudflare Tunnel:

```text
Ctrl+C
```

Kiểm tra `cloudflared` đã tắt:

```powershell
Get-Process cloudflared -ErrorAction SilentlyContinue
```

Nếu không có output thì tunnel đã tắt.

#### Unload model Ministral khỏi Ollama

Chỉ chạy lệnh này khi chắc chắn **không có người khác đang dùng cùng model**:

```powershell
ollama stop ministral-3:8b
```

Lệnh này chỉ unload model khỏi Ollama/VRAM, không stop toàn bộ Ollama server.

Kiểm tra:

```powershell
ollama ps
```

Nếu `ministral-3:8b` không còn xuất hiện thì model đã được unload.

#### Kiểm tra GPU sau khi dừng

```powershell
nvidia-smi
```

VRAM nên giảm nếu không còn workload khác.

---

### 5. Checklist ngắn cho lần chạy sau

#### Windows

```powershell
nvidia-smi
```

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match "ollama|llama|lmstudio|python|vllm|sglang" } |
    Select-Object ProcessId,Name,CommandLine
```

```powershell
ollama list
ollama ps
```

Chạy tunnel:

```powershell
$DIR="$env:USERPROFILE\llm-tunnel-test"

& "$DIR\cloudflared.exe" tunnel `
  --url http://127.0.0.1:11434 `
  --no-autoupdate
```

Copy URL mới.

#### Jetson

```bash
cd ~/jetson-voice-assistant

export VOICE_ASSISTANT_GTCRN=1
export VOICE_ASSISTANT_SMART_TURN=0
export VOICE_ASSISTANT_SPECULATIVE=0

export LLM_MODE=remote
export REMOTE_LLM_URL="https://xxxxx.trycloudflare.com"
export REMOTE_LLM_MODEL="ministral-3:8b"
unset REMOTE_LLM_API_KEY

python3 app/voice_assistant.py
```

#### Khi kết thúc

Jetson:

```text
Ctrl+C
```

Windows:

```text
Ctrl+C
```

Sau đó:

```powershell
ollama stop ministral-3:8b
Get-Process cloudflared -ErrorAction SilentlyContinue
ollama ps
nvidia-smi
```

> Chỉ chạy `ollama stop ministral-3:8b` khi chắc chắn model đó không đang được người khác sử dụng.
