# Benchmark STT — Jetson Voice Assistant

**Thiết bị:** Jetson Nano 4GB  
**Project:** `jetson-voice-assistant`  
**Thời gian benchmark:** 2026-08-26 → 2026-08-27

## 1. Mục tiêu

Benchmark tập trung vào hai vấn đề:

1. So sánh ba backend STT để chọn model phù hợp cho pipeline.
2. So sánh kiến trúc streaming trước và sau khi thêm VAD-gated decode + pre-roll.

Báo cáo này **không dùng latency giữa từng turn LLM để so sánh**, vì mục tiêu chính là STT và cơ chế streaming.

---

## 2. Các backend STT

| Backend | Kiểu xử lý | Vai trò |
|---|---|---|
| Whisper Tiny.en | Offline | Accuracy baseline / fallback |
| Zipformer 20M — 2023-02-17 | Streaming | Lightweight / speed baseline |
| Zipformer — 2023-06-21 | Streaming | Primary streaming candidate |

Benchmark cố định:

```text
3 model
× 3 điều kiện nhiễu
× 3 câu
= 27 lượt chạy
```

Nguồn dữ liệu trên Jetson:

```text
logs/benchmarks/stt/reference_audio/
logs/benchmarks/stt/reference_segments/
logs/benchmarks/stt/reference_results/
```

File tổng hợp:

```text
logs/benchmarks/stt/reference_results/summary.tsv
```

---

## 3. So sánh ba model STT

| Model | Exact | Avg WER | Avg RTF | Max RSS | Nhận xét |
|---|---:|---:|---:|---:|---|
| **Whisper Tiny.en** | **6/9** | **6.06%** | 0.668 | 355.4 MB | Chính xác nhất, RAM vừa phải, nhưng xử lý offline |
| **Zipformer 20M** | 0/9 | 52.41% | **0.267** | **218.8 MB** | Nhanh và nhẹ nhất nhưng accuracy chưa đạt |
| **Zipformer 2023-06-21** | 5/9 | 6.88% | 0.613 | 760.8 MB | Accuracy gần Whisper và hỗ trợ true streaming |

### Đánh giá theo tiêu chí

| Tiêu chí | Whisper Tiny.en | Zipformer 20M | Zipformer 2023-06-21 |
|---|---|---|---|
| Accuracy | **Tốt nhất** | Kém | Gần Whisper |
| RAM | Trung bình | **Thấp nhất** | Cao nhất |
| RTF | Chậm hơn | **Nhanh nhất** | Gần Whisper |
| True streaming | Không | Có | **Có** |
| Phù hợp backend chính | Fallback | Không | **Có** |

### Vấn đề từ vựng kỹ thuật

Cả ba model đều có xu hướng nhận:

```text
UART -> "you are"
```

Đây được xem là vấn đề technical vocabulary / context bias, không phải lỗi của cơ chế streaming.

---

## 4. Quyết định model

| Backend | Trạng thái |
|---|---|
| Whisper Tiny.en | Stable baseline / fallback |
| Zipformer 20M | Experimental lightweight / speed baseline |
| **Zipformer 2023-06-21** | **Primary streaming backend** |

Cấu hình launcher vẫn giữ:

```bash
VOICE_ASSISTANT_STT="whisper"
VOICE_ASSISTANT_STT="zipformer_20m"
VOICE_ASSISTANT_STT="zipformer_2023_06_21"
```

---

# 5. Kiến trúc streaming ban đầu

Ban đầu Zipformer nhận PCM liên tục, kể cả khi người dùng không nói.

```text
Mic
  ↓
VAD
  ↓
Toàn bộ PCM
  ↓
stream_queue
  ↓
Zipformer OnlineRecognizer
```

### Bản chất

| Trạng thái | Cơ chế cũ |
|---|---|
| Có speech | Zipformer decode |
| Không có speech | Zipformer vẫn decode |
| Silence / background noise | Vẫn feed vào recognizer |
| Idle | OnlineRecognizer vẫn hoạt động |

Hệ quả là CPU idle cao mặc dù assistant chỉ đang chờ người dùng nói.

Baseline đo trên Jetson:

| Metric | BEFORE gating |
|---|---:|
| Stable idle ASR CPU avg | **120.4%** |
| Idle CPU range | 113.9% – 126.0% |
| ASR RAM | ~785 MB |
| Available RAM | ~1.0 GB |
| Swap used | ~82 MB |

Nguồn log:

```text
logs/benchmarks/stt/live_baseline_before_gating/
```

Các file chính:

```text
summary.txt
idle_cpu_top.txt
idle_memory.txt
2026-08-26_09-47-41.txt
full_pipeline_latency_2026-08-26_09-47-41.jsonl
python_llm_latency_2026-08-26_09-47-41.jsonl
```

---

# 6. Kiến trúc mới: VAD-gated streaming

Mục tiêu là giữ true streaming nhưng không để Zipformer decode liên tục khi idle.

```text
Mic PCM
  ↓
Silero VAD
  ↓
┌──────────────────────────┐
│ Không có speech          │
│ - giữ rolling pre-roll   │
│ - không feed Zipformer   │
└──────────────────────────┘
  ↓ speech detected
┌──────────────────────────┐
│ Có speech                │
│ - flush pre-roll         │
│ - feed PCM realtime      │
│ - Zipformer decode       │
└──────────────────────────┘
  ↓
Endpoint
  ↓
Final transcript
```

### So sánh kiến trúc

| Thành phần | BEFORE | AFTER |
|---|---|---|
| Mic capture | Liên tục | Liên tục |
| VAD | Liên tục | Liên tục |
| Pre-roll | Không | **480 ms rolling buffer** |
| Zipformer khi idle | **Decode liên tục** | **Không decode** |
| Khi phát hiện speech | Đã decode từ trước | Flush pre-roll rồi bắt đầu decode |
| Khi speech kết thúc | Finalize | Finalize rồi quay lại idle |

Bản chất của thay đổi:

```text
BEFORE:
VAD chạy + Zipformer chạy liên tục

AFTER:
VAD chạy liên tục
Zipformer chỉ chạy khi có speech
```

---

## 7. Tuning pre-roll

VAD cần một khoảng thời gian ngắn mới xác nhận được speech. Nếu chỉ bắt đầu feed STT sau thời điểm đó thì có thể mất đầu câu.

| Pre-roll | Kết quả | Quyết định |
|---:|---|---|
| 320 ms | Có hiện tượng clipping / mất đầu câu | Reject |
| **480 ms** | Không thấy mất đầu câu trong live test cuối | **Selected** |

Cấu hình hiện tại:

```text
pre-roll = 480 ms
```

---

# 8. So sánh BEFORE vs AFTER speech gating

## 8.1 Tài nguyên khi idle

| Metric | BEFORE | AFTER | Thay đổi |
|---|---:|---:|---:|
| Idle ASR CPU avg | **120.4%** | **22.3%** | **-81.5%** |
| Idle CPU range | 113.9–126.0% | 20.5–23.4% | Giảm mạnh |
| ASR RAM | ~785 MB | ~760 MiB | Gần như không đổi |
| Swap used | ~82 MB | 82 MB | Không đổi |

Kết quả chính:

```text
CPU idle:
120.4%
  ↓
22.3%

Giảm khoảng:
81.5%
```

---

## 8.2 Speech frontend latency

Chỉ so sánh phần VAD + STT, không dùng thời gian LLM giữa các turn.

| Metric | BEFORE | AFTER | Chênh lệch |
|---|---:|---:|---:|
| VAD avg | 0.500 s | 0.500 s | 0 |
| STT avg | 0.020 s | 0.070 s | +0.050 s |
| VAD + STT avg | **0.520 s** | **0.570 s** | **+0.050 s** |

Trade-off:

```text
+ khoảng 50 ms speech frontend latency
đổi lại
- khoảng 81.5% idle CPU
```

---

## 8.3 Accuracy live

| Metric | BEFORE | AFTER |
|---|---:|---:|
| Exact transcript | 2/3 | 2/3 |
| Lỗi quan sát được | `WANT -> WENT` | `TODAY -> TO DAY` |
| Mất đầu câu | Không dùng gating | **Không thấy với 480 ms pre-roll** |

Kết luận:

```text
Accuracy không giảm rõ rệt sau speech gating.
Không thấy clipping đầu câu với pre-roll 480 ms.
```

---

# 9. Nguồn log để trace trên Jetson

Root benchmark STT:

```text
~/jetson-voice-assistant/logs/benchmarks/stt/
```

## Fixed-WAV benchmark

| Path | Nội dung |
|---|---|
| `reference_audio/` | Audio gốc |
| `reference_segments/` | Speech segment sau VAD + padding |
| `reference_results/` | Kết quả benchmark ba model |
| `reference_results/summary.tsv` | Bảng tổng hợp |

## BEFORE speech gating

```text
logs/benchmarks/stt/live_baseline_before_gating/
```

| File | Nội dung |
|---|---|
| `summary.txt` | Tổng hợp baseline |
| `idle_cpu_top.txt` | CPU idle samples |
| `idle_memory.txt` | Process RSS + system RAM + swap |
| `2026-08-26_09-47-41.txt` | Transcript live |
| `full_pipeline_latency_2026-08-26_09-47-41.jsonl` | VAD/STT/full-pipeline timing |
| `python_llm_latency_2026-08-26_09-47-41.jsonl` | Python/LLM timing |

## AFTER speech gating

```text
logs/benchmarks/stt/live_after_gating/
```

| File | Nội dung |
|---|---|
| `summary.txt` | Tổng hợp sau gating |
| `idle_cpu_top.txt` | 15 stable CPU samples |
| `idle_memory.txt` | Process RSS + system RAM + swap |
| `2026-08-27_01-16-54.txt` | Transcript live |
| `full_pipeline_latency_2026-08-27_01-16-54.jsonl` | VAD/STT/full-pipeline timing |
| `python_llm_latency_2026-08-27_01-16-54.jsonl` | Python/LLM timing |

---

# 10. Kết luận

## Model

| Model | Kết luận |
|---|---|
| Whisper Tiny.en | Giữ làm accuracy baseline / fallback |
| Zipformer 20M | Giữ làm lightweight / speed baseline |
| **Zipformer 2023-06-21** | **Chọn làm backend streaming chính** |

## Streaming architecture

| Kiến trúc | CPU idle | Latency STT | Accuracy | Kết luận |
|---|---:|---:|---|---|
| Continuous streaming | ~120.4% | Thấp nhất | Tốt | Không phù hợp do idle CPU cao |
| **VAD-gated + 480 ms pre-roll** | **~22.3%** | +~50 ms | Tương đương | **Được chọn** |

Cấu hình cuối:

```text
Mic
-> Silero VAD
-> 480 ms rolling pre-roll
-> Zipformer 2023-06-21
   chỉ decode khi speech active
-> final transcript
-> LLM
```

Kết quả chính:

```text
Primary STT:
Zipformer 2023-06-21

Streaming architecture:
VAD-gated streaming

Pre-roll:
480 ms

Idle CPU:
120.4% -> 22.3%

CPU reduction:
~81.5%

Speech frontend latency:
+~50 ms

RAM:
gần như không đổi

Live accuracy:
2/3 -> 2/3

Beginning-of-speech:
không thấy clipping với 480 ms pre-roll
```
