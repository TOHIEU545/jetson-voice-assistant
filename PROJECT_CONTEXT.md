# PROJECT_CONTEXT

## Project

`jetson-voice-assistant` — local voice assistant trên Jetson Nano 4GB.

## Workflow

```text
HOST → test → commit/push → GitHub → Jetson pull → hardware benchmark
```

GitHub là source of truth.

Paths:

```text
HOST repo:
~/jetson-voice-assistant

HOST sherpa dev:
~/jetson-voice-assistant-runtime-dev/sherpa-onnx

Jetson repo:
~/jetson-voice-assistant

Jetson sherpa:
~/jetson-voice-assistant/runtime/sherpa-onnx
```

Branch:

```text
dev
```

## Current architecture

```text
Mic
 ↓
GTCRN optional
 ↓
Silero VAD
 ↓
Smart Turn optional
 ↓
Whisper Tiny.en
 ↓
Transcript Gate
 ↓
ConversationManager
 ↓
LLMHandler / LLMBackend
 ↓
Gemma via llama.cpp
```

Barge-in:

```text
VAD speech start
 ↓
[SPEECH_STARTED]
 ↓
cancel active LLM
```

## Recommended config

```text
VOICE_ASSISTANT_GTCRN=1
VOICE_ASSISTANT_SMART_TURN=0
VOICE_ASSISTANT_SPECULATIVE=0
LLM_MODE=local
```

## LLM endpoint

```text
http://127.0.0.1:8080/v1/chat/completions
```

## Main models

```text
GTCRN simple ONNX
Silero VAD ONNX
Whisper Tiny.en ONNX
Smart Turn compatible ONNX (optional)
Gemma 3 1B Q4_K_M
```

## Main Python files

```text
app/config.py
app/voice_assistant.py
app/core/conversation.py
app/core/messages.py
app/core/revisions.py
app/core/cancellation.py
app/handlers/speech_runtime.py
app/handlers/transcript_gate.py
app/handlers/llm.py
```

## Sherpa

Pinned commit:

```text
3e409338959097c6518998c9b72757db257f5f6f
```

Patch order:

```text
latency-instrumentation.patch
vad-stt-decoupling.patch
gtcrn-enhancement-integration.patch
smart-turn-integration.patch
speculative-turn-integration.patch
barge-in-speech-started.patch
streaming-asr-integration.patch
streaming-asr-speech-gating.patch
```

## Validated

```text
VAD/STT decoupling          PASS
GTCRN integration           PASS
bounded history             PASS
LLM backend abstraction     PASS
revision protection         PASS
Smart Turn integration      PASS / optional
speculative flow            implemented / default OFF
real Jetson barge-in        PASS
```

## Recent baseline

```text
GTCRN ON
Smart Turn OFF
Speculative OFF

VAD          ~0.53 s
STT          ~1.1–1.4 s
LLM TTFT     ~0.47–0.56 s
Speech→First ~2.1–2.5 s
```

## Known issues

```text
noise can cause bad VAD/STT transcripts
Smart Turn feature extraction is expensive
Smart Turn can false-INCOMPLETE in noise
speculative can expose repeated provisional responses
```

## Next optimization candidates

```text
Smart Turn incremental feature cache
fixed-WAV regression tests
continued latency profiling
TTS later
```

## Git policy

Track source/scripts/config/tests/docs/patches/manifests/checksums.

Do not track model weights, build outputs, cache, recordings or temporary benchmark artifacts.
