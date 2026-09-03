# M06 — Chất lượng Smart Turn v3.2 standalone

M06 validate Smart Turn độc lập trước khi tích hợp với streaming Zipformer trong M07.

## One-command benchmark

Từ repository root trên Jetson:

```bash
./benchmarks/stt/M06_smart_turn_quality/run.sh
```

Đây là command duy nhất cần dùng cho normal rerun. `run.sh` kiểm tra dataset/model/runtime, build lại probe nếu thiếu hoặc stale, tự cấu hình `LD_LIBRARY_PATH` khi ONNX Runtime là shared library, validate dataset rồi chạy benchmark. M06 dùng standalone WAV probe nên không cần ALSA Loopback.

Output:

```text
logs/benchmarks/stt/M06_smart_turn_quality/<timestamp>/
├── samples.jsonl
├── smart_turn_v3_2/
│   └── config_metadata.json
├── summary.json
└── summary.md
```

## Fixed configuration

```text
Official Smart Turn v3.2 test data
  → 30 COMPLETE + 30 INCOMPLETE
  → smart_turn_probe
  → probability
  → threshold 0.5
  → COMPLETE / INCOMPLETE
  → classification + latency metrics
```

- Dataset: `data/stt/smart_turn_v3_2_test/source/hf_selected_60/`
- Model: `models/turn/smart-turn-v3.2-cpu-opset16-ir8-clean.onnx`
- Threshold: `0.5`
- Threads mặc định: `4`
- Positive class: `COMPLETE`

`endpoint_bool = 1` là COMPLETE; `endpoint_bool = 0` là INCOMPLETE. False positive là trường hợp INCOMPLETE bị phân loại thành COMPLETE, có nguy cơ cắt turn sớm.

Metric gồm Accuracy, Precision, Recall, F1, FPR, FNR, TP/TN/FP/FN, audio preparation latency, feature extraction latency, ONNX inference latency và TOTAL latency. `TOTAL` bằng audio preparation + feature extraction + ONNX inference. Model load được báo riêng vì production `SmartTurnRuntime` giữ model resident.

## Developer/debug commands

Các command dưới đây chỉ dành cho build, validation hoặc smoke test; normal rerun dùng `run.sh`.

Build probe thủ công:

```bash
./benchmarks/stt/M06_smart_turn_quality/build_probe.sh
```

Dataset preparation không thuộc normal rerun và chỉ cần khi fixed subset chưa tồn tại:

```bash
python3 benchmarks/stt/M06_smart_turn_quality/prepare_subset.py
```

Self-test và dataset validation:

```bash
python3 benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --self-test

python3 benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --validate-dataset
```

Smoke test chạy một COMPLETE và một INCOMPLETE:

```bash
python3 benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --limit-per-class 1
```

Runner tự tạo summary. `summarize_results.py` chỉ dùng để rebuild summary từ một run đã có:

```bash
python3 benchmarks/stt/M06_smart_turn_quality/summarize_results.py \
  logs/benchmarks/stt/M06_smart_turn_quality/<timestamp>
```
