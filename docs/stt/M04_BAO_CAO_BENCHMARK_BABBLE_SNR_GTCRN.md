# M04 — Báo cáo benchmark Babble SNR: GTCRN OFF vs ON

## 1. Tổng quan

Sau M01, M02 và M03, backend STT tiếp tục được cố định là:

```text
Zipformer 2023-06-21
```

M04 được thực hiện để kiểm tra GTCRN với một loại noise khó hơn AirConditioner.

Speech sạch vẫn dùng 15 mẫu VoiceBank đã sử dụng trong các milestone trước. Noise lấy từ:

```text
MS-SNSD
Babble_1.wav
```

Speech và Babble được trộn ở 4 mức SNR:

```text
20 dB
10 dB
 5 dB
 0 dB
```

Dataset:

```text
data/stt/ms_snsd/mixed/
└── voicebank_prepared_15/
    └── babble/
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
MS-SNSD Babble noise
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
2026-09-02_16-37-46
2026-09-02_16-45-21
2026-09-02_16-52-57
```

Mục tiêu của M04 là:

- kiểm tra STT khi gặp speech-like noise khó hơn;
- xác định GTCRN có giúp khi SNR giảm mạnh hay không;
- đo ảnh hưởng của GTCRN lên latency, CPU và RAM;
- chốt quyết định có nên giữ GTCRN trong production pipeline hay không.

---

## 2. Cách chạy benchmark

### Chuẩn bị ALSA Loopback

Sau khi Jetson reboot:

```bash
cd ~/jetson-voice-assistant

./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh load
```

Có thể kiểm tra:

```bash
./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh status
```

### Validate dataset

```bash
python3 \
  benchmarks/stt/M04_babble_snr_stress/benchmark_noise_snr.py \
  --validate-dataset
```

Dataset gồm:

```text
Samples : 60

20 dB : 15
10 dB : 15
 5 dB : 15
 0 dB : 15
```

### Chạy full benchmark

Để giảm ảnh hưởng của thứ tự chạy, ba run sử dụng:

```text
Run 1: GTCRN OFF → GTCRN ON
Run 2: GTCRN ON  → GTCRN OFF
Run 3: GTCRN OFF → GTCRN ON
```

Lệnh tương ứng:

```bash
python3 \
  benchmarks/stt/M04_babble_snr_stress/benchmark_noise_snr.py \
  --order gtcrn_off,gtcrn_on
```

```bash
python3 \
  benchmarks/stt/M04_babble_snr_stress/benchmark_noise_snr.py \
  --order gtcrn_on,gtcrn_off
```

```bash
python3 \
  benchmarks/stt/M04_babble_snr_stress/benchmark_noise_snr.py \
  --order gtcrn_off,gtcrn_on
```

Kết quả mỗi run được lưu tại:

```text
logs/benchmarks/stt/M04_babble_snr_stress/<run-id>/
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

Cấu hình được giữ cố định:

```text
STT         : Zipformer 2023-06-21
Noise       : MS-SNSD Babble
SNR         : 20 / 10 / 5 / 0 dB
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
| 20 dB | **7.55%** | 8.49% | +0.94 điểm % | **36/45** | 34/45 |
| 10 dB | **8.81%** | 11.01% | +2.20 điểm % | **36/45** | 29/45 |
| 5 dB | **10.69%** | 22.33% | **+11.64 điểm %** | **32/45** | 22/45 |
| 0 dB | **29.87%** | 49.37% | **+19.50 điểm %** | **17/45** | 12/45 |

Kết quả cho thấy khi Babble noise tăng mạnh, WER của cả hai cấu hình đều tăng.

Tuy nhiên:

```text
GTCRN ON luôn có WER cao hơn GTCRN OFF
```

ở cả bốn mức SNR.

Chênh lệch đặc biệt lớn tại:

```text
5 dB : +11.64 điểm %
0 dB : +19.50 điểm %
```

Tại `5 dB`, WER khi bật GTCRN cao hơn khoảng gấp đôi cấu hình OFF.

Tại `0 dB`:

```text
GTCRN OFF : 29.87%
GTCRN ON  : 49.37%
```

GTCRN làm accuracy suy giảm rất rõ trong điều kiện Babble mạnh.

### Accuracy và latency tổng thể

Mỗi cấu hình có:

```text
60 samples/run × 3 run
= 180 lượt
```

| Metric | GTCRN OFF | GTCRN ON | Chênh lệch ON - OFF |
|---|---:|---:|---:|
| Corpus WER | **14.23%** | 22.80% | **+8.57 điểm %** |
| Exact Match | **121/180** | 97/180 | **-24 câu** |
| VAD mean | **0.500 s** | 0.532 s | +32 ms |
| STT mean | **0.048 s** | 0.053 s | +5 ms |
| TOTAL mean | **0.548 s** | 0.585 s | **+37 ms** |
| TOTAL p95 | **0.661 s** | 0.694 s | **+33 ms** |

Tỷ lệ Exact Match:

```text
GTCRN OFF : 121/180 ≈ 67.2%
GTCRN ON  :  97/180 ≈ 53.9%
```

WER khi bật GTCRN tăng tương đối khoảng:

```text
(22.80 - 14.23) / 14.23
≈ 60%
```

so với cấu hình OFF.

`TOTAL` tiếp tục là metric realtime chính từ speech-end đến transcript.

### Tài nguyên

Giá trị dưới đây được tổng hợp từ ba full run.

| Metric | GTCRN OFF | GTCRN ON | Chênh lệch |
|---|---:|---:|---:|
| ONNX footprint | **340.9 MB** | 341.4 MB | +0.5 MB |
| Startup → READY | **10.05 s** | 10.23 s | +0.17 s |
| Idle CPU | **10.0%** | 42.7% | **+32.7 pp** |
| Active CPU mean | **107.3%** | 142.2% | **+34.9 pp** |
| CPU peak | **308.7%** | 354.3% | +45.6 pp |
| Peak RSS | 766.4 MB | **765.8 MB** | gần như không đổi |

GTCRN gần như không làm tăng RAM đáng kể.

Ngược lại, chi phí CPU tăng rõ rệt:

```text
Idle CPU   : ~10.0% → ~42.7%
Active CPU : ~107.3% → ~142.2%
```

trong khi accuracy lại giảm.

### So sánh paired theo từng sample

Trong tổng cộng 180 cặp cùng sample và cùng SNR:

```text
GTCRN cải thiện :   7 / 180
GTCRN làm xấu   :  55 / 180
Không đổi       : 118 / 180
```

Chi tiết:

| SNR | Improved | Worsened | Unchanged |
|---:|---:|---:|---:|
| 20 dB | 2/45 | 5/45 | 38/45 |
| 10 dB | 0/45 | 7/45 | 38/45 |
| 5 dB | 1/45 | 18/45 | 26/45 |
| 0 dB | 4/45 | 25/45 | 16/45 |

Tại `0 dB`:

```text
GTCRN cải thiện :  4
GTCRN làm xấu   : 25
Không đổi       : 16
```

Số trường hợp bị GTCRN làm xấu lớn hơn rõ rệt số trường hợp được cải thiện.

### Kết quả từng run

| Run | Order | WER OFF | WER ON | Exact OFF | Exact ON |
|---|---|---:|---:|---:|---:|
| 16-37-46 | OFF → ON | **15.09%** | 21.93% | **40/60** | 34/60 |
| 16-45-21 | ON → OFF | **13.44%** | 24.53% | **39/60** | 29/60 |
| 16-52-57 | OFF → ON | **14.15%** | 21.93% | **42/60** | 34/60 |

Cả ba run đều cho cùng một kết luận:

```text
WER GTCRN OFF < WER GTCRN ON
```

Run 2 đã đảo thứ tự thành `ON → OFF`, nhưng GTCRN ON vẫn cho kết quả xấu hơn rõ rệt.

Do đó xu hướng này không phụ thuộc đơn giản vào thứ tự chạy.

---

## 4. Đánh giá

M04 tạo được bài stress khó hơn M03.

Với Babble noise, WER của Zipformer khi GTCRN OFF tăng theo mức noise mạnh:

```text
20 dB :  7.55%
10 dB :  8.81%
 5 dB : 10.69%
 0 dB : 29.87%
```

Đặc biệt `0 dB` đã tạo ra degradation rõ rệt, cho thấy benchmark lần này thực sự đưa STT vào điều kiện khó.

Tuy nhiên GTCRN không cải thiện tình hình.

Khi bật GTCRN:

- Corpus WER tăng từ **14.23% lên 22.80%**;
- Exact Match giảm từ **121/180 xuống 97/180**;
- TOTAL latency tăng khoảng **37 ms**;
- Idle CPU tăng khoảng **32.7 điểm phần trăm**;
- Active CPU tăng khoảng **34.9 điểm phần trăm**;
- RAM gần như không thay đổi.

Paired comparison:

```text
Improved :   7
Worsened :  55
Unchanged: 118
```

cho thấy kết quả tổng thể không chỉ bị chi phối bởi một vài sample bất thường.

Khi noise mạnh hơn, số trường hợp bị GTCRN làm xấu tăng rõ:

```text
5 dB : 18 / 45 worsened
0 dB : 25 / 45 worsened
```

Điều này cho thấy output sau GTCRN Simple hiện tại không phù hợp với Zipformer 2023-06-21 trong bài benchmark Babble này.

Có thể đặt giả thuyết rằng enhancement đang làm thay đổi một phần đặc trưng speech mà STT cần, đặc biệt khi speech và Babble có mức năng lượng gần nhau.

Tuy nhiên benchmark hiện tại chỉ chứng minh rằng:

```text
STT accuracy sau GTCRN bị giảm
```

và chưa đủ để xác định chính xác nguyên nhân bên trong model enhancement.

---

## 5. Kết luận

Kết quả M04:

```text
STT backend : Zipformer 2023-06-21
GTCRN       : OFF
```

M04 cung cấp thêm bằng chứng mạnh để giữ GTCRN ở trạng thái OFF vì:

- GTCRN không cải thiện WER ở bất kỳ mức SNR nào;
- degradation tăng mạnh ở `5 dB` và `0 dB`;
- cả ba full run đều cho GTCRN OFF tốt hơn;
- paired comparison cho số trường hợp worsened lớn hơn nhiều improved;
- GTCRN tăng đáng kể CPU;
- GTCRN tăng thêm latency;
- RAM gần như không thay đổi.

Kết hợp với kết quả các milestone trước, có thể chốt:

```text
GTCRN Simple hiện tại
không phù hợp với production STT pipeline
trên cấu hình và các điều kiện benchmark đã thử.
```

Không nên diễn giải kết quả này thành:

```text
mọi model GTCRN hoặc mọi speech enhancement đều không tốt
```

vì kết luận chỉ áp dụng cho model GTCRN Simple, pipeline, backend STT và các dataset đã benchmark trong project.

---

## 6. Bước tiếp theo

Sau M04, không cần tiếp tục mở rộng benchmark GTCRN bằng thêm noise type ngay lúc này.

Cấu hình STT được giữ:

```text
Primary STT : Zipformer 2023-06-21
GTCRN       : OFF
```

Các kết quả M02 → M04 đã đủ để đóng nhánh đánh giá GTCRN Simple hiện tại.

Project có thể chuyển sang benchmark hoặc tối ưu thành phần tiếp theo của voice assistant pipeline, thay vì tiếp tục dành tài nguyên cho audio enhancement này.

GTCRN vẫn có thể được giữ trong source như một feature thử nghiệm:

```text
default = OFF
```

để phục vụ benchmark hoặc thử model enhancement khác trong tương lai.
