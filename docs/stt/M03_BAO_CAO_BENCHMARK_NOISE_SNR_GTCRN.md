# M03 — Báo cáo benchmark Controlled SNR: GTCRN OFF vs ON

## 1. Tổng quan

Sau M01 và M02, backend STT tiếp tục được cố định là:

```text
Zipformer 2023-06-21
```

M03 được thực hiện để kiểm tra GTCRN trong điều kiện noise có mức độ được kiểm soát rõ ràng bằng SNR.

Speech sạch lấy từ 15 mẫu VoiceBank đã dùng trong các milestone trước. Noise lấy từ:

```text
MS-SNSD
AirConditioner_1.wav
```

Sau đó speech và noise được trộn ở 4 mức:

```text
20 dB
10 dB
 5 dB
 0 dB
```

Dataset sinh ra:

```text
data/stt/ms_snsd/mixed/
└── voicebank_prepared_15/
    └── airconditioner/
        ├── snr20/
        ├── snr10/
        ├── snr05/
        ├── snr00/
        └── manifest.tsv
```

Pipeline benchmark:

```text
VoiceBank clean
  +
MS-SNSD AirConditioner noise
  ↓
Controlled SNR WAV
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
15 WAV × 4 SNR × 2 cấu hình × 3 run
= 360 lượt xử lý
```

Ba full run sử dụng để tổng hợp:

```text
2026-09-02_15-51-36
2026-09-02_16-01-45
2026-09-02_16-09-38
```

Mục tiêu là xác định GTCRN có bắt đầu cải thiện STT khi noise tăng mạnh hay không, đồng thời đo chi phí về latency, CPU và RAM.

---

## 2. Cách chạy benchmark

### Chuẩn bị ALSA Loopback

Sau khi Jetson reboot:

```bash
cd ~/jetson-voice-assistant

./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh load
```

Có thể kiểm tra trạng thái:

```bash
./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh status
```

### Validate dataset

```bash
python3 \
  benchmarks/stt/M03_noise_snr_stress/benchmark_noise_snr.py \
  --validate-dataset
```

Kỳ vọng:

```text
Samples : 60

20 dB : 15
10 dB : 15
 5 dB : 15
 0 dB : 15
```

### Chạy full benchmark

Run 1:

```bash
python3 \
  benchmarks/stt/M03_noise_snr_stress/benchmark_noise_snr.py \
  --order gtcrn_off,gtcrn_on
```

Run 2 đảo thứ tự để giảm ảnh hưởng do order/cache/thermal:

```bash
python3 \
  benchmarks/stt/M03_noise_snr_stress/benchmark_noise_snr.py \
  --order gtcrn_on,gtcrn_off
```

Run 3:

```bash
python3 \
  benchmarks/stt/M03_noise_snr_stress/benchmark_noise_snr.py \
  --order gtcrn_off,gtcrn_on
```

Kết quả mỗi run được lưu tại:

```text
logs/benchmarks/stt/M03_noise_snr_stress/<run-id>/
```

Các file chính:

```text
metadata.json
samples.jsonl
summary.json
summary.md
paired_effect.json
gtcrn_off/
gtcrn_on/
```

Các feature được giữ cố định:

```text
STT         : Zipformer 2023-06-21
Smart Turn  : OFF
Speculative : OFF
Barge-in    : ON
Input       : ALSA Loopback
```

---

## 3. Kết quả tổng hợp 3 lần chạy

### Accuracy theo từng mức SNR

Mỗi mức SNR có:

```text
15 samples × 3 run = 45 kết quả / cấu hình
```

| SNR | WER OFF | WER ON | Chênh lệch ON - OFF | Exact OFF | Exact ON |
|---:|---:|---:|---:|---:|---:|
| 20 dB | **7.23%** | 8.81% | +1.57 điểm % | **36/45** | 31/45 |
| 10 dB | **7.86%** | 9.75% | +1.89 điểm % | **36/45** | 31/45 |
| 5 dB | **7.23%** | 10.69% | +3.46 điểm % | **36/45** | 32/45 |
| 0 dB | **9.43%** | 10.06% | +0.63 điểm % | **36/45** | 32/45 |

GTCRN ON không cho WER tốt hơn GTCRN OFF ở bất kỳ mức SNR nào khi tổng hợp cả 3 run.

Ở `0 dB`, run đầu tiên từng cho kết quả:

```text
OFF : 9.43%
ON  : 7.55%
```

nhưng hiệu quả này không lặp lại ở hai run sau. Khi tổng hợp đủ 3 run:

```text
OFF : 9.43%
ON  : 10.06%
```

Do đó chưa có bằng chứng ổn định rằng GTCRN bắt đầu có lợi tại `0 dB`.

### Accuracy và latency tổng thể

Tổng cộng cho mỗi cấu hình:

```text
60 samples/run × 3 run
= 180 lượt
```

| Metric | GTCRN OFF | GTCRN ON | Chênh lệch ON - OFF |
|---|---:|---:|---:|
| Corpus WER | **7.94%** | 9.83% | **+1.89 điểm %** |
| Exact Match | **144/180** | 126/180 | **-18 câu** |
| VAD mean | **0.500 s** | 0.532 s | +32 ms |
| STT mean | 0.055 s | **0.054 s** | gần như không đổi |
| TOTAL mean | **0.555 s** | 0.586 s | **+31 ms** |
| TOTAL p95 | **0.660 s** | 0.695 s | **+35 ms** |

`TOTAL` tiếp tục là metric realtime chính từ speech-end đến transcript.

### Tài nguyên

| Metric | GTCRN OFF | GTCRN ON | Chênh lệch |
|---|---:|---:|---:|
| ONNX footprint | **340.9 MB** | 341.4 MB | +0.5 MB |
| Startup → READY | **10.02 s** | 10.26 s | +0.25 s |
| Idle CPU | **10.4%** | 42.8% | **+32.5 pp** |
| Active CPU mean | **98.6%** | 136.0% | **+37.4 pp** |
| Peak RSS | **766.2 MB** | 767.0 MB | +0.8 MB |

Chi phí RAM của GTCRN gần như không đáng kể, nhưng CPU tăng rõ rệt cả khi idle và khi xử lý audio.

### So sánh paired theo từng sample

Trong tổng cộng 180 cặp OFF/ON:

```text
GTCRN cải thiện :   6 / 180
GTCRN làm xấu   :  28 / 180
Không đổi       : 146 / 180
```

Chi tiết theo SNR:

| SNR | Improved | Worsened | Unchanged |
|---:|---:|---:|---:|
| 20 dB | 1/45 | 6/45 | 38/45 |
| 10 dB | 2/45 | 8/45 | 35/45 |
| 5 dB | 0/45 | 9/45 | 36/45 |
| 0 dB | 3/45 | 5/45 | 37/45 |

Ở cả 4 mức SNR, số sample bị GTCRN làm xấu đều lớn hơn hoặc bằng số sample được cải thiện.

### Kết quả từng run

| Run | Order | WER OFF | WER ON | Exact OFF | Exact ON |
|---|---|---:|---:|---:|---:|
| 15-51-36 | OFF → ON | **7.78%** | 8.73% | **48/60** | 43/60 |
| 16-01-45 | ON → OFF | **8.25%** | 10.38% | **48/60** | 41/60 |
| 16-09-38 | OFF → ON | **7.78%** | 10.38% | **48/60** | 42/60 |

Không có full run nào GTCRN ON cho WER tổng thể tốt hơn GTCRN OFF.

---

## 4. Đánh giá

Kết quả M03 tiếp tục xác nhận xu hướng đã thấy ở M02:

```text
GTCRN OFF tốt hơn GTCRN ON
```

với pipeline và model hiện tại.

Ngay cả khi noise được tăng có kiểm soát từ `20 dB` xuống `0 dB`, GTCRN vẫn không tạo ra lợi ích ổn định về accuracy.

Khi bật GTCRN:

- Corpus WER tổng thể tăng từ **7.94% lên 9.83%**;
- Exact Match giảm từ **144/180 xuống 126/180**;
- TOTAL latency trung bình tăng khoảng **31 ms**;
- TOTAL p95 tăng khoảng **35 ms**;
- Idle CPU tăng khoảng **32.5 điểm phần trăm**;
- Active CPU tăng khoảng **37.4 điểm phần trăm**;
- RAM gần như không thay đổi.

Paired comparison cũng cho thấy:

```text
Improved :  6
Worsened : 28
Unchanged: 146
```

tức số trường hợp bị làm xấu nhiều hơn khoảng 4.7 lần số trường hợp được cải thiện.

Một điểm đáng chú ý là AirConditioner là loại noise tương đối liên tục và ổn định. Zipformer vẫn giữ WER dưới khoảng 10% khi GTCRN OFF ngay cả ở `0 dB`, cho thấy loại noise này chưa tạo ra bài toán quá khó cho backend STT hiện tại.

WER theo SNR cũng không giảm/tăng hoàn toàn đơn điệu giữa `20 / 10 / 5 / 0 dB`. Vì tập chỉ có 15 câu và AirConditioner là stationary noise, không nên suy luận rằng một mức SNR riêng lẻ luôn khó hơn mức khác chỉ từ các chênh lệch nhỏ này.

---

## 5. Kết luận

Kết quả M03 với MS-SNSD AirConditioner:

```text
STT backend : Zipformer 2023-06-21
GTCRN       : OFF
```

GTCRN vẫn chưa nên được bật trong cấu hình production hiện tại vì:

- không cải thiện WER ở bất kỳ mức SNR nào khi tổng hợp đủ 3 run;
- giảm Exact Match;
- số sample bị làm xấu nhiều hơn số sample được cải thiện;
- tăng đáng kể CPU;
- tăng thêm realtime latency;
- không mang lại lợi ích RAM đáng kể.

Kết quả tốt hơn của GTCRN tại `0 dB` trong run đầu tiên không được tái lập ở hai run tiếp theo, vì vậy không thể xem đó là breakpoint ổn định.

---

## 6. Bước tiếp theo

AirConditioner là noise tương đối stationary, trong khi Zipformer hiện vẫn xử lý khá tốt.

Bước tiếp theo nên giữ nguyên:

```text
STT   = Zipformer 2023-06-21
GTCRN = OFF vs ON
```

nhưng chuyển loại noise sang:

```text
MS-SNSD Babble
```

Babble chứa nhiều thành phần tiếng nói chồng lẫn nhau nên có khả năng gây nhiễu trực tiếp lên đặc trưng speech mạnh hơn AirConditioner.

Có thể tiếp tục dùng cùng các mức:

```text
20 dB
10 dB
5 dB
0 dB
```

để kết quả có thể đối chiếu trực tiếp với M03 AirConditioner.

Nếu GTCRN vẫn không mang lại lợi ích ổn định với Babble, có thể kết luận mạnh hơn rằng `GTCRN simple` hiện tại không phù hợp với production STT pipeline trên Jetson Nano và nên giữ ở trạng thái disabled.
