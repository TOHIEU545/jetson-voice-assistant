# M07 — Smart Turn + Streaming Zipformer

Purpose: measure whether Smart Turn reduces premature VAD turn splits when integrated with the primary streaming Zipformer backend, and quantify the endpoint-latency / Smart Turn compute trade-off.

## One-command benchmark

From repository root on Jetson:

```bash
./benchmarks/stt/M07_smart_turn_zipformer/run.sh
```

That is the only command required for a normal M07 rerun.

`run.sh` automatically validates `prepared_en_20`, prepares ALSA Loopback, runs the same 20 WAV files with Smart Turn OFF and ON, stores raw per-case logs, writes `results.jsonl`, `summary.json`, and `SUMMARY.md`, and cleans up loopback only if this run loaded it.

Runtime outputs are stored under:

```text
logs/benchmarks/stt/M07_smart_turn_zipformer/<timestamp>/
```

## Fixed configuration

- STT: streaming Zipformer 2023-06-21
- VAD: Silero
- GTCRN: OFF
- Speculative Turn: OFF
- Input: `data/stt/eot_bench/prepared_en_20/`
- Playback: `plughw:Loopback,0,0`
- Capture: `plughw:Loopback,1,0`

Each dataset row is one complete user turn:

- `SINGLE_TURN`: exactly one transcript
- `FALSE_CUTOFF`: more than one transcript for one dataset turn
- `EOT_MISS`: no transcript after the complete WAV finishes

Each WAV is isolated in its own runtime process so an EOT miss cannot leak held audio into the next benchmark case. Model load time is reported separately and is not treated as endpoint latency.
