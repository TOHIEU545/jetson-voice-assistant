# M01 — Báo cáo benchmark 3 model STT trong pipeline hoàn chỉnh

## 1. Tổng quan

Bài benchmark M01 dùng để so sánh 3 backend STT hiện có trong project:

- Whisper Tiny.en
- Zipformer 20M — 2023-02-17
- Zipformer — 2023-06-21

Điểm quan trọng là benchmark **không decode WAV trực tiếp bằng model**, mà đưa audio đi qua pipeline speech hiện tại của project:

```text
WAV clean
  ↓
ALSA Loopback
  ↓
Silero VAD
  ↓
Speech runtime hiện tại
  ↓
STT backend
  ↓
Transcript + latency
```

Với Zipformer, benchmark giữ nguyên cơ chế streaming đã tối ưu của project gồm speech gating và rolling pre-roll.

Benchmark được chạy 3 lần độc lập:

```text
15 WAV × 3 model × 3 run = 135 lượt xử lý
```

Mục tiêu là chọn model phù hợp nhất dựa trên:

- độ chính xác;
- độ trễ realtime;
- CPU;
- RAM;
- thời gian khởi động;
- kích thước model.

---

## 2. Cách chạy benchmark

### Chuẩn bị ALSA Loopback

Sau khi Jetson reboot:

```bash
cd ~/jetson-voice-assistant

./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh load
```

Loopback dùng để đưa file WAV vào đúng input ALSA của speech runtime mà không cần phát loa rồi thu lại bằng microphone.

Thiết bị mặc định:

```text
playback : plughw:Loopback,0,0
capture  : plughw:Loopback,1,0
```

### Chạy full benchmark

```bash
python3   benchmarks/stt/M01_model_comparison/benchmark_stt_pipeline.py   --condition clean
```

Mỗi lần chạy sẽ tạo một thư mục mới:

```text
logs/benchmarks/stt/M01_model_comparison/<run-id>/
```

Kết quả chính nằm trong:

```text
summary.md
summary.json
samples.jsonl
metadata.json
```

### Cấu hình chung

```text
Dataset      : VoiceBank clean subset
Samples      : 15 WAV
Provider     : CPU
STT threads  : 2
GTCRN        : OFF
Smart Turn   : OFF
Speculative  : OFF
Input        : ALSA Loopback
```

Benchmark lấy command runtime trực tiếp từ `app.config.build_speech_command()` để bám đúng cấu hình hiện tại của project.

---

## 3. Kết quả tổng hợp 3 lần chạy

### Accuracy và realtime latency

| Model | Corpus WER | Exact / 45 | STT mean | TOTAL mean | TOTAL p95 |
|---|---:|---:|---:|---:|---:|
| Whisper Tiny.en | 14.15% | 23/45 | 1.809 s | 2.309 s | 3.425 s |
| Zipformer 20M | 11.32% | 33/45 | **0.020 s** | **0.520 s** | **0.565 s** |
| Zipformer 2023-06-21 | **6.92%** | **35/45** | 0.059 s | 0.559 s | 0.701 s |

VAD latency gần như cố định:

```text
~0.500 s
```

Do đó chênh lệch realtime chủ yếu nằm ở phần STT.

### Tài nguyên

| Model | ONNX size | Ready mean | Idle CPU | Idle RSS | Active CPU | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|
| Whisper Tiny.en | 145.7 MB | 6.84 s | 17.9% | 238.0 MB | 84.0% | 318.5 MB |
| Zipformer 20M | **88.3 MB** | **6.18 s** | **17.8%** | **215.4 MB** | **61.3%** | **219.5 MB** |
| Zipformer 2023-06-21 | 340.9 MB | 12.95 s | 18.4% | 759.7 MB | 98.5% | 766.7 MB |

---

## 4. Đánh giá

### Whisper Tiny.en

Ưu điểm:

- RAM thấp hơn Zipformer 2023;
- có thể giữ làm baseline hoặc fallback.

Nhược điểm:

- accuracy thấp nhất;
- STT latency cao nhất;
- TOTAL latency trung bình khoảng 2.3 s;
- không phù hợp bằng Zipformer cho trải nghiệm realtime.

### Zipformer 20M

Ưu điểm:

- nhanh nhất;
- nhẹ nhất;
- RAM thấp nhất;
- CPU active thấp nhất;
- kết quả giữa các lần chạy rất ổn định.

Nhược điểm:

- accuracy thấp hơn Zipformer 2023;
- một số câu bị mất từ dù latency rất tốt.

Đây là lựa chọn tốt nếu ưu tiên tài nguyên và tốc độ.

### Zipformer 2023-06-21

Ưu điểm:

- WER thấp nhất;
- số câu exact cao nhất;
- latency vẫn rất thấp;
- chỉ chậm hơn Zipformer 20M một lượng nhỏ trong cảm nhận realtime.

Nhược điểm:

- model lớn nhất;
- RAM cao nhất;
- CPU active cao hơn;
- startup lâu hơn.

Dù tốn tài nguyên hơn, model này cho cân bằng tốt nhất giữa **accuracy và realtime response**.

---

## 5. Kết luận

Kết quả M01:

```text
Primary STT backend:
Zipformer 2023-06-21

Lightweight alternative:
Zipformer 20M

Baseline / fallback:
Whisper Tiny.en
```

Lý do chọn Zipformer 2023-06-21:

- accuracy tốt nhất trong cả 3 lần benchmark;
- WER khoảng 6.9%;
- TOTAL latency trung bình khoảng 0.56 s;
- TOTAL p95 vẫn dưới 1 s;
- phù hợp với mục tiêu voice assistant realtime;
- tận dụng được kiến trúc streaming + speech gating + rolling pre-roll đã tối ưu trước đó.

Điểm đánh đổi chính là RAM và CPU cao hơn Zipformer 20M.

---

## 6. Bước tiếp theo

Sau M01, giữ cố định:

```text
STT = Zipformer 2023-06-21
```

và chuyển sang:

```text
M02_noise_gtcrn_ablation
```

Bài test tiếp theo sẽ so sánh:

```text
Noisy audio + GTCRN OFF
vs
Noisy audio + GTCRN ON
```

với các metric tương tự:

- WER;
- Exact match;
- VAD/STT/TOTAL latency;
- CPU;
- RAM.

Nếu bộ noisy hiện tại chưa đủ khó và hai cấu hình cho kết quả gần như nhau, sẽ chuyển sang bộ noise mạnh hơn hoặc controlled SNR.
