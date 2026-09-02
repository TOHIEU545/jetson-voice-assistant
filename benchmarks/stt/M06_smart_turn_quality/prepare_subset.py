#!/usr/bin/env python3

import argparse
import csv
import io
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf
from datasets import Audio, load_dataset
from huggingface_hub import HfApi

DATASET_ID = "pipecat-ai/smart-turn-data-v3.2-test"
SPLIT = "train"
EXPECTED_SR = 16000


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        default=(
            "data/stt/smart_turn_v3_2_test/"
            "source/hf_selected_60"
        ),
    )

    parser.add_argument(
        "--per-class",
        type=int,
        default=30,
    )

    parser.add_argument(
        "--revision",
        default=None,
        help="Pinned Hugging Face dataset revision.",
    )

    parser.add_argument(
        "--include-synthetic",
        action="store_true",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
    )

    return parser.parse_args()


def as_bool(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, np.integer)):
        return bool(value)

    text = str(value).strip().lower()

    if text in ("1", "true", "yes"):
        return True

    if text in ("0", "false", "no", "", "none"):
        return False

    raise ValueError("Cannot parse bool value: %r" % value)


def safe_filename(sample_id):
    name = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(sample_id),
    )

    return name.strip("_") or "sample"


def decode_audio(audio):
    """
    Audio column is forced to decode=False so we don't depend on
    torchcodec/PyTorch. Decode source bytes with libsndfile instead.
    """

    if not isinstance(audio, dict):
        raise RuntimeError(
            "Expected raw Audio dict, got: %r"
            % type(audio)
        )

    raw_bytes = audio.get("bytes")
    path = audio.get("path")

    if raw_bytes is not None:
        source = io.BytesIO(raw_bytes)

    elif path:
        # In normal HF streaming Audio(decode=False), bytes are usually
        # provided. Keep a local-path fallback for robustness.
        p = Path(path)

        if not p.is_file():
            raise RuntimeError(
                "Audio has no bytes and path is not local: %s"
                % path
            )

        source = str(p)

    else:
        raise RuntimeError(
            "Audio row contains neither bytes nor usable path"
        )

    samples, sample_rate = sf.read(
        source,
        dtype="float32",
        always_2d=True,
    )

    # soundfile shape = [samples, channels]
    samples = samples.mean(axis=1)

    if sample_rate != EXPECTED_SR:
        raise RuntimeError(
            "Expected 16 kHz official audio, got %d Hz"
            % sample_rate
        )

    if samples.size == 0:
        raise RuntimeError("Decoded empty audio")

    if not np.all(np.isfinite(samples)):
        raise RuntimeError("Audio contains non-finite samples")

    return samples.astype(np.float32), sample_rate


def main():
    args = parse_args()

    if args.per_class <= 0:
        raise SystemExit("--per-class must be > 0")

    output = Path(args.output).resolve()
    audio_dir = output / "audio"

    if output.exists():
        if not args.overwrite:
            raise SystemExit(
                "Output already exists:\n"
                "  %s\n"
                "Use --overwrite only if you intentionally "
                "want to regenerate it."
                % output
            )

        shutil.rmtree(output)

    audio_dir.mkdir(parents=True)

    if args.revision:
        revision = args.revision
    else:
        revision = HfApi().dataset_info(
            DATASET_ID
        ).sha

    print("==========================================")
    print(" M06 Smart Turn dataset preparation")
    print("==========================================")
    print("Dataset        :", DATASET_ID)
    print("Split          :", SPLIT)
    print("Revision       :", revision)
    print("Language       : eng")
    print(
        "Synthetic      :",
        "allowed"
        if args.include_synthetic
        else "excluded",
    )
    print("Per class      :", args.per_class)
    print("Output         :", output)
    print()

    dataset = load_dataset(
        DATASET_ID,
        split=SPLIT,
        revision=revision,
        streaming=True,
    )

    # Important:
    # keep raw bytes instead of invoking datasets audio decoder.
    dataset = dataset.cast_column(
        "audio",
        Audio(decode=False),
    )

    selected = {
        True: [],
        False: [],
    }

    source_counts = Counter()

    for row in dataset:
        if row.get("language") != "eng":
            continue

        synthetic = as_bool(
            row.get("synthetic", False)
        )

        if (
            synthetic
            and not args.include_synthetic
        ):
            continue

        truth_complete = as_bool(
            row["endpoint_bool"]
        )

        if (
            len(selected[truth_complete])
            >= args.per_class
        ):
            continue

        samples, sample_rate = decode_audio(
            row["audio"]
        )

        sample_id = str(row["id"])
        filename = (
            "%s.wav"
            % safe_filename(sample_id)
        )

        wav_path = audio_dir / filename

        sf.write(
            str(wav_path),
            samples,
            sample_rate,
            subtype="PCM_16",
            format="WAV",
        )

        dataset_source = str(
            row.get("dataset", "")
        )

        item = {
            "sample_id": sample_id,
            "audio_file": "audio/" + filename,
            "endpoint_bool": (
                "1"
                if truth_complete
                else "0"
            ),
            "language": row.get(
                "language",
                "",
            ),
            "midfiller": (
                "1"
                if as_bool(
                    row.get(
                        "midfiller",
                        False,
                    )
                )
                else "0"
            ),
            "endfiller": (
                "1"
                if as_bool(
                    row.get(
                        "endfiller",
                        False,
                    )
                )
                else "0"
            ),
            "synthetic": (
                "1" if synthetic else "0"
            ),
            "dataset": dataset_source,
            "duration_s": (
                "%.6f"
                % (
                    len(samples)
                    / float(sample_rate)
                )
            ),
        }

        selected[truth_complete].append(
            item
        )

        source_counts[
            dataset_source
        ] += 1

        print(
            "%-10s  complete=%d  "
            "duration=%6.3fs  source=%s"
            % (
                sample_id,
                1
                if truth_complete
                else 0,
                len(samples)
                / float(sample_rate),
                dataset_source,
            )
        )

        if (
            len(selected[True])
            >= args.per_class
            and len(selected[False])
            >= args.per_class
        ):
            break

    if (
        len(selected[True])
        != args.per_class
    ):
        raise RuntimeError(
            "Could not collect enough "
            "COMPLETE samples: %d/%d"
            % (
                len(selected[True]),
                args.per_class,
            )
        )

    if (
        len(selected[False])
        != args.per_class
    ):
        raise RuntimeError(
            "Could not collect enough "
            "INCOMPLETE samples: %d/%d"
            % (
                len(selected[False]),
                args.per_class,
            )
        )

    rows = (
        selected[True]
        + selected[False]
    )

    rows.sort(
        key=lambda x: (
            x["endpoint_bool"] != "1",
            x["sample_id"],
        )
    )

    manifest_path = (
        output / "manifest.tsv"
    )

    fields = [
        "sample_id",
        "audio_file",
        "endpoint_bool",
        "language",
        "midfiller",
        "endfiller",
        "synthetic",
        "dataset",
        "duration_s",
    ]

    with manifest_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
        )

        writer.writeheader()
        writer.writerows(rows)

    source_metadata = {
        "dataset_id": DATASET_ID,
        "split": SPLIT,
        "revision": revision,
        "language": "eng",
        "include_synthetic": (
            args.include_synthetic
        ),
        "sample_rate_hz": EXPECTED_SR,
        "complete_samples": (
            len(selected[True])
        ),
        "incomplete_samples": (
            len(selected[False])
        ),
        "selection_rule": (
            "First matching rows in the "
            "pinned streaming dataset order, "
            "balanced by endpoint_bool."
        ),
        "dataset_source_counts": dict(
            sorted(source_counts.items())
        ),
    }

    (
        output / "source.json"
    ).write_text(
        json.dumps(
            source_metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("==========================================")
    print(" PREPARATION PASS")
    print("==========================================")
    print(
        "COMPLETE   :",
        len(selected[True]),
    )
    print(
        "INCOMPLETE :",
        len(selected[False]),
    )
    print("TOTAL      :", len(rows))
    print("Manifest   :", manifest_path)
    print(
        "Source meta:",
        output / "source.json",
    )


if __name__ == "__main__":
    main()
