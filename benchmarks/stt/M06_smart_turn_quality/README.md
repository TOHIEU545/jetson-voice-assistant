# M06 — Smart Turn v3.2 standalone quality

M06 validates Smart Turn independently before integrating it into the
streaming Zipformer runtime in M07.

```text
Official Smart Turn v3.2 test data
  ↓
30 COMPLETE + 30 INCOMPLETE
  ↓
smart_turn_probe
  ↓
Probability
  ↓
Threshold = 0.5
  ↓
COMPLETE / INCOMPLETE
  ↓
Classification + latency metrics
```

Dataset:

```text
data/stt/smart_turn_v3_2_test/source/hf_selected_60/
├── audio/
├── manifest.tsv
└── source.json
```

Ground truth:

```text
endpoint_bool = 1 -> COMPLETE
endpoint_bool = 0 -> INCOMPLETE
```

Positive class is `COMPLETE`.

A false positive means an INCOMPLETE turn is classified COMPLETE and is
therefore the dangerous premature-turn-cut case.

## Build probe

```bash
./benchmarks/stt/M06_smart_turn_quality/build_probe.sh
```

## Checks

```bash
python3 -m py_compile \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  benchmarks/stt/M06_smart_turn_quality/summarize_results.py

python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --self-test

python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --validate-dataset
```

Expected dataset validation:

```text
Samples    : 60
COMPLETE   : 30
INCOMPLETE : 30
VALIDATION PASS
```

## Smoke

```bash
python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py \
  --limit-per-class 1
```

This runs:

```text
1 COMPLETE + 1 INCOMPLETE = 2 samples
```

## Full benchmark

```bash
python3 \
  benchmarks/stt/M06_smart_turn_quality/benchmark_smart_turn.py
```

Each run contains:

```text
30 COMPLETE + 30 INCOMPLETE = 60 samples
```

Results:

```text
logs/benchmarks/stt/M06_smart_turn_quality/<timestamp>/
├── samples.jsonl
├── smart_turn_v3_2/
│   └── config_metadata.json
├── summary.json
└── summary.md
```

Primary metrics:

- Accuracy;
- Precision;
- Recall;
- F1;
- FPR;
- FNR;
- TP / TN / FP / FN;
- audio preparation latency;
- feature extraction latency;
- ONNX inference latency;
- TOTAL latency.

`TOTAL` is:

```text
audio preparation + feature extraction + ONNX inference
```

Model load latency is reported separately because the production
SmartTurnRuntime keeps the model resident instead of loading it for every
turn.

## Rebuild summary

```bash
python3 \
  benchmarks/stt/M06_smart_turn_quality/summarize_results.py \
  logs/benchmarks/stt/M06_smart_turn_quality/<timestamp>
```
