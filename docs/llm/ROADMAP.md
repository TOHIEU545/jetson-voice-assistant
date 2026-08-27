# LLM Optimization Roadmap — Phase 1 → 5

**Project:** `jetson-voice-assistant`
**Target:** Jetson Nano 4GB
**Branch:** `dev`
**Scope:** tối ưu LLM sau khi speech/STT baseline đủ ổn để đo tách biệt.
**Không mở rộng sang Speaker Verification, TTS, Smart Turn, GTCRN hay Speculative trong Phase 1–5 này.**

---

## 0. Trạng thái thực tế trước khi bắt đầu

### Speech frontend đã chốt

Theo `docs/stt/BENCHMARK.md`:

```text
Primary STT:
Zipformer 2023-06-21

Architecture:
VAD-gated streaming

Pre-roll:
480 ms
```

Kết quả chính:

| Metric | Before gating | After gating |
|---|---:|---:|
| Idle ASR CPU | 120.4% | 22.3% |
| VAD + STT avg | 0.520 s | 0.570 s |
| Live exact | 2/3 | 2/3 |

Speech frontend hiện không phải mục tiêu tối ưu chính trong Phase 1–5.

### LLM runtime hiện tại

Từ `scripts/llama_server.sh`:

```text
Model   : gemma-3-1b-it-Q4_K_M.gguf
Server  : llama.cpp
URL     : http://127.0.0.1:8080
Context : 2048
GPU     : -ngl 99
Threads : -t 2
```

Từ `deps/llama-server.manifest`:

```text
llama.cpp version: 5050 (23106f94)
Jetson GPU       : Tegra X1, compute capability 5.3
```

### History hiện tại

`app/config.py`:

```python
MAX_CONVERSATION_TURNS = 6
```

`ConversationManager` hiện đã có **bounded history theo số turn**.

Điều này rất quan trọng: Phase 1 không được giả định rằng history đang tăng vô hạn. Cần benchmark để biết giới hạn 6 turn hiện tại đã tốt chưa, rồi mới quyết định có đổi policy hay không.

### System prompt hiện tại

`INITIAL_HISTORY` trong `app/config.py` chứa một system prompt tương đối dài, chuyên cho Embedded.

System prompt này được gửi lại cùng history ở mỗi request nên sẽ được xem xét ở Phase 4, không chỉnh ngay từ Phase 1.

### Điểm config cần lưu ý

`docs/stt/BENCHMARK.md` đã chọn `zipformer_2023_06_21` làm primary STT, nhưng `scripts/run_voice_assistant.sh` vẫn default:

```bash
VOICE_ASSISTANT_STT="whisper"
```

Tài liệu đã ghi rõ discrepancy này. Không tự ý đổi runtime default trong benchmark LLM vì như vậy sẽ thay thêm một biến.

---

# Nguyên tắc làm việc bắt buộc

## Development workflow

**Chỉ phát triển source trên HOST. Không sửa source trực tiếp trên Jetson.**

```text
HOST
~/jetson-voice-assistant
        ↓
edit source / tests / scripts / docs
        ↓
HOST syntax + unit tests
        ↓
git diff --check
        ↓
commit + push branch dev
        ↓
GitHub = source of truth
        ↓
JETSON
~/jetson-voice-assistant
        ↓
git pull origin dev
        ↓
runtime / hardware benchmark
```

Jetson chỉ dùng cho:

```text
runtime test
hardware test
benchmark
resource measurement
log generation
```

Không dùng Jetson để chỉnh tracked source rồi giữ thay đổi lâu dài.

## Git policy

Commit:

```text
app/
scripts/
tests/
docs/
patches/
deps/
config source
benchmark tooling
benchmark fixture
```

Không commit:

```text
models/
runtime builds/
*.onnx
*.gguf
conversation runtime logs
benchmark runtime logs
cache
temporary artifacts
```

## Benchmark discipline

Mỗi benchmark chỉ thay **một biến chính**.

Ví dụ:

```text
ĐÚNG:
same model + same prompt + same history
chỉ đổi n_threads

SAI:
đổi n_threads + history + system prompt cùng lúc
```

Mỗi kết quả phải trace được về:

```text
Git commit
runtime config
fixture
benchmark command
Jetson log
summary
```

Không tối ưu dựa trên cảm giác.

---

# PHASE 1 — History Scaling Benchmark

## Mục tiêu

Đo chính xác history ảnh hưởng đến TTFT và generation như thế nào trên Jetson.

Không dùng microphone trong benchmark chính.

Lý do:

```text
Mic / VAD / STT
→ tạo thêm biến nhiễu

History benchmark cần cô lập:
text → LLM
```

## Test matrix

Dùng một conversation fixture cố định tối thiểu 20 turn.

Cùng một final prompt cho mọi case.

| Case | History trước final prompt |
|---|---:|
| H0 | 0 turn |
| H5 | 5 turn |
| H10 | 10 turn |
| H20 | 20 turn |

Mỗi case chạy nhiều lần, tối thiểu:

```text
1 warm-up run
+
3 measured runs
```

Nếu thời gian cho phép:

```text
5 measured runs
```

## Dữ liệu phải giữ cố định

```text
LLM model
llama.cpp config
system prompt
final user prompt
max_tokens
temperature
fixture content
```

Chỉ thay số lượng history.

## Metrics

Bắt buộc:

```text
history turns
request size / prompt token count nếu runtime hỗ trợ đo đáng tin cậy
TTFT
generation time
total time
output length
RSS
available RAM
swap
```

Nếu chưa có cách lấy **token count thực** từ runtime/tokenizer thì không được giả `word count = token count`.

Có thể ghi:

```text
prompt token count: unavailable
```

cho đến khi xác minh được API/runtime hỗ trợ.

## Source/tooling đề xuất

Old `tests/latency/benchmark_llm_latency.py` đã bị xóa trong benchmark infrastructure reset. Không khôi phục hoặc mở rộng runner cũ.

Tạo benchmark riêng, ví dụ:

```text
benchmarks/llm/history_scaling/benchmark_history_scaling.py
benchmarks/llm/history_scaling/fixtures/history_scaling.json
```

Runtime output trên Jetson:

```text
logs/benchmarks/llm/history_scaling/
```

Ví dụ:

```text
history_0.jsonl
history_5.jsonl
history_10.jsonl
history_20.jsonl
summary.txt
```

Các log này là runtime artifact, không commit.

## Exit criteria

Phase 1 chỉ PASS khi trả lời được:

```text
TTFT tăng bao nhiêu từ H0 → H5 → H10 → H20?
Generation speed có đổi đáng kể không?
RAM/swap có tăng không?
Current max_turns=6 có đang nằm trong vùng hợp lý không?
```

Không đổi history policy trước khi có kết quả này.

---

# PHASE 2 — History Policy

## Mục tiêu

Chọn policy history dựa trên dữ liệu Phase 1.

Current baseline:

```python
MAX_CONVERSATION_TURNS = 6
```

Không mặc định coi nó là sai.

## Candidate policies

Ưu tiên từ đơn giản đến phức tạp:

| Policy | Mô tả |
|---|---|
| Current turn window | Giữ 6 turn như hiện tại |
| Smaller/larger turn window | Chọn N turn dựa trên benchmark |
| Token-budget history | Giữ history theo token budget nếu có cách đếm token đáng tin cậy |
| Summary history | Chưa làm trừ khi các policy đơn giản không đáp ứng |

### Nguyên tắc

Nếu current 6-turn window:

```text
TTFT ổn
RAM ổn
context đủ dùng
```

thì **không cần đổi chỉ để có thêm code**.

Nếu history làm TTFT tăng đáng kể thì mới tối ưu.

## Yêu cầu implementation nếu đổi policy

- Không phá `ConversationManager` lifecycle.
- Failed/aborted turn không được lọt vào history.
- Revision/barge-in behavior không đổi.
- System message luôn được giữ.
- User/assistant pair phải được loại cùng nhau.
- Có unit test cho boundary.
- Policy phải có config rõ ràng.
- Không hard-code benchmark-only behavior vào production path.

## Test bắt buộc

Existing:

```text
tests/conversation/test_conversation_manager.py
```

Phải tiếp tục PASS.

Nếu thêm token budget/policy mới thì thêm test riêng.

## Exit criteria

Có một policy được chọn và ghi rõ:

```text
policy
limit
lý do
benchmark evidence
```

Sau đó chạy lại chính benchmark Phase 1 để xác nhận improvement/regression.

---

# PHASE 3 — llama.cpp Runtime Tuning

## Mục tiêu

Giảm TTFT và/hoặc tăng generation throughput mà không gây RAM/swap regression.

Baseline hiện tại:

```text
-c 2048
-ngl 99
-t 2
```

## Bước đầu tiên

Trên Jetson chỉ **đọc runtime capability**, không sửa source:

```bash
runtime/llama.cpp/bin/llama-server --help
```

Không giả định flag nào tồn tại ở llama.cpp version hiện tại.

## Thứ tự tune

Chỉ đổi một nhóm biến một lần.

### 3A. CPU threads

Baseline:

```text
-t 2
```

Test các giá trị hợp lý mà runtime hỗ trợ, ví dụ:

```text
2
3
4
```

Không mặc định nhiều thread hơn sẽ nhanh hơn.

### 3B. Context size

Baseline:

```text
-c 2048
```

Chỉ giảm nếu Phase 1/2 chứng minh context thực tế không cần 2048 và việc giảm có lợi về RAM/runtime.

### 3C. GPU offload

Baseline:

```text
-ngl 99
```

Đo current full-offload trước.

Chỉ thử cấu hình khác nếu có lý do rõ ràng; không hy sinh ổn định/RAM chỉ để giảm vài ms.

### 3D. Batch/prefill settings

Chỉ test nếu `llama-server --help` của version hiện tại xác nhận option tương ứng.

Không copy flag từ llama.cpp version mới trên mạng rồi áp dụng mù.

## Benchmark input

Dùng fixture cố định từ Phase 1.

Có ít nhất hai độ dài:

```text
short history
selected production history
```

Metrics:

```text
TTFT
generation time
throughput
RSS
available RAM
swap
server stability
```

## Quy tắc chọn config

Không chọn config chỉ vì TTFT thấp nhất.

Ưu tiên:

```text
no crash
no heavy swap
stable memory
good TTFT
good generation speed
```

Jetson Nano 4GB cần margin RAM.

## Exit criteria

Chốt một `llama_server.sh` runtime config có benchmark chứng minh tốt hơn hoặc bằng baseline.

Nếu không có config nào cải thiện rõ:

```text
giữ baseline
```

và ghi kết luận.

---

# PHASE 4 — Warm-up + System Prompt Optimization

Phase này chia thành 2 phép thử riêng.

Không thay cả hai cùng lúc.

## 4A. LLM Warm-up

### Mục tiêu

Kiểm tra request thật đầu tiên có bị startup/warm-up penalty hay không.

So sánh:

| Case | Startup |
|---|---|
| A | Server ready → request thật |
| B | Server ready → dummy short inference → request thật |

Đo:

```text
first real request TTFT
RSS
time added to startup
```

Chỉ giữ warm-up nếu lợi ích lặp lại được.

Không được kết luận chỉ từ một turn bất thường.

## 4B. System prompt

Current prompt trong `INITIAL_HISTORY` cần giữ behavior:

```text
voice assistant
embedded domain
short/natural answer
technical correctness
ask repeat on corrupted STT
```

Tạo:

```text
baseline prompt
candidate compact prompt
```

Cùng một evaluation fixture.

So sánh:

```text
prompt size
TTFT
answer quality
instruction following
```

Không rút prompt nếu model bắt đầu:

```text
trả lời dài dòng
đoán transcript lỗi
mất embedded specialization
```

## Exit criteria

Chốt độc lập:

```text
warm-up: ON/OFF
system prompt: baseline/compact
```

Mỗi quyết định phải có benchmark riêng.

---

# PHASE 5 — Full Conversation Scaling Validation

## Mục tiêu

Xác nhận các tối ưu Phase 1–4 thực sự tốt khi quay lại full pipeline.

## 5A. LLM-only regression

Chạy lại fixture:

```text
H0
H5
H10
H20
```

với config cuối.

So sánh với Phase 1 baseline.

Mục tiêu:

```text
TTFT không tăng bất hợp lý
RAM/swap ổn
generation ổn
```

## 5B. Voice full-pipeline validation

Sau khi LLM-only PASS mới dùng mic.

Architecture:

```text
Mic
→ Silero VAD
→ 480 ms pre-roll
→ Zipformer 2023-06-21
→ selected history policy
→ optimized llama.cpp
→ streamed text
```

Test một session thực khoảng:

```text
10 turn
```

Không cần nói cùng một câu 10 lần.

Đây là stability/behavior validation, không phải STT accuracy benchmark.

Theo dõi:

```text
Speech runtime ready
STT transcript
LLM TTFT
Speech→First
RAM
swap
crash
barge-in regression
history behavior
```

## Exit criteria

Phase 5 PASS khi:

```text
10-turn session chạy ổn
history không tăng vô hạn
TTFT không drift bất thường
không crash
không swap tăng mất kiểm soát
không regression STT
không regression barge-in
```

Sau đó mới quyết định roadmap tiếp:

```text
technical vocabulary
GTCRN A/B
Smart Turn A/B
speculative latency
speaker verification
TTS
```

Các mục trên **không thuộc Phase 1–5 hiện tại**.

---

# Deliverables sau Phase 1–5

Source/tooling:

```text
benchmarks/llm/history_scaling/benchmark_history_scaling.py
benchmarks/llm/history_scaling/fixtures/history_scaling.json
```

Có thể thêm source/config khác nếu benchmark chứng minh cần.

Docs:

```text
docs/llm/ROADMAP.md
docs/llm-models/BENCHMARK.md      # nếu cần report riêng
PROJECT_CONTEXT.md                # cập nhật sau khi chốt
```

Jetson runtime logs:

```text
logs/benchmarks/llm/history_scaling/
logs/benchmarks/llm/runtime_tuning/
logs/benchmarks/llm/warmup/
logs/benchmarks/llm/full_conversation/
```

Runtime logs không commit.

---

# Trình tự thực hiện

```text
PHASE 1
History scaling benchmark
        ↓
PHASE 2
History policy decision
        ↓
PHASE 3
llama.cpp runtime tuning
        ↓
PHASE 4
Warm-up
+
system prompt optimization
        ↓
PHASE 5
LLM-only regression
+
10-turn voice validation
```

Mỗi Phase phải:

```text
HOST implement/test
→ commit/push dev
→ Jetson pull
→ Jetson benchmark
→ lưu evidence
→ kết luận
→ mới sang Phase tiếp theo
```
