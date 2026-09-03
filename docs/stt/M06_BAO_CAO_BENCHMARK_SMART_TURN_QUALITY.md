# M06 — Báo cáo benchmark Smart Turn v3.2 standalone quality

## 1. Tổng quan

Sau M05, backend STT production đã được chốt theo hướng:

```text
STT   = Zipformer 2023-06-21
GTCRN = OFF
```

M06 chuyển sang đánh giá riêng thành phần **Smart Turn / endpointing**, trước khi tích hợp Smart Turn vào pipeline streaming Zipformer ở M07.

Mục tiêu của M06 là trả lời hai câu hỏi:

```text
1. Smart Turn có phân biệt tốt:
   COMPLETE   = người dùng đã nói xong
   INCOMPLETE = người dùng chưa nói xong
   hay không?

2. Chi phí xử lý Smart Turn standalone trên Jetson Nano là bao nhiêu?
```

M06 không benchmark transcript, WER hay STT backend. Smart Turn được chạy độc lập bằng C++ probe sử dụng cùng preprocessing và ONNX model đã được tích hợp trong project.

Pipeline benchmark:

```text
Official Smart Turn v3.2 test data
  ↓
30 COMPLETE + 30 INCOMPLETE
  ↓
PCM WAV 16 kHz
  ↓
Smart Turn preprocessing
  ├── lấy tối đa 8 giây cuối
  ├── zero-pad nếu ngắn hơn
  ├── normalize audio
  └── tạo Whisper-style feature [1, 80, 800]
  ↓
Smart Turn v3.2 ONNX
  ↓
probability
  ↓
threshold = 0.5
  ↓
COMPLETE / INCOMPLETE
```

Positive class được quy ước là:

```text
COMPLETE
```

Do đó:

```text
False Positive:
truth      = INCOMPLETE
prediction = COMPLETE
→ có nguy cơ kết thúc turn quá sớm

False Negative:
truth      = COMPLETE
prediction = INCOMPLETE
→ giữ turn lâu hơn cần thiết
```

M06 đặc biệt quan tâm tới **False Positive Rate (FPR)** vì đây là lỗi có thể làm voice assistant cắt lời người dùng.

---

## 2. Dataset và cấu hình benchmark

Dataset nguồn:

```text
pipecat-ai/smart-turn-data-v3.2-test
```

Revision được pin:

```text
0500378e8ed6d38e37b016e24d261e8e6c6a6859
```

Subset local:

```text
data/stt/smart_turn_v3_2_test/source/hf_selected_60/
├── audio/
├── manifest.tsv
└── source.json
```

Điều kiện chọn:

```text
Language  : eng
Synthetic : false
COMPLETE  : 30
INCOMPLETE: 30
Total     : 60
```

Phân bố source trong subset:

| Dataset source | Samples |
|---|---:|
| `liva_1` | 45 |
| `midcentury_1` | 11 |
| `human_5` | 4 |
| **Total** | **60** |

Subset được cân bằng theo nhãn COMPLETE/INCOMPLETE nhưng **không cân bằng theo dataset source**. Vì vậy M06 phù hợp để kiểm tra chất lượng ban đầu của Smart Turn trên project, nhưng chưa nên coi 60 mẫu này là đánh giá tổng quát cho toàn bộ dataset chính thức.

Cấu hình model:

```text
Model     : smart-turn-v3.2-cpu-opset16-ir8-clean.onnx
Model size: 8.30 MB
Threshold : 0.500
Threads   : 4
```

Platform từ metadata:

```text
Linux 4.9.253-tegra
aarch64
Ubuntu 18.04 bionic
Python 3.6.9
```

---

## 3. Cách chạy benchmark

### Build standalone probe

```bash
cd ~/jetson-voice-assistant

./benchmarks/stt/M06_smart_turn_quality/build_probe.sh
```

### Validate tooling

```bash
python3 -m py_compile \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  benchmarks/stt/M06_smart_turn_quality/summarize_results.py
```

Self-test:

```bash
python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --self-test
```

Validate dataset:

```bash
python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --validate-dataset
```

Expected:

```text
Samples    : 60
COMPLETE   : 30
INCOMPLETE : 30
VALIDATION PASS
```

### Smoke test

```bash
python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --limit-per-class 1
```

Smoke test xử lý:

```text
1 COMPLETE + 1 INCOMPLETE
= 2 samples
```

### Full benchmark

```bash
python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py
```

Full benchmark xử lý:

```text
30 COMPLETE + 30 INCOMPLETE
= 60 samples
```

Run chính thức:

```text
2026-09-03_00-06-37
```

Kết quả được lưu tại:

```text
logs/benchmarks/stt/M06_smart_turn_quality/
└── 2026-09-03_00-06-37/
    ├── samples.jsonl
    ├── smart_turn_v3_2/
    │   └── config_metadata.json
    ├── summary.json
    └── summary.md
```

---

## 4. Kết quả classification

Kết quả tổng thể:

| Samples | Correct | Accuracy | Precision | Recall | F1 | FPR | FNR |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 60 | 58 | **96.67%** | **93.75%** | **100.00%** | **96.77%** | **6.67%** | **0.00%** |

Confusion matrix:

```text
                 Pred COMPLETE   Pred INCOMPLETE
Truth COMPLETE        30                 0
Truth INCOMPLETE       2                28
```

Tức là:

```text
COMPLETE:
30/30 đúng

INCOMPLETE:
28/30 đúng
 2/30 bị dự đoán nhầm COMPLETE
```

Smart Turn không bỏ sót sample COMPLETE nào:

```text
FN  = 0
FNR = 0%
```

Nhưng có hai trường hợp premature-turn risk:

```text
FP  = 2
FPR = 6.67%
```

Với mục tiêu voice assistant, đây là hai lỗi cần quan tâm nhất vì model có thể báo người dùng đã nói xong khi câu thực tế vẫn chưa hoàn tất.

---

## 5. Phân tích hai False Positive

Hai sample INCOMPLETE bị dự đoán thành COMPLETE:

| Sample ID | Source | Duration | Probability | Prediction |
|---|---|---:|---:|---|
| `00b53923-5402-4e87-9552-5fdda0797705` | `liva_1` | 12.749 s | **0.805015** | COMPLETE |
| `01dcfe3b-05f5-4e61-9b72-95b2418e3e64` | `liva_1` | 11.563 s | **0.864268** | COMPLETE |

Cả hai lỗi đều đến từ:

```text
liva_1
```

Tuy nhiên `liva_1` cũng chiếm tới:

```text
45 / 60 samples
```

nên chưa thể kết luận rằng source `liva_1` bản thân là nguyên nhân gây lỗi.

Phân bố probability theo ground truth:

| Ground truth | Min | Median | Mean | Max |
|---|---:|---:|---:|---:|
| COMPLETE | 0.606652 | 0.984260 | 0.966710 | 0.990130 |
| INCOMPLETE | 0.005077 | 0.006678 | 0.076888 | 0.864268 |

Phần lớn hai class được tách khá rõ:

```text
COMPLETE
→ probability chủ yếu rất gần 1

INCOMPLETE
→ probability chủ yếu rất gần 0
```

Nhưng tồn tại vùng overlap:

```text
COMPLETE thấp nhất   : 0.606652

INCOMPLETE cao nhất  : 0.864268
INCOMPLETE cao thứ 2 : 0.805015
```

Điều này cho thấy hai False Positive không đơn giản chỉ là threshold `0.5` hơi thấp; probability của chúng nằm khá sâu về phía COMPLETE.

---

## 6. Phân tích threshold từ probability đã lưu

Vì `samples.jsonl` đã lưu probability của toàn bộ 60 mẫu, có thể phân tích threshold offline mà không chạy lại model.

Đây chỉ là **post-hoc analysis**, không phải cấu hình benchmark chính thức.

| Threshold | Accuracy | Precision | Recall | F1 | FPR | FNR | FP | FN |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.50 | 96.67% | 93.75% | 100.00% | 96.77% | 6.67% | 0.00% | 2 | 0 |
| 0.60 | 96.67% | 93.75% | 100.00% | 96.77% | 6.67% | 0.00% | 2 | 0 |
| 0.70 | 95.00% | 93.55% | 96.67% | 95.08% | 6.67% | 3.33% | 2 | 1 |
| 0.80 | 95.00% | 93.55% | 96.67% | 95.08% | 6.67% | 3.33% | 2 | 1 |
| 0.85 | 96.67% | 96.67% | 96.67% | 96.67% | 3.33% | 3.33% | 1 | 1 |
| 0.90 | **98.33%** | **100.00%** | 96.67% | **98.31%** | **0.00%** | 3.33% | 0 | 1 |

Trên đúng subset 60 mẫu này, threshold `0.90` loại được cả hai False Positive nhưng tạo ra một False Negative.

Tuy nhiên không nên đổi production threshold từ `0.5` sang `0.9` chỉ dựa trên 60 sample, vì:

- subset nhỏ;
- source distribution không cân bằng;
- threshold `0.9` được nhìn thấy sau khi đã biết kết quả;
- có nguy cơ overfit vào benchmark subset.

Do đó M06 giữ:

```text
Threshold = 0.5
```

làm baseline chính thức.

Threshold tuning chỉ nên được xem xét sau khi có thêm dữ liệu hoặc sau M07 nếu actual pipeline cho thấy premature endpoint vẫn là vấn đề rõ rệt.

---

## 7. Latency trên Jetson Nano

Kết quả latency:

| Metric | Mean | Median | p95 | Max |
|---|---:|---:|---:|---:|
| Audio prep | 1.58 ms | 1.55 ms | 1.76 ms | 1.78 ms |
| Feature extraction | **1329.56 ms** | 1329.60 ms | 1331.28 ms | 1332.55 ms |
| ONNX inference | **324.93 ms** | 324.79 ms | 326.66 ms | 328.35 ms |
| TOTAL | **1656.07 ms** | 1656.03 ms | **1658.53 ms** | 1659.90 ms |
| Model load | 296.79 ms | 296.62 ms | 301.27 ms | 304.93 ms |

Trong benchmark:

```text
TOTAL
=
audio preparation
+
feature extraction
+
ONNX inference
```

Mean:

```text
Audio prep :    1.58 ms
Feature    : 1329.56 ms
Inference  :  324.93 ms
----------------------
TOTAL      : 1656.07 ms
```

Feature extraction chiếm khoảng:

```text
1329.56 / 1656.07
≈ 80.3%
```

tổng Smart Turn compute latency.

ONNX inference chỉ chiếm khoảng:

```text
324.93 / 1656.07
≈ 19.6%
```

Do đó bottleneck chính của Smart Turn hiện tại không phải ONNX classifier mà là:

```text
Whisper-style feature extraction
```

---

## 8. Ý nghĩa của model load

Standalone probe hiện chạy theo kiểu one-shot:

```text
process start
→ load Smart Turn model
→ process một WAV
→ exit
```

Vì vậy mỗi sample đều có `load_ms`.

Mean model load:

```text
296.79 ms
```

Tuy nhiên production `SmartTurnRuntime` được thiết kế để giữ model resident trong process.

Runtime thực tế:

```text
startup
→ load model một lần
→ nhiều Smart Turn evaluations
```

Do đó model load **không được cộng vào per-turn TOTAL**.

Metric realtime cần quan tâm là:

```text
~1.656 s / Smart Turn evaluation
```

không phải:

```text
~1.953 s
```

nếu cộng thêm model load.

---

## 9. Đánh giá chất lượng

### Điểm tốt

Smart Turn v3.2 đạt:

```text
Accuracy : 96.67%
F1       : 96.77%
Recall   : 100%
FNR      : 0%
```

Đặc biệt:

```text
30 / 30 COMPLETE
```

đều được nhận đúng.

Điều này cho thấy model có khả năng phân biệt semantic turn completion khá tốt trên subset M06.

Phần lớn prediction cũng có confidence tách biệt rõ:

```text
COMPLETE   → probability gần 1
INCOMPLETE → probability gần 0
```

### Điểm cần lưu ý

Có:

```text
2 / 30 INCOMPLETE
```

bị nhận nhầm COMPLETE.

Đây là loại lỗi quan trọng nhất đối với turn-taking vì có thể gây:

```text
user vẫn đang nói
↓
Smart Turn báo COMPLETE
↓
pipeline finalize turn sớm
↓
LLM bắt đầu xử lý trước khi user nói xong
```

FPR `6.67%` trên 30 sample INCOMPLETE chưa đủ thấp để kết luận rằng Smart Turn sẽ không bao giờ gây premature endpoint trong thực tế.

M07 cần kiểm tra trực tiếp behavior này khi Smart Turn nằm trong actual streaming pipeline.

---

## 10. Đánh giá chi phí realtime

Về quality, Smart Turn cho kết quả tốt.

Nhưng standalone compute cost hiện khá lớn:

```text
~1.656 s / evaluation
```

Trong đó:

```text
~1.330 s feature extraction
~0.325 s inference
```

Nếu implementation M07 làm:

```text
VAD endpoint candidate
↓
bắt đầu Smart Turn feature extraction
↓
chờ ~1.65 s
↓
mới quyết định COMPLETE
```

thì perceived latency sẽ tăng mạnh và có thể làm mất lợi ích realtime của Zipformer.

Vì vậy M06 **không chứng minh rằng Smart Turn có thể được bật trực tiếp trong production với implementation hiện tại**.

M06 chỉ chứng minh:

```text
Quality:
tốt

Standalone latency:
cao

Primary bottleneck:
feature extraction
```

M07 phải đo actual pipeline behavior trước khi quyết định bật Smart Turn mặc định.

---

## 11. Resource scope

M06 log hiện tại đo:

- classification quality;
- model size;
- model load latency;
- audio preprocessing latency;
- feature extraction latency;
- ONNX inference latency;
- TOTAL latency.

M06 **không thu thập CPU/RAM runtime sampling** cho Smart Turn standalone.

Vì vậy báo cáo này không đưa ra kết luận định lượng về:

```text
Idle CPU
Active CPU
CPU peak
Idle RSS
Peak RSS
```

Chi phí CPU/RAM nên được đo ở M07 trong pipeline tích hợp, nơi Smart Turn chạy cùng VAD + Zipformer và phản ánh đúng deployment architecture hơn.

---

## 12. Kết luận M06

Kết quả M06:

```text
Smart Turn v3.2 standalone quality:
ACCEPTED for integration experiment
```

Lý do:

```text
Accuracy : 96.67%
F1       : 96.77%
Recall   : 100%
FNR      : 0%
```

Model cho chất lượng đủ tốt để tiếp tục sang bước integration benchmark.

Tuy nhiên:

```text
FPR          : 6.67%
False Positive: 2 / 30 INCOMPLETE

TOTAL mean   : 1.656 s
TOTAL p95    : 1.659 s
```

nên **chưa thể bật Smart Turn làm production default**.

Decision sau M06:

```text
Quality:
PASS để sang M07

Production enable:
CHƯA

Threshold:
giữ 0.5 làm baseline

Optimization target:
feature extraction
```

Nói ngắn gọn:

```text
Smart Turn hiểu semantic turn completion khá tốt,
nhưng implementation hiện tại quá chậm để chỉ đơn giản
chèn thêm ~1.65 s synchronous compute sau endpoint.
```

---

## 13. Bước tiếp theo — M07

M07 sẽ chuyển từ standalone model validation sang actual integration benchmark:

```text
Baseline:
VAD
↓
Zipformer
↓
final transcript

vs

Candidate:
VAD
↓
Smart Turn
↓
Zipformer
↓
final transcript
```

M07 cần trả lời:

```text
1. Smart Turn có giảm premature turn / endpoint error trong pipeline thật không?

2. TOTAL speech-end → transcript / turn accepted tăng bao nhiêu?

3. Smart Turn có làm mất lợi thế realtime của streaming Zipformer không?

4. CPU/RAM tăng bao nhiêu khi Smart Turn resident cùng Zipformer?

5. Có cần incremental feature extraction / feature cache không?

6. Threshold 0.5 có phù hợp trong actual pipeline không?
```

Nếu M07 cho thấy synchronous Smart Turn quá chậm, hướng optimization cần ưu tiên:

```text
Mic / speech PCM
      ↓
incremental feature extraction
      ↓
feature cache sẵn trước endpoint
      ↓
endpoint candidate
      ↓
chỉ chạy phần Smart Turn inference còn lại
```

Mục tiêu là tránh phải tạo toàn bộ fixed-window features sau khi người dùng đã dừng nói.

---

## 14. Reproducibility

Run M06 chính thức:

```text
2026-09-03_00-06-37
```

Git commit được metadata ghi nhận:

```text
0e47db906abc17fe0ea8e843dbe061378c11142a
```

Dataset revision:

```text
0500378e8ed6d38e37b016e24d261e8e6c6a6859
```

Benchmark config:

```text
Model     : smart-turn-v3.2-cpu-opset16-ir8-clean.onnx
Threshold : 0.5
Threads   : 4
Samples   : 60
```

Metadata cũng ghi nhận Jetson working tree có thay đổi cục bộ:

```text
M scripts/run_voice_assistant.sh
```

M06 không chạy launcher `scripts/run_voice_assistant.sh`; benchmark sử dụng standalone probe:

```text
benchmarks/stt/M06_smart_turn_quality/build/smart_turn_probe
```

nên thay đổi launcher không trực tiếp tham gia đường benchmark M06.

Raw result được giữ ngoài Git tại:

```text
logs/benchmarks/stt/M06_smart_turn_quality/2026-09-03_00-06-37/
```

Các file nguồn benchmark có thể rerun:

```text
benchmarks/stt/M06_smart_turn_quality/
├── benchmark_smart_turn.py
├── build_probe.sh
├── prepare_subset.py
├── README.md
├── smart_turn_probe.cc
└── summarize_results.py
```

Accepted methodology và conclusion của M06 nên được lưu trong:

```text
docs/stt/M06_BAO_CAO_BENCHMARK_SMART_TURN_QUALITY.md
```
