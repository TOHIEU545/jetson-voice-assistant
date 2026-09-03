#!/usr/bin/env python3
"""Prepare a fixed 20-turn English LiveKit EoT subset for M07.

The full official dataset remains only as parquet under source/.
Only 20 representative WAV files are extracted for Jetson benchmarking.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq
import soundfile as sf
from huggingface_hub import HfApi, hf_hub_download

DATASET_REPO = "livekit/eot-bench-data"
LANGUAGE = "en"
EXPECTED_SR = 16000
TARGET_TURNS = 20


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
        default=Path("data/stt/eot_bench/prepared_en_20"),
    )
    p.add_argument("--revision", default=None)
    return p.parse_args()


def json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, bytes):
        raise TypeError("Unexpected raw bytes outside audio")
    return obj


def label_spans(spans: Any) -> list[dict[str, Any]]:
    spans = json_ready(spans or [])
    if not spans:
        raise ValueError("Row has no silence_spans")

    out = []
    last = len(spans) - 1
    for i, span in enumerate(spans):
        item = dict(span)
        item["label"] = "eot" if i == last else "hold"
        out.append(item)
    return out


def extract_audio(audio_obj: Any) -> tuple[np.ndarray, int]:
    if not isinstance(audio_obj, dict):
        raise TypeError(f"Unexpected audio object: {type(audio_obj)!r}")

    raw = audio_obj.get("bytes")
    if raw is None:
        raise ValueError("Audio bytes missing from parquet row")

    wav, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if wav.ndim != 1:
        raise ValueError(f"Expected mono audio, got shape={wav.shape}")
    if sr != EXPECTED_SR:
        raise ValueError(f"Expected {EXPECTED_SR} Hz, got {sr} Hz")
    return wav, sr


def sample_across_duration(rows: list[dict[str, Any]], want: int):
    if not rows or want <= 0:
        return []

    rows = sorted(rows, key=lambda r: (float(r["duration"]), str(r["id"])))
    if len(rows) <= want:
        return rows
    if want == 1:
        return [rows[len(rows) // 2]]

    idxs = [round(i * (len(rows) - 1) / (want - 1)) for i in range(want)]
    picked = []
    used = set()
    for idx in idxs:
        rid = str(rows[idx]["id"])
        if rid not in used:
            picked.append(rows[idx])
            used.add(rid)

    for row in rows:
        if len(picked) >= want:
            break
        rid = str(row["id"])
        if rid not in used:
            picked.append(row)
            used.add(rid)

    return picked[:want]


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    output_dir = args.output_dir.resolve()
    audio_dir = output_dir / "audio"

    source_dir.mkdir(parents=True, exist_ok=True)

    api = HfApi()
    revision = args.revision or api.dataset_info(DATASET_REPO).sha

    print(f"Dataset : {DATASET_REPO}")
    print(f"Revision: {revision}")
    print(f"Target  : {TARGET_TURNS} turns")

    repo_files = api.list_repo_files(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        revision=revision,
    )

    parquet_files = sorted(
        f for f in repo_files
        if f.startswith("data/en/validation-") and f.endswith(".parquet")
    )
    if not parquet_files:
        raise RuntimeError("No English validation parquet found")

    local_parquets = []
    for filename in parquet_files:
        local = hf_hub_download(
            repo_id=DATASET_REPO,
            repo_type="dataset",
            filename=filename,
            revision=revision,
            local_dir=str(source_dir),
        )
        local_parquets.append(Path(local))

    rows = []
    for parquet_path in local_parquets:
        table = pq.read_table(parquet_path)
        required = {"id", "audio", "language", "duration", "silence_spans", "words", "messages"}
        missing = required.difference(table.column_names)
        if missing:
            raise RuntimeError(f"Missing columns: {sorted(missing)}")

        for row in table.to_pylist():
            if row["language"] != LANGUAGE:
                continue
            spans = label_spans(row["silence_spans"])
            row["_spans"] = spans
            row["_hold_count"] = sum(1 for s in spans if s["label"] == "hold")
            rows.append(row)

    if len(rows) < TARGET_TURNS:
        raise RuntimeError(f"Only {len(rows)} English turns available")

    groups = {
        "0_hold": [r for r in rows if r["_hold_count"] == 0],
        "1_hold": [r for r in rows if r["_hold_count"] == 1],
        "2_hold": [r for r in rows if r["_hold_count"] == 2],
        "3plus_hold": [r for r in rows if r["_hold_count"] >= 3],
    }

    selected = []
    for name in ("0_hold", "1_hold", "2_hold", "3plus_hold"):
        selected.extend(sample_across_duration(groups[name], 5))

    selected_ids = {str(r["id"]) for r in selected}
    if len(selected) < TARGET_TURNS:
        remaining = sorted(
            (r for r in rows if str(r["id"]) not in selected_ids),
            key=lambda r: (r["_hold_count"], float(r["duration"]), str(r["id"])),
        )
        for row in remaining:
            selected.append(row)
            if len(selected) == TARGET_TURNS:
                break

    selected = selected[:TARGET_TURNS]
    if len({str(r["id"]) for r in selected}) != TARGET_TURNS:
        raise RuntimeError("Subset contains duplicate IDs")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    total_hold = 0

    with (output_dir / "manifest.jsonl").open("w", encoding="utf-8") as mf:
        for row in selected:
            turn_id = str(row["id"])
            wav, sr = extract_audio(row["audio"])
            wav_path = audio_dir / f"{turn_id}.wav"
            sf.write(wav_path, wav, sr, subtype="PCM_16")

            item = {
                "id": turn_id,
                "audio": f"audio/{turn_id}.wav",
                "language": row["language"],
                "duration": float(row["duration"]),
                "sample_rate": sr,
                "hold_count": row["_hold_count"],
                "silence_spans": row["_spans"],
                "words": json_ready(row["words"]),
                "messages": json_ready(row["messages"]),
            }
            total_hold += row["_hold_count"]
            manifest_rows.append(item)
            mf.write(json.dumps(item, ensure_ascii=False) + "\n")

    meta = {
        "dataset": DATASET_REPO,
        "revision": revision,
        "language": LANGUAGE,
        "split": "validation",
        "source_rows": len(rows),
        "selected_turns": TARGET_TURNS,
        "selection": {
            "method": "deterministic stratified subset",
            "strata": {"0_hold": 5, "1_hold": 5, "2_hold": 5, "3plus_hold": 5},
            "within_stratum": "sample across duration range",
        },
        "hold_spans": total_hold,
        "eot_spans": TARGET_TURNS,
        "sample_rate_hz": EXPECTED_SR,
        "audio_format": "WAV PCM16 mono",
        "turns": [
            {
                "id": r["id"],
                "duration": r["duration"],
                "hold_count": r["hold_count"],
            }
            for r in manifest_rows
        ],
    }

    (output_dir / "source.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (source_dir / "revision.txt").write_text(revision + "\n", encoding="utf-8")

    print("\n=== M07 PREPARATION SUMMARY ===")
    print(f"Source rows : {len(rows)}")
    print(f"Prepared    : {len(manifest_rows)}")
    print(f"HOLD spans  : {total_hold}")
    print(f"EOT spans   : {TARGET_TURNS}")
    for name in ("0_hold", "1_hold", "2_hold", "3plus_hold"):
        if name == "0_hold":
            n = sum(r["hold_count"] == 0 for r in manifest_rows)
        elif name == "1_hold":
            n = sum(r["hold_count"] == 1 for r in manifest_rows)
        elif name == "2_hold":
            n = sum(r["hold_count"] == 2 for r in manifest_rows)
        else:
            n = sum(r["hold_count"] >= 3 for r in manifest_rows)
        print(f"{name:12}: {n}")

    print(f"Output      : {output_dir}")
    print("\nPREPARATION PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise
