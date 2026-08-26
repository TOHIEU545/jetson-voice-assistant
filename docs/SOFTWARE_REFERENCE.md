# Software Reference

Tài liệu này là bản tra cứu cho developer: source code nằm đâu, model nào đang dùng và runtime config hoạt động thế nào.

---

## 1. Source layout chính

```text
jetson-voice-assistant/
│
├── app/
│   ├── config.py
│   ├── voice_assistant.py
│   ├── core/
│   │   ├── conversation.py
│   │   ├── messages.py
│   │   ├── revisions.py
│   │   └── cancellation.py
│   └── handlers/
│       ├── speech_runtime.py
│       ├── transcript_gate.py
│       └── llm.py
│
├── deps/
├── models/                    # ignored weights
├── patches/sherpa-onnx/
├── tests/
├── logs/
└── docs/
```

## 2. File responsibilities

| File | Trách nhiệm |
|---|---|
| `app/voice_assistant.py` | composition root, queues, workers, startup/shutdown |
| `app/config.py` | model path, feature flag, speech command, LLM mode |
| `speech_runtime.py` | bridge C++ runtime → Python events/transcripts |
| `transcript_gate.py` | lọc transcript trước LLM |
| `llm.py` | LLM worker, streaming, stale/cancel checks |
| `conversation.py` | bounded history, commit/abort |
| `revisions.py` | latest revision của logical turn |
| `cancellation.py` | active generation và barge-in |

## 3. Data flow

```text
C++ transcript
      ↓
SpeechRuntimeHandler
      ↓
transcript_queue
      ↓
TranscriptGateHandler
      ↓
valid_turn_queue
      ↓
LLMHandler
```

C++ có `speech_queue` riêng để tách VAD khỏi Whisper.

## 4. Models

| Stage | Model/runtime | Trạng thái |
|---|---|---|
| Enhancement | GTCRN simple ONNX | optional |
| VAD | Silero VAD ONNX | active |
| Turn completion | Smart Turn compatible ONNX | optional |
| STT | Whisper Tiny.en ONNX | active |
| LLM | Gemma 3 1B Q4_K_M | active |
| LLM runtime | llama.cpp | active |

Known paths:

```text
models/vad/silero_vad.onnx

models/stt/whisper-tiny.en/
├── tiny.en-encoder.onnx
├── tiny.en-decoder.onnx
└── tokens.txt

models/turn/
└── smart-turn-v3.2-cpu-opset16-ir8-clean.onnx
```

Weights không commit vào Git.

## 5. Runtime constraints

```text
Jetson Nano 4GB
JetPack 4.6.1 / L4T 32.x
CUDA 10.2
Maxwell cc 5.3
Python 3.6.9
```

Sherpa production runtime hiện gắn với ONNX Runtime 1.11.0. Không upgrade global ONNX Runtime tùy tiện.

## 6. Feature flags

GTCRN:

```bash
VOICE_ASSISTANT_GTCRN=0
VOICE_ASSISTANT_GTCRN=1
```

Smart Turn:

```bash
VOICE_ASSISTANT_SMART_TURN=0
VOICE_ASSISTANT_SMART_TURN=1
```

Speculative:

```bash
VOICE_ASSISTANT_SPECULATIVE=0
VOICE_ASSISTANT_SPECULATIVE=1
```

Speculative chỉ có ý nghĩa khi Smart Turn bật và hiện không khuyến nghị dùng.

LLM:

```bash
LLM_MODE=local
```

Local endpoint:

```text
http://127.0.0.1:8080/v1/chat/completions
```

## 7. Recommended configs

Stable baseline:

```bash
VOICE_ASSISTANT_GTCRN=1 \
VOICE_ASSISTANT_SMART_TURN=0 \
VOICE_ASSISTANT_SPECULATIVE=0 \
LLM_MODE=local \
python3 app/voice_assistant.py
```

Smart Turn test:

```bash
VOICE_ASSISTANT_GTCRN=1 \
VOICE_ASSISTANT_SMART_TURN=1 \
VOICE_ASSISTANT_SPECULATIVE=0 \
LLM_MODE=local \
python3 app/voice_assistant.py
```

Speculative test only:

```bash
VOICE_ASSISTANT_GTCRN=1 \
VOICE_ASSISTANT_SMART_TURN=1 \
VOICE_ASSISTANT_SPECULATIVE=1 \
LLM_MODE=local \
python3 app/voice_assistant.py
```

## 8. Sherpa patch chain

```text
1. latency-instrumentation.patch
2. vad-stt-decoupling.patch
3. gtcrn-enhancement-integration.patch
4. smart-turn-integration.patch
5. speculative-turn-integration.patch
6. barge-in-speech-started.patch
7. streaming-asr-integration.patch
8. streaming-asr-speech-gating.patch
```

Pinned commit:

```text
3e409338959097c6518998c9b72757db257f5f6f
```

## 9. Barge-in contract

C++ event:

```text
[SPEECH_STARTED]
```

Python action:

```text
cancel_active("barge_in")
```

Nếu không có active generation thì event được bỏ qua an toàn.

## 10. Logs

```text
logs/conversations/
logs/benchmarks/python_llm_latency/
logs/benchmarks/full_pipeline_latency/
```

## 11. Git policy

Track:

```text
source, scripts, config, tests, docs, patches,
manifests, checksums, runtime metadata
```

Do not track:

```text
*.onnx, *.gguf, build outputs, cache,
recordings, temporary benchmark artifacts
```
