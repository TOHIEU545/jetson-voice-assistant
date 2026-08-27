# Jetson Voice Assistant

Local voice-assistant pipeline chạy trên **Jetson Nano 4GB**.

```text
Microphone
   ↓
Audio Enhancement
   ↓
Voice Activity Detection
   ↓
Speech-to-Text
   ↓
Transcript Validation
   ↓
Conversation / LLM
   ↓
Streaming Text Response
```

## Mục tiêu

Project tập trung vào một voice assistant chạy local với các yêu cầu chính:

- xử lý microphone liên tục;
- STT và LLM không block audio capture;
- có lọc noise tùy chọn;
- có turn management và conversation history;
- hỗ trợ barge-in: user nói chen có thể hủy generation hiện tại;
- LLM backend có thể thay đổi độc lập với speech frontend;
- ưu tiên latency và RAM phù hợp Jetson Nano 4GB.

TTS chưa nằm trong runtime hiện tại; output chính là text.

## Runtime hiện tại

| Khối | Thành phần |
|---|---|
| Audio enhancement | GTCRN simple, optional |
| VAD | Silero VAD |
| Turn completion | Smart Turn, optional |
| STT | Whisper Tiny.en offline hoặc Zipformer streaming |
| LLM | Gemma 3 1B Q4_K_M |
| LLM runtime | llama.cpp / llama-server |
| Orchestration | Python workers + queues |
| Speech runtime | sherpa-onnx C++ |

Cấu hình mặc định hiện tại từ source/launcher:

```bash
VOICE_ASSISTANT_STT=whisper
VOICE_ASSISTANT_GTCRN=0
VOICE_ASSISTANT_SMART_TURN=0
VOICE_ASSISTANT_SPECULATIVE=0
VOICE_ASSISTANT_BARGE_IN=1
LLM_MODE=local
```

Benchmark đã chọn Zipformer 2023-06-21 làm primary streaming backend, nhưng runtime default vẫn là Whisper; đây là hai trạng thái khác nhau. Whisper là accuracy baseline/fallback, còn Zipformer 20M chỉ là experimental lightweight baseline.

Smart Turn đã tích hợp nhưng chỉ hỗ trợ Whisper và hiện để optional. Speculative turn đã implement nhưng **không khuyến nghị bật trên Jetson Nano ở trạng thái hiện tại**.

## Tài liệu

- [Architecture](docs/ARCHITECTURE.md) — kiến trúc và data flow của hệ thống.
- [Software Reference](docs/SOFTWARE_REFERENCE.md) — bản đồ source, deps, patches, tests và runtime contract.
- [Setup & Deployment](docs/SETUP_AND_DEPLOYMENT.md) — build/deploy local và remote.
- [STT Benchmark](docs/stt/BENCHMARK.md) — accepted STT/speech performance results.
- [STT Roadmap](docs/stt/ROADMAP.md) — roadmap nghiên cứu/tối ưu speech frontend.
- [LLM Benchmark](docs/llm/BENCHMARK.md) — accepted LLM performance evidence.
- [LLM Roadmap](docs/llm/ROADMAP.md) — kế hoạch benchmark/tối ưu LLM.
- [Benchmark Policy](benchmarks/README.md) — quy tắc code/input/output và HOST → Jetson workflow.
- [Project Context](PROJECT_CONTEXT.md) — trạng thái dev ngắn gọn để tiếp tục phát triển.

## Workflow

```text
HOST
  │
  ├── edit
  ├── test
  └── commit / push
        │
        ▼
      GitHub
        │
        ▼
      Jetson
        │
        ├── git pull
        ├── rebuild nếu cần
        └── hardware/runtime benchmark
```

**GitHub là source of truth.** Không chỉnh production source trực tiếp trên Jetson trừ khi đang debug runtime/hardware tạm thời.
