# M02 — Báo cáo benchmark tiếng ồn: GTCRN OFF vs ON

## 1. Tổng quan

Sau M01, backend STT được cố định là:

```text
Zipformer 2023-06-21
```

M02 dùng cùng một bộ audio noisy để so sánh hai cấu hình:

```text
GTCRN OFF
vs
GTCRN ON
```

Pipeline benchmark:

```text
Noisy WAV
  ↓
ALSA Loopback
  ↓
[GTCRN OFF / ON]
  ↓
Silero VAD
  ↓
Streaming Zipformer 2023-06-21
  ↓
Transcript
```

Benchmark được chạy 3 lần độc lập:

```text
15 noisy WAV × 2 cấu hình × 3 lần
= 90 lượt xử lý
```

Ba full run sử dụng để tổng hợp:

```text
2026-08-27_21-25-45
2026-08-27_21-30-02
2026-08-27_21-32-59
```

Mục tiêu là kiểm tra GTCRN có giúp tăng độ chính xác nhận dạng tiếng nói trong môi trường có noise hay không, đồng thời đo chi phí về latency, CPU và RAM.

---

## 2. Cách chạy

Sau khi Jetson reboot, chuẩn bị ALSA Loopback:

```bash
cd ~/jetson-voice-assistant

./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh load
```

Chạy benchmark:

```bash
python3   benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py
```

Để giảm ảnh hưởng do thứ tự chạy, ba lần benchmark sử dụng thứ tự:

```text
Run 1: GTCRN OFF → GTCRN ON
Run 2: GTCRN ON  → GTCRN OFF
Run 3: GTCRN OFF → GTCRN ON
```

Kết quả mỗi run được lưu tại:

```text
logs/benchmarks/stt/M02_noise_gtcrn_ablation/<run-id>/
```

Dataset:

```text
data/stt/voicebank_demand/prepared_15/noisy/
```

Transcript decode được so sánh với transcript chuẩn trong:

```text
data/stt/voicebank_demand/prepared_15/manifest.tsv
```

Các metric chính:

- Corpus WER;
- Exact Match;
- VAD / STT / TOTAL latency;
- CPU;
- RAM;
- startup time.

---

## 3. Kết quả tổng hợp 3 lần chạy

### Accuracy và latency

| Metric | GTCRN OFF | GTCRN ON | Chênh lệch ON - OFF |
|---|---:|---:|---:|
| Corpus WER | **6.60%** | 8.81% | **+2.20 điểm %** |
| Exact Match | **35/45** | 30/45 | **-5 câu** |
| VAD mean | **0.500 s** | 0.532 s | +32 ms |
| STT mean | **0.062 s** | 0.067 s | +5 ms |
| TOTAL mean | **0.562 s** | 0.599 s | **+37 ms** |
| TOTAL p95 | **0.657 s** | 0.693 s | **+36 ms** |
| Wall mean | **0.321 s** | 0.385 s | +64 ms |

### Tài nguyên

| Metric | GTCRN OFF | GTCRN ON | Chênh lệch |
|---|---:|---:|---:|
| ONNX footprint | 340.9 MB | 341.4 MB | +0.5 MB |
| Startup → READY | **9.58 s** | 9.78 s | +0.19 s |
| Idle CPU | **17.8%** | 44.0% | **+26.2 pp** |
| Active CPU mean | **98.8%** | 133.5% | **+34.8 pp** |
| Peak RSS | 766.0 MB | 766.1 MB | gần như không đổi |

### So sánh theo từng sample

Trong tổng cộng 45 cặp kết quả:

```text
GTCRN cải thiện :  3 / 45
GTCRN làm xấu   :  6 / 45
Không đổi       : 36 / 45
```

Kết quả từng run:

| Run | WER OFF | WER ON | Exact OFF | Exact ON |
|---|---:|---:|---:|---:|
| 21-25-45 | **6.60%** | 11.32% | **12/15** | 8/15 |
| 21-30-02 | **5.66%** | 7.55% | **12/15** | 11/15 |
| 21-32-59 | 7.55% | 7.55% | 11/15 | 11/15 |

Không có run nào GTCRN ON cho WER tốt hơn GTCRN OFF.

---

## 4. Đánh giá

Với bộ VoiceBank noisy hiện tại, GTCRN chưa mang lại lợi ích cho STT.

Khi bật GTCRN:

- WER trung bình tăng từ **6.60% lên 8.81%**;
- Exact Match giảm từ **35/45 xuống 30/45**;
- TOTAL latency tăng khoảng **37 ms**;
- Idle CPU tăng khoảng **26 điểm phần trăm**;
- Active CPU tăng khoảng **35 điểm phần trăm**;
- RAM gần như không thay đổi.

Đặc biệt, phần lớn sample không thay đổi kết quả nhận dạng, trong khi số sample bị làm xấu nhiều hơn số sample được cải thiện.

Vì vậy với dataset và pipeline hiện tại:

```text
GTCRN OFF tốt hơn GTCRN ON
```

xét cả accuracy lẫn chi phí tính toán.

---

## 5. Kết luận

Kết quả M02:

```text
STT backend : Zipformer 2023-06-21
GTCRN       : OFF
```

GTCRN chưa nên được bật trong cấu hình production hiện tại vì:

- không cải thiện độ chính xác trên bộ noisy đang test;
- có xu hướng làm WER xấu hơn;
- tăng đáng kể CPU;
- tăng thêm latency.

Tuy nhiên, kết quả này chỉ áp dụng cho mức noise của bộ dữ liệu hiện tại. Zipformer khi không có enhancement vẫn đạt WER khoảng 5.7–7.6%, cho thấy bộ noisy này có thể chưa đủ khó để đánh giá đầy đủ lợi ích của GTCRN.

Bước tiếp theo nên là:

```text
M03_noise_snr_stress
```

với noise mạnh hơn hoặc các mức SNR được kiểm soát để kiểm tra xem GTCRN có phát huy tác dụng trong điều kiện khó hơn hay không.
