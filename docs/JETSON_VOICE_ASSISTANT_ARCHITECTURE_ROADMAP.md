# Jetson Voice Assistant — Kiến trúc hiện tại và Roadmap tối ưu theo `huggingface/speech-to-speech`

> **Roadmap revision — 2026-08-22**
>
> Bản này cập nhật theo **implementation thực tế hiện tại trên branch `dev` sau khi Phase 7C Smart Turn full-pipeline PASS trên Jetson Nano**.
>
> Các mô tả cũ như “Phase 4 NEXT”, “GTCRN chưa integrate”, “ConversationManager chưa có”, “LLM backend hard-code”, “Smart Turn later” đã được thay bằng trạng thái thật hiện tại.

---

# 0. Nguyên tắc phát triển đã chốt

```text
HOST / laptop = máy phát triển chính
GitHub        = source of truth
JETSON        = runtime / hardware / benchmark target
```

Workflow bắt buộc:

```text
HOST edit
  ↓
HOST test
  ↓
git commit
  ↓
git push
  ↓
JETSON git pull
  ↓
apply patch / rebuild nếu cần
  ↓
run / benchmark trên hardware
```

Không phát triển production source trực tiếp trên Jetson, ngoại trừ probe/debug tạm thời. Model weight, runtime build, cache, recording và benchmark artifact lớn không commit vào Git.

Reference kiến trúc vẫn là:

```text
huggingface/speech-to-speech
```

Nhưng project chỉ port **kiến trúc modular realtime**, không copy nguyên dependency/model stack hiện đại của Hugging Face lên Jetson Nano.

---

# PHẦN I — TRẠNG THÁI PROJECT HIỆN TẠI

# 1. Hardware / runtime target

```text
Jetson Nano Developer Kit 4GB
├── JetPack / L4T : JetPack 4.6.1 / L4T 32.x
├── Architecture  : aarch64
├── CUDA          : 10.2
├── GPU           : Maxwell, compute capability 5.3
├── RAM           : ~3.9 GB shared
├── Swap          : ~1.9 GB
├── Python        : 3.6.9 trên runtime Jetson
└── ONNX Runtime  : 1.11.0 trong sherpa-onnx runtime hiện tại
```

Constraint quan trọng:

```text
Không upgrade ONNX Runtime toàn cục chỉ để chạy Smart Turn.
Không giả định CUDA/PyTorch stack mới sẽ chạy được trên Nano.
```

---

# 2. Repo / runtime paths

## HOST

```text
~/jetson-voice-assistant-source
```

Branches:

```text
main = stable
dev  = active development
```

Sherpa dev tree dùng để dựng/rebuild patch:

```text
~/jetson-voice-assistant-runtime-dev/sherpa-onnx
```

## JETSON

```text
~/jetson-voice-assistant
```

Sherpa runtime:

```text
~/jetson-voice-assistant/runtime/sherpa-onnx
```

Speech executable:

```text
runtime/sherpa-onnx/build/bin/sherpa-onnx-vad-alsa-offline-asr
```

LLM server:

```text
runtime/llama.cpp/bin/llama-server
```

---

# 3. Kiến trúc production hiện tại

Pipeline hiện tại đã khác đáng kể roadmap cũ.

```text
                          JETSON NANO

Mic / ALSA
   ↓
[GTCRN online enhancement — optional]
   ↓
Silero VAD producer
   ↓
speech_queue                        ← C++
   ↓
[Smart Turn v3.2 — optional]
   ├── COMPLETE
   │      ↓
   │   resident Whisper worker
   │
   └── INCOMPLETE
          ↓
       hold/merge audio
          ↓
       wait continuation
          ↓
       Smart Turn evaluate again
          ↓
       COMPLETE → Whisper
   ↓
transcript + latency
   ↓
SpeechRuntimeHandler                ← Python
   ↓
transcript_queue
   ↓
TranscriptGateHandler
   ↓
valid_turn_queue
   ↓
ConversationManager
   ↓
LLMHandler
   ↓
LLMBackend
   ├── LocalLlamaCppBackend
   └── RemoteOpenAICompatibleBackend
   ↓
llm_output_queue
   ↓
ResponseProcessor
   ↓
terminal + conversation logs + benchmark JSONL
```

Hai optional frontend feature hiện có feature flag riêng:

```bash
VOICE_ASSISTANT_GTCRN=0       # default OFF
VOICE_ASSISTANT_GTCRN=1       # ON

VOICE_ASSISTANT_SMART_TURN=0  # default OFF
VOICE_ASSISTANT_SMART_TURN=1  # ON
```

Default OFF là chủ đích: integration đã PASS nhưng quality dài hạn chưa đủ dữ liệu để bật mặc định.

---

# 4. Models / runtime hiện tại

## 4.1 Audio enhancement

Model:

```text
models/enhancement/gtcrn_simple.onnx
```

Known SHA256:

```text
e77603ac0c23dac3227dd2d7135b3a585cbee2679048aecfa886657d3ae1b534
```

Status:

```text
standalone benchmark     PASS
C++ production integrate PASS
feature flag             PASS
default                   OFF
quality conclusion        NOT CONCLUSIVE
```

GTCRN chạy trước Silero VAD trong C++ runtime.

DPDFNet2 vẫn không dùng vì incompatibility với ONNX Runtime/opset hiện tại.

---

## 4.2 VAD

```text
models/vad/silero_vad.onnx
```

Runtime:

```text
sherpa-onnx → ONNX Runtime → CPU
```

VAD chỉ quyết định speech activity; không quyết định câu đã hoàn chỉnh về mặt hội thoại.

---

## 4.3 Smart Turn

Official candidate đã khảo sát:

```text
smart-turn-v3.2-cpu.onnx
```

Original model không load được trên Jetson ORT 1.11:

```text
Unsupported model IR version: 10
max supported IR version: 8
```

Project không upgrade ORT mà dùng transformed candidate:

```text
models/turn/smart-turn-v3.2-cpu-opset16-ir8-clean.onnx
```

Transformation đã kiểm chứng trong experiment:

```text
10 LayerNormalization nodes
    ↓ decompose to primitive ONNX ops
opset 18 → 16
IR 10 → 8
remove unused non-default opset imports
```

Fixed-input numerical compare:

```text
max_abs_diff  = 0.0
mean_abs_diff = 0.0
```

Đây là strong evidence cho test input đó, không phải proof tuyệt đối cho mọi input.

### Jetson standalone performance

```text
1 thread ~794 ms
2 threads ~475 ms
4 threads ~320 ms
```

Real-audio preprocessing/inference:

```text
audio prep          ~0.002 s
Whisper features    ~1.33 s
Smart Turn ONNX     ~0.32 s
--------------------------------
hot total           ~1.65 s/evaluation
RAM                  ~75 MB peak trong probe
```

Bottleneck hiện tại của Smart Turn là **feature extraction**, không phải ONNX model inference.

---

## 4.4 STT

```text
Whisper Tiny.en ONNX
```

Files:

```text
models/stt/whisper-tiny.en/
├── tiny.en-encoder.onnx
├── tiny.en-decoder.onnx
└── tokens.txt
```

Runtime:

```text
sherpa-onnx → ONNX Runtime → CPU
```

Whisper recognizer resident trong C++ worker; không reload theo từng turn.

---

## 4.5 LLM

Current local model:

```text
Gemma 3 1B Instruct Q4_K_M
models/llm/gemma-3-1b-it-Q4_K_M.gguf
```

Runtime:

```text
llama.cpp / llama-server
```

Endpoint:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Server parameters hiện dùng:

```text
--host 127.0.0.1
--port 8080
-c 2048
-ngl 99
-t 2
```

---

# 5. Python application architecture hiện tại

Cấu trúc logic chính:

```text
app/
├── voice_assistant.py
├── config.py
├── backends/
│   └── llm.py
├── core/
│   ├── messages.py
│   ├── conversation.py
│   ├── revisions.py
│   └── cancellation.py
└── handlers/
    ├── speech_runtime.py
    ├── transcript_gate.py
    ├── llm.py
    └── response.py
```

Các queue production:

```text
C++:
  speech_queue

Python:
  transcript_queue
  valid_turn_queue
  llm_output_queue
```

Linux pipe không còn được coi là application queue chính cho transcript ingestion.

---

# 6. Transcript Gate

Gate vẫn được giữ như safeguard riêng của project:

```text
empty transcript          → DROP
contains ()[]{}           → DROP
normal transcript         → PASS
```

Thực tế Phase 7C regression trong phòng ồn vẫn thấy gate drop đúng các annotation như:

```text
(mumbling)
(buzzing)
(speaking in foreign language)
[BLANK_AUD...
```

Dropped transcript không vào ConversationManager và không được gửi tới LLM.

---

# 7. ConversationManager

Đã tách khỏi orchestration chính.

Current history bound:

```text
MAX_CONVERSATION_TURNS = 6
```

Responsibilities hiện có:

```text
bounded history
current logical turn
turn_id / revision validation
commit accepted user + assistant turn
abort stale/cancelled turn
protect history from obsolete output
```

Known Phase 5 commit:

```text
af920d1 refactor: add bounded conversation manager
```

---

# 8. LLMBackend abstraction

Đã có:

```text
LLMHandler
   ↓
LLMBackend
   ├── LocalLlamaCppBackend
   └── RemoteOpenAICompatibleBackend
```

Config:

```text
LLM_MODE
LLM_BASE_URL
LLM_MODEL
LLM_API_KEY
LLM_MAX_TOKENS
LLM_TEMPERATURE
```

Known Phase 6 commit:

```text
b5ed516 refactor: add swappable LLM backends
```

Speech pipeline không phải thay khi chuyển local ↔ remote backend.

---

# 9. Turn lifecycle / revision / cancellation hiện tại

Turn message hiện có các khái niệm:

```text
turn_id
revision
turn_state
turn_id_source
completion_source
segment_count
```

Turn states:

```text
open
waiting_continuation
complete
```

RevisionTracker đã có để biết revision mới nhất của từng logical turn.

LLMHandler đã kiểm tra stale revision:

```text
turn N rev 0 đang generate
       ↓
RevisionTracker thấy turn N rev 1
       ↓
rev 0 trở thành stale
       ↓
stop stale stream
       ↓
không commit stale assistant output vào history
```

Đây là **Phase 8A infrastructure**, đã DONE và có regression test synthetic.

---

# 10. Barge-in infrastructure hiện tại

`GenerationCancellationController` đã có để hủy generation đang active.

Phase 9A đã hỗ trợ cancellation event contract và synthetic `[SPEECH_STARTED]` path.

Nhưng C++ speech runtime hiện **chưa emit real speech_started event**, vì vậy barge-in thực sự vẫn chưa hoàn thiện.

Known commit:

```text
efb153e feat: add barge-in cancellation infrastructure
```

---

# 11. Latency instrumentation — giữ nguyên contract

```text
T0 = actual speech end
T1 = VAD completed segment
T2 = transcript ready / Python receives transcript
T3 = Python starts LLM generation/request
T4 = first non-empty LLM token
T5 = last non-empty LLM token
```

Metrics:

```text
T0→T1 = VAD endpoint/tail
T1→T2 = STT path
T3→T4 = LLM TTFT
T4→T5 = LLM generation
T0→T4 = speech end → first token
T0→T5 = speech end → last token
```

Python queue/worker metrics cũng được giữ:

```text
transcript_queue_wait_ms
valid_turn_queue_wait_ms
gate_processing_ms
llm_worker_processing_ms
queue depth
```

Smart Turn thêm:

```text
smart_turn_audio_prep_s
smart_turn_feature_s
smart_turn_inference_s
smart_turn_total_s
smart_turn_score
smart_turn_decision
segment_count
```

---

# 12. Baseline latency reference

Historical baseline chỉ dùng làm reference, không coi là constant:

| Stage | Reference |
|---|---:|
| VAD | ~0.500 s |
| STT | ~1.995 s |
| VAD + STT | ~2.495 s |
| Python | ~0.001 s |
| LLM TTFT | ~0.810 s |
| LLM generation | ~2.593 s |
| Speech → First | ~3.306 s |
| Speech → Last | ~5.899 s |

Sau Smart Turn ON, STT path tăng vì Smart Turn preprocessing + inference nằm trước Whisper.

Observed Phase 7C full-pipeline examples:

### GTCRN OFF / Smart Turn ON

```text
Smart Turn total  ~1.678 s
score             0.963355
segments          1
VAD               0.500 s
STT               3.098 s
Speech→First      3.963 s
```

### GTCRN ON / Smart Turn ON

```text
Smart Turn total  1.779–1.802 s trong các sample run
scores            ~0.973–0.987
VAD               ~0.532 s
STT               ~3.27–4.53 s
```

Các số này chứng minh integration/performance behavior, **không chứng minh quality model tốt trong mọi tình huống**.

---

# PHẦN II — MAPPING VỚI `huggingface/speech-to-speech`

# 13. Mapping kiến trúc hiện tại

| HF `speech-to-speech` | Jetson project hiện tại |
|---|---|
| Audio input | ALSA microphone |
| Audio enhancement | optional GTCRN trong C++ |
| `VADHandler` | Silero VAD producer trong C++ |
| spoken prompt queue | C++ `speech_queue` |
| Smart Turn | Pipecat Smart Turn v3.2 compatible ONNX path |
| STT backend | resident Whisper Tiny.en worker |
| STT output queue | Python `transcript_queue` |
| validation layer | `TranscriptGateHandler` |
| text prompt queue | `valid_turn_queue` |
| realtime/chat state | `ConversationManager` |
| LLM handler | `LLMHandler` |
| backend abstraction | Local llama.cpp / remote OpenAI-compatible |
| output processor | `ResponseProcessor` |
| revision tracker | `RevisionTracker` |
| cancel scope idea | `GenerationCancellationController` + LLM stale checks |
| speculative tracker | Phase 8B real integration — NEXT |
| barge-in | Phase 9A infra DONE, 9B real speech_started pending |
| TTS | deferred |

Project hiện đã chuyển từ “học architecture của HF” sang **đã implement phần lớn boundary cốt lõi**.

---

# PHẦN III — ROADMAP TRIỂN KHAI

# 14. Phase status tổng quan

| Phase | Nội dung | Status hiện tại |
|---|---|---|
| Phase 0 | Baseline + instrumentation | **DONE** |
| Phase 1 | Conservative Transcript Gate | **DONE** |
| Phase 2 | Audio enhancement benchmark | **DONE** |
| Phase 3 | C++ VAD/STT decoupling | **DONE** |
| Phase 4 | Python Handler/Queue architecture | **DONE** |
| Phase 4.5 | Optional GTCRN integration | **DONE — default OFF** |
| Phase 5 | ConversationManager + bounded history | **DONE** |
| Phase 6 | Swappable LLM backends | **DONE** |
| Phase 7A | Turn lifecycle foundation | **DONE** |
| Phase 7B | Smart Turn compatibility/performance | **DONE** |
| Phase 7C | Optional Smart Turn production integration | **DONE — default OFF** |
| Phase 8A | Revision-aware cancellation infrastructure | **DONE** |
| Phase 8B | Real speculative turn integration | **NEXT** |
| Phase 9A | Barge-in cancellation infrastructure | **DONE** |
| Phase 9B | Real C++ `speech_started` event | **LATER** |
| Phase 10 | TTS | **DEFERRED** |

---

# 15. Phase 0 — Baseline & instrumentation

**Status: DONE**

Đã có:

```text
runtime/model manifests
sherpa pinned commit
latency patch
VAD/STT benchmark
LLM benchmark
full-pipeline benchmark
conversation logs
```

Không bỏ instrumentation ở các phase sau.

---

# 16. Phase 1 — Transcript Gate

**Status: DONE**

```text
Whisper
  ↓
TranscriptGateHandler
  ├── DROP suspicious annotations
  └── PASS normal transcript
```

Gate đã tiếp tục hoạt động đúng trong Phase 7C noisy-room test.

---

# 17. Phase 2 — Audio Enhancement benchmark

**Status: DONE**

```text
DPDFNet2 → FAIL runtime compatibility
GTCRN    → PASS standalone online/offline
```

GTCRN benchmark reference:

```text
RTF      ~0.360
peak RSS ~27 MB
threads  1
swap     0
```

Quality standalone chưa đủ để kết luận.

---

# 18. Phase 3 — C++ Audio/VAD ↔ STT decoupling

**Status: DONE**

```text
ALSA / Silero producer
        ↓
   speech_queue
        ↓
resident Whisper worker
```

Whisper decode không còn block microphone capture.

Patch:

```text
patches/sherpa-onnx/vad-stt-decoupling.patch
```

---

# 19. Phase 4 — Python Handler/Queue architecture

**Status: DONE**

Production Python path:

```text
SpeechRuntimeHandler
   ↓ transcript_queue
TranscriptGateHandler
   ↓ valid_turn_queue
LLMHandler
   ↓ llm_output_queue
ResponseProcessor
```

Đã giải quyết vấn đề orchestration tuần tự cũ và cho phép speech runtime tiếp tục được drain trong lúc LLM generation chạy.

---

# 20. Phase 4.5 — GTCRN integration

**Status: DONE — optional / default OFF**

Production C++ path khi bật:

```text
ALSA
 ↓
GTCRN online denoiser
 ↓
Silero VAD
 ↓
speech_queue
 ↓
Whisper
```

Feature flag:

```bash
VOICE_ASSISTANT_GTCRN=0
VOICE_ASSISTANT_GTCRN=1
```

Phase 7C đã regression cả:

```text
GTCRN=0 SMART_TURN=1  PASS
GTCRN=1 SMART_TURN=1  PASS
```

Không tuyên bố GTCRN quality đã được chứng minh; tiếp tục dùng optional để đánh giá thực tế dài hạn.

Patch:

```text
patches/sherpa-onnx/gtcrn-enhancement-integration.patch
```

---

# 21. Phase 5 — ConversationManager

**Status: DONE**

```text
bounded history
max 6 conversation turns
turn lifecycle validation
safe commit/abort
```

Known commit:

```text
af920d1 refactor: add bounded conversation manager
```

---

# 22. Phase 6 — LLMBackend abstraction

**Status: DONE**

```text
LocalLlamaCppBackend
RemoteOpenAICompatibleBackend
```

Known commit:

```text
b5ed516 refactor: add swappable LLM backends
```

Local full pipeline trên Jetson đã PASS.

---

# 23. Phase 7A — Turn lifecycle foundation

**Status: DONE**

Đã thêm contract:

```text
turn_id
revision
turn_state
completion_source
segment_count
```

Known commit:

```text
4abefc4 refactor: add revision-aware turn lifecycle
```

---

# 24. Phase 7B — Smart Turn compatibility / benchmark

**Status: DONE**

Kết quả:

```text
ORT 1.11 compatibility       PASS sau graph transform
transformed model load       PASS
fixed-input numerical compare PASS
core inference benchmark     PASS
real-audio preprocessing     PASS
repeatability                PASS
RAM technical feasibility    PASS
quality validation           NOT CONCLUSIVE
```

Standalone hot overhead ~1.65 s/evaluation.

---

# 25. Phase 7C — Optional Smart Turn production integration

**Status: DONE — 2026-08-22**

Feature flag:

```bash
VOICE_ASSISTANT_SMART_TURN=0  # default
VOICE_ASSISTANT_SMART_TURN=1
```

Production behavior:

```text
SMART_TURN=0
VAD segment → Whisper
```

```text
SMART_TURN=1
VAD candidate
   ↓
Smart Turn
   ├── INCOMPLETE → hold/merge → wait continuation
   └── COMPLETE   → Whisper
```

Important design choice:

```text
Smart Turn chạy trong worker path, không block ALSA/VAD producer.
```

Smart Turn runtime resident, không load model lại theo từng evaluation.

### Instrumentation

Terminal summary:

```text
[SMART_TURN] decision=COMPLETE score=... total=... segments=...
```

Structured fields được đưa vào Python turn metadata / JSONL.

### HOST tests

```text
Smart Turn feature flag                    PASS
INCOMPLETE → COMPLETE parser metadata      PASS
ERROR → fail-open Whisper                  PASS
Phase 4–9 full regression                  PASS
C++ patch reproducibility / rebuild        PASS
```

### Jetson full pipeline

```text
GTCRN=0 SMART_TURN=0  PASS
GTCRN=0 SMART_TURN=1  PASS
GTCRN=1 SMART_TURN=1  PASS
```

Representative run:

```text
What is Linux?
Smart Turn decision = COMPLETE
score               = 0.963355
total               = 1.678 s
segments            = 1
```

With GTCRN + Smart Turn:

```text
Smart Turn totals ~1.779–1.802 s
full speech pipeline remains functional
Transcript Gate remains functional
Ctrl+C graceful shutdown remains functional
```

### Kết luận Phase 7C

```text
integration correctness = PASS
runtime compatibility   = PASS
latency instrumentation = PASS
quality long-term       = NOT CONCLUSIVE
production default      = OFF
```

### Remaining housekeeping

Model conversion/provenance cần được officialize đầy đủ trong `deps/`/script khi project đóng gói release:

```text
original source/version/license
original SHA256
converted SHA256
deterministic conversion script
conversion documentation
```

Không blocker cho Phase 8, nhưng không được quên trước khi coi model artifact là release dependency hoàn chỉnh.

---

# 26. Phase 8A — Revision-aware cancellation infrastructure

**Status: DONE**

Current components:

```text
RevisionTracker
LLMHandler stale-revision checks
ConversationManager abort protection
turn_cancelled event
history commit guard
```

Synthetic test đã chứng minh:

```text
rev 0 generation starts
        ↓
rev 1 observed for same turn_id
        ↓
rev 0 becomes stale
        ↓
stale token stream stops
        ↓
rev 0 assistant output is NOT committed
```

Known commit:

```text
61c6890 feat: add revision-aware generation cancellation
```

Phase 8A chỉ là **infrastructure**. Production frontend trước Phase 8B chưa thực sự phát sinh speculative rev0 → rev1 trong normal mic flow.

---

# 27. Phase 8B — Real speculative turn integration

**Status: NEXT**

Đây là phase tiếp theo.

## Mục tiêu

Biến revision cancellation từ synthetic test thành **real runtime behavior**.

Phase 8A đã chứng minh rằng nếu `RevisionTracker` biết có `turn N rev 1` thì LLM của `turn N rev 0` có thể bị hủy an toàn. Điểm còn thiếu là production frontend phải thực sự tạo revision mới trong cửa sổ mà một turn vừa được soft-finalize nhưng vẫn có thể bị user nói tiếp.

Reference HF hiện dùng đúng ý tưởng này: một soft-ended turn có `speculative_reopen_ms` (current default 800 ms); Smart Turn có thể kéo dài grace khi đánh giá câu chưa hoàn chỉnh (`smart_turn_max_wait_ms`, current default 2000 ms), và có một delay nhỏ trước expensive STT/LLM work khi Smart Turn báo incomplete. Project **không copy mù các giá trị này**, chỉ học lifecycle.

## Target behavior gần nhất

```text
VAD candidate
   ↓
Smart Turn + STT
   ↓
soft-final turn N rev 0
   ↓
LLM generation có thể bắt đầu
   ↓
reopen grace vẫn còn hiệu lực

Nếu user KHÔNG nói tiếp:
   ↓
rev 0 trở thành final
   ↓
commit response/history

Nếu user nói tiếp trong reopen window:
   ↓
frontend reopen cùng logical turn_id
   ↓
merge/refresh transcript
   ↓
turn N rev 1
   ↓
RevisionTracker.observe(N, 1)
   ↓
rev 0 becomes stale
   ↓
LLMHandler cancels rev 0
   ↓
rev 1 becomes current work
```

Điểm quan trọng là **revision phải được publish lên `RevisionTracker` ngay khi frontend/Gate nhận rev mới**, không chờ LLM worker dequeue rev mới; nếu không rev 0 đang stream sẽ không biết mình đã stale.

## Constraint quan trọng

Không được phá các invariant đã có:

```text
stale assistant output không vào history
GTCRN semantics không đổi
Smart Turn OFF path không đổi
barge-in controller không bị trộn lẫn với stale_revision
C++ producer không bị block
shutdown vẫn drain an toàn
```

`stale_revision` và `barge_in` vẫn là hai cancellation domain khác nhau:

```text
stale_revision → same logical turn, newer revision
barge_in       → user starts a new interrupting speech event
```

## Acceptance Phase 8B

```text
[ ] revision được observe trước LLM dequeue
[ ] real frontend có thể reopen same turn_id
[ ] continuation tạo rev mới
[ ] rev 0 có thể đang generate khi rev 1 xuất hiện
[ ] stale rev 0 generation bị cancel
[ ] stale assistant output never commits to history
[ ] final revision response commits exactly once
[ ] metrics record speculative start/reopen/cancel/finalization
[ ] SMART_TURN=0 baseline remains compatible
[ ] HOST regression PASS
[ ] Jetson real mic test PASS
```

Phase 8B không phải “làm cancellation lại”; cancellation core đã có. Phase này nối **real soft-final/reopen revisions** vào infrastructure đã tồn tại.

---

# 28. Phase 9A — Barge-in infrastructure

**Status: DONE**

Có:

```text
GenerationCancellationController
synthetic speech_started contract
barge_in cancellation reason
history protection
```

Known commit:

```text
efb153e feat: add barge-in cancellation infrastructure
```

---

# 29. Phase 9B — Real speech_started event

**Status: LATER**

Cần C++ speech runtime emit real event ngay khi VAD phát hiện speech bắt đầu:

```text
assistant generating
   ↓
real user speech start
   ↓
C++ [SPEECH_STARTED]
   ↓
Python cancellation controller
   ↓
cancel current generation
```

Phase này làm sau khi speculative revision path Phase 8B ổn định.

---

# 30. Phase 10 — TTS

**Status: DEFERRED**

Project hiện vẫn ưu tiên text output.

Nếu sau này thêm TTS:

```text
LLM output
  ↓
TTS Handler
  ↓
audio output
```

Không mặc định đưa model TTS lớn của HF lên Nano; phải benchmark backend riêng theo resource constraint.

---

# PHẦN IV — MODEL PLAN HIỆN TẠI

# 31. Model plan

| Stage | Model/runtime hiện tại | Target gần | Status |
|---|---|---|---|
| Audio enhancement | GTCRN simple ONNX | giữ optional | **Integrated / default OFF / quality not conclusive** |
| VAD | Silero ONNX | giữ | **Production** |
| Smart Turn | Pipecat Smart Turn v3.2 compatible ONNX | giữ optional | **Integrated / default OFF / quality not conclusive** |
| STT | Whisper Tiny.en ONNX | giữ | **Production** |
| Transcript validation | custom Gate | giữ modular handler | **Production** |
| LLM local | Gemma 3 1B Q4_K_M / llama.cpp | giữ baseline local | **Production** |
| LLM remote | OpenAI-compatible backend | benchmark khi cần | **Architecture ready** |
| TTS | none | optional later | **Deferred** |

---

# PHẦN V — METRIC / TEST POLICY

# 32. Benchmark philosophy

Benchmark dùng để đánh giá:

```text
compatibility
latency
CPU/RAM
repeatability
regression
```

Long-term real usage dùng để đánh giá:

```text
noise suppression quality
speech distortion
false COMPLETE
false INCOMPLETE
natural pause behavior
conversation feel
```

Không overfit architecture vào vài câu sample.

---

# 33. Resource metrics

Mỗi phase có runtime/model mới nên theo dõi:

```text
RAM RSS
system available RAM
CPU usage
GPU utilization nếu liên quan
swap
queue depth/backlog
```

---

# 34. Quality metrics

Speech frontend/STT:

```text
valid speech accepted
Whisper hallucination / annotation
garbage transcript dropped
false Gate rejection
false VAD activation
Smart Turn false COMPLETE
Smart Turn false INCOMPLETE
GTCRN speech distortion
```

---

# 35. Realtime correctness metrics

```text
speech ingestion có tiếp tục khi LLM generate không?
queue backlog có tăng bất thường không?
revision cũ có bị cancel đúng không?
stale output có lọt vào history không?
final turn có commit đúng một lần không?
barge-in có cancel đúng generation scope không?
```

---

# PHẦN VI — PATCH / DEPENDENCY REPRODUCIBILITY

# 36. Sherpa pin

Remote:

```text
https://github.com/k2-fsa/sherpa-onnx.git
```

Pinned commit:

```text
3e409338959097c6518998c9b72757db257f5f6f
```

Current patch chain:

```text
patches/sherpa-onnx/
├── latency-instrumentation.patch
├── vad-stt-decoupling.patch
├── gtcrn-enhancement-integration.patch
└── smart-turn-integration.patch
```

Phase 7C đã test reproducibility theo đúng sequence:

```text
pinned sherpa
 + latency patch
 + VAD/STT decoupling patch
 + GTCRN patch
 + Smart Turn patch
        ↓
C++ target rebuild PASS trên HOST
        ↓
Jetson rebuild PASS
```

Không giữ production change chỉ trong runtime source trên Jetson.

---

# PHẦN VII — CHECKLIST HIỆN TẠI

# 37. Checklist

```text
[x] Baseline runtime ổn định
[x] LLM streaming
[x] Latency instrumentation
[x] Full-pipeline benchmark
[x] Transcript Gate

[x] Benchmark enhancement candidates
[x] Integrate GTCRN optional before Silero
[x] GTCRN feature flag default OFF
[x] GTCRN + Smart Turn coexistence runtime test
[ ] Long-term GTCRN quality decision

[x] Decouple Audio/VAD from STT
[x] C++ speech_queue
[x] Resident Whisper worker

[x] SpeechRuntimeHandler
[x] transcript_queue
[x] TranscriptGateHandler
[x] valid_turn_queue
[x] LLMHandler
[x] llm_output_queue
[x] ResponseProcessor
[x] queue/worker metrics

[x] ConversationManager
[x] bounded history

[x] Local LLM backend
[x] Remote OpenAI-compatible backend abstraction
[ ] Optional remote GPU benchmark when needed

[x] Turn lifecycle foundation
[x] turn_id / revision schema
[x] Smart Turn compatibility benchmark
[x] Smart Turn transformed ORT1.11-compatible model validated
[x] Smart Turn optional integration
[x] Smart Turn host regression
[x] Smart Turn Jetson full-pipeline test
[x] GTCRN + Smart Turn combined test
[ ] Long-term Smart Turn quality decision
[ ] Finish release-grade Smart Turn model provenance/conversion script

[x] RevisionTracker
[x] Synthetic stale-revision cancellation
[x] Stale history commit protection
[ ] Phase 8B real speculative rev0 → rev1 pipeline   ← NEXT

[x] Barge-in cancellation infrastructure
[ ] Real C++ speech_started event

[ ] Optional TTS
```

---

# PHẦN VIII — TARGET KIẾN TRÚC SAU PHASE 8B

# 38. Target gần nhất

```text
                        C++ SPEECH RUNTIME

Mic / ALSA
   ↓
[GTCRN optional]
   ↓
Silero VAD
   ↓
Smart Turn / soft-final boundary
   ↓
Whisper transcript
   ↓
turn N rev 0
   ↓
Python Gate observes rev 0
   ↓
LLM generation starts
   ↓
reopen grace
   ├── no continuation
   │      ↓
   │   rev 0 final / commit
   │
   └── continuation
          ↓
       same turn_id reopened
          ↓
       merged/new transcript
          ↓
       turn N rev 1
          ↓
       Gate observes rev 1 immediately
          ↓
       RevisionTracker invalidates rev 0
          ↓
       cancel stale generation
          ↓
       rev 1 wins / final commit
```

Đây là bước biến hệ thống từ:

```text
correct modular pipeline
```

thành:

```text
revision-aware realtime speculative pipeline
```

mà vẫn giữ rollback/cancellation có kiểm soát.

---

# 39. Kiến trúc dài hạn

```text
Audio
 ↓
[Enhancement]
 ↓
VAD / turn frontend
 ↓
Smart Turn + speculative revision state
 ↓
STT
 ↓
Gate
 ↓
ConversationManager
 ↓
LLMBackend
 ↓
revision / cancellation / barge-in coordination
 ↓
ResponseProcessor
 ↓
[Optional TTS]
```

Hai deployment mode vẫn được giữ:

```text
Mode A: Fully local Jetson Nano
Mode B: Jetson speech frontend + remote GPU LLM backend
```

---

# 40. Không nên làm

Không:

```text
upgrade ORT globally như shortcut
rewrite unrelated architecture trong một phase
bật GTCRN default ON khi quality chưa đủ dữ liệu
bật Smart Turn default ON khi quality chưa đủ dữ liệu
fake Smart Turn bằng transcript heuristic
commit model binary lớn vào Git
phát triển source chỉ trên Jetson
trộn stale_revision cancellation với barge_in cancellation thành một khái niệm
commit speculative output vào history trước khi revision final
```

---

# 41. Trạng thái tiếp theo

```text
CURRENT:
Phase 7C = DONE
Phase 8A = DONE

NEXT:
Phase 8B = Real speculative turn integration
```

Mục tiêu Phase 8B không phải viết lại cancellation. Infrastructure đã tồn tại. Công việc chính là tạo **real revision event từ speech/Smart-Turn frontend**, để cùng một `turn_id` thực sự có `rev 0 → rev 1` trong normal runtime và kích hoạt cancellation path đã test.

---

# 42. Câu giải thích ngắn khi báo cáo

> Project hiện đã hoàn thành pipeline modular `optional GTCRN → Silero VAD → optional Smart Turn → resident Whisper → Transcript Gate → ConversationManager → swappable LLMBackend`, có queue/worker riêng, latency instrumentation, turn ID/revision và cancellation infrastructure. Smart Turn đã chạy full pipeline trên Jetson Nano với feature flag default OFF; integration PASS nhưng quality dài hạn chưa kết luận. Phase tiếp theo là Phase 8B: nối real speculative turn revisions vào `RevisionTracker`, để một generation của revision cũ có thể bắt đầu sớm rồi bị hủy an toàn nếu người dùng tiếp tục nói và tạo revision mới.

---

# 43. Nguồn / context chính

Project source và runtime context:

```text
source.tar.gz / current dev branch
PROJECT_CONTEXT.md / handoff context
patches/sherpa-onnx/*
logs/benchmarks/*
deps/*
```

Architecture reference:

```text
https://github.com/huggingface/speech-to-speech
```

Smart Turn reference:

```text
Pipecat Smart Turn v3.2 CPU ONNX
```

---

**END — Roadmap revision 2026-08-22 — Phase 7C DONE / Phase 8B NEXT**
