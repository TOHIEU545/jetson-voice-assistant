# STT Pipeline Model Comparison

Benchmark này so sánh ba STT backend **trong speech pipeline hiện tại của project**, không phải direct model decode.

## One-command benchmark

Từ repository root trên Jetson:

```bash
./benchmarks/stt/M01_model_comparison/run.sh
```

Đây là command duy nhất cần dùng cho một lần chạy M01 thông thường. `run.sh` kiểm tra input và dependency, chuẩn bị ALSA Loopback, chạy đủ ba backend, tự dọn Loopback nếu chính nó đã load, rồi in đường dẫn tới result và summary.

## Mục tiêu

Chứng minh backend nào phù hợp nhất cho Jetson Nano khi chạy trong architecture thực tế đã xây dựng:

```text
fixed clean WAV
      ↓
ALSA Loopback
      ↓
current project speech runtime
      ↓
Silero VAD
      ↓
backend architecture
      ↓
transcript + latency instrumentation
```

Whisper:

```text
VAD
→ resident offline STT worker
→ Whisper Tiny.en
```

Zipformer:

```text
VAD
→ rolling pre-roll / speech gating
→ streaming Zipformer
→ final transcript
```

Không benchmark lại continuous-vs-gated architecture. Hai Zipformer chạy bằng **streaming runtime hiện tại**, tức các optimization đã được project adopt vẫn được sử dụng.

## Backends

```text
whisper
zipformer_20m
zipformer_2023_06_21
```

Runner **không hard-code model path/thread/provider**.

Với mỗi backend, runner đặt environment rồi gọi:

```python
app.config.build_speech_command()
```

Do đó command benchmark bám theo config/source hiện tại của project.

Benchmark cố định:

```text
GTCRN       OFF
Smart Turn  OFF
Speculative OFF
Barge-in    ON
Input       ALSA Loopback
Condition   clean
```

## Vì sao dùng ALSA Loopback?

Direct WAV decoder sẽ bypass VAD, pre-roll và speech gating.

ALSA Loopback cho phép:

```text
WAV
→ aplay
→ virtual ALSA capture
→ exact runtime architecture
```

Ba backend nhận cùng fixed PCM nhưng vẫn đi qua speech frontend thực tế.

Expected devices:

```text
playback : plughw:Loopback,0,0
capture  : plughw:Loopback,1,0
```

## Metrics

### Accuracy

- corpus WER;
- per-sample WER;
- exact match / N;
- reference + hypothesis cho từng WAV.

### Realtime latency

- `VAD latency`: speech end → VAD endpoint (mean/median/p95/max trong JSON summary);
- `STT latency`: VAD endpoint → final transcript (mean/median/p95/max);
- `TOTAL latency`: speech end → final transcript (mean/median/p95/max);
- `STT p95`;
- `TOTAL p95`;
- independent `wall_end_to_transcript`: từ lúc `aplay` kết thúc tới lúc runtime phát transcript.

`TOTAL` là metric quan trọng nhất cho cảm giác realtime của speech frontend.

### Resource

- total ONNX model size referenced by the runtime command;
- runtime startup → `[READY]`;
- idle CPU;
- idle RSS;
- active CPU mean;
- active CPU peak;
- peak RSS;
- temperature/system snapshot trước và sau benchmark.

CPU >100% là bình thường khi process dùng nhiều hơn một core.

## Dataset

Default:

```text
data/stt/voicebank_demand/prepared_15/
├── clean/      # 15 WAV
├── noisy/
└── manifest.tsv
```

Vòng model-comparison hiện tại chỉ dùng `clean/`.

## Output

```text
logs/benchmarks/stt/M01_model_comparison/<run-id>/
├── metadata.json
├── samples.jsonl
├── summary.json
├── summary.md
├── whisper/
│   ├── command.txt
│   ├── runtime.log
│   └── model_metadata.json
├── zipformer_20m/
└── zipformer_2023_06_21/
```

Raw/generated result không commit.

## HOST validation

```bash
python3 -m py_compile \
  benchmarks/stt/M01_model_comparison/benchmark_stt_pipeline.py \
  benchmarks/stt/M01_model_comparison/summarize_results.py

python3 benchmarks/stt/M01_model_comparison/benchmark_stt_pipeline.py \
  --self-test

git diff --check
```

## Developer/debug commands

Các command dưới đây chỉ dành cho smoke test hoặc debug; normal rerun dùng `run.sh` ở đầu tài liệu.

Chuẩn bị loopback thủ công nếu cần debug:

```bash
./scripts/prepare_alsa_loopback.sh load
```

Sau khi pull:

```bash
python3 benchmarks/stt/M01_model_comparison/benchmark_stt_pipeline.py \
  --condition clean \
  --limit 1
```

Đây là `1 WAV × 3 backend`.

Nếu PASS, chạy official:

```bash
python3 benchmarks/stt/M01_model_comparison/benchmark_stt_pipeline.py \
  --condition clean
```

Tức `15 WAV × 3 backend = 45 turns`.

Runtime được load **một lần cho mỗi backend** và giữ resident trong toàn bộ 15 turns. Không reload model mỗi WAV.

## Sau benchmark

Đọc:

```bash
cat logs/benchmarks/stt/M01_model_comparison/<run-id>/summary.md
```

Accepted conclusion mới được migrate vào:

```text
docs/stt/BENCHMARK.md
```

Raw result vẫn ở `logs/`.
