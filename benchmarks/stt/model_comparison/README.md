# STT Model Comparison

Benchmark chính thức để so sánh 3 STT model hiện có của `jetson-voice-assistant` trên fixed clean WAV.

## Câu hỏi benchmark

Trong điều kiện audio clean, model nào cho cân bằng tốt nhất giữa:

- WER / exact match;
- decode latency;
- realtime factor (RTF);
- CPU;
- peak RSS;
- stability trên Jetson Nano?

Ba model:

```text
Whisper Tiny.en
Zipformer 20M 2023-02-17
Zipformer 2023-06-21
```

## Scope cố định

Benchmark này **không** so sánh lại architecture streaming.

```text
Input       : data/stt/voicebank_demand/prepared_15/clean/*.wav
Samples     : 15
GTCRN       : OFF
VAD         : bypass
Smart Turn  : OFF
Speculative : OFF
Provider    : CPU
STT threads : 2
Precision   : FP32 / non-int8 ONNX
Decoding    : greedy_search
```

`--enable-endpoint=false` chỉ dùng cho hai direct-file Zipformer CLI để toàn bộ fixed WAV được decode; đây không phải thay đổi runtime architecture của application.

## Vì sao decode WAV trực tiếp?

Mục tiêu ở benchmark này là cô lập STT model:

```text
fixed WAV
   ↓
STT model
   ↓
transcript
```

Không đưa ALSA, microphone, VAD endpoint, pre-roll hoặc speech gating vào phép so sánh.

## Output

Runner tạo:

```text
logs/benchmarks/stt/model_comparison/<run-id>/
├── metadata.json
├── samples.jsonl
├── summary.json
├── summary.md
└── raw/
    ├── whisper_tiny_en/
    ├── zipformer_20m/
    └── zipformer_2023_06_21/
```

`logs/` là ignored generated output.

## Metric

Mỗi sample:

- reference;
- hypothesis;
- normalized exact match;
- WER;
- audio duration;
- sherpa internal decode seconds;
- RTF;
- process wall time;
- average CPU;
- sampled peak CPU;
- sampled peak RSS;
- exit status;
- raw stdout/stderr.

Summary:

- mean WER;
- exact / N;
- decode mean / median / p95;
- mean RTF;
- mean CPU;
- maximum sampled CPU;
- maximum peak RSS;
- errors / parse failures.

CPU có thể lớn hơn 100% vì process có thể sử dụng nhiều hơn một core.

`decode_seconds`/`RTF` ưu tiên timing do sherpa-onnx in ra. `process_wall_seconds` bao gồm model load/startup + decode + teardown, nên không dùng thay decode latency.

## Workflow

Source benchmark phải được phát triển trên HOST.

HOST:

```bash
python3 -m py_compile benchmarks/stt/model_comparison/*.py
git diff --check

git add benchmarks/stt/model_comparison
git commit -m "bench: add STT model comparison benchmark"
git push origin dev
```

Jetson:

```bash
git pull origin dev
```

Smoke test tracked runner với 1 WAV/model:

```bash
python3 benchmarks/stt/model_comparison/benchmark_stt_models.py \
  --condition clean \
  --limit 1
```

Nếu cả 3 model PASS, chạy official 15 × 3:

```bash
python3 benchmarks/stt/model_comparison/benchmark_stt_models.py \
  --condition clean
```

Không chạy song song 3 model. Chạy tuần tự để tránh tranh CPU/RAM và làm sai resource measurement.

## Rebuild summary

```bash
python3 benchmarks/stt/model_comparison/summarize_results.py \
  logs/benchmarks/stt/model_comparison/<run-id>
```

## Accepted result

Sau khi review result trên HOST, chỉ accepted conclusion mới được migrate vào:

```text
docs/stt/BENCHMARK.md
```

Raw result không commit.
