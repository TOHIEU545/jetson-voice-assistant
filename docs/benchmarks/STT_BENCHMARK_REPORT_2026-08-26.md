# STT Benchmark Report — Jetson Voice Assistant

**Date:** 2026-08-26  
**Target:** Jetson Nano 4GB  
**Project:** `jetson-voice-assistant`  
**Benchmark scope:** STT-only, fixed reference audio, CPU inference

## 1. Objective

Compare the three STT backends currently available in the project under identical recorded audio:

- Whisper Tiny.en
- Streaming Zipformer 20M — 2023-02-17
- Streaming Zipformer — 2023-06-21

Metrics: recognition accuracy, noise robustness, RTF, memory usage, and suitability for the deployed voice-assistant pipeline.

## 2. Reference sentences

1. `What is embedded programming?`
2. `Can you explain how UART communication works in an embedded system?`
3. `Today I want to understand how a voice assistant can listen to my speech, recognize my words accurately, and respond quickly even when there is background noise.`

## 3. Noise conditions

| Condition | Description |
|---|---|
| `02_fan` | Continuous fan noise |
| `03_fan_mouse` | Fan + mouse activity |
| `04_fan_mouse_keyboard` | Fan + mouse + keyboard activity |

The original recordings were 16 kHz, mono, 16-bit PCM WAV files.

## 4. Audio preparation

Original files:

```text
logs/benchmarks/stt/reference_audio/
├── 02_fan.wav
├── 03_fan_mouse.wav
└── 04_fan_mouse_keyboard.wav
```

The initial WAV headers were not finalized correctly after stopping `arecord` with `Ctrl+C`, causing the files to report `1073741824` frames and about `67108.864 s` duration. Sherpa-ONNX then failed with `std::bad_alloc`.

After repairing RIFF/data chunk sizes from the actual file sizes, the correct durations were:

| Recording | Duration |
|---|---:|
| `02_fan.wav` | 36.750 s |
| `03_fan_mouse.wav` | 41.250 s |
| `04_fan_mouse_keyboard.wav` | 39.625 s |

Silero VAD was then used with the project baseline:

```text
threshold            = 0.5
min_silence_duration = 0.5 s
min_speech_duration  = 0.25 s
window_size          = 512
```

Detected speech regions:

```text
02_fan
3.270  -- 4.908
13.062 -- 17.164
25.702 -- 35.628

03_fan_mouse
4.390  -- 14.252
22.150 -- 26.380
34.470 -- 36.012

04_fan_mouse_keyboard
5.734  -- 7.404
14.342 -- 18.668
26.598 -- 36.556
```

A 300 ms pre/post padding was added around each speech segment.

Final benchmark clips:

```text
logs/benchmarks/stt/reference_segments/
├── 02_fan/
│   ├── 01_short.wav
│   ├── 02_uart.wav
│   └── 03_long.wav
├── 03_fan_mouse/
│   ├── 01_short.wav
│   ├── 02_uart.wav
│   └── 03_long.wav
└── 04_fan_mouse_keyboard/
    ├── 01_short.wav
    ├── 02_uart.wav
    └── 03_long.wav
```

## 5. Benchmark matrix

```text
3 STT models
× 3 noise conditions
× 3 sentences
= 27 runs
```

All 27 runs completed without `std::bad_alloc`, segmentation faults, aborts, kills, or runtime errors.

## 6. Overall results

| Model | Exact | Avg WER | Avg RTF | Max RSS |
|---|---:|---:|---:|---:|
| Whisper Tiny.en | **6 / 9** | **6.06%** | 0.668 | 355.4 MB |
| Zipformer 20M | 0 / 9 | 52.41% | **0.267** | **218.8 MB** |
| Zipformer 2023-06-21 | 5 / 9 | 6.88% | 0.613 | 760.8 MB |

## 7. Whisper Tiny.en

| Condition | Sentence | Exact | WER | Decode | RTF | RAM |
|---|---|---:|---:|---:|---:|---:|
| fan | short | Yes | 0.00% | 1.776 s | 0.794 | 312.0 MB |
| fan | UART | No | 18.18% | 2.992 s | 0.636 | 313.3 MB |
| fan | long | Yes | 0.00% | 6.095 s | 0.579 | 352.7 MB |
| fan + mouse | short | Yes | 0.00% | 1.739 s | 0.812 | 315.0 MB |
| fan + mouse | UART | No | 18.18% | 3.064 s | 0.634 | 313.7 MB |
| fan + mouse | long | Yes | 0.00% | 5.985 s | 0.572 | 351.4 MB |
| fan + mouse + keyboard | short | Yes | 0.00% | 1.792 s | 0.789 | 313.5 MB |
| fan + mouse + keyboard | UART | No | 18.18% | 3.041 s | 0.617 | 313.9 MB |
| fan + mouse + keyboard | long | Yes | 0.00% | 6.090 s | 0.577 | 355.4 MB |

Recurring error:

```text
UART -> "you are"
```

Assessment: best WER, stable under the tested noise conditions, moderate RAM, but offline recognition adds post-speech latency.

## 8. Zipformer 20M

| Condition | Sentence | Exact | WER | Decode | RTF | RAM |
|---|---|---:|---:|---:|---:|---:|
| fan | short | No | 100.00% | 0.690 s | 0.310 | 213.9 MB |
| fan | UART | No | 36.36% | 1.200 s | 0.260 | 218.8 MB |
| fan | long | No | 14.81% | 2.500 s | 0.230 | 213.8 MB |
| fan + mouse | short | No | 100.00% | 0.690 s | 0.320 | 215.3 MB |
| fan + mouse | UART | No | 45.45% | 1.200 s | 0.260 | 215.8 MB |
| fan + mouse | long | No | 14.81% | 2.500 s | 0.230 | 212.8 MB |
| fan + mouse + keyboard | short | No | 100.00% | 0.690 s | 0.300 | 215.2 MB |
| fan + mouse + keyboard | UART | No | 45.45% | 1.300 s | 0.260 | 214.1 MB |
| fan + mouse + keyboard | long | No | 14.81% | 2.400 s | 0.230 | 214.2 MB |

Representative failures:

```text
What is embedded programming?
-> DDED PROGRAMING

Can you explain how UART communication works in an embedded system?
-> U EXPLAIN HOW YOU ARE COMMUNICATION WORKS IN AN EMBEDDED SYSTEM
```

Assessment: fastest and lightest model, but current accuracy is insufficient for the primary assistant backend. Keep as a lightweight/speed-reference backend.

## 9. Zipformer 2023-06-21

| Condition | Sentence | Exact | WER | Decode | RTF | RAM |
|---|---|---:|---:|---:|---:|---:|
| fan | short | Yes | 0.00% | 1.600 s | 0.700 | 758.4 MB |
| fan | UART | No | 18.18% | 2.800 s | 0.600 | 758.4 MB |
| fan | long | Yes | 0.00% | 5.600 s | 0.540 | 758.4 MB |
| fan + mouse | short | Yes | 0.00% | 1.600 s | 0.730 | 759.0 MB |
| fan + mouse | UART | No | 18.18% | 2.900 s | 0.590 | 758.2 MB |
| fan + mouse | long | No | 7.41% | 5.600 s | 0.540 | 759.7 MB |
| fan + mouse + keyboard | short | Yes | 0.00% | 1.600 s | 0.690 | 760.8 MB |
| fan + mouse + keyboard | UART | No | 18.18% | 3.000 s | 0.600 | 757.3 MB |
| fan + mouse + keyboard | long | Yes | 0.00% | 5.600 s | 0.530 | 758.3 MB |

Recurring error:

```text
UART -> YOU ARE
```

One additional minor error:

```text
Today -> TO DAY
```

Assessment: accuracy is close to Whisper while supporting true streaming. It is the selected primary streaming candidate, but its ~761 MB STT RSS must be checked again in the complete Jetson pipeline.

## 10. Backend decision

Keep all three backends available:

| Backend | Role |
|---|---|
| `whisper` | Stable accuracy baseline / fallback |
| `zipformer_20m` | Experimental lightweight / speed baseline |
| `zipformer_2023_06_21` | Selected primary streaming candidate |

Do not delete any of the three models at this stage.

The launcher should continue to support:

```bash
VOICE_ASSISTANT_STT="whisper"
VOICE_ASSISTANT_STT="zipformer_20m"
VOICE_ASSISTANT_STT="zipformer_2023_06_21"
```

## 11. Interpretation of RTF vs runtime latency

The fixed-WAV benchmark measures total processing of a completed clip. It does not show the main benefit of streaming recognition.

Whisper runtime:

```text
speech -> endpoint -> offline decode -> final transcript
```

Streaming Zipformer runtime:

```text
speech starts -> decode continuously while speaking
              -> endpoint -> remaining queue/finalization
              -> final transcript
```

Therefore the larger Zipformer's value is not just its WAV RTF. The key metric for deployment remains:

```text
speech end -> final transcript
```

## 12. Technical vocabulary issue

All three model families misrecognized the technical term:

```text
UART -> "you are"
```

This is treated as a separate context-bias / technical-vocabulary problem rather than a streaming-architecture failure.

Future work, after the streaming architecture is stable, may evaluate context bias/hotwords for terms such as:

```text
UART
SPI
I2C
GPIO
STM32
Jetson
```

## 13. Next development step

Next isolated architecture change:

```text
speech-gated PCM + pre-roll
```

Current:

```text
Mic
-> all PCM including inter-turn silence/noise
-> stream_queue
-> OnlineRecognizer
```

Target:

```text
Mic
-> VAD
   ├── no speech: keep short rolling pre-roll
   └── speech detected:
       ├── flush pre-roll
       ├── enqueue speech PCM continuously
       └── endpoint -> enqueue TurnEnd
-> STT worker
-> OnlineRecognizer
```

Goal: avoid feeding continuous inter-turn noise/silence into Zipformer while preserving the start of speech and keeping true streaming.

## 14. Dependency/model control recommendation

All three STT model definitions should be controlled from the HOST repository even though model weights remain ignored.

Recommended model status:

```text
Whisper Tiny.en
status: stable baseline / fallback

Zipformer 20M
status: benchmarked lightweight / experimental backend

Zipformer 2023-06-21
status: benchmarked selected streaming candidate
```

Dependency metadata should record:

- canonical model name,
- official source/download URL,
- expected model directory,
- expected filenames,
- checksums,
- compatible runtime/version,
- benchmark status,
- backend role,
- download/setup script or command.

Do not commit:

```text
*.onnx
large model archives
raw reference WAVs
runtime benchmark logs
temporary benchmark artifacts
```

Commit the report, dependency/model metadata, checksums/download information, and reproducible benchmark tooling.

## 15. Benchmark artifacts

Runtime artifacts:

```text
logs/benchmarks/stt/reference_audio/
logs/benchmarks/stt/reference_segments/
logs/benchmarks/stt/reference_results/
```

Generated summary:

```text
logs/benchmarks/stt/reference_results/summary.tsv
```

The durable repository record should be this Markdown report plus dependency/model metadata and benchmark scripts.
