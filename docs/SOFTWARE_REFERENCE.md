# Software Reference

Tài liệu này là bản tra cứu source dài hạn của `jetson-voice-assistant`. Nội dung được đối chiếu với tracked source, dependency metadata và actual diff trong patch stack; runtime data dưới `data/`, `models/`, `runtime/` và `logs/` không phải source of truth.

## 1. Tổng quan repository

Project tách thành hai vùng:

```text
C++ sherpa-onnx runtime
→ ALSA capture, GTCRN optional, Silero VAD, Smart Turn optional, STT

Python application
→ parse event/transcript, gate, turn/revision/cancellation, conversation, LLM, output/log
```

Flow Python:

```text
C++ stderr/stdout
→ SpeechRuntimeHandler
→ transcript_queue
→ TranscriptGateHandler
→ valid_turn_queue
→ LLMHandler
→ llm_output_queue
→ ResponseProcessor
```

`app/voice_assistant.py` start consumer từ downstream lên trước khi start producer; khi shutdown, C++ nhận `SIGINT`, rồi ba queue được drain theo thứ tự trước khi `stop_event` kết thúc worker.

## 2. Bản đồ thư mục

| Path | Vì sao tồn tại | Source hay artifact |
|---|---|---|
| `app/` | Source Python của orchestration layer cho voice assistant. | Tracked source |
| `app/core/` | Contract/state độc lập backend: message, bounded conversation, revision và cancellation. | Tracked source |
| `app/backends/` | Adapter cho local llama.cpp và remote OpenAI-compatible endpoint. | Tracked source |
| `app/handlers/` | Worker nối speech runtime, transcript gate, LLM request lifecycle và output/log. | Tracked source |
| `deps/` | Metadata để tái tạo chính xác third-party runtime/model đã được project chính thức chấp nhận; không chứa binary thực tế. | Tracked source metadata |
| `docs/` | Architecture, setup, benchmark methodology/report, runbook và roadmap. | Tracked/untracked documentation |
| `patches/` | Local delta của project áp lên upstream sherpa-onnx đã pin trong `deps/`. | Tracked source delta |
| `scripts/` | Provisioning, launcher và network/runtime operational tooling. | Tracked tooling |
| `tests/` | Software unit/regression/parser/state/backend contract tests; không chứa board benchmark. | Tracked test source |
| `benchmarks/` | Reproducible source/procedure cho hardware, model và performance benchmark chạy trên Jetson. | Tracked benchmark source |
| `data/` | Benchmark/runtime input local, ignored. Không phải source và không phải generated output. | Ignored runtime data |
| `models/` | Model weights local/runtime. Không phải tracked source. | Ignored runtime data |
| `runtime/` | Third-party source/build/binary cục bộ trên máy. Không phải source of truth của project. | Ignored runtime data |
| `logs/` | Generated runtime/benchmark output, conversation log và raw result. Không chứa dataset/input hoặc source code. | Ignored/generated data; một số legacy result từng được track |

## 3. Python application

### `app/config.py`

- Tạo absolute path từ repository root đến binary/model/runtime output.
- Đọc `VOICE_ASSISTANT_STT`; hỗ trợ `whisper`, `zipformer_20m`, `zipformer_2023_06_21`.
- `build_speech_command()` chọn offline Whisper binary hoặc streaming Zipformer binary và truyền VAD/model/thread/device flags.
- Chặn Smart Turn với backend streaming vì integration hiện chỉ có trong Whisper offline runtime.
- Điều khiển `VOICE_ASSISTANT_GTCRN`, `VOICE_ASSISTANT_SMART_TURN`, `VOICE_ASSISTANT_SPECULATIVE`, `VOICE_ASSISTANT_BARGE_IN` và `VOICE_ASSISTANT_MIC_DEVICE`.
- Chọn local/remote LLM bằng `LLM_MODE`; remote cần `REMOTE_LLM_URL`, optional `REMOTE_LLM_MODEL` và `REMOTE_LLM_API_KEY`.
- Giữ system prompt, `LLM_MAX_TOKENS=128`, `LLM_TEMPERATURE=0.5`, `MAX_CONVERSATION_TURNS=6`.
- `create_session_paths()` tạo conversation log, Python/LLM latency JSONL và full-pipeline JSONL.

Default trực tiếp từ source:

```text
STT         whisper
GTCRN       OFF
Smart Turn  OFF
Speculative OFF
Barge-in    ON
LLM         local
Mic         plughw:2,0
```

### `app/voice_assistant.py`

Composition root tạo `RevisionTracker`, `GenerationCancellationController`, `ConversationManager`, ba queue và bốn handler. Nó đợi `[READY]` tối đa 30 giây trước khi hiển thị `Speak...`; failure readiness làm shutdown không-graceful. Shutdown bình thường bảo vệ contract drain queue và gom lỗi từ mọi handler.

### `app/core/messages.py`

Định nghĩa `turn_id`, `revision`, `turn_state`, `turn_id_source`, `completion_source`, timing field và Smart Turn metadata. `create_transcript_turn()` tạo record chung; `is_ready_transcript_turn()` yêu cầu đủ VAD/STT/TOTAL latency, còn `is_complete_transcript_turn()` thêm điều kiện lifecycle complete.

### `app/core/conversation.py`

`ConversationManager` chỉ commit user/assistant pair khi response thành công. History giữ system message và tối đa `max_turns` pair; aborted turn không làm bẩn history. Revision mới cùng `turn_id` có thể thay pair cũ, revision stale bị từ chối.

### `app/core/revisions.py`

`RevisionTracker` lưu revision mới nhất theo logical `turn_id`. Gate publish revision ngay khi accept để generation cũ có thể trở thành stale trước khi revision mới rời queue.

### `app/core/cancellation.py`

`GenerationCancellationController` cấp scope cho đúng một active generation. `cancel_active()` chỉ đánh dấu scope đang active, nên event speech-start lúc idle không poison request tương lai. Scope được release trong `finally` của `LLMHandler`.

## 4. Speech runtime

`SpeechRuntimeHandler` sở hữu C++ subprocess, merge stderr vào stdout và parse line liên tục. Ba contract từ C++:

```text
[READY]
[SPEECH_STARTED]
<index>: <transcript>
[LATENCY] VAD/STT/TOTAL
```

`SpeechRuntimeParser` ghép transcript với ba latency record. Khi có Smart Turn metadata, parser giữ logical `turn_id`, segment count, revision, COMPLETE/INCOMPLETE/fallback và timing. Handler không gọi LLM trực tiếp; nó chỉ enqueue transcript hoặc chuyển speech-start thành cancellation.

Hai binary runtime:

| Binary | Backend | Bản chất |
|---|---|---|
| `sherpa-onnx-vad-alsa-offline-asr` | Whisper Tiny.en | VAD producer tách khỏi resident offline STT worker; hỗ trợ Smart Turn và Speculative. |
| `sherpa-onnx-vad-alsa-streaming-asr` | Hai Zipformer | Online recognizer nhận PCM khi speech gate mở, finalize ở VAD endpoint. |

## 5. STT backends

Các trạng thái không được đồng nhất:

| Backend | Implemented | Benchmark selection | Runtime default | Vai trò |
|---|---|---|---|---|
| Whisper Tiny.en | Có | Accuracy tốt nhất trong benchmark 9 mẫu | Có | Stable accuracy baseline/fallback; offline |
| Zipformer 20M 2023-02-17 | Có | Không được chọn | Không | Experimental lightweight/speed baseline |
| Zipformer 2023-06-21 | Có | Được chọn làm primary streaming backend | Không | Streaming candidate chính, accuracy gần Whisper nhưng RSS cao hơn |

Source và launcher vẫn default `whisper`. Đây là discrepancy được giữ nguyên trong task tài liệu để không thay behavior.

`scripts/download_stt_models.sh` provision cả ba model từ official sherpa-onnx archives và verify từng runtime file bằng `deps/models.sha256`.

## 6. VAD và Speech Gating

Silero VAD chạy liên tục ở 16 kHz với threshold 0.5; log runtime legacy cho thấy min silence 0.5 s, min speech 0.25 s và window 512 sample. VAD tạo hai loại signal:

- transition vào speech phát `[SPEECH_STARTED]` cho barge-in;
- completed segment/end marker tạo final STT turn và VAD latency.

Streaming Zipformer không nhận silence liên tục. `streaming-asr-speech-gating.patch` giữ rolling pre-roll 480 ms khi idle; lúc `IsSpeechDetected()` chuyển true, nó flush pre-roll đúng một lần rồi feed chunk tiếp theo realtime đến endpoint. Mục tiêu đã đo là giảm idle ASR CPU từ khoảng 120.4% xuống 22.3%, trade-off khoảng 50 ms speech-frontend latency.

## 7. Audio Enhancement

GTCRN simple là optional frontend trước cả VAD và STT. Khi flag bật, cùng enhanced PCM đi vào VAD và backend STT. Runtime validate sample rate 16 kHz. Raw microphone sample timeline vẫn dùng để tính VAD latency nên con số bao gồm buffering của enhancement.

Model official ở runtime path `models/enhancement/gtcrn_simple.onnx`; source, size và SHA256 nằm trong `deps/` và download script. `VOICE_ASSISTANT_GTCRN` default OFF trong cả source và launcher dù README cũ từng gọi GTCRN ON là stable config.

## 8. Turn Management

Smart Turn trả lời semantic completion sau VAD endpoint, không thay VAD. Runtime lấy tối đa 8 giây audio cuối, pad zero ở đầu, normalize, tạo Whisper feature `[800, 80]`, transpose thành model input `[1, 80, 800]`, rồi so probability với threshold 0.5.

- COMPLETE: Whisper chạy trên toàn logical turn đã merge.
- INCOMPLETE: audio được giữ để nối VAD segment sau.
- ERROR: fail-open sang Whisper.
- Shutdown với held audio: runtime discard và log rõ.

Smart Turn optional, 4 intra-op threads, chỉ dùng với Whisper. Feature extraction là bottleneck khoảng 1.3 giây; total evaluation khoảng 1.65–1.8 giây.

Speculative Turn chỉ hiệu lực khi Smart Turn bật. Với INCOMPLETE, runtime giữ một copy audio để nối tiếp nhưng vẫn chạy provisional Whisper và phát revision hiện tại. Revision mới làm generation cũ stale. Infrastructure có test, nhưng default OFF và không được khuyến nghị trên Nano vì extra compute/repeated provisional response.

## 9. Conversation / Revision / Cancellation

`TranscriptGateHandler` bỏ empty transcript hoặc text chứa một trong `()[]{}`; accepted turn được publish vào `RevisionTracker` trước khi enqueue LLM.

`LLMHandler` kiểm tra stale revision trước generation, giữa các streamed token và trước history commit. Barge-in cũng được kiểm tra giữa token và trước commit. Turn cancel/failed bị abort nên không vào history.

Hai cơ chế độc lập:

```text
revision cancellation
→ revision mới của cùng logical turn

barge-in cancellation
→ external speech-start hủy active generation hiện tại
```

`ResponseProcessor` là writer duy nhất cho terminal và ba loại log. Nó xử lý status, gate drop, turn start/token/done và LLM error. Hiện event `turn_cancelled` không có nhánh hiển thị/log riêng; cancellation vẫn được bảo vệ ở state/history nhưng đây là discrepancy cần report, không sửa trong task cleanup.

## 10. LLM Backends

`LLMBackend` định nghĩa generator `stream_generate()`. `OpenAICompatibleBackend` dựng POST `/v1/chat/completions`, parse SSE `data:`, hỗ trợ `delta.content` và `choice.text`.

- `LocalLlamaCppBackend`: endpoint `http://127.0.0.1:8080/v1/chat/completions`, không API key.
- `RemoteOpenAICompatibleBackend`: endpoint do `REMOTE_LLM_URL` cung cấp, optional model và Bearer token.

`scripts/llama_server.sh` quản lý local server ở port 8080 với Gemma 3 1B Q4_K_M, context 2048, `-ngl 99`, `-t 2`; PID/log nằm dưới `logs/`.

## 11. Scripts

| Script | Chạy ở đâu | Input/config | Output/side effect | Dependency và mục đích |
|---|---|---|---|---|
| `download_enhancement_models.sh` | HOST hoặc Jetson có network | URL, expected size/SHA hard-code | `models/enhancement/gtcrn_simple.onnx` | `wget`, `stat`, `sha256sum`; provision GTCRN atomic qua `.tmp`. |
| `download_stt_models.sh` | HOST hoặc Jetson có network | argument `all/whisper/zipformer_*`, `deps/models.sha256` | model dưới `models/stt/`, staging dưới `models/.downloads/stt` | `wget`, `tar`, `sha256sum`; download và verify official STT files. |
| `llama_server.sh` | Jetson | `start/stop/status`; fixed binary/model path | `logs/llama_server.log`, PID và local port 8080 | llama.cpp, CUDA libs, `curl`; quản lý local LLM server. |
| `run_voice_assistant.sh` | Jetson | config block và environment export | exec `python3 app/voice_assistant.py`; runtime logs do app tạo | speech runtime/model/LLM endpoint; launcher chuẩn hiện default Whisper/GTCRN OFF. |
| `setup-jetson-internet-laptop.sh` | HOST Linux laptop | `JETSON_NET`, `LAPTOP_USB_IP` | bật IP forwarding, NAT và FORWARD rule | `sudo`, `ip`, `iptables`; chia sẻ internet qua USB network. |
| `setup-jetson-internet-jetson.sh` | Jetson | `LAPTOP_USB_IP`, `JETSON_USB_IP` | thay default route và kiểm tra Internet/DNS | `sudo`, `ip`, `ping`; dùng laptop làm gateway. |

Hai network script thay đổi network state của máy và cần quyền root; không chạy như unit test.

## 12. Dependency Metadata (`deps/`)

| File | Mục đích | Nó pin/khai báo cái gì | Khi nào sửa |
|---|---|---|---|
| `sherpa-onnx.commit` | Xác định upstream base duy nhất. | Exact commit `3e409338959097c6518998c9b72757db257f5f6f`. | Chỉ khi chủ động rebase patch stack và rebuild/retest toàn runtime. |
| `sherpa-onnx.remote` | Xác định provenance Git. | `https://github.com/k2-fsa/sherpa-onnx.git`. | Khi upstream source chính thức đổi. |
| `runtime-sources.md` | Runbook provenance/build của third-party runtime và model. | llama.cpp installer/manifest, sherpa base + ordered patches, model role/source. | Khi adopt runtime/model/patch hoặc evidence chính thức thay đổi. |
| `models.manifest` | Inventory model đã được project adopt. | Relative path và byte size của LLM, VAD, Whisper, GTCRN và hai Zipformer; gồm cả support file/test WAV trong Whisper archive. | Khi official model set/file layout/size thay đổi sau acceptance. |
| `models.sha256` | Integrity pin cho official model files. | SHA256 theo path dưới `models/`; download STT script đọc file này. | Khi official bytes thay đổi và provenance đã được xác minh. |
| `llama-server.manifest` | Snapshot binary llama-server đã validate trên Jetson. | Runtime path, version 5050/commit `23106f94`, GCC/arch/CUDA device, ELF info và SHA256. | Khi rebuild/replace official llama-server rồi test lại hardware. |

Policy:

```text
EXPERIMENT
download local vào ignored models/runtime
→ benchmark
→ chưa update manifest/checksum/script

OFFICIAL
benchmark PASS + quyết định adopt
→ update deps + checksum + provisioning + source docs
```

## 13. Sherpa-ONNX Patch Stack (`patches/sherpa-onnx/`)

Quan hệ nền tảng:

```text
deps/sherpa-onnx.commit
= upstream base

patches/sherpa-onnx/*
= ordered project-specific delta
```

Thứ tự apply hiện tại:

```text
1  latency-instrumentation.patch
2  vad-stt-decoupling.patch
3  gtcrn-enhancement-integration.patch
4  smart-turn-integration.patch
5  speculative-turn-integration.patch
6  barge-in-speech-started.patch
7  streaming-asr-integration.patch
8  streaming-asr-speech-gating.patch
9  speech-runtime-readiness.patch
10 alsa-capture-retry.patch
```

| Patch | Vấn đề giải quyết | File/subsystem upstream bị sửa | Feature tạo ra | Dependency patch | Cách verify |
|---|---|---|---|---|---|
| `latency-instrumentation.patch` | Offline demo không tách được endpoint delay và decode latency. | `sherpa-onnx-vad-alsa-offline-asr.cc`; sample timeline và `steady_clock`. | Phát transcript kèm `[LATENCY] VAD`, `STT`, `TOTAL`. | Upstream base. | Parser test; runtime log có ba line và `TOTAL≈VAD+STT`. |
| `vad-stt-decoupling.patch` | Whisper decode block ALSA/VAD loop. | Offline ALSA ASR demo; thêm queue, mutex/CV và STT thread. | Audio/VAD producer enqueue owned segment; resident STT worker drain queue, gồm queue wait trong STT latency và drain khi shutdown. | Latency patch vì sửa trên output/timing đã thêm. | `test_pipeline_integration.py`; live mic vẫn capture khi STT bận; graceful SIGINT drain. |
| `gtcrn-enhancement-integration.patch` | Denoiser đã tồn tại upstream nhưng chưa nằm trong voice runtime. | Offline ALSA ASR demo; `OnlineSpeechDenoiserConfig/OnlineSpeechDenoiser`. | Optional `--speech-denoiser-gtcrn-model`; enhanced PCM vào VAD/STT, validate 16 kHz. | VAD/STT decoupling layout. | Config feature-flag test; startup `[ENHANCEMENT]`; RAW/GTCRN hardware A/B. |
| `smart-turn-integration.patch` | VAD endpoint có thể cắt logical sentence ở pause. | Offline demo; custom ONNX Runtime session, Whisper feature extraction và held-audio lifecycle. | Smart Turn 8 s/pad/normalize/feature/inference; merge segment; fail-open Whisper; detailed metadata. | GTCRN/VAD-worker source state. | Smart Turn parser, fallback, feature flag và lifecycle tests; runtime COMPLETE/INCOMPLETE logs. |
| `speculative-turn-integration.patch` | INCOMPLETE phải chờ continuation trước STT/LLM. | Smart Turn block trong offline demo. | `--smart-turn-speculative`; provisional transcript/revision trong khi vẫn giữ audio cho continuation. | Smart Turn patch bắt buộc. | Speculative feature flag/parser và revision cancellation tests. |
| `barge-in-speech-started.patch` | Đợi endpoint + STT mới cancel làm assistant tiếp tục generate quá lâu. | Offline ALSA/VAD producer. | Phát `[SPEECH_STARTED]` một lần mỗi speech transition và reset sau endpoint. | Offline source sau Smart/Speculative stack. | `test_barge_in.py`; hardware generation bị cancel trước transcript mới. |
| `streaming-asr-integration.patch` | Không có project runtime cho true streaming Zipformer với cùng Python output contract. | `CMakeLists.txt`; tạo `sherpa-onnx-vad-alsa-streaming-asr.cc`. | Binary mới với OnlineRecognizer, PCM/end-marker queue, GTCRN optional, VAD, speech-start, final transcript/latency cùng format Python. | Base APIs; patch order đặt sau offline changes. | Build target; STT backend config test; live Zipformer final transcript và latency parse. |
| `streaming-asr-speech-gating.patch` | Initial streaming runtime feed silence/noise liên tục, idle CPU cao. | Streaming binary vừa được tạo. | Idle chỉ chạy VAD và giữ rolling pre-roll 480 ms; speech-start flush một lần, gate mở đến endpoint. | Streaming integration bắt buộc. | STT benchmark BEFORE/AFTER: idle CPU ~120.4%→22.3%, không thấy clipping với 480 ms. |
| `speech-runtime-readiness.patch` | Python có thể báo `Speak...` trước khi STT worker thật sự sẵn sàng. | Cả offline và streaming runtime. | Worker readiness mutex/CV và unified `[READY]` sau backend worker init. | Cả hai runtime phải đã tồn tại; áp sau streaming gating. | `SpeechRuntimeHandler.wait_until_ready()`; startup chỉ tiếp tục sau `[READY]`, timeout/failure dừng app. |
| `alsa-capture-retry.patch` | ALSA device có thể tạm trả `-EBUSY` khi mở mic ở startup. | `sherpa-onnx/csrc/alsa.cc`. | Retry riêng `-EBUSY` tối đa 20 attempt, delay 500 ms; lỗi khác hoặc attempt cuối fail ngay theo help/error cũ. Tổng cửa sổ xấp xỉ 9.5 giây sau lần đầu. | Độc lập về file nhưng áp cuối stack hiện tại. | Giữ mic bận rồi nhả trong cửa sổ retry; kiểm tra success count; giữ bận hết 20 lần phải exit. |

Patch verification đầy đủ cần clean upstream tree đúng commit, `git apply --check` theo thứ tự, build cả hai binary, chạy Python regressions và hardware test trên Jetson. HOST workspace hiện không thay thế được phần hardware này.

## 14. Tests

Các regression test được nhóm theo feature; chúng giữ nguyên nội dung và contract sau khi đổi path khỏi cấu trúc phase-based.

| Test/file | Contract được bảo vệ |
|---|---|
| `tests/speech/test_speech_runtime_parser.py` | Transcript + VAD/STT/TOTAL thành turn có Python/runtime identity. |
| `tests/pipeline/test_transcript_gate.py` | Empty/Whisper annotation bị drop; accepted turn được enqueue và có timing. |
| `tests/llm/test_llm_handler.py` | Queue → streamed request/events → successful conversation commit. |
| `tests/pipeline/test_response_processor.py` | Terminal/conversation/latency/full-pipeline output và queue metric. |
| `tests/pipeline/test_pipeline_integration.py` | End-to-end Python queue pipeline và graceful drain. |
| `tests/conversation/test_conversation_manager.py` | Bounded user/assistant pairs; abort không pollute history. |
| `tests/llm/test_llm_backend.py` | Local/remote OpenAI-compatible body/header/SSE parsing. |
| `tests/turns/test_turn_lifecycle.py` | Turn/revision/state contract và revision mismatch protection. |
| `tests/speech/test_smart_turn_feature_flag.py` | Smart Turn default OFF, command flags và coexistence GTCRN. |
| `tests/speech/test_smart_turn_runtime_parser.py` | INCOMPLETE→COMPLETE merge, metrics và logical identity. |
| `tests/speech/test_smart_turn_fallback.py` | Smart Turn ERROR fail-open sang Whisper. |
| `tests/speech/test_speculative_feature_flag.py` | Speculative chỉ bật khi Smart Turn bật. |
| `tests/speech/test_speculative_runtime_parser.py` | Provisional rev0 và completed rev1 metadata. |
| `tests/turns/test_gate_revision_observation.py` | Accepted revision được observe trước LLM dequeue; dropped revision không advance. |
| `tests/turns/test_revision_cancellation.py` | Generation stale bị cancel và không commit history. |
| `tests/turns/test_conversation_revision_supersede.py` | Revision mới thay committed pair cũ, không duplicate history. |
| `tests/turns/test_barge_in.py` | Speech-start bridge, active cancel, history protection, scope cleanup và flag OFF. |
| `tests/speech/test_stt_backend_config.py` | Whisper/Zipformer chọn đúng binary/model và guard Smart Turn streaming. |

Phần lớn file là executable regression script với `main()`, không phải pytest function. Vì vậy `python3 -m pytest tests` không tự chạy toàn bộ contract; khi sửa feature liên quan phải chạy trực tiếp file tương ứng.

## 15. Benchmark source

Top-level `benchmarks/` là nơi duy nhất chứa tracked benchmark/hardware measurement source. `benchmarks/README.md` định nghĩa HOST-first workflow, Jetson execution-only policy, reproducibility metadata và ranh giới debug/accepted measurement.

Old `tests/latency/benchmark_llm_latency.py` đã bị xóa trong infrastructure reset vì nó là Jetson LLM latency runner cũ, không phải software regression. Hiện chưa có benchmark implementation mới ngoài policy README.

VoiceBank-DEMAND/MS-SNSD runner mới phải được tạo dưới `benchmarks/stt/noise_robustness/` trên HOST. Dataset/subset runtime đã tồn tại, nhưng tracked producer/procedure mới chưa được implement.

## 16. Runtime-only directories

- `models/`: official/experimental weights local; Git ignore toàn bộ.
- `runtime/`: sherpa-onnx/llama.cpp source, build và binary local; Git ignore toàn bộ.
- `logs/conversations/`: transcript/assistant output theo session.
- `data/`: benchmark/runtime input local; hiện có `data/stt/voicebank_demand/prepared_15/` gồm 15 clean + 15 noisy WAV 16 kHz và `manifest.tsv` mapping/reference.
- `logs/benchmarks/`: generated benchmark output/result; bắt đầu sạch sau infrastructure reset.
- `.venv/`, `__pycache__/`, archive và bytecode: local artifact, không phải source.

Runtime result phải nằm dưới `logs/benchmarks/<topic>/`; runnable code không được đặt tại đó. Accepted methodology/conclusion nằm trong `docs/`.

## 17. Các discrepancy hiện tại

1. Zipformer 2023-06-21 được benchmark chọn làm primary streaming backend, nhưng `app/config.py` và launcher vẫn default Whisper.
2. README/PROJECT_CONTEXT cũ từng gọi GTCRN ON là stable/recommended, trong khi actual source và launcher default GTCRN OFF.
3. Smart Turn/Speculative chỉ tồn tại ở Whisper offline runtime; architecture dùng Zipformer không thể đồng thời bật chúng.
4. `ResponseProcessor` không render/persist event `turn_cancelled`, dù state/history cancellation đã hoạt động và có unit regression.
5. STT report hiện là historical accepted benchmark; raw implementation cũ không còn được sử dụng và không đạt policy reproducibility mới.
6. VoiceBank-DEMAND đã có prepared subset nhưng chưa có tracked preparation/runner/metrics code dưới `benchmarks/`; noise robustness chưa hoàn tất.
7. `models.manifest` chứa Whisper support/test WAV trong official inventory, trong khi Git policy cấm commit audio; đây là metadata path/size, không phải audio tracked.

Task documentation/cleanup không tự sửa các discrepancy có thể đổi behavior.

## 18. Muốn sửa feature X thì vào đâu?

| Muốn sửa | Entry point cần đọc trước | Contract/test liên quan |
|---|---|---|
| STT backend/default/model path | `app/config.py`, `scripts/run_voice_assistant.sh` | `tests/speech/test_stt_backend_config.py` |
| C++ transcript/event parsing | `app/handlers/speech_runtime.py` | speech parser tests + turns barge-in |
| Transcript filtering | `app/handlers/transcript_gate.py` | pipeline gate + turns gate revision |
| Turn schema/lifecycle | `app/core/messages.py` | turns lifecycle/parser tests |
| Conversation window/commit | `app/core/conversation.py` | conversation + turns supersede |
| Revision/stale generation | `app/core/revisions.py`, `app/handlers/llm.py` | turns cancellation tests |
| Barge-in | cancellation core, speech/LLM handlers, barge-in patch | turns barge-in + Jetson hardware test |
| LLM local/remote protocol | `app/backends/llm.py`, `app/config.py` | llm backend test |
| Output và latency log | `app/handlers/response.py`, `create_session_paths()` | pipeline response/integration tests |
| GTCRN/Smart/Speculative C++ behavior | ordered patches 3–6 | speech feature flag/parser tests + Jetson |
| Streaming Zipformer/gating | patches 7–9 | speech STT config test + STT benchmark report |
| ALSA startup recovery | `alsa-capture-retry.patch` | build + real device busy/release test |
| Official dependency/model | `deps/`, download scripts | checksum/provenance + hardware acceptance |
| Benchmark methodology/path | `benchmarks/README.md`, `docs/BENCHMARKS.md`, source dưới `benchmarks/` | result dưới `logs/benchmarks/<topic>/` |
