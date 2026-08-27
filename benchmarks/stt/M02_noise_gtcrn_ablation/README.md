# M02 — Noise + GTCRN Ablation

## Mục tiêu

Sau M01, backend STT được cố định:

```text
Zipformer 2023-06-21
```

M02 chỉ thay đổi một biến:

```text
GTCRN OFF
vs
GTCRN ON
```

Dataset:

```text
data/stt/voicebank_demand/prepared_15/noisy/
```

Mục tiêu là trả lời:

> GTCRN có cải thiện nhận dạng tiếng nói trong noise đủ nhiều để bù lại chi phí latency, CPU và RAM hay không?

## Pipeline

GTCRN OFF:

```text
noisy WAV
  ↓
ALSA Loopback
  ↓
Silero VAD
  ↓
optimized streaming Zipformer 2023-06-21
  ↓
transcript
```

GTCRN ON:

```text
noisy WAV
  ↓
ALSA Loopback
  ↓
GTCRN
  ↓
Silero VAD
  ↓
optimized streaming Zipformer 2023-06-21
  ↓
transcript
```

Runner gọi trực tiếp:

```python
app.config.build_speech_command()
```

và xác nhận command thật sự có/không có:

```text
--speech-denoiser-gtcrn-model=...
```

tương ứng với GTCRN ON/OFF.

## Metric

Accuracy:

- Corpus WER
- Exact match
- WER từng sample
- paired comparison cùng một WAV

Realtime:

- VAD mean / median / p95 / max
- STT mean / median / p95 / max
- TOTAL mean / median / p95 / max
- wall-after-audio

Resource:

- startup → READY
- idle CPU
- idle RSS
- active CPU
- CPU peak
- peak RSS
- ONNX footprint

Runner cũng tính trực tiếp:

```text
GTCRN ON - GTCRN OFF
```

cho:

- WER
- exact match
- TOTAL latency
- CPU
- RAM

## Chuẩn bị

Sau reboot Jetson:

```bash
cd ~/jetson-voice-assistant

./benchmarks/stt/M01_model_comparison/prepare_alsa_loopback.sh load
```

## HOST validation

```bash
python3 -m py_compile \
  benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py \
  benchmarks/stt/M02_noise_gtcrn_ablation/summarize_results.py

python3 \
  benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py \
  --self-test

git diff --check
```

## Jetson smoke

Một WAV, cả GTCRN OFF và ON:

```bash
python3 \
  benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py \
  --limit 1
```

## Full run

```bash
python3 \
  benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py
```

Mỗi full run:

```text
15 noisy WAV × 2 configs = 30 turns
```

Để giảm bias do thứ tự/thermal, nếu chạy 3 lần thì nên đổi order:

Run 1:

```bash
python3 benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py \
  --order gtcrn_off,gtcrn_on
```

Run 2:

```bash
python3 benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py \
  --order gtcrn_on,gtcrn_off
```

Run 3:

```bash
python3 benchmarks/stt/M02_noise_gtcrn_ablation/benchmark_noise_gtcrn.py \
  --order gtcrn_off,gtcrn_on
```

## Output

```text
logs/benchmarks/stt/M02_noise_gtcrn_ablation/<run-id>/
├── metadata.json
├── samples.jsonl
├── summary.json
├── summary.md
├── paired_effect.json
├── gtcrn_off/
└── gtcrn_on/
```

## Quyết định sau M02

Nếu GTCRN giảm WER rõ rệt với overhead chấp nhận được:

```text
→ giữ GTCRN trong candidate production
```

Nếu GTCRN OFF và ON gần như giống nhau:

```text
→ chưa kết luận GTCRN vô ích
→ dataset hiện tại có thể quá dễ
→ chuyển M03_noise_snr_stress
```

M03 nên sử dụng noise mạnh hơn hoặc controlled SNR.
