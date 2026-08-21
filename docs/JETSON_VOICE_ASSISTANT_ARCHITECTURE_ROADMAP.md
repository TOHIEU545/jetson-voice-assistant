# Jetson Voice Assistant — Kiến trúc hiện tại và Roadmap tối ưu theo `huggingface/speech-to-speech`

> **Roadmap revision — 2026-08-21**
>
> Bản cập nhật này phản ánh implementation thực tế sau Phase 2/3:
>
> - Audio enhancement: DPDFNet2 không tương thích ONNX opset hiện tại; GTCRN chạy được và đã có benchmark ban đầu, nhưng chưa integrate.
> - Phase 3: `ALSA/Silero VAD producer → speech_queue → resident Whisper STT worker` đã được hiện thực trong C++.
> - Phase 4 được tinh chỉnh: Python không tạo lại Audio/VAD/STT worker; pipeline Python bắt đầu từ `SpeechRuntimeHandler → transcript_queue`.
> - ConversationManager, LLMBackend abstraction, Smart Turn, cancellation/barge-in vẫn giữ nguyên ở các phase sau.
>

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

Ta sẽ giữ triết lý đó nhưng ánh xạ theo implementation thực tế của project:

```text
                      Jetson Nano
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  C++ speech runtime                                          │
│  Mic / ALSA                                                  │
│      ↓                                                       │
│  [Audio Enhancement — optional, chưa integrate]              │
│      ↓                                                       │
│  Silero VAD producer                                         │
│      ↓ speech_queue                                          │
│  Whisper Tiny.en STT worker                                  │
│      ↓ transcript + latency                                  │
│                                                              │
│  Python application                                          │
│  SpeechRuntimeHandler                                        │
│      ↓ transcript_queue                                      │
│  TranscriptGateHandler                                       │
│      ↓ valid_turn_queue                                      │
│  LLMHandler                                                  │
│      ↓ llm_output_queue                                      │
│  ResponseProcessor                                           │
│                                                              │
│  [ConversationManager / LLMBackend abstraction / Smart Turn  │
│   / cancellation / TTS được thêm ở các phase sau]            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

> Sau Phase 3, `speech_queue` và STT worker đã nằm trong C++ runtime. Vì vậy Phase 4 **không tạo lại Audio/VAD Handler hoặc STT Handler bằng Python**; Python pipeline bắt đầu từ transcript output của C++ runtime.

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
│       ├── latency-instrumentation.patch
│       └── vad-stt-decoupling.patch
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

> Sau Phase 3, VAD và STT vẫn nằm trong **cùng một C++ executable**, nhưng đã được tách execution thành producer–consumer: Audio/VAD producer tiếp tục capture, còn Whisper chạy trong một STT worker riêng nối qua `speech_queue`. Đây là decoupling thật sự mà không cần tách thành hai process.

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

## 10.1 VAD và STT — bottleneck cũ đã được xử lý ở Phase 3

Trước Phase 3, source C++ chạy tuần tự:

```cpp
vad->AcceptWaveform(...)

while (!vad->Empty()) {
    ...
    recognizer.DecodeStream(...)
    ...
}
```

Nghĩa là:

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

Trong lúc `DecodeStream()` chạy, audio loop bị dừng.

Sau Phase 3, binary đã được refactor thành:

```text
ALSA / Silero VAD producer
        ↓
   speech_queue
        ↓
Whisper STT worker
```

Whisper recognizer vẫn được load một lần và resident. Audio/VAD producer không còn gọi `DecodeStream()`, nên microphone capture không bị STT block nữa.

> Đây là **Phase 3 DONE**. Bottleneck chính còn lại nằm ở Python: `voice_assistant.py` vẫn block đọc sherpa output trong lúc LLM đang stream response.

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

## 10.5 Audio enhancement chưa được integrate

Project đã benchmark candidate enhancement nhưng production pipeline hiện vẫn đưa raw microphone audio vào Silero.

GTCRN đã chạy được trên runtime hiện tại; DPDFNet2 bị chặn bởi ONNX opset incompatibility. Enhancement vẫn là optional module và sẽ chỉ integrate sau khi architecture refactor ổn định và noisy real-world A/B test đạt yêu cầu.

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

Target được chia rõ thành **C++ speech runtime** và **Python application runtime**:

```text
                    C++ SPEECH RUNTIME
                         Audio / ALSA
                              │
                              ▼
                 [Audio Enhancement — optional]
                              │
                              ▼
                    Silero VAD producer
                              │
                        speech_queue
                              │
                              ▼
                  Whisper Tiny.en STT worker
                              │
                    transcript + latency
                              │
                              ▼
                    PYTHON APPLICATION
                    SpeechRuntimeHandler
                              │
                     transcript_queue
                              │
                              ▼
                 TranscriptGateHandler
                              │
                     valid_turn_queue
                              │
                              ▼
                         LLMHandler
                              │
                     llm_output_queue
                              │
                              ▼
                    ResponseProcessor
                              │
                              ▼
             [ConversationManager — Phase 5]
                              │
                              ▼
             [LLMBackend abstraction — Phase 6]
                              │
                              ▼
                 [Smart Turn / Cancel / TTS later]
```

Điểm khóa:

- `speech_queue` thuộc C++ runtime và đã có từ Phase 3.
- Python **không tạo lại Audio/VAD hoặc STT worker**.
- Phase 4 bắt đầu tại `SpeechRuntimeHandler → transcript_queue`.
- `ConversationManager`, `LLMBackend`, Smart Turn và cancellation tiếp tục nằm đúng phase riêng.

# 19. Mapping HF → Project

| HF `speech-to-speech` | Project Jetson |
|---|---|
| `VADHandler` | Silero VAD producer trong C++ speech runtime |
| `spoken_prompt_queue` | `speech_queue` trong C++ |
| STT backend | Whisper Tiny.en worker / sherpa-onnx |
| `stt_output_queue` | `transcript_queue` trong Python Phase 4 |
| `TranscriptionNotifier` | `SpeechRuntimeHandler` + transcript event |
| validation layer | `TranscriptGateHandler` riêng của project |
| `text_prompt_queue` | `valid_turn_queue` |
| LLM handler | `LLMHandler` ở Phase 4; backend abstraction ở Phase 6 |
| `LMOutputProcessor` | `ResponseProcessor` |
| `CancelScope` | Cancellation token / response cancel — later |
| `SpeculativeTurnTracker` | Turn ID + revision + Smart Turn state — later |
| TTS handler | Deferred |
| `RealtimeService` | Future `ConversationManager` / realtime coordination |

Đây vẫn là mapping trực tiếp từ HF, nhưng boundary giữa C++ và Python được giữ theo implementation thực tế của project.

# 20. Model strategy mới

## 20.1 Audio Enhancement — **optional, benchmark đã có candidate thực tế**

Reference architecture của HF có slot:

```text
audio_enhancement
```

và HF dùng DeepFilterNet cho feature này.

Trên Jetson Nano, project không copy nguyên implementation đó mà benchmark model/runtime phù hợp với sherpa-onnx hiện có.

### Kết quả benchmark hiện tại

Đã thử:

```text
DPDFNet2 ONNX
```

nhưng model dùng ONNX opset 17, trong khi ONNX Runtime hiện tại của Jetson chỉ guarantee đến opset 16:

```text
DPDFNet2 → model load FAIL do opset incompatibility
```

Candidate chạy được:

```text
GTCRN simple ONNX
```

Kết quả online benchmark ban đầu:

```text
chunk duration : 10 ms
audio duration : 6.625 s
elapsed        : 2.383 s
RTF            : 0.360
peak RSS       : ~27 MB
threads        : 1
swap           : 0
```

Clean-speech preservation test:

```text
RAW WAV   → Whisper
GTCRN WAV → Whisper
```

cho cùng transcript, nên chưa thấy dấu hiệu GTCRN phá speech sạch.

### Quyết định

- GTCRN là candidate phù hợp để giữ lại.
- **Chưa integrate vào production pipeline trong Phase 3/4.**
- Audio enhancement vẫn là optional module.
- Khi quay lại integration phải tiếp tục test noisy real-world audio và regression với STT.

Điều này vẫn bám đúng triết lý HF: enhancement là optional frontend module, còn implementation được chọn theo giới hạn Jetson Nano.

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

# 25. Worker + Queue — kiến trúc thực tế sau Phase 3

Phase 3 đã hoàn thành phần speech concurrency trong C++:

```text
C++ speech runtime
ALSA / Silero producer
       ↓
speech_queue
       ↓
Whisper STT worker
```

Nhờ đó Whisper decode không còn block microphone capture.

Bottleneck hiện tại nằm ở Python:

```text
Speech runtime output
       ↓
voice_assistant.py
       ↓
read transcript
       ↓
LLM HTTP streaming
       ↓
Python block cho đến khi response kết thúc
       ↓
mới quay lại đọc sherpa output
```

Sherpa vẫn có thể tiếp tục chạy, nhưng output phải nằm trong Linux pipe buffer. Đây là **implicit buffering**, chưa phải application-controlled queue.

## Target Phase 4

```text
C++ speech runtime
       ↓ transcript + latency
SpeechRuntimeHandler
       ↓
transcript_queue
       ↓
TranscriptGateHandler
       ↓
valid_turn_queue
       ↓
LLMHandler
       ↓
llm_output_queue
       ↓
ResponseProcessor
```

### Lợi ích chính

Không phải:

> “Queue làm Whisper hoặc Gemma nhanh hơn.”

Mà là:

```text
SpeechRuntimeHandler luôn drain sherpa output
LLM generation không khóa transcript ingestion
Gate chạy độc lập
LLM worker sở hữu request/history tạm thời
ResponseProcessor là nơi duy nhất print/log
turn metadata và queue metrics rõ ràng
chuẩn bị cho cancellation/barge-in sau này
```

Phase 4 **không tạo thêm `speech_queue` Python**, vì queue đó đã thuộc C++ runtime.

# 26. Phase 3 prerequisite — **DONE**

Điều kiện bắt buộc trước khi làm Python queue architecture là phải tách Audio/VAD khỏi STT thật sự.

Điều này đã được xử lý trong Phase 3 bằng producer–consumer bên trong C++:

```text
ALSA / Silero producer
        ↓
   speech_queue
        ↓
Whisper STT worker
```

Giữ nguyên:

```text
sherpa-onnx
Silero
Whisper Tiny.en
```

Không cần tách thành hai process và không cần spawn `sherpa-onnx-offline` cho từng WAV.

Whisper recognizer được load một lần và resident.

Vì prerequisite này đã hoàn thành, Phase 4 chỉ cần giải quyết Python orchestration từ transcript trở đi.

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

**Status: BENCHMARKED / integration deferred**

HF reference có optional `audio_enhancement`, nhưng Jetson cần model/runtime phù hợp phần cứng hiện tại.

Đã kiểm tra:

```text
DPDFNet2
→ không load được vì model opset 17 vượt mức ONNX Runtime hiện tại
```

GTCRN simple:

```text
offline denoiser → PASS
online denoiser  → PASS
RTF online       → 0.360
peak RSS         → ~27 MB
threads          → 1
swap             → 0
```

Clean-speech preservation:

```text
RAW → Whisper
GTCRN → Whisper
```

cho cùng transcript.

### Kết luận Phase 2

- GTCRN là candidate phù hợp với runtime hiện tại.
- Chưa integrate enhancement vào production pipeline.
- Integration được trì hoãn để Phase 3/4 chỉ thay architecture, tránh đổi nhiều biến cùng lúc.
- Khi quay lại enhancement cần noisy real-world A/B test và regression STT trước khi officialize dependency.

# 33. Phase 3 — Tách Audio/VAD khỏi STT

**Status: DONE**

Đã refactor binary C++ hiện tại theo producer–consumer:

```text
ALSA / Silero VAD producer
        ↓
   speech_queue
        ↓
Whisper STT worker
```

### Giữ nguyên

```text
Silero
Whisper Tiny.en
sherpa-onnx
Python interface bên ngoài
GTCRN chưa integrate
```

Whisper recognizer được load một lần và resident.

Audio/VAD producer không gọi `DecodeStream()` nữa; STT worker duy nhất chịu trách nhiệm:

```text
CreateStream
→ AcceptWaveform
→ DecodeStream
→ GetResult
```

Queue sở hữu copy/move của speech samples trước `vad->Pop()`.

### Latency contract

Giữ nguyên:

```text
VAD = speech end → segment ready
STT = segment ready → transcript ready
```

Queue wait bên trong C++ hiện được tính chung vào STT latency. Phase 4 mới thêm queue/worker metric chi tiết ở Python.

### Kết quả kiến trúc

```text
Whisper decode không còn block microphone capture
```

Đây là prerequisite đã hoàn thành để chuyển sang Phase 4.

# 34. Phase 4 — Python Handler/Queue architecture

**Status: NEXT / PLANNED**

Sau Phase 3, `Audio/VAD → speech_queue → STT` đã thuộc C++ runtime. Vì vậy Phase 4 **không tách lại Audio/VAD hoặc Whisper bằng Python**.

Kiến trúc Phase 4:

```text
                    C++ speech runtime
ALSA → Silero VAD → speech_queue → Whisper worker
                              │
                              │ transcript + latency
                              ▼
                    SpeechRuntimeHandler
                              │
                     transcript_queue
                              ▼
                  TranscriptGateHandler
                              │
                     valid_turn_queue
                              ▼
                         LLMHandler
                              │
                     llm_output_queue
                              ▼
                    ResponseProcessor
```

### Mục tiêu chính

Hiện `voice_assistant.py` đọc transcript rồi gọi LLM HTTP streaming ngay trong cùng loop, nên trong lúc LLM generate Python không tiếp tục drain sherpa output.

Phase 4 phải đảm bảo:

```text
LLMHandler đang generate
        │
        └── SpeechRuntimeHandler vẫn đọc sherpa output liên tục
```

Không còn dùng Linux pipe như queue ngầm.

### Cấu trúc Python vừa đủ

```text
app/
├── voice_assistant.py
├── config.py
├── core/
│   ├── __init__.py
│   └── messages.py
└── handlers/
    ├── __init__.py
    ├── speech_runtime.py
    ├── transcript_gate.py
    ├── llm.py
    └── response.py
```

### Responsibility

`SpeechRuntimeHandler`

```text
start sherpa subprocess
→ continuously read runtime output
→ parse transcript + VAD/STT/TOTAL
→ timestamp T2 ngay khi transcript đến
→ construct turn metadata
→ transcript_queue.put()
```

`TranscriptGateHandler`

```text
transcript_queue
→ giữ nguyên Gate v1 hiện tại
→ DROP hoặc valid_turn_queue
```

`LLMHandler`

```text
valid_turn_queue
→ giữ history list hiện tại
→ HTTP /v1/chat/completions
→ stream token vào llm_output_queue
```

Chưa tạo `ConversationManager` ở Phase 4.

`ResponseProcessor`

```text
terminal output
conversation log
benchmark/full-pipeline log
latency summary
```

là nơi duy nhất chịu trách nhiệm print/write output.

### Queue tối thiểu

```text
transcript_queue
valid_turn_queue
llm_output_queue
```

`speech_queue` **không nằm trong Python** vì đã có trong C++ Phase 3.

### Queue policy

Phase 4 ưu tiên queue không block transcript ingestion. Không để:

```text
SpeechRuntimeHandler
→ blocking Queue.put()
→ ngừng drain sherpa output
```

Text/metadata rất nhỏ, nên trước tiên đo queue depth và backlog thực tế; backpressure/bounded policy nâng cao để phase realtime/cancellation sau.

### Turn metadata

Mỗi turn giữ tối thiểu:

```text
turn_id / transcript identity
text
t2
vad_s
stt_s
vad_stt_total_s
transcript_queue_enter
transcript_queue_leave
valid_turn_queue_enter
valid_turn_queue_leave
gate_processing_s
llm_processing_s
t3
t4
t5
```

Lưu ý: nếu C++ output hiện vẫn expose transcript index thay vì true VAD `turn_id`, phải phân biệt rõ hai khái niệm và không giả định chúng luôn giống nhau.

### Metric mới

```text
transcript_queue_wait_ms
valid_turn_queue_wait_ms
gate_processing_ms
llm_worker_processing_ms
queue_depth
```

Vẫn giữ metric baseline:

```text
T0 → T1 VAD
T1 → T2 STT
T2 → T3 Python
T3 → T4 LLM TTFT
T4 → T5 LLM generation
```

### Ngoài scope Phase 4

```text
GTCRN integration → Phase 4.5
ConversationManager → Phase 5
LLMBackend abstraction → Phase 6
Smart Turn
speculative turn / cancellation
barge-in
TTS
```

Các phần này giữ đúng phase riêng phía sau.

# 34.5. Phase 4.5 — GTCRN Audio Enhancement Integration & Full-Pipeline Regression

**Status: PLANNED — sau khi Phase 4 ổn định**

Phase 2 đã chứng minh GTCRN chạy được trên Jetson Nano và không phá clean speech trong test ban đầu. Phase này mới đưa enhancement vào production speech path.

### Mục tiêu

```text
CURRENT:
Mic / ALSA
    ↓
Silero VAD
    ↓
speech_queue
    ↓
Whisper

TARGET:
Mic / ALSA
    ↓
GTCRN online enhancement
    ↓
Silero VAD
    ↓
speech_queue
    ↓
Whisper
```

GTCRN chạy trong **C++ speech runtime**, trước Silero VAD. Không đưa enhancement sang Python.

### Giữ nguyên

```text
Silero VAD
Whisper Tiny.en
C++ speech_queue
STT worker
Python Phase 4 handlers/queues
Gemma local LLM
```

Không refactor thêm architecture trong phase này.

### Benchmark bắt buộc

So sánh:

```text
GTCRN OFF
vs
GTCRN ON
```

Đo lại:

```text
VAD latency
STT latency
VAD + STT
Speech → First
Speech → Last
CPU usage
RAM RSS
system available RAM
queue depth / backlog
transcript quality
noisy-room behavior
```

### Quality test

```text
clean speech preservation
background noise reduction
Whisper annotation/hallucination
false VAD activation
valid speech bị mất hay không
```

Ưu tiên audio thực tế từ microphone của project.

### Go / No-Go

Chỉ giữ GTCRN trong production khi:

```text
quality improvement rõ
AND
realtime/resource regression chấp nhận được
AND
không gây queue backlog bất thường
```

Nếu FAIL:

```text
rollback GTCRN integration
→ production pipeline quay về raw audio → Silero
```

### Officialize dependency

Chỉ sau khi integration PASS mới cập nhật chính thức:

```text
deps/models.manifest
deps/models.sha256
deps/runtime-sources.md
download/setup script nếu cần
```

GTCRN không được coi là dependency production chỉ vì benchmark standalone đã PASS.

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
| Audio enhancement | Không có | GTCRN simple candidate | Benchmarked / integration deferred |
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

Sau Phase 3/4, metric được chia theo boundary thực tế:

```text
C++:
T1 = VAD segment ready
T2 = transcript ready
STT latency hiện bao gồm C++ speech_queue wait nếu có

Python Phase 4:
T_transcript_enqueue
T_transcript_dequeue
T_valid_enqueue
T_valid_dequeue
T3 = LLM request start
T4 = first token
T5 = last token
```

Để tính:

```text
transcript_queue_wait_ms
valid_turn_queue_wait_ms
gate_processing_ms
llm_worker_processing_ms
queue_depth
end-to-end latency
```

Phase 4 không bắt buộc thay đổi định nghĩa baseline `T0..T5`; metric mới được thêm song song để so trước/sau refactor.

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

[x] Benchmark audio enhancement candidate
    - DPDFNet2: incompatible với ONNX Runtime hiện tại
    - GTCRN: online/offline PASS, RTF ~0.360, peak RSS ~27 MB
[ ] Noisy real-world GTCRN A/B test trước khi integrate
[ ] Verify current Silero version / compare v5 only if needed

[x] Decouple Audio/VAD from STT trong C++
[x] Introduce C++ speech_queue
[x] Introduce resident Whisper STT worker

[ ] Phase 4: SpeechRuntimeHandler
[ ] Introduce Python transcript_queue
[ ] Convert Gate thành TranscriptGateHandler
[ ] Introduce valid_turn_queue
[ ] Introduce LLMHandler worker
[ ] Introduce llm_output_queue
[ ] Introduce ResponseProcessor
[ ] Add Python queue/worker metrics

[ ] Phase 4.5: Integrate GTCRN before Silero VAD
[ ] GTCRN ON/OFF full-pipeline regression
[ ] Noisy real-world GTCRN A/B test
[ ] Officialize GTCRN dependency only if integration PASS

[ ] Add ConversationManager / bounded chat_size
[ ] Add Local/Remote LLM backend abstraction
[ ] Benchmark RTX 5090 remote backend
[ ] Add Smart Turn v3.2
[ ] Add true turn_id / revision where required
[ ] Add cancellation/speculative turn
[ ] Add barge-in
[ ] Optional TTS
```

# 55. Kiến trúc cuối mong muốn

```text
                  ┌─────────────────────────────┐
                  │       Audio Input/Mic       │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ Audio Enhancement [optional]│
                  │ GTCRN candidate on Nano     │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
            ┌──────────────── C++ SPEECH RUNTIME ────────────────┐
            │                                                     │
            │  Silero VAD producer                               │
            │          │                                          │
            │     speech_queue                                    │
            │          │                                          │
            │          ▼                                          │
            │  Whisper Tiny.en STT worker                         │
            │  sherpa-onnx / ONNX Runtime                         │
            │                                                     │
            └───────────────────┬─────────────────────────────────┘
                                │ transcript + latency
                                ▼
                  ┌─────────────────────────────┐
                  │ SpeechRuntimeHandler        │
                  └──────────────┬──────────────┘
                                 │
                        transcript_queue
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ TranscriptGateHandler       │
                  └──────────────┬──────────────┘
                                 │
                         valid_turn_queue
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ LLMHandler                  │
                  │ Phase 4: current history    │
                  └──────────────┬──────────────┘
                                 │
                         llm_output_queue
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │ ResponseProcessor           │
                  │ print / logs / metrics      │
                  └──────────────┬──────────────┘
                                 │
                 ┌───────────────┴────────────────┐
                 │                                │
                 ▼                                ▼
      [ConversationManager]            [LLMBackend abstraction]
            Phase 5                          Phase 6
                                                │
                                     ┌──────────┴──────────┐
                                     ▼                     ▼
                                  local                 remote
                                llama.cpp             RTX 5090
                                Gemma 1B           API-compatible

                  [Smart Turn / cancellation / barge-in later]
                              [Optional TTS]
```

# 56. Câu giải thích ngắn khi báo cáo với sếp

> Project hiện tại đã chạy local hoàn chỉnh theo pipeline `Silero VAD → Whisper Tiny → Transcript Gate → Gemma 1B`, sử dụng sherpa-onnx/ONNX Runtime cho speech và llama.cpp cho LLM. Hệ thống đã có streaming và benchmark latency.
>
> Project đã hoàn thành bước tách Audio/VAD khỏi Whisper STT ở C++ bằng producer–consumer và `speech_queue`, nên microphone capture không còn bị `DecodeStream()` block. Bước tiếp theo là Phase 4 ở Python: tách việc đọc speech runtime, Transcript Gate, LLM streaming và output/logging thành các handler riêng nối bằng `transcript_queue`, `valid_turn_queue` và `llm_output_queue`. Sau khi Python orchestration không còn blocking mới tách ConversationManager, LLM backend local/remote, rồi thêm Smart Turn và interruption.
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

Ta sẽ biến project hiện tại thành một **phiên bản edge-oriented của cùng kiến trúc modular realtime đó**, với boundary rõ: speech concurrency ở C++, orchestration/queue từ transcript trở đi ở Python.
