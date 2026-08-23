# Performance

Tài liệu này chỉ chứa latency, benchmark và bottleneck.

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

## 3. Stable baseline samples

Config:

```text
GTCRN ON
Smart Turn OFF
Speculative OFF
```

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

## 7. Current priorities

```text
1. speech/STT latency
2. Smart Turn feature extraction nếu bật
3. noise robustness
4. LLM generation length
```

## 8. Optimization direction

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

## 9. Benchmark rule

Khi A/B:

```text
same hardware
same model
same audio/prompt
same environment
change one variable only
```
