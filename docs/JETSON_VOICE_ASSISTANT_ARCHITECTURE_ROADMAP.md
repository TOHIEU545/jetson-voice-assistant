# Jetson Voice Assistant — Kiến trúc hiện tại và Roadmap tối ưu theo `huggingface/speech-to-speech`

> **Mục tiêu tài liệu**
>
> Tài liệu này tổng hợp trạng thái thực tế của project trong `source.tar.gz`, giải thích kiến trúc/model/runtime hiện tại, sau đó đề xuất kiến trúc mới và roadmap phát triển **bám sát cách tổ chức của repo `huggingface/speech-to-speech`**.
>
> Nguyên tắc quan trọng: **không copy mù các model mặc định của Hugging Face lên Jetson Nano**. Ta học **kiến trúc, cách chia module, queue/worker, turn state, backend abstraction và realtime workflow**; còn model/runtime được chọn theo giới hạn phần cứng Jetson Nano.

---

## 0. Quyết định kiến trúc đã chốt

Reference chính từ thời điểm này:

- Repository: `huggingface/speech-to-speech`
- Kiểu kiến trúc: **cascaded speech pipeline**
- Pipeline khái quát của repo:

```text
Audio
  ↓
VAD
  ↓
STT
  ↓
LLM
  ↓
TTS
```

Nhưng phần quan trọng hơn sơ đồ trên là cách repo triển khai:

```text
Audio input
    ↓
VAD Handler
    ↓ Queue
STT Handler
    ↓ Queue
LLM Handler
    ↓ Queue
TTS Handler
    ↓
Audio output
```

Mỗi stage là một component riêng, được nối bằng `Queue`, có state/cancellation/turn management và có thể thay backend.

### Hướng của project Jetson

Ta sẽ giữ triết lý đó nhưng dùng các component nhẹ hơn:

```text
                      Jetson Nano
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  Mic                                                       │
│   ↓                                                        │
│  [Audio Enhancement]                                       │
│   ↓                                                        │
│  Silero VAD Worker                                         │
│   ↓ speech_queue                                           │
│  [Smart Turn / Turn Controller]                            │
│   ↓                                                        │
│  Whisper Tiny.en STT Worker                                │
│   ↓ transcript_queue                                       │
│  Transcript Gate                                           │
│   ↓ valid_turn_queue                                       │
│  LLM Backend                                               │
│   ├── Local: Gemma 3 1B Q4 + llama.cpp                     │
│   └── Remote: OpenAI-compatible API trên GPU server        │
│                                                            │
│  [TTS slot — để sau, chưa cần ở phiên bản hiện tại]        │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### Những thứ **không nằm trong scope hiện tại**

Không thêm nếu chưa có dữ liệu chứng minh cần thiết:

- Wake word / KWS.
- Speaker verification / voiceprint.
- Speaker diarization.
- Microphone array / beamforming.
- Một model audio-language lớn end-to-end.
- Thay hàng loạt model cùng lúc.

Mục tiêu trước mắt vẫn là:

> **Voice assistant local chạy ổn định trên Jetson Nano, giảm transcript rác, realtime hơn, dễ benchmark và có thể đổi LLM local/remote mà không phá pipeline.**

---

# PHẦN I — PROJECT HIỆN TẠI

## 1. Phần cứng và môi trường mục tiêu

Project hiện nhắm tới:

```text
Jetson Nano
├── Architecture : ARM64 / aarch64
├── GPU          : NVIDIA Tegra X1 / Maxwell
├── CUDA         : 10.2
├── Kernel       : 4.9.253-tegra
└── RAM target   : 4 GB shared memory
```

Theo `docs/system_snapshot.txt`:

```text
Linux jetson 4.9.253-tegra
CUDA 10.2 V10.2.300
aarch64
```

Đây là constraint rất quan trọng. Repo Hugging Face hiện đại có thể sử dụng Python/PyTorch/CUDA mới hơn, vì vậy **không nên cố cài nguyên repo lên Nano**. Ta dùng repo đó làm reference architecture.

---

# 2. Cấu trúc source hiện tại

Các phần quan trọng trong archive:

```text
jetson-voice-assistant-source/
├── app/
│   └── voice_assistant.py
│
├── scripts/
│   └── llama_server.sh
│
├── tests/
│   ├── audio/
│   └── latency/
│       └── test_llm_latency.py
│
├── logs/
│   └── benchmarks/
│       ├── full_pipeline_latency/
│       ├── llm_latency/
│       ├── python_llm_latency/
│       └── vad_stt_latency/
│
├── deps/
│   ├── llama-server.manifest
│   ├── models.manifest
│   ├── models.sha256
│   ├── runtime-sources.md
│   ├── sherpa-onnx.commit
│   └── sherpa-onnx.remote
│
├── patches/
│   └── sherpa-onnx/
│       └── latency-instrumentation.patch
│
└── docs/
    ├── project_tree.txt
    └── system_snapshot.txt
```

### Ý nghĩa

- `voice_assistant.py`: orchestration chính hiện tại.
- `llama_server.sh`: quản lý local LLM server.
- `sherpa-onnx`: runtime speech.
- `patches/sherpa-onnx`: giữ modification đo latency trên C++.
- `logs/benchmarks`: baseline để so sánh trước/sau optimization.
- `deps/*`: lưu exact runtime/model information để project reproducible.

Đây là nền tảng khá tốt để tiếp tục refactor có kiểm soát.

---

# 3. Kiến trúc hiện tại

Pipeline hiện tại:

```text
                           Jetson Nano

Microphone / ALSA
      ↓
sherpa-onnx C++ executable
      │
      ├── Silero VAD
      │
      └── Whisper Tiny.en offline ASR
      ↓
stdout pipe
      ↓
Python `voice_assistant.py`
      ↓
Transcript Gate
      ↓
Conversation history
      ↓
HTTP /v1/chat/completions
      ↓
llama-server
      ↓
Gemma 3 1B Q4_K_M
      ↓
streamed text response
```

Tên executable speech hiện tại:

```text
runtime/sherpa-onnx/build/bin/
└── sherpa-onnx-vad-alsa-offline-asr
```

Điểm cần hiểu:

> Hiện tại **VAD và STT chưa phải hai worker độc lập**. Chúng đang nằm chung trong một C++ executable.

---

# 4. Model và runtime hiện tại

## 4.1 VAD

Model:

```text
models/vad/silero_vad.onnx
```

Kích thước:

```text
643,854 bytes ≈ 0.61 MiB
```

Runtime:

```text
sherpa-onnx
  ↓
ONNX Runtime
  ↓
CPU
```

Config explicit trong `voice_assistant.py`:

```text
--silero-vad-threshold=0.5
--silero-vad-max-speech-duration=60
--vad-provider=cpu
--vad-num-threads=1
```

Vai trò:

```text
audio stream
   ↓
Silero
   ↓
speech / non-speech
   ↓
speech segment
```

Silero không xác định:

- người nói là ai;
- câu có ý nghĩa hay không;
- người nói có đang nói với assistant hay không.

Nó chỉ làm **Voice Activity Detection**.

---

## 4.2 STT

Model:

```text
Whisper Tiny.en
```

File đang sử dụng trực tiếp:

```text
tiny.en-encoder.onnx   ≈ 37.6 MB
tiny.en-decoder.onnx   ≈ 114.5 MB
tiny.en-tokens.txt
```

Archive cũng chứa INT8 variants nhưng `voice_assistant.py` hiện dùng bản non-INT8.

Runtime:

```text
sherpa-onnx
  ↓
ONNX Runtime
  ↓
CPU
```

Config:

```text
--model-type=whisper
--provider=cpu
--num-threads=2
```

Đây là **offline ASR trên từng speech segment**, không phải streaming Whisper decoder.

---

# 5. Transcript Gate hiện tại

Gate đã được thêm trực tiếp sau STT:

```python
if any(ch in text for ch in "()[]{}"):
    # DROP
    continue
```

Luồng:

```text
Whisper result
     ↓
Transcript Gate
     ├── suspicious annotation → DROP
     └── normal text           → PASS
```

Ví dụ thực tế:

```text
(buzzing)          → DROP
(muffled speaking  → DROP
[inaudible]        → DROP
```

Điểm rất quan trọng:

```text
DROP
 ↓
không append history
 ↓
không gửi LLM
 ↓
không làm bẩn conversation context
```

Gate hiện tại cố tình **bảo thủ**: chỉ loại những pattern có tín hiệu rất rõ. Nó không cố semantic-classify mọi transcript.

### Đây có phải component của HF repo không?

**Không phải chính xác.**

Đây là một safeguard riêng của project dựa trên transcript rác thực tế đã quan sát.

Tuy nhiên vị trí của nó phù hợp với thiết kế modular:

```text
STT Handler
   ↓
Validation Handler
   ↓
LLM Handler
```

Do đó ta giữ Gate như một **project-specific handler**, không nhét logic này vào STT hoặc LLM.

---

# 6. LLM hiện tại

Model:

```text
Gemma 3 1B Instruct
```

Quantization:

```text
Q4_K_M
```

File:

```text
gemma-3-1b-it-Q4_K_M.gguf
```

Kích thước:

```text
806,058,240 bytes ≈ 769 MiB
```

Runtime:

```text
llama.cpp
```

Exact `llama-server` manifest:

```text
version: 5050 (23106f94)
architecture: aarch64
GPU: NVIDIA Tegra X1
compute capability: 5.3
```

Server config:

```text
host     : 127.0.0.1
port     : 8080
context  : 2048
-ngl     : 99
threads  : 2
```

API:

```text
POST http://127.0.0.1:8080/v1/chat/completions
```

Streaming:

```json
"stream": true
```

Điểm rất tốt trong kiến trúc hiện tại:

> LLM **đã chạy ngoài Python application như một backend HTTP riêng**.

Đây là bước gần với cách HF `speech-to-speech` thiết kế swappable LLM backend.

---

# 7. Conversation state hiện tại

History nằm trong Python:

```text
history = [
    system,
    user,
    assistant,
    user,
    assistant,
    ...
]
```

Hiện chưa có một `ConversationManager` riêng.

Một vấn đề cần tối ưu sau:

```text
history tăng dần
      ↓
context 2048 có giới hạn
```

HF repo có khái niệm `chat_size` và một realtime service quản lý state riêng. Ta nên học cách này thay vì để một list không giới hạn trong `voice_assistant.py`.

---

# 8. Latency instrumentation hiện tại

Project đã instrument 5 mốc:

```text
T0 = actual speech end
T1 = VAD completed segment
T2 = transcript ready
T3 = Python starts LLM request
T4 = first LLM token
T5 = last LLM token
```

Các metric:

```text
VAD                 = T1 - T0
STT                 = T2 - T1
VAD + STT           = T2 - T0
Python overhead     = T3 - T2
LLM TTFT            = T4 - T3
LLM generation      = T5 - T4
Speech → First      = T4 - T0
Speech → Last       = T5 - T0
```

Patch hiện nằm tại:

```text
patches/sherpa-onnx/latency-instrumentation.patch
```

Đây là một điểm rất tốt và **phải giữ xuyên suốt refactor**, vì mọi optimization phải được chứng minh bằng benchmark.

---

# 9. Baseline latency

Từ benchmark `full_pipeline_latency_2026-08-18_03-26-26.jsonl`:

| Stage | Trung bình |
|---|---:|
| VAD | ~0.500 s |
| STT | ~1.995 s |
| VAD + STT | ~2.495 s |
| Python overhead | ~0.001 s |
| LLM TTFT | ~0.810 s |
| LLM generation | ~2.593 s |
| Speech end → first token | ~3.306 s |
| Speech end → last token | ~5.899 s |

Kết luận:

```text
Before first token:
VAD + STT chiếm phần lớn latency
Python overhead gần như bằng 0
LLM TTFT tương đối ổn
```

Việc LLM generate dài có thể kéo `Speech → Last` lên cao, nhưng do streaming nên trải nghiệm thực tế dựa nhiều hơn vào `Speech → First`.

---

# 10. Điểm yếu kiến trúc hiện tại

## 10.1 VAD và STT bị gắn chung

Trong source C++ instrumented:

```cpp
vad->AcceptWaveform(...)

while (!vad->Empty()) {
    ...
    recognizer.DecodeStream(...)
    ...
}
```

Tức là:

```text
ALSA read
 ↓
VAD
 ↓
segment ready
 ↓
offline Whisper DecodeStream()
 ↓
quay lại audio loop
```

Trong lúc `DecodeStream()` chạy, cùng thread đó không tiếp tục `alsa.Read()`.

ALSA buffer có thể giữ audio nên thực tế hiện tại vẫn khá ổn, nhưng đây **không phải kiến trúc realtime decoupled**.

---

## 10.2 Python bị block trong lúc stream LLM

Python hiện:

```text
read transcript
 ↓
urllib.request.urlopen()
 ↓
for streamed token...
 ↓
đợi response kết thúc
 ↓
quay lại đọc sherpa stdout
```

Trong lúc đó sherpa subprocess vẫn có thể tiếp tục và OS pipe có thể buffer output.

Do đó hệ thống hiện có:

```text
implicit buffering
```

chứ chưa có:

```text
explicit controlled queue
```

Hai thứ này khác nhau.

---

## 10.3 Chưa có Turn Manager thực sự

Hiện chưa có:

```text
turn_id
revision
cancel scope
queue ownership
response state
barge-in
```

Điều này sẽ làm các feature realtime nâng cao khó triển khai.

---

## 10.4 LLM backend còn hard-code

Hiện:

```python
LLM_URL = "http://127.0.0.1:8080/v1/chat/completions"
```

Ta đã dùng API architecture đúng hướng, nhưng chưa abstraction thành:

```text
LLMBackend
├── NanoLocalBackend
└── RemoteBackend
```

---

## 10.5 Không có audio enhancement

Raw microphone audio được đưa trực tiếp vào Silero.

Khi có:

```text
fan
hum
hiss
environment noise
```

VAD/STT phải tự chịu toàn bộ noise.

---

# PHẦN II — `huggingface/speech-to-speech` ĐANG LÀM GÌ?

## 11. Bản chất repo HF

Repo tự mô tả là một **fully open and modular cascaded pipeline**:

```text
1. VAD
2. STT
3. Language Model
4. TTS
```

Khác với một cloud audio model kín, source của pipeline orchestration được public.

Các phần public gồm:

```text
VAD Handler
STT handlers
TranscriptionNotifier
LLM handlers
LMOutputProcessor
TTS handlers
RealtimeService
PipelineUnit
Queue types
CancelScope
SpeculativeTurnTracker
ThreadManager
Realtime server
```

Đây là lý do repo phù hợp làm reference architecture.

---

# 12. Queue architecture của HF

Trong `s2s_pipeline.py`, mỗi `PipelineUnit` có riêng:

```text
recv_audio_chunks_queue
spoken_prompt_queue
stt_output_queue
text_prompt_queue
lm_response_queue
lm_processed_queue
send_audio_chunks_queue
text_output_queue
```

Luồng cơ bản:

```text
recv_audio_chunks_queue
        ↓
       VAD
        ↓
spoken_prompt_queue
        ↓
       STT
        ↓
stt_output_queue
        ↓
TranscriptionNotifier
        ↓
text_prompt_queue
        ↓
       LLM
        ↓
lm_response_queue
        ↓
LMOutputProcessor
        ↓
lm_processed_queue
        ↓
       TTS
        ↓
send_audio_chunks_queue
```

Đây **không phải chỉ để code đẹp**.

Nó cho phép từng stage:

- hoạt động độc lập;
- chạy thread riêng;
- buffer có kiểm soát;
- cancel độc lập;
- đo latency riêng;
- gắn metadata/turn ID;
- không block toàn pipeline khi một stage chậm.

---

# 13. Model/reference mặc định của HF

Theo `main` hiện tại:

### VAD

```text
Silero VAD v5
```

### Smart Turn

```text
Pipecat Smart Turn v3.2
CPU ONNX
```

Bật mặc định trong realtime mode.

### STT default

```text
Parakeet TDT
```

Repo cũng support:

```text
Whisper
Faster Whisper
Parakeet
Paraformer
MLX Whisper variants
```

Điều quan trọng:

> **Repo không bắt buộc Parakeet.**

Do đó giữ Whisper trên Jetson vẫn đúng với architecture của repo.

### LLM default

Backend mặc định hiện theo API-compatible path.

Repo hỗ trợ:

```text
Transformers local
MLX local
Responses API
Chat Completions-compatible backend
llama.cpp server
vLLM server
cloud provider
```

### TTS

Repo hỗ trợ nhiều backend, bao gồm:

```text
Qwen3-TTS
Pocket TTS
Kokoro
ChatTTS
Facebook MMS
```

### Audio enhancement

Có option:

```text
audio_enhancement
```

và repo sử dụng **DeepFilterNet** cho feature này.

Mặc định audio enhancement hiện **OFF**.

---

# 14. VAD design của HF đáng học ở điểm nào?

HF không chỉ có:

```text
threshold
```

Mà còn state/temporal behavior:

```text
min_speech_ms
min_silence_ms
min_speech_continuation_ms
speech_pad_ms
speculative_reopen_ms
short_segment_merge_ms
```

Điều đáng học không phải là copy tất cả giá trị mặc định, mà là:

> **VAD được xem là một stateful turn frontend, không chỉ là một hàm `probability > threshold`.**

---

# 15. Smart Turn của HF có vai trò gì?

Đây phải được hiểu đúng:

```text
Silero
 ↓
speech segment kết thúc
 ↓
Smart Turn
 ↓
turn đã thực sự complete chưa?
```

Smart Turn **không phải noise suppression** và không phải speaker verification.

Nó giúp các trường hợp:

```text
"Can you explain..."
      [pause]
"...how UART works?"
```

không bị coi thành hai turn độc lập quá sớm.

HF còn dùng:

```text
turn revision
speculative reopen window
incomplete delay
```

để cho phép work bắt đầu sớm nhưng vẫn rollback/cancel khi user tiếp tục nói.

---

# 16. LLM abstraction của HF

Đây là phần rất phù hợp với project.

Concept:

```text
                         LLM Handler
                             │
        ┌────────────────────┼────────────────────┐
        ↓                    ↓                    ↓
Transformers local       llama.cpp/vLLM      Cloud/API
```

Pipeline phía trước không cần biết model chạy ở đâu.

Đây là kiến trúc nên copy gần như nguyên ý tưởng.

---

# PHẦN III — KIẾN TRÚC MỚI ĐỀ XUẤT

## 17. Nguyên tắc chuyển đổi

Ta **không rewrite toàn bộ project một lần**.

Quy tắc:

```text
1 phase
 ↓
benchmark
 ↓
verify behavior
 ↓
commit
 ↓
phase tiếp theo
```

Mỗi phase phải giữ hệ thống runnable.

Không đổi nhiều model cùng lúc vì khi quality/latency thay đổi sẽ không biết nguyên nhân.

---

# 18. Target pipeline

```text
                         AUDIO FRONTEND
                              │
                              ▼
                    Audio Enhancement
                      [optional module]
                              │
                              ▼
                     Silero VAD Worker
                              │
                        speech_queue
                              │
                              ▼
                    Turn Controller
                 [Smart Turn về sau]
                              │
                              ▼
                    Whisper STT Worker
                              │
                     transcript_queue
                              │
                              ▼
                    Transcript Gate
                              │
                     valid_turn_queue
                              │
                              ▼
                       LLM Worker
                  ┌───────────┴───────────┐
                  ▼                       ▼
            Local Backend           Remote Backend
              Gemma 1B            RTX 5090 / server
              llama.cpp           OpenAI-compatible
                  │                       │
                  └───────────┬───────────┘
                              ▼
                      Streaming response
                              │
                              ▼
                    [TTS Handler — later]
```

---

# 19. Mapping HF → Project

| HF `speech-to-speech` | Project Jetson |
|---|---|
| `VADHandler` | Silero/sherpa VAD Worker |
| `spoken_prompt_queue` | `speech_queue` |
| STT backend | Whisper Tiny.en / sherpa-onnx |
| `stt_output_queue` | `transcript_queue` |
| `TranscriptionNotifier` | Transcript event + project Transcript Gate |
| `text_prompt_queue` | `valid_turn_queue` |
| LLM handler | Local/Remote LLM Backend |
| `LMOutputProcessor` | Streaming response processor |
| `CancelScope` | Cancellation token / response cancel |
| `SpeculativeTurnTracker` | Turn ID + revision + Smart Turn state |
| TTS handler | Deferred |
| `RealtimeService` | Future conversation/turn manager |

Đây là mapping trực tiếp, không phải tự nghĩ một kiến trúc hoàn toàn khác.

---

# 20. Model strategy mới

## 20.1 Audio Enhancement — **candidate mới**

Reference từ HF:

```text
DeepFilterNet
```

### Tại sao thêm?

Vị trí theo HF:

```text
raw audio
 ↓
audio enhancement
 ↓
speech pipeline
```

Mục đích:

- giảm stationary/background noise;
- đưa audio sạch hơn cho downstream;
- giảm gánh nặng cho VAD/STT;
- giảm khả năng Whisper hallucinate từ audio xấu.

### Quyết định

**Không integrate ngay.**

Trước tiên:

```text
standalone benchmark
├── compatibility
├── RAM
├── CPU
├── realtime factor
└── STT quality before/after
```

Chỉ merge nếu Nano chạy được trong headroom cho phép.

Điều này bám đúng repo: `audio_enhancement` vốn cũng là **optional feature**, không phải bắt buộc.

---

## 20.2 VAD — **giữ Silero**

HF dùng:

```text
Silero VAD v5
```

Project cũng đã dùng Silero.

### Thay đổi đề xuất

Không thay model VAD một cách tùy tiện.

Việc cần làm:

```text
1. xác định version file silero_vad.onnx hiện tại
2. nếu chưa phải v5 → benchmark Silero v5
3. chỉ đổi nếu latency/false activation tốt hơn
```

Không tune threshold liên tục theo từng môi trường.

### Lý do

Điều này bám sát HF hơn là chạy đi tìm một VAD khác:

```text
HF reference → Silero V5
Project      → Silero
```

---

# 21. STT — **giữ Whisper Tiny.en trước**

HF hỗ trợ Whisper như một backend chính thức.

Do đó không có lý do phải đổi sang Parakeet chỉ vì Parakeet là default hiện tại.

### Vì sao giữ?

- model đã chạy ổn;
- latency đã đo;
- sherpa-onnx runtime hiện đã build ổn trên Nano;
- không phải kéo PyTorch/Nemo stack mới;
- accuracy hiện tại còn quan trọng hơn tiết kiệm vài trăm ms.

### Thay đổi chính không phải model

Thay đổi là:

```text
CURRENT
VAD + STT chung executable

TARGET
VAD worker
 ↓ queue
STT worker
```

Tức là **architecture optimization trước model optimization**.

---

# 22. Transcript Gate — **giữ**

Gate không phải component mặc định của HF nhưng là project-specific validation layer.

Target:

```text
STT Worker
 ↓
Transcript Gate
 ↓
LLM
```

Gate v1:

```text
empty                     → DROP
Whisper annotation ()[]{} → DROP
normal transcript         → PASS
```

Không semantic-classify mạnh ở giai đoạn này.

### Lý do giữ

Log thực tế đã chứng minh Whisper sinh:

```text
(buzzing)
(muffled speaking)
...
```

Nếu không Gate:

```text
garbage transcript
 ↓
LLM
 ↓
garbage conversation context
```

Gate ngăn đúng lỗi này với chi phí gần như 0.

---

# 23. LLM — chuyển thành backend abstraction

## 23.1 Backend A — Nano standalone

```text
Gemma 3 1B Q4_K_M
 ↓
llama-server
 ↓
127.0.0.1:8080
```

Giữ nguyên để:

- fully local;
- demo không cần PC;
- có baseline edge-only.

---

## 23.2 Backend B — Remote GPU

Có thể dùng:

```text
Jetson
 ↓ LAN
OpenAI-compatible request
 ↓
RTX 5090 PC
 ↓
larger open-weight LLM
```

PC có thể expose API bằng:

```text
llama.cpp
hoặc
vLLM
```

Điểm quan trọng:

```text
speech frontend KHÔNG đổi
```

Chỉ thay config:

```text
LLM endpoint
model name
API key nếu cần
```

Đây đúng với kiến trúc LLM backend của HF.

---

# 24. Conversation/History Manager mới

Hiện tại:

```text
history.append(...)
```

Target:

```text
ConversationManager
├── system prompt
├── bounded chat history
├── current turn
├── turn_id
├── response state
└── cancellation state
```

Học từ:

```text
RealtimeService
chat_size
SpeculativeTurnTracker
CancelScope
```

trong HF repo.

### Tại sao cần?

1. Không để context tăng vô hạn.
2. Turn nào ra turn đó.
3. Có thể cancel response.
4. Chuẩn bị cho barge-in.
5. Có thể benchmark từng turn chính xác.

---

# 25. Worker + Queue — thay đổi kiến trúc quan trọng nhất

## Hiện tại

```text
Sherpa process
  ↓ stdout
Python
  ↓
LLM request
  ↓
Python block cho đến khi LLM xong
```

Có buffering, nhưng phần lớn là:

```text
OS pipe / ALSA buffering
```

không phải application-controlled realtime flow.

---

## Target theo HF

```text
Audio/VAD Worker
       ↓
speech_queue
       ↓
STT Worker
       ↓
transcript_queue
       ↓
Gate
       ↓
LLM Worker
```

### Lợi ích chính

Không phải:

> “Queue làm Whisper nhanh hơn.”

Mà là:

```text
VAD không phải chờ LLM
STT không phụ thuộc LLM generation time
LLM streaming không khóa audio frontend
mỗi stage có queue riêng
turn metadata rõ
cancellation dễ
backpressure đo được
```

Ví dụ:

```text
Turn 1:
VAD ─ STT ─────────────── LLM generation ─────

Turn 2:
          VAD ─ STT ─ queue ───────────── LLM

Turn 3:
                 VAD ─ STT ─ queue ───────────
```

---

# 26. Quan trọng: phải tách VAD/STT thật sự

Nếu chỉ viết:

```python
vad_queue = Queue()
stt_queue = Queue()
```

nhưng vẫn gọi cùng executable:

```text
sherpa-onnx-vad-alsa-offline-asr
```

thì chưa giải quyết bản chất.

Executable đó hiện làm:

```text
Audio read → VAD → Offline STT
```

trong cùng loop.

Do đó phase queue cần một prerequisite:

> **Tách speech capture/VAD khỏi offline STT execution.**

Vẫn có thể giữ:

```text
sherpa-onnx
Silero
Whisper Tiny.en
```

nhưng orchestration phải tách stage theo cách HF tách `VADHandler` và STT backend.

---

# 27. Smart Turn — thêm sau khi Worker/Turn State ổn định

HF bật Smart Turn v3.2 mặc định trong realtime path.

Candidate:

```text
Pipecat Smart Turn v3.2
CPU ONNX
```

### Vai trò

```text
VAD says "speech stopped"
        ↓
Smart Turn
        ↓
complete turn?
```

Không dùng Smart Turn để:

- noise suppression;
- nhận diện người dùng;
- lọc người ngoài phòng.

Dùng nó để:

- tránh cắt câu sớm;
- conversation turn tự nhiên hơn;
- speculative endpoint handling.

### Vì sao không thêm ngay?

Smart Turn cần:

```text
turn_id
revision
reopen state
cancel state
```

Nếu pipeline chưa có Turn Manager/Queue thì lợi ích của Smart Turn chưa được khai thác đúng như HF.

---

# 28. Barge-in / interruption

Sau khi có:

```text
Audio Worker
Turn Manager
CancelScope
LLM Worker
```

ta mới làm:

```text
Assistant đang generate
        ↓
user bắt đầu nói
        ↓
VAD event
        ↓
cancel response hiện tại
        ↓
STT turn mới
        ↓
LLM xử lý turn mới
```

Đây là feature rất quan trọng để conversation giống realtime assistant hơn.

HF đã xây kiến trúc `CancelScope` + turn state cho mục đích này.

---

# 29. TTS

Project hiện mới cần text output.

Do đó:

```text
TTS = DEFERRED
```

Nhưng architecture vẫn chừa slot:

```text
LLM
 ↓
Response Processor
 ↓
[TTS Handler]
```

Nếu sau này cần TTS, ta benchmark một backend HF support phù hợp edge trước; không mặc định đưa Qwen3-TTS 1.7B lên Nano.

---

# PHẦN IV — ROADMAP TRIỂN KHAI

# 30. Phase 0 — Baseline & instrumentation

**Status: DONE**

Đã có:

- current models;
- runtime manifests;
- sherpa commit;
- latency patch;
- standalone LLM benchmark;
- VAD/STT benchmark;
- full pipeline benchmark;
- conversation logs.

### Không được bỏ instrumentation trong các phase sau.

---

# 31. Phase 1 — Conservative Transcript Gate

**Status: DONE / đang test thực tế**

Pipeline:

```text
Whisper
 ↓
Transcript Gate
 ↓
Gemma
```

Current hard rule:

```text
contains ()[]{} → DROP
```

### Acceptance

- `"(buzzing)"` không tạo LLM response.
- dropped transcript không vào `history`.
- valid transcript không bị ảnh hưởng.

---

# 32. Phase 2 — Audio Enhancement benchmark

**Status: NEXT**

Bám theo HF feature:

```text
audio_enhancement → DeepFilterNet
```

### Không sửa production pipeline ngay.

Test standalone:

```text
raw wav
 ↓
DeepFilterNet
 ↓
cleaned wav
```

Benchmark:

```text
1. installation/runtime compatibility
2. RAM increase
3. CPU usage
4. processing latency / realtime factor
5. Whisper transcript before vs after
6. số annotation/hallucination giảm hay không
```

### Go / No-Go

Chỉ integrate khi:

```text
quality improvement rõ
AND
resource overhead chấp nhận được
```

Nếu không pass thì bỏ module; architecture vẫn giữ optional enhancement slot.

---

# 33. Phase 3 — Tách Audio/VAD khỏi STT

**Status: PLANNED**

Mục tiêu:

```text
Audio Capture / VAD Worker
        ↓
speech_queue
        ↓
STT Worker
```

### Giữ model

```text
Silero
Whisper Tiny.en
sherpa-onnx
```

Không đổi model trong cùng phase.

### Acceptance

- audio capture chạy liên tục;
- STT decode không block audio capture;
- mỗi segment có `turn_id`;
- queue không mất segment trong test overlap;
- latency không regression đáng kể.

---

# 34. Phase 4 — Handler/Queue architecture

**Status: PLANNED**

Tạo module gần với cách HF tổ chức:

```text
Audio/VAD Handler
STT Handler
Transcript Gate Handler
LLM Handler
Response Processor
```

Mỗi handler có:

```text
queue_in
queue_out
stop_event
metrics
turn metadata
```

### Queue tối thiểu

```text
speech_queue
transcript_queue
valid_turn_queue
llm_output_queue
```

### Thêm metric

```text
queue_wait_ms
queue_depth
worker_processing_ms
turn_id
```

---

# 35. Phase 5 — Conversation Manager + bounded history

**Status: PLANNED**

Tách:

```text
history
```

khỏi `voice_assistant.py`.

Thiết kế:

```text
ConversationManager
├── history
├── max_turns/chat_size
├── current_turn
├── assistant_state
└── timestamps
```

Bám theo khái niệm:

```text
RealtimeService
chat_size
```

của HF.

---

# 36. Phase 6 — LLM Backend abstraction

**Status: PLANNED**

Interface:

```text
LLMBackend
  generate(messages, stream=True)
```

Backend:

```text
LocalLlamaCppBackend
RemoteOpenAICompatibleBackend
```

Config thay vì hard-code:

```text
LLM_BASE_URL
LLM_MODEL
LLM_API_KEY
LLM_MODE=local|remote
```

### Test

Cùng một speech pipeline:

```text
Test A → Gemma Nano
Test B → RTX 5090 API
```

So:

- TTFT;
- total generation;
- network overhead;
- response quality;
- Jetson RAM;
- Jetson CPU/GPU load.

---

# 37. Phase 7 — Smart Turn v3.2

**Status: LATER**

Bám chính xác HF:

```text
Silero finalized segment
 ↓
Smart Turn
 ↓
complete / incomplete
```

Không đưa vào trước khi turn ID/revision đã có.

Benchmark:

```text
model load RAM
inference latency
false complete
false incomplete
```

Test chính:

```text
"I want you to explain..."
[pause]
"...how SPI works."
```

---

# 38. Phase 8 — Speculative Turn + Cancellation

**Status: LATER**

Học:

```text
SpeculativeTurnTracker
CancelScope
```

Target:

```text
turn 4 rev 0
    ↓
user continues
    ↓
turn 4 rev 1
    ↓
discard stale output rev 0
```

Đây là phase giúp assistant realtime hơn rõ nhất.

---

# 39. Phase 9 — Barge-in

**Status: LATER**

User có thể nói khi assistant đang generate.

```text
LLM response
    ↓
speech_started event
    ↓
cancel current generation
    ↓
accept new turn
```

---

# 40. Phase 10 — Optional TTS

**Status: DEFERRED**

Chỉ làm nếu product requirement cần speech output.

Bám HF backend architecture nhưng benchmark model phù hợp hardware.

---

# PHẦN V — THỨ TỰ MODEL

## 41. Model plan đã chốt

| Stage | Hiện tại | Target gần | Trạng thái |
|---|---|---|---|
| Audio enhancement | Không có | DeepFilterNet candidate theo HF | Benchmark |
| VAD | Silero ONNX | Silero, verify/v5 benchmark | Giữ |
| Smart Turn | Không | Pipecat Smart Turn v3.2 CPU ONNX | Later |
| STT | Whisper Tiny.en ONNX | Whisper Tiny.en | Giữ |
| Transcript validation | custom Gate | modular Gate handler | Giữ |
| LLM local | Gemma 3 1B Q4 | Gemma local backend | Giữ |
| LLM remote | Không | OpenAI-compatible GPU server | Thêm |
| TTS | Không | optional HF-supported backend | Deferred |

---

# 42. Vì sao không copy default models của HF?

HF default hiện có thể gồm:

```text
Silero
Parakeet TDT
Smart Turn
API LLM
Qwen3-TTS
```

Nhưng modularity chính là điểm của repo.

Do đó:

```text
"bám theo repo"
```

**không có nghĩa**:

```text
"bắt buộc dùng đúng mọi model mặc định"
```

Mà có nghĩa:

```text
bám:
handler abstraction
queue
turn state
backend registry concept
realtime flow
cancellation
speculative turns
```

Model được thay theo device.

Whisper là backend mà HF chính thức hỗ trợ, nên dùng Whisper Tiny trên Nano vẫn hoàn toàn đúng tinh thần repo.

---

# PHẦN VI — KIẾN TRÚC LOCAL VÀ HYBRID

# 43. Mode A — Fully local Nano

```text
Mic
 ↓
Enhancement
 ↓
Silero
 ↓
Whisper Tiny
 ↓
Gate
 ↓
Gemma 1B Q4 / llama.cpp
 ↓
Text
```

Ưu điểm:

- không phụ thuộc mạng;
- demo standalone;
- chứng minh edge deployment;
- privacy/local processing.

---

# 44. Mode B — Jetson + RTX 5090

```text
                   Jetson Nano
Mic
 ↓
Enhancement
 ↓
VAD
 ↓
STT
 ↓
Gate
 ↓
LLM Backend
 ↓ LAN/API
                   RTX 5090
                     ↓
                 Larger LLM
                     ↓
                stream response
                     ↓
                   Jetson
```

### Điểm quan trọng

Mode B **không thay speech pipeline**.

Chỉ thay LLM backend.

Đây là lý do abstraction ở Phase 6 quan trọng.

---

# 45. Tại sao nên giữ cả hai mode?

Ta có thể báo cáo hai architecture:

```text
Edge-only
vs
Edge + GPU inference server
```

Và đo bằng cùng benchmark.

Điều này có giá trị kỹ thuật hơn việc chọn một cách rồi bỏ hoàn toàn cách còn lại.

---

# PHẦN VII — CÁC METRIC BẮT BUỘC

## 46. Latency

Giữ:

```text
T0 speech end
T1 VAD segment
T2 STT result
T3 LLM request
T4 first token
T5 last token
```

Sau Worker/Queue thêm:

```text
T_vad_enqueue
T_stt_dequeue
T_stt_enqueue
T_llm_dequeue
```

Để tính:

```text
queue wait
worker processing
end-to-end latency
```

---

# 47. Resource

Mỗi phase đo:

```text
RAM RSS
system available RAM
CPU %
GPU utilization
GPU memory/shared RAM
queue depth
```

Không chỉ đo file model size.

---

# 48. Quality

Với audio frontend/STT:

```text
valid speech accepted
garbage annotation dropped
false Gate rejection
Whisper hallucination
background-noise false activation
```

Không cần xây một lab noise bao quát mọi tiếng ồn.

Dùng:

```text
real-world logs
+
một tập audio nhỏ reproducible
```

để regression test.

---

# 49. Realtime behavior

Sau Queue/Turn Manager:

```text
Can user speak while LLM is generating?
Is audio preserved?
Does STT process next turn?
Does queue backlog grow?
Can stale turn be cancelled?
```

Đây là metric mà pipeline tuần tự khó đo chính xác.

---

# PHẦN VIII — CÁC ĐIỂM KHÔNG NÊN LÀM

## 50. Không refactor và đổi model cùng lúc

Sai:

```text
đổi VAD
+ đổi STT
+ thêm enhancement
+ thêm queue
+ thêm Smart Turn
```

trong một commit.

Nếu kết quả xấu sẽ không biết lỗi nằm đâu.

---

## 51. Không cài nguyên HF stack lên Nano chỉ để “giống repo”

Repo hiện dùng ecosystem mới:

```text
Python mới
PyTorch mới
Transformers mới
nhiều optional backend
```

Jetson Nano hiện:

```text
CUDA 10.2
JetPack cũ
RAM thấp
```

Mục tiêu:

> **Port architecture, không port toàn dependency graph.**

---

## 52. Không xem Smart Turn như noise filter

Smart Turn:

```text
turn completeness
```

Noise enhancement:

```text
audio quality
```

VAD:

```text
speech activity
```

Transcript Gate:

```text
final text safeguard
```

Các module giải quyết bài toán khác nhau.

---

## 53. Không phụ thuộc vào implicit OS buffering lâu dài

Hiện tại hệ thống chạy khá tốt nhờ:

```text
ALSA buffer
stdout pipe
separate sherpa subprocess
```

Đây là một lợi thế thực tế nhưng không phải realtime architecture có control.

Target là:

```text
explicit Queue
bounded state
turn ID
metrics
cancellation
```

---

# PHẦN IX — FINAL DEVELOPMENT PLAN

## 54. Checklist

```text
[x] Baseline runtime ổn định
[x] LLM streaming
[x] Latency instrumentation
[x] Full pipeline benchmark
[x] Transcript Gate v1

[ ] Benchmark DeepFilterNet audio enhancement
[ ] Verify current Silero version / compare v5 only if needed
[ ] Decouple Audio/VAD from STT
[ ] Introduce speech_queue
[ ] Introduce STT worker
[ ] Introduce transcript_queue
[ ] Convert Gate into handler
[ ] Introduce LLM worker
[ ] Add ConversationManager / bounded chat_size
[ ] Add Local/Remote LLM backend abstraction
[ ] Benchmark RTX 5090 remote backend
[ ] Add Smart Turn v3.2
[ ] Add turn_id / revision
[ ] Add cancellation/speculative turn
[ ] Add barge-in
[ ] Optional TTS
```

---

# 55. Kiến trúc cuối mong muốn

```text
                  ┌─────────────────────────────┐
                  │       Audio Input/Mic       │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ Audio Enhancement Handler   │
                  │ DeepFilterNet if benchmark  │
                  │ proves viable               │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ Silero VAD Worker           │
                  └──────────────┬──────────────┘
                                 │
                           speech_queue
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ Turn Controller             │
                  │ Smart Turn v3.2 later       │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ Whisper Tiny.en STT Worker  │
                  │ sherpa-onnx / ONNX Runtime  │
                  └──────────────┬──────────────┘
                                 │
                        transcript_queue
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ Transcript Gate Handler     │
                  └──────────────┬──────────────┘
                                 │
                         valid_turn_queue
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ Conversation Manager        │
                  │ history / turn_id / state   │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ LLM Backend Handler         │
                  └──────────┬─────────┬────────┘
                             │         │
                   local     │         │ remote
                             ▼         ▼
                       llama.cpp    RTX 5090
                       Gemma 1B    API-compatible
                             │         │
                             └────┬────┘
                                  ▼
                  ┌─────────────────────────────┐
                  │ Streaming Response          │
                  │ + Cancel/Interruption       │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                     [Optional TTS Handler]
```

---

# 56. Câu giải thích ngắn khi báo cáo với sếp

> Project hiện tại đã chạy local hoàn chỉnh theo pipeline `Silero VAD → Whisper Tiny → Transcript Gate → Gemma 1B`, sử dụng sherpa-onnx/ONNX Runtime cho speech và llama.cpp cho LLM. Hệ thống đã có streaming và benchmark latency.
>
> Bước tối ưu tiếp theo không phải đổi model ngẫu nhiên mà là refactor architecture theo `huggingface/speech-to-speech`: tách từng stage thành handler/worker, nối bằng queue, quản lý turn/state riêng, thêm audio enhancement ở frontend và biến LLM thành backend có thể thay giữa local Nano và remote GPU server. Sau khi nền tảng queue/turn ổn định mới thêm Smart Turn và interruption giống realtime pipeline của Hugging Face.
>
> Vì Jetson Nano có giới hạn CUDA/RAM, project học **framework architecture** của Hugging Face nhưng giữ các model nhẹ đang chạy tốt thay vì copy nguyên default Parakeet/Qwen3-TTS stack.

---

# PHẦN X — NGUỒN ĐỐI CHIẾU

## Source project hiện tại

Phân tích từ archive:

```text
source.tar.gz
```

Các file chính đã dùng để đối chiếu:

```text
app/voice_assistant.py
scripts/llama_server.sh
deps/runtime-sources.md
deps/models.manifest
deps/llama-server.manifest
deps/sherpa-onnx.commit
patches/sherpa-onnx/latency-instrumentation.patch
docs/system_snapshot.txt
logs/benchmarks/*
```

## Hugging Face reference

Main repository:

- https://github.com/huggingface/speech-to-speech

Pipeline source:

- https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/s2s_pipeline.py

VAD arguments / Smart Turn / audio enhancement:

- https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/arguments_classes/vad_arguments.py

Realtime architecture:

- https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/api/openai_realtime/README.md

LLM backends:

- https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/LLM/README.md

TTS backends:

- https://github.com/huggingface/speech-to-speech/blob/main/src/speech_to_speech/TTS/README.md

Project dependencies:

- https://github.com/huggingface/speech-to-speech/blob/main/pyproject.toml

---

## Kết luận cuối

Hướng tối ưu từ đây được cố định:

```text
Reference architecture = Hugging Face speech-to-speech
Runtime/model choice   = phù hợp Jetson Nano
Development strategy   = từng phase + benchmark + rollback được
```

Ta sẽ không cố biến Jetson Nano thành máy chạy nguyên default stack của Hugging Face.

Ta sẽ biến project hiện tại thành một **phiên bản edge-oriented của cùng kiến trúc modular realtime đó**.
