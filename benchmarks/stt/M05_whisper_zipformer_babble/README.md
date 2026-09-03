# M05 — Whisper và Zipformer trong Babble noise nặng

M05 so sánh hai production STT runtime trên hai mức Babble khó nhất đã được M04 chuẩn bị.

## One-command benchmark

Từ repository root trên Jetson:

```bash
./benchmarks/stt/M05_whisper_zipformer_babble/run.sh
```

Đây là command duy nhất cần dùng cho normal rerun. `run.sh` validate fixed dataset, chuẩn bị ALSA Loopback và chạy đủ ba order A→B, B→A, A→B. Loopback chỉ được cleanup nếu chính wrapper đã load nó.

Mỗi campaign được lưu dưới:

```text
logs/benchmarks/stt/M05_whisper_zipformer_babble/<timestamp>/
├── run_1_whisper_first/
├── run_2_zipformer_first/
└── run_3_whisper_first/
```

## Fixed configuration

```text
VoiceBank clean speech + MS-SNSD Babble tại 5/0 dB
  → ALSA Loopback
  → Silero VAD
  → Whisper Tiny.en hoặc Zipformer 2023-06-21
  → transcript + latency + CPU/RAM
```

- GTCRN: OFF
- Smart Turn: OFF
- Speculative: OFF
- Barge-in: ON
- Dataset: `data/stt/ms_snsd/mixed/voicebank_prepared_15/babble/`

Runner lấy command của từng backend từ `app.config.build_speech_command()`; M05 không thay đổi runtime/model integration.

Mỗi independent run gồm `15 samples × 2 SNR × 2 models = 60 turns`. Ba run dùng thứ tự:

```text
Run 1: Whisper   → Zipformer
Run 2: Zipformer → Whisper
Run 3: Whisper   → Zipformer
```

Metric chính là Corpus WER, Exact Match, TOTAL mean/p95, startup → READY, CPU/RAM và ONNX footprint. `TOTAL` là metric realtime chính; `STT` latency chỉ là diagnostic vì hai backend có runtime architecture khác nhau.

## Developer/debug commands

Các command dưới đây chỉ dành cho validation hoặc smoke test; normal rerun dùng `run.sh`.

```bash
python3 benchmarks/stt/M05_whisper_zipformer_babble/benchmark_model_noise.py \
  --self-test

python3 benchmarks/stt/M05_whisper_zipformer_babble/benchmark_model_noise.py \
  --validate-dataset
```

Smoke test chạy `2 SNR × 1 sample × 2 models = 4 turns` sau khi chuẩn bị Loopback:

```bash
./scripts/prepare_alsa_loopback.sh load
python3 benchmarks/stt/M05_whisper_zipformer_babble/benchmark_model_noise.py \
  --limit-per-snr 1
```

Runner tự tạo `summary.json`, `summary.md` và `paired_effect.json`; `summarize_results.py` chỉ dùng để rebuild summary từ một run đã có.
