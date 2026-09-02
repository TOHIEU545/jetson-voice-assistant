# M05 — Báo cáo benchmark Whisper Tiny.en vs Zipformer 2023-06-21 trong Babble noise

## 1. Tổng quan

Sau M01, M02, M03 và M04, M05 được thực hiện để kiểm tra lại lựa chọn backend STT trong điều kiện noise rất mạnh.

Hai model được so sánh:

- Whisper Tiny.en
- Zipformer 2023-06-21

Dataset sử dụng lại bộ audio Babble đã tạo cho M04:

```text
data/stt/ms_snsd/mixed/
└── voicebank_prepared_15/
    └── babble/
        ├── snr05/
        ├── snr00/
        └── manifest.tsv
```

M05 chỉ dùng hai mức noise khó nhất:

```text
5 dB
0 dB
```

GTCRN được giữ:

```text
OFF
```

Pipeline benchmark:

```text
Babble mixed WAV
  ↓
ALSA Loopback
  ↓
Silero VAD
  ↓
Speech runtime hiện tại
  ↓
┌─────────────────────────────┐
│ Whisper Tiny.en             │
│             vs              │
│ Zipformer 2023-06-21        │
└─────────────────────────────┘
  ↓
Transcript + latency
```

Hai backend sử dụng runtime architecture riêng đã được tích hợp trong project.

Benchmark không decode WAV trực tiếp bằng model mà lấy runtime command từ cấu hình project, để kết quả phản ánh cách mỗi backend thực sự hoạt động trong voice assistant.

Benchmark được chạy 3 lần độc lập:

```text
15 câu × 2 SNR × 2 model × 3 run
= 180 lượt xử lý
```

Ba full run:

```text
2026-09-02_17-53-47
2026-09-02_17-58-48
2026-09-02_18-03-46
```

Mục tiêu là so sánh đồng thời:

- độ chính xác;
- realtime latency;
- CPU;
- RAM;
- startup time;
- kích thước model.

---

## 2. Cách chạy benchmark

### Chuẩn bị ALSA Loopback

Sau khi Jetson reboot:

```bash
cd ~/jetson-voice-assistant

./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh load
```

Kiểm tra:

```bash
./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh status
```

### Validate dataset

```bash
python3 \
  benchmarks/stt/M05_whisper_zipformer_babble/benchmark_model_noise.py \
  --validate-dataset
```

Kết quả:

```text
Samples : 30

5 dB : 15
0 dB : 15

VALIDATION PASS
```

### Chạy benchmark

Để giảm ảnh hưởng do thứ tự chạy, ba run dùng:

```text
Run 1: Whisper  → Zipformer
Run 2: Zipformer → Whisper
Run 3: Whisper  → Zipformer
```

Run 1 và Run 3:

```bash
python3 \
  benchmarks/stt/M05_whisper_zipformer_babble/benchmark_model_noise.py \
  --order whisper,zipformer_2023_06_21
```

Run 2:

```bash
python3 \
  benchmarks/stt/M05_whisper_zipformer_babble/benchmark_model_noise.py \
  --order zipformer_2023_06_21,whisper
```

Kết quả mỗi run được lưu tại:

```text
logs/benchmarks/stt/M05_whisper_zipformer_babble/<run-id>/
```

Các file chính:

```text
metadata.json
samples.jsonl
summary.json
summary.md
paired_effect.json
whisper/config_metadata.json
zipformer_2023_06_21/config_metadata.json
```

Cấu hình chung:

```text
Dataset      : VoiceBank 15 câu + MS-SNSD Babble
SNR          : 5 dB, 0 dB
GTCRN        : OFF
Smart Turn   : OFF
Speculative  : OFF
Barge-in     : ON
Input        : ALSA Loopback
```

---

## 3. Kết quả tổng hợp 3 lần chạy

### Accuracy theo từng mức SNR

Mỗi mức SNR có:

```text
15 samples × 3 run
= 45 kết quả / model
```

| SNR | Whisper WER | Zipformer WER | Whisper - Zipformer | Exact Whisper | Exact Zipformer |
|---:|---:|---:|---:|---:|---:|
| 5 dB | 49.69% | **10.38%** | +39.31 điểm % | 9/45 | **32/45** |
| 0 dB | 87.74% | **30.19%** | +57.55 điểm % | 10/45 | **15/45** |

Ở cả hai mức SNR, Zipformer cho WER thấp hơn rõ rệt.

Tại `5 dB`:

```text
Whisper   : 49.69%
Zipformer : 10.38%
```

Tại `0 dB`:

```text
Whisper   : 87.74%
Zipformer : 30.19%
```

Whisper suy giảm rất mạnh khi gặp Babble noise.

Lưu ý: WER có thể vượt `100%` ở một run riêng lẻ nếu số lỗi chèn thêm từ (`Insertion`) làm tổng số lỗi lớn hơn số từ reference. Trong M05, Whisper tại `0 dB` ở Run 2 đạt WER `102.83%`.

### Realtime latency theo SNR

| SNR | TOTAL mean Whisper | TOTAL mean Zipformer | TOTAL p95 Whisper | TOTAL p95 Zipformer |
|---:|---:|---:|---:|---:|
| 5 dB | 2.562 s | **0.541 s** | 4.266 s | **0.660 s** |
| 0 dB | 2.517 s | **0.558 s** | 4.191 s | **0.656 s** |

Noise mạnh làm accuracy thay đổi đáng kể, nhưng Zipformer vẫn giữ realtime latency quanh `0.54–0.56 s`.

Whisper tiếp tục cần khoảng `2.5 s` trung bình và p95 trên `4 s`.

### Kết quả tổng thể

Tổng cho mỗi model:

```text
30 samples/run × 3 run
= 90 lượt
```

| Metric | Whisper Tiny.en | Zipformer 2023-06-21 |
|---|---:|---:|
| Corpus WER | 68.71% | **20.28%** |
| Exact Match | 19/90 | **47/90** |
| VAD mean | 0.500 s | 0.500 s |
| STT mean | 2.040 s | **0.050 s** |
| TOTAL mean | 2.540 s | **0.550 s** |
| TOTAL p95 | 4.243 s | **0.657 s** |

Zipformer giảm TOTAL mean từ:

```text
2.540 s
→
0.550 s
```

tương đương nhanh hơn khoảng:

```text
2.540 / 0.550 ≈ 4.6 lần
```

xét theo metric speech-end → transcript.

`STT mean` chỉ được giữ như diagnostic metric vì Whisper và Zipformer sử dụng hai runtime architecture khác nhau.

Metric chính để so trải nghiệm realtime vẫn là:

```text
TOTAL
```

### Tài nguyên

Các giá trị resource dưới đây được lấy trung bình từ ba full run.

| Metric | Whisper Tiny.en | Zipformer 2023-06-21 |
|---|---:|---:|
| ONNX size | **145.7 MB** | 340.9 MB |
| Startup → READY | **2.72 s** | 9.99 s |
| Idle CPU | 10.4% | **9.5%** |
| Idle RSS | **242.9 MB** | 760.6 MB |
| Active CPU mean | **81.7%** | 113.7% |
| CPU peak | **256.6%** | 302.1% |
| Peak RSS | **328.6 MB** | 766.4 MB |

Whisper có lợi thế rõ về footprint tài nguyên:

```text
Model size nhỏ hơn
RAM thấp hơn
Active CPU thấp hơn
Startup nhanh hơn
```

Trong khi Zipformer đánh đổi tài nguyên để đạt accuracy và realtime latency tốt hơn đáng kể.

### Paired comparison

Trong tổng cộng 90 cặp cùng sample, cùng SNR và cùng run:

```text
Whisper tốt hơn   :  2 / 90
Zipformer tốt hơn : 68 / 90
Bằng nhau         : 20 / 90
```

Theo từng mức SNR:

| SNR | Whisper better | Zipformer better | Same |
|---:|---:|---:|---:|
| 5 dB | 0/45 | **35/45** | 10/45 |
| 0 dB | 2/45 | **33/45** | 10/45 |

Tại `5 dB`, không có sample-run nào Whisper cho word edit distance thấp hơn Zipformer.

Tại `0 dB`, Whisper chỉ tốt hơn trong `2/45` cặp, trong khi Zipformer tốt hơn `33/45`.

Điều này cho thấy khác biệt WER tổng thể không phải chỉ do một vài sample bất thường.

### Kết quả từng run

| Run | Order | WER Whisper | WER Zipformer | Exact Whisper | Exact Zipformer |
|---|---|---:|---:|---:|---:|
| 17-53-47 | Whisper → Zipformer | 63.68% | **20.28%** | 7/30 | **16/30** |
| 17-58-48 | Zipformer → Whisper | 70.28% | **20.75%** | 7/30 | **16/30** |
| 18-03-46 | Whisper → Zipformer | 72.17% | **19.81%** | 5/30 | **15/30** |

Cả ba run đều cho cùng một xu hướng:

```text
Zipformer accuracy tốt hơn Whisper rất rõ
```

Run 2 đã đảo thứ tự thành:

```text
Zipformer → Whisper
```

nhưng kết quả vẫn không thay đổi về mặt kết luận.

---

## 4. Đánh giá

### Whisper Tiny.en

Ưu điểm:

- model nhỏ hơn;
- RAM thấp hơn đáng kể;
- CPU active thấp hơn;
- startup nhanh hơn.

Nhược điểm:

- WER rất cao trong Babble noise;
- Exact Match thấp;
- STT latency cao;
- TOTAL latency trung bình khoảng 2.54 s;
- TOTAL p95 trên 4 s.

Đặc biệt tại:

```text
5 dB : WER 49.69%
0 dB : WER 87.74%
```

cho thấy Whisper Tiny.en không phù hợp làm severe-noise fallback cho cấu hình hiện tại.

### Zipformer 2023-06-21

Ưu điểm:

- WER thấp hơn rất nhiều ở cả 5 dB và 0 dB;
- Exact Match cao hơn;
- latency rất thấp;
- TOTAL mean vẫn khoảng 0.55 s;
- kết quả ổn định qua cả ba run;
- paired comparison thắng trên phần lớn sample.

Nhược điểm:

- model lớn hơn;
- RAM cao hơn khoảng 2.3 lần nếu so Peak RSS;
- CPU active cao hơn;
- startup lâu hơn.

Tuy vậy, trên mục tiêu voice assistant realtime, mức tài nguyên cao hơn mang lại lợi ích lớn cả về accuracy và response latency.

### Trade-off chính

M05 cho thấy trade-off rất rõ:

```text
Whisper Tiny.en
→ nhẹ hơn
→ ít RAM hơn
→ CPU thấp hơn
→ nhưng accuracy và latency kém rõ rệt

Zipformer 2023-06-21
→ nặng RAM hơn
→ CPU cao hơn
→ nhưng accuracy tốt hơn nhiều
→ realtime nhanh hơn khoảng 4.6 lần
```

Với Jetson Nano 4GB, Zipformer dùng khoảng `766 MB` Peak RSS cho speech runtime vẫn nằm trong ngân sách có thể sử dụng của project, trong khi lợi ích accuracy và latency là đáng kể.

---

## 5. Kết luận

Kết quả M05:

```text
Primary STT backend:
Zipformer 2023-06-21

Whisper Tiny.en:
Không chọn làm severe-noise fallback
```

Lý do:

- Zipformer có Corpus WER `20.28%`, thấp hơn nhiều so với `68.71%` của Whisper;
- Zipformer đạt `47/90` Exact Match so với `19/90`;
- Zipformer TOTAL mean khoảng `0.55 s` so với `2.54 s`;
- Zipformer TOTAL p95 khoảng `0.66 s` so với `4.24 s`;
- paired comparison cho Zipformer tốt hơn trong `68/90` cặp;
- cả ba run đều tái lập cùng một xu hướng;
- đảo order ở Run 2 không làm thay đổi kết luận.

Whisper chỉ có lợi thế chính về:

```text
RAM
CPU
model size
startup
```

nhưng lợi thế này không đủ bù lại degradation rất lớn về accuracy và realtime latency.

Sau M05 có thể chốt backend STT production:

```text
STT   = Zipformer 2023-06-21
GTCRN = OFF
```

---

## 6. Bước tiếp theo

Sau M05, không cần tiếp tục mở rộng benchmark model STT ngay lúc này.

Chuỗi benchmark M01 → M05 đã trả lời các câu hỏi chính:

```text
M01 : chọn model STT
M02 : GTCRN trên noisy VoiceBank
M03 : GTCRN + AirConditioner controlled SNR
M04 : GTCRN + Babble controlled SNR
M05 : Whisper vs Zipformer trong Babble 5/0 dB
```

Kết quả cho phép đóng nhánh lựa chọn STT với:

```text
Primary STT : Zipformer 2023-06-21
GTCRN       : OFF
```

Bước tiếp theo nên chuyển sang đánh giá:

```text
Smart Turn / endpointing
```

vì sau khi Zipformer được chọn, thời gian decode STT chỉ còn khoảng vài chục millisecond, trong khi quyết định khi nào người dùng thực sự nói xong trở thành thành phần quan trọng hơn đối với perceived latency của voice assistant.

---

## 7. Ghi chú reproducibility

Ba run M05 được thực hiện trên cùng commit:

```text
d5583601442cbeb2bdecdb2b44bc0b0368c18dd8
```

Metadata ghi nhận Jetson chạy:

```text
NVIDIA Jetson Nano Developer Kit
L4T R32.7.1
Python 3.6.9
NV Power Mode: MAXN
```

Benchmark metadata cũng ghi nhận working tree trên Jetson có thay đổi cục bộ:

```text
M scripts/run_voice_assistant.sh
```

M05 không chạy launcher này mà sử dụng benchmark runtime command riêng được xây từ cấu hình project, nên thay đổi launcher không được dùng làm biến benchmark. Tuy nhiên trạng thái này vẫn được ghi lại để đảm bảo reproducibility.
