# Performance

Tài liệu này chỉ chứa latency, benchmark và bottleneck.

> Các số liệu đã ghi là historical accepted evidence. Raw benchmark implementation/result cũ không còn được sử dụng sau infrastructure reset. Measurement mới phải có tracked producer/procedure trong `benchmarks/` trước khi chạy trên Jetson.

## 1. Platform

```text
Jetson Nano 4GB
JetPack 4.6.1
CUDA 10.2
Maxwell cc 5.3
```

## 2. Timeline

```text
T0 speech end
 │
 ├── VAD ───────────► T1
 ├── STT ─────────────────► T2
 ├── Python ───────────────────► T3
 ├── LLM TTFT ─────────────────────► T4 first token
 └── generation ─────────────────────────► T5 last token
```

```text
T0→T1  VAD
T1→T2  STT
T3→T4  LLM TTFT
T0→T4  speech → first token
```

## 3. Whisper/GTCRN baseline samples

Config:

```text
GTCRN ON
Smart Turn OFF
Speculative OFF
```

Đây là measured config lịch sử, không phải default hiện tại. Source và launcher hiện default Whisper, GTCRN OFF, Smart Turn OFF và Speculative OFF.

Sample A:

```text
VAD             0.532 s
STT             1.406 s
LLM TTFT        0.557 s
Speech → First  2.496 s
```

Sample B:

```text
VAD             0.532 s
STT             1.077 s
LLM TTFT        0.468 s
Speech → First  2.077 s
```

Queue waits ở các run này chỉ ở mức sub-millisecond; model inference mới là bottleneck chính.

## 4. Smart Turn

Measured order:

```text
feature extraction  ~1.3 s
inference           ~0.32 s
hot total           ~1.65 s
```

Full runtime thường khoảng:

```text
~1.7–1.9 s / evaluation
```

Bottleneck chính là feature extraction.

## 5. Speculative

```text
Implemented : YES
Recommended : NO
Default     : OFF
```

Lý do observed:

```text
provisional work
   +
revision mới đến chậm
   ↓
response lặp / extra compute / unstable UX
```

## 6. Barge-in

Hardware test PASS:

```text
LLM đang generate
   ↓
user speech start
   ↓
generation cũ dừng
   ↓
new speech vẫn được STT/LLM
```

Đã xác nhận:

```text
speech-start bridge
cancellation
history protection
runtime recovery
```

## 7. Streaming Zipformer đã được chọn bằng benchmark

Zipformer 2023-06-21 với VAD-gated streaming và pre-roll 480 ms đã giảm idle ASR CPU từ khoảng 120.4% xuống 22.3%. Speech frontend latency trung bình tăng từ 0.520 s lên 0.570 s; live exact vẫn 2/3 trong phép đo được report. Chi tiết và nguồn log logical nằm trong `docs/stt-models/BENCHMARK.md`.

Kết quả này chọn backend streaming chính nhưng không tự đổi runtime default khỏi Whisper.

## 8. Current priorities

```text
1. speech/STT latency
2. Smart Turn feature extraction nếu bật
3. noise robustness
4. LLM generation length
```

## 9. Optimization direction

Smart Turn:

```text
Mic
 ├── VAD
 └── incremental feature extraction
           ↓
       feature cache
```

Mục tiêu: feature sẵn sàng trước endpoint.

Noise test nên dùng fixed WAV để A/B reproducible thay vì chỉ dựa vào mic live.

## 10. Benchmark rule

Khi A/B:

```text
same hardware
same model
same audio/prompt
same environment
change one variable only
```

Quy ước code/dataset/result và retention nằm trong `docs/BENCHMARKS.md`.
