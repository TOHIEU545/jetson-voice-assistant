# PROJECT_CONTEXT

## Project và workflow

`jetson-voice-assistant` là local speech-to-LLM assistant cho Jetson Nano 4GB. Branch phát triển chính là `dev`.

```text
HOST edit/test
→ commit/push
→ GitHub source of truth
→ Jetson git pull
→ runtime/hardware/benchmark
```

Không chỉnh tracked source trực tiếp trên Jetson.

Paths hiện dùng:

```text
HOST repo:        ~/jetson-voice-assistant
HOST sherpa dev: ~/jetson-voice-assistant-runtime-dev/sherpa-onnx
Jetson repo:      ~/jetson-voice-assistant
Jetson sherpa:    ~/jetson-voice-assistant/runtime/sherpa-onnx
```

## Architecture hiện tại

```text
ALSA microphone
→ GTCRN optional
→ Silero VAD
→ Whisper offline hoặc Zipformer streaming
→ SpeechRuntimeHandler
→ TranscriptGateHandler
→ LLMHandler
→ local/remote OpenAI-compatible LLM
→ ResponseProcessor
```

C++ giữ audio/VAD/STT worker. Python giữ queue orchestration, logical turn/revision, bounded conversation, cancellation, LLM streaming và logs.

Runtime event:

```text
[READY]          → Python chỉ báo Speak... sau khi STT worker sẵn sàng
[SPEECH_STARTED] → cancel active LLM nếu barge-in bật
transcript       → gate → revision → LLM
```

## STT status

| Backend | Trạng thái |
|---|---|
| Whisper Tiny.en | Implemented; runtime default; accuracy baseline/fallback; offline |
| Zipformer 20M | Implemented; experimental lightweight/speed baseline |
| Zipformer 2023-06-21 | Implemented; benchmark-selected primary streaming backend; chưa là launcher default |

Streaming Zipformer dùng VAD gating và rolling pre-roll 480 ms. Benchmark gần nhất ghi idle ASR CPU khoảng 120.4% xuống 22.3%, đổi lại khoảng 50 ms speech-frontend latency.

Discrepancy cần giữ rõ: `app/config.py` và `scripts/run_voice_assistant.sh` vẫn default `VOICE_ASSISTANT_STT=whisper`. Không đổi default nếu chưa có quyết định behavior riêng.

## Feature flags và default thực tế

```text
VOICE_ASSISTANT_STT=whisper
VOICE_ASSISTANT_GTCRN=0
VOICE_ASSISTANT_SMART_TURN=0
VOICE_ASSISTANT_SPECULATIVE=0
VOICE_ASSISTANT_BARGE_IN=1
VOICE_ASSISTANT_MIC_DEVICE=plughw:2,0
LLM_MODE=local
```

Smart Turn và Speculative Turn hiện chỉ hỗ trợ Whisper offline runtime. Speculative chỉ có hiệu lực khi Smart Turn bật và không được khuyến nghị trên Nano ở trạng thái hiện tại.

## Conversation, revision và cancellation

- `ConversationManager`: system prompt + tối đa 6 committed user/assistant pair; failed/cancelled turn không commit.
- `RevisionTracker`: revision mới của cùng logical turn làm generation cũ stale.
- `GenerationCancellationController`: chỉ cancel scope đang active; speech-start lúc idle không ảnh hưởng request tương lai.
- Barge-in đã có Python regression và đã được hardware test PASS theo tài liệu hiện có.

## LLM

Local endpoint:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Local runtime/model:

```text
llama.cpp server 5050 (23106f94)
Gemma 3 1B Q4_K_M
context 2048
-ngl 99
-t 2
```

Remote mode dùng `REMOTE_LLM_URL`, `REMOTE_LLM_MODEL` và `REMOTE_LLM_API_KEY`.

## Sherpa base và patch order

Pinned base:

```text
remote: https://github.com/k2-fsa/sherpa-onnx.git
commit: 3e409338959097c6518998c9b72757db257f5f6f
```

Apply:

```text
1. latency-instrumentation.patch
2. vad-stt-decoupling.patch
3. gtcrn-enhancement-integration.patch
4. smart-turn-integration.patch
5. speculative-turn-integration.patch
6. barge-in-speech-started.patch
7. streaming-asr-integration.patch
8. streaming-asr-speech-gating.patch
9. speech-runtime-readiness.patch
10. alsa-capture-retry.patch
```

`speech-runtime-readiness.patch` thêm unified `[READY]`. `alsa-capture-retry.patch` retry startup `-EBUSY` tối đa 20 attempt, cách nhau 500 ms.

## Runtime/model paths

```text
runtime/sherpa-onnx/build/bin/sherpa-onnx-vad-alsa-offline-asr
runtime/sherpa-onnx/build/bin/sherpa-onnx-vad-alsa-streaming-asr
runtime/llama.cpp/bin/llama-server

models/vad/silero_vad.onnx
models/enhancement/gtcrn_simple.onnx
models/stt/whisper-tiny.en/
models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/
models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-21/
models/turn/smart-turn-v3.2-cpu-opset16-ir8-clean.onnx
models/llm/gemma-3-1b-it-Q4_K_M.gguf
```

Models/runtime/logs đều local và ignored. Official identity nằm trong `deps/`.

## Current development focus

```text
Benchmark infrastructure đã được reset.

Old raw benchmark implementation/result đã bị xóa
khi historical conclusion đã được giữ trong report.

Mọi benchmark mới:
HOST phát triển + track dưới benchmarks/
→ commit/push dev
→ Jetson git pull và execute
→ output dưới logs/benchmarks/
```

Benchmark tiếp theo:

```text
STT noise robustness
Whisper Tiny.en vs Zipformer 2023-06-21
clean/noisy
GTCRN OFF/ON
```

HOST hiện có runtime dataset:

```text
data/stt/voicebank_demand/
└── prepared_15/{clean,noisy,manifest.tsv}
```

VoiceBank-DEMAND `prepared_15/` được giữ làm runtime input: 15 clean/noisy pair và `manifest.tsv`. Chưa có tracked preparation/runner/metrics implementation theo policy mới. Source/procedure official phải đặt dưới `benchmarks/stt/noise_robustness/`; input nằm dưới `data/stt/voicebank_demand/` và result nằm dưới `logs/benchmarks/stt/noise_robustness/`.

## Commands kiểm tra trên HOST

```bash
python3 -m pytest tests

# Các regression script main() không được pytest discover phải chạy trực tiếp
python3 tests/pipeline/test_pipeline_integration.py
python3 tests/conversation/test_conversation_manager.py
python3 tests/llm/test_llm_backend.py
python3 tests/speech/test_smart_turn_runtime_parser.py
python3 tests/turns/test_revision_cancellation.py
python3 tests/turns/test_barge_in.py
python3 tests/speech/test_stt_backend_config.py

git diff --check
git status --short
```

## Known issues / chưa chốt

- Noise có thể gây false VAD/STT transcript; noise robustness benchmark chưa xong.
- Smart Turn feature preparation đắt và có thể false INCOMPLETE trong noise.
- Speculative có thể tạo repeated provisional response/extra compute.
- `ResponseProcessor` chưa có output/log branch cho `turn_cancelled`.
- Zipformer được benchmark chọn nhưng launcher vẫn default Whisper.
- Hardware apply/build validation của full 10-patch stack phải thực hiện trên clean pinned tree/Jetson.

Reference dài hạn: `docs/SOFTWARE_REFERENCE.md`. Benchmark policy: `benchmarks/README.md`. Accepted STT results: `docs/stt/BENCHMARK.md`; LLM results: `docs/llm/BENCHMARK.md`.
