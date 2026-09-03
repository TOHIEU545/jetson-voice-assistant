# M04 — Babble SNR Stress

M04 cố định backend `Zipformer 2023-06-21`, so sánh GTCRN OFF/ON trên VoiceBank clean speech trộn deterministic với MS-SNSD `Babble` tại 20/10/5/0 dB.

## One-command benchmark

Từ repository root trên Jetson:

```bash
./benchmarks/stt/M04_babble_snr_stress/run.sh
```

Đây là command duy nhất cần dùng cho normal rerun khi fixed dataset đã được chuẩn bị. `run.sh` validate manifest và toàn bộ WAV được tham chiếu, chuẩn bị ALSA Loopback, chạy hai cấu hình, tự dọn Loopback nếu chính nó đã load, rồi in đường dẫn output.

Runtime output:

```text
logs/benchmarks/stt/M04_babble_snr_stress/<run-id>/
├── metadata.json
├── samples.jsonl
├── summary.json
├── summary.md
├── paired_effect.json
├── gtcrn_off/
└── gtcrn_on/
```

## Fixed configuration

- STT: `Zipformer 2023-06-21`
- Noise: MS-SNSD `Babble`
- SNR: 20, 10, 5 và 0 dB
- Config: GTCRN OFF rồi GTCRN ON
- Input: `data/stt/ms_snsd/mixed/voicebank_prepared_15/babble/`
- Transport: fixed WAV qua ALSA Loopback

## Developer/debug commands

Dataset preparation không thuộc normal rerun. Chỉ chạy khi fixed input chưa tồn tại:

```bash
python3 benchmarks/stt/M04_babble_snr_stress/prepare_snr_dataset.py
```

Smoke test một sample cho mỗi SNR:

```bash
./scripts/prepare_alsa_loopback.sh load
python3 benchmarks/stt/M04_babble_snr_stress/benchmark_noise_snr.py \
  --limit-per-snr 1
```

Runner tự tạo `summary.json`, `summary.md` và `paired_effect.json`; `summarize_results.py` chỉ dùng để rebuild summary từ một run đã có.
