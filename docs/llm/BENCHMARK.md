# Benchmark LLM — Jetson Voice Assistant

> **Trạng thái:** historical summary. Benchmark LLM mới chưa được chạy lại theo benchmark infrastructure mới.
>
> Từ thời điểm policy mới có hiệu lực, mọi benchmark LLM phải có tracked source/procedure dưới `benchmarks/llm/` trên HOST trước khi chạy trên Jetson.

## 1. Runtime hiện tại

Local runtime hiện tại:

```text
Model   : Gemma 3 1B Q4_K_M
Runtime : llama.cpp / llama-server
URL     : http://127.0.0.1:8080/v1/chat/completions
Context : 2048
GPU     : -ngl 99
Threads : -t 2
```

Python hiện dùng:

```text
max_tokens   = 128
temperature  = 0.5
history      = tối đa 6 user/assistant turns
```

Remote backend cũng được hỗ trợ qua OpenAI-compatible endpoint; deployment Windows thử nghiệm nằm trong `docs/SETUP_AND_DEPLOYMENT.md`.

## 2. Evidence latency lịch sử

Hai sample full-pipeline lịch sử với:

```text
GTCRN ON
Smart Turn OFF
Speculative OFF
```

cho LLM TTFT:

| Sample | LLM TTFT | Speech → first token |
|---|---:|---:|
| A | 0.557 s | 2.496 s |
| B | 0.468 s | 2.077 s |

Các sample này chỉ cho thấy TTFT trong full pipeline lịch sử; chúng **không thay thế một LLM-only benchmark reproducible**.

Old one-off LLM latency runner/result đã được loại khỏi working tree khi reset benchmark infrastructure. Nếu cần baseline LLM mới, phải đo lại từ đầu bằng runner tracked.

## 3. Những gì chưa được benchmark lại

Hiện chưa có benchmark mới, reproducible cho:

- TTFT theo số turn/history;
- prompt/context scaling;
- generation throughput;
- CPU threads;
- context size;
- GPU offload;
- local vs remote LLM;
- RAM/VRAM theo workload;
- quality vs latency.

Các hạng mục này được quy hoạch trong `docs/llm/ROADMAP.md`.

## 4. Quy tắc benchmark mới

```text
HOST
benchmarks/llm/...
→ review/test
→ commit + push

JETSON / remote target
→ git pull hoặc dùng exact tracked procedure
→ run
→ logs/benchmarks/llm/<run-id>/

HOST
→ review result
→ cập nhật accepted conclusion tại file này
```

Không dùng shell history hoặc script tạm trên Jetson làm official benchmark.

## 5. Kết luận hiện tại

```text
LLM backend abstraction : implemented
Local llama.cpp          : implemented
Remote compatible backend: implemented
Reproducible LLM benchmark mới: chưa chạy
LLM optimization roadmap : có, hiện chưa phải ưu tiên trước STT noise robustness
```

Khi benchmark LLM được làm lại, file này sẽ là nơi giữ **accepted results**; raw output vẫn nằm dưới `logs/benchmarks/llm/`.
