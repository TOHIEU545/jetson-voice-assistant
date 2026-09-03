#!/usr/bin/env python3
"""
Prepare the English LiveKit EoT benchmark subset for M07.

Source:
  https://huggingface.co/datasets/livekit/eot-bench-data

The official dataset schema contains:
  id, audio, language, duration, silence_spans, words, messages

Per the dataset card:
  - each row is one complete user turn
  - every silence span except the final one is HOLD
  - the final silence span is EOT
  - audio is 16 kHz mono WAV
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import soundfile as sf
from huggingface_hub import HfApi, hf_hub_download


DATASET_REPO = "livekit/eot-bench-data"
LANGUAGE = "en"
EXPECTED_ROWS = 400
EXPECTED_SR = 16000


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--source-dir",
        type=Path,
        default=Path("data/stt/eot_bench/source/livekit_en"),
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/stt/eot_bench/prepared_en_400"),
    )
    p.add_argument(
        "--revision",
        default=None,
        help="Dataset git revision. Default: current dataset HEAD, recorded into source.json.",
    )
    return p.parse_args()


def json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, bytes):
        raise TypeError("Unexpected raw bytes outside the audio field")
    return obj


def extract_audio(audio_obj: Any) -> tuple[np.ndarray, int]:
    """
    Hugging Face parquet audio is normally a struct:
      {"bytes": <wav bytes>, "path": "..."}
    """
    if not isinstance(audio_obj, dict):
        raise TypeError(f"Unexpected audio object type: {type(audio_obj)!r}")

    raw = audio_obj.get("bytes")
    if raw is None:
        raise ValueError(
            "Audio bytes are missing from the parquet row; "
            f"path={audio_obj.get('path')!r}"
        )

    wav, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)

    if wav.ndim != 1:
        raise ValueError(f"Expected mono audio, got shape={wav.shape}")

    if sr != EXPECTED_SR:
        raise ValueError(f"Expected {EXPECTED_SR} Hz audio, got {sr} Hz")

    return wav, sr


def label_silence_spans(spans: Any) -> list[dict[str, Any]]:
    spans = json_ready(spans or [])
    if not spans:
        raise ValueError("Row has no silence_spans")

    labeled: list[dict[str, Any]] = []
    last = len(spans) - 1

    for i, span in enumerate(spans):
        if not isinstance(span, dict):
            raise TypeError(f"Unexpected silence span: {span!r}")

        item = dict(span)
        item["label"] = "eot" if i == last else "hold"
        labeled.append(item)

    return labeled


def main() -> int:
    args = parse_args()

    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    audio_dir = output_dir / "audio"

    source_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    api = HfApi()
    revision = args.revision or api.dataset_info(DATASET_REPO).sha

    print(f"Dataset : {DATASET_REPO}")
    print(f"Revision: {revision}")
    print(f"Language: {LANGUAGE}")

    repo_files = api.list_repo_files(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        revision=revision,
    )

    parquet_files = sorted(
        f for f in repo_files
        if f.startswith(f"data/{LANGUAGE}/validation-") and f.endswith(".parquet")
    )

    if not parquet_files:
        raise RuntimeError(
            f"No English validation parquet found under data/{LANGUAGE}/"
        )

    print("Parquet files:")
    for name in parquet_files:
        print(f"  - {name}")

    local_parquets: list[Path] = []
    for filename in parquet_files:
        local = hf_hub_download(
            repo_id=DATASET_REPO,
            repo_type="dataset",
            filename=filename,
            revision=revision,
            local_dir=str(source_dir),
        )
        local_parquets.append(Path(local))

    manifest_path = output_dir / "manifest.jsonl"
    seen_ids: set[str] = set()
    count = 0
    hold_count = 0
    eot_count = 0

    with manifest_path.open("w", encoding="utf-8") as mf:
        for parquet_path in local_parquets:
            table = pq.read_table(parquet_path)

            required = {
                "id",
                "audio",
                "language",
                "duration",
                "silence_spans",
                "words",
                "messages",
            }
            missing = required.difference(table.column_names)
            if missing:
                raise RuntimeError(
                    f"{parquet_path} missing required columns: {sorted(missing)}"
                )

            for row in table.to_pylist():
                if row["language"] != LANGUAGE:
                    raise ValueError(
                        f"Expected language={LANGUAGE!r}, got {row['language']!r}"
                    )

                turn_id = str(row["id"])
                if turn_id in seen_ids:
                    raise ValueError(f"Duplicate id: {turn_id}")
                seen_ids.add(turn_id)

                wav, sr = extract_audio(row["audio"])
                wav_path = audio_dir / f"{turn_id}.wav"

                # Canonical benchmark copy: PCM16, mono, 16 kHz.
                sf.write(wav_path, wav, sr, subtype="PCM_16")

                spans = label_silence_spans(row["silence_spans"])
                hold_count += sum(1 for s in spans if s["label"] == "hold")
                eot_count += sum(1 for s in spans if s["label"] == "eot")

                item = {
                    "id": turn_id,
                    "audio": str(Path("audio") / f"{turn_id}.wav"),
                    "language": row["language"],
                    "duration": float(row["duration"]),
                    "sample_rate": sr,
                    "silence_spans": spans,
                    "words": json_ready(row["words"]),
                    "messages": json_ready(row["messages"]),
                }

                mf.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1

    source_meta = {
        "dataset": DATASET_REPO,
        "revision": revision,
        "language": LANGUAGE,
        "split": "validation",
        "parquet_files": parquet_files,
        "prepared_rows": count,
        "hold_spans": hold_count,
        "eot_spans": eot_count,
        "labeling_rule": (
            "For each complete user turn, every silence span except the final "
            "span is HOLD; the final silence span is EOT."
        ),
        "sample_rate_hz": EXPECTED_SR,
        "audio_format": "WAV PCM16 mono",
    }

    (output_dir / "source.json").write_text(
        json.dumps(source_meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (source_dir / "revision.txt").write_text(
        revision + "\n",
        encoding="utf-8",
    )

    print()
    print("=== PREPARATION SUMMARY ===")
    print(f"Rows      : {count}")
    print(f"HOLD spans: {hold_count}")
    print(f"EOT spans : {eot_count}")
    print(f"Manifest  : {manifest_path}")
    print(f"Audio dir : {audio_dir}")
    print(f"Metadata  : {output_dir / 'source.json'}")

    if count != EXPECTED_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_ROWS} English turns, prepared {count}"
        )

    if eot_count != count:
        raise RuntimeError(
            f"Expected exactly one EOT span per turn: rows={count}, eot={eot_count}"
        )

    print()
    print("PREPARATION PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
