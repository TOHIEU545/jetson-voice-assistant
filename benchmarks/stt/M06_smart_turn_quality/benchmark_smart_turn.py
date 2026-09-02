#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M06 - Smart Turn v3.2 standalone quality + latency benchmark.

Input:
    Official pipecat-ai/smart-turn-data-v3.2-test subset
      -> 30 COMPLETE
      -> 30 INCOMPLETE
      -> standalone Smart Turn C++ probe
      -> probability + COMPLETE/INCOMPLETE
      -> classification metrics + latency

Positive class:
    COMPLETE

Python 3.6 compatible.
"""

from __future__ import print_function

import argparse
import csv
import datetime
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[3]

DEFAULT_DATASET = (
    REPO_ROOT
    / "data"
    / "stt"
    / "smart_turn_v3_2_test"
    / "source"
    / "hf_selected_60"
)

DEFAULT_MANIFEST = DEFAULT_DATASET / "manifest.tsv"

DEFAULT_PROBE = (
    REPO_ROOT
    / "benchmarks"
    / "stt"
    / "M06_smart_turn_quality"
    / "build"
    / "smart_turn_probe"
)

DEFAULT_MODEL = (
    REPO_ROOT
    / "models"
    / "turn"
    / "smart-turn-v3.2-cpu-opset16-ir8-clean.onnx"
)

DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "logs"
    / "benchmarks"
    / "stt"
    / "M06_smart_turn_quality"
)

CONFIG_KEY = "smart_turn_v3_2"

CONFIGS = {
    CONFIG_KEY: {
        "label": "Smart Turn v3.2",
    },
}


def now_id():
    return datetime.datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )


def run_text(cmd, env=None, timeout=None):
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        out, err = p.communicate(
            timeout=timeout
        )

        return (
            p.returncode,
            out.strip(),
            err.strip(),
        )

    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()

        return (
            124,
            out.strip(),
            err.strip(),
        )

    except Exception as exc:
        return 127, "", str(exc)


def git_commit():
    rc, out, _ = run_text(
        ["git", "rev-parse", "HEAD"]
    )

    return out if rc == 0 else "unknown"


def git_status_short():
    rc, out, _ = run_text(
        ["git", "status", "--short"]
    )

    return out if rc == 0 else "unknown"


def percentile(values, p):
    values = sorted(values)

    if not values:
        return None

    if len(values) == 1:
        return values[0]

    k = (len(values) - 1) * p
    lo = int(math.floor(k))
    hi = int(math.ceil(k))

    if lo == hi:
        return values[lo]

    return (
        values[lo] * (hi - k)
        + values[hi] * (k - lo)
    )


def safe_div(a, b):
    if not b:
        return 0.0

    return a / float(b)


def fnum(value, digits=3):
    if value is None:
        return "-"

    return (
        ("%." + str(digits) + "f")
        % value
    )


def load_dataset(
    manifest_path,
    limit_per_class=0,
):
    with manifest_path.open(
        "r",
        newline="",
    ) as f:
        reader = csv.DictReader(
            f,
            delimiter="\t",
        )

        headers = list(
            reader.fieldnames or []
        )

        rows = list(reader)

    required = {
        "sample_id",
        "audio_file",
        "endpoint_bool",
    }

    missing = required - set(headers)

    if missing:
        raise RuntimeError(
            "M06 manifest missing columns: %s"
            % ", ".join(sorted(missing))
        )

    items = []

    selected = {
        True: 0,
        False: 0,
    }

    for row in rows:
        sample_id = (
            row.get("sample_id") or ""
        ).strip()

        audio_file = (
            row.get("audio_file") or ""
        ).strip()

        endpoint = (
            row.get("endpoint_bool") or ""
        ).strip()

        if not sample_id:
            raise RuntimeError(
                "Empty sample_id"
            )

        if endpoint not in ("0", "1"):
            raise RuntimeError(
                "Invalid endpoint_bool for %s: %r"
                % (
                    sample_id,
                    endpoint,
                )
            )

        truth_complete = (
            endpoint == "1"
        )

        if (
            limit_per_class > 0
            and selected[truth_complete]
            >= limit_per_class
        ):
            continue

        wav_path = (
            manifest_path.parent
            / audio_file
        ).resolve()

        if not wav_path.is_file():
            raise RuntimeError(
                "WAV not found: %s"
                % wav_path
            )

        duration_s = None

        raw_duration = (
            row.get("duration_s") or ""
        ).strip()

        if raw_duration:
            duration_s = float(
                raw_duration
            )

        items.append({
            "sample_id": sample_id,
            "wav": wav_path,
            "audio_file": audio_file,
            "truth_complete":
                truth_complete,
            "truth_label": (
                "COMPLETE"
                if truth_complete
                else "INCOMPLETE"
            ),
            "duration_s": duration_s,
            "language": (
                row.get("language") or ""
            ).strip(),
            "dataset": (
                row.get("dataset") or ""
            ).strip(),
            "synthetic": (
                row.get("synthetic") or ""
            ).strip(),
        })

        selected[
            truth_complete
        ] += 1

    items.sort(
        key=lambda item: (
            0
            if item["truth_complete"]
            else 1,
            item["sample_id"],
        )
    )

    return items


def validate_dataset(manifest_path):
    items = load_dataset(
        manifest_path
    )

    complete = sum(
        1
        for x in items
        if x["truth_complete"]
    )

    incomplete = (
        len(items) - complete
    )

    print(
        "Samples    : %d"
        % len(items)
    )
    print(
        "COMPLETE   : %d"
        % complete
    )
    print(
        "INCOMPLETE : %d"
        % incomplete
    )

    if len(items) != 60:
        raise RuntimeError(
            "Expected 60 samples"
        )

    if complete != 30:
        raise RuntimeError(
            "Expected 30 COMPLETE"
        )

    if incomplete != 30:
        raise RuntimeError(
            "Expected 30 INCOMPLETE"
        )

    print("VALIDATION PASS")


def parse_probe_output(text):
    line = None

    for candidate in text.splitlines():
        candidate = candidate.strip()

        if candidate.startswith(
            "SMART_TURN_RESULT "
        ):
            line = candidate
            break

    if line is None:
        raise RuntimeError(
            "SMART_TURN_RESULT not found"
        )

    values = {}

    for token in line.split()[1:]:
        if "=" not in token:
            continue

        key, value = token.split(
            "=",
            1,
        )

        values[key] = value

    required = {
        "probability",
        "decision",
        "threshold",
        "load_ms",
        "audio_prep_ms",
        "feature_ms",
        "infer_ms",
        "total_ms",
        "samples",
    }

    missing = required - set(values)

    if missing:
        raise RuntimeError(
            "Probe output missing: %s"
            % ", ".join(sorted(missing))
        )

    decision = values["decision"]

    if decision not in (
        "COMPLETE",
        "INCOMPLETE",
    ):
        raise RuntimeError(
            "Invalid probe decision: %s"
            % decision
        )

    return {
        "probability":
            float(values["probability"]),
        "decision": decision,
        "threshold":
            float(values["threshold"]),
        "load_ms":
            float(values["load_ms"]),
        "audio_prep_ms":
            float(values["audio_prep_ms"]),
        "feature_ms":
            float(values["feature_ms"]),
        "infer_ms":
            float(values["infer_ms"]),
        "total_ms":
            float(values["total_ms"]),
        "samples":
            int(values["samples"]),
    }


def build_runtime_env():
    env = os.environ.copy()

    candidates = []

    sherpa_src = env.get(
        "SHERPA_ONNX_SRC"
    )

    if sherpa_src:
        candidates.append(
            Path(sherpa_src)
            / "build"
            / "_deps"
            / "onnxruntime-src"
            / "lib"
        )

    candidates += [
        (
            REPO_ROOT
            / "runtime"
            / "sherpa-onnx"
            / "build"
            / "_deps"
            / "onnxruntime-src"
            / "lib"
        ),
        (
            REPO_ROOT
            / "runtime"
            / "sherpa-onnx"
            / "build"
            / "lib"
        ),
        (
            Path.home()
            / "jetson-voice-assistant-runtime-dev"
            / "sherpa-onnx"
            / "build"
            / "_deps"
            / "onnxruntime-src"
            / "lib"
        ),
    ]

    for path in candidates:
        if (
            path
            / "libonnxruntime.so"
        ).is_file():

            old = env.get(
                "LD_LIBRARY_PATH",
                "",
            )

            env["LD_LIBRARY_PATH"] = (
                str(path)
                + (
                    ":" + old
                    if old
                    else ""
                )
            )

            break

    return env


def run_probe(
    probe,
    model,
    wav,
    threshold,
    threads,
    timeout,
):
    cmd = [
        str(probe),
        "--model",
        str(model),
        "--wav",
        str(wav),
        "--threshold",
        str(threshold),
        "--threads",
        str(threads),
    ]

    env = build_runtime_env()

    t0 = time.time()

    rc, out, err = run_text(
        cmd,
        env=env,
        timeout=timeout,
    )

    wall_s = time.time() - t0

    if rc != 0:
        raise RuntimeError(
            "Probe failed rc=%d\n"
            "stdout:\n%s\n"
            "stderr:\n%s"
            % (
                rc,
                out,
                err,
            )
        )

    result = parse_probe_output(
        out
    )

    result["wall_s"] = wall_s
    result["probe_stdout"] = out

    return result


def summary_for_config(rows, meta):
    tp = 0
    tn = 0
    fp = 0
    fn = 0

    for row in rows:
        truth = bool(
            row["truth_complete"]
        )

        pred = bool(
            row["predicted_complete"]
        )

        if truth and pred:
            tp += 1
        elif (
            not truth
            and not pred
        ):
            tn += 1
        elif (
            not truth
            and pred
        ):
            fp += 1
        else:
            fn += 1

    accuracy = safe_div(
        tp + tn,
        len(rows),
    )

    precision = safe_div(
        tp,
        tp + fp,
    )

    recall = safe_div(
        tp,
        tp + fn,
    )

    if precision + recall:
        f1 = (
            2.0
            * precision
            * recall
            / (
                precision
                + recall
            )
        )
    else:
        f1 = 0.0

    out = {
        "config": meta["config"],
        "label": meta["label"],
        "samples": len(rows),
        "complete_samples": sum(
            1
            for r in rows
            if r["truth_complete"]
        ),
        "incomplete_samples": sum(
            1
            for r in rows
            if not r[
                "truth_complete"
            ]
        ),
        "correct_samples": (
            tp + tn
        ),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fpr": safe_div(
            fp,
            fp + tn,
        ),
        "fnr": safe_div(
            fn,
            fn + tp,
        ),
        "threshold":
            meta["threshold"],
        "threads":
            meta["threads"],
        "model_size_mb":
            meta["model_size_mb"],
    }

    for name in (
        "probability",
        "load_ms",
        "audio_prep_ms",
        "feature_ms",
        "infer_ms",
        "total_ms",
        "wall_s",
    ):
        values = [
            float(r[name])
            for r in rows
            if r.get(name)
            is not None
        ]

        out[
            name + "_mean"
        ] = (
            statistics.mean(values)
            if values
            else None
        )

        out[
            name + "_median"
        ] = (
            statistics.median(values)
            if values
            else None
        )

        out[
            name + "_p95"
        ] = percentile(
            values,
            0.95,
        )

        out[
            name + "_max"
        ] = (
            max(values)
            if values
            else None
        )

    return out


def render_summary(summary):
    s = summary[CONFIG_KEY]

    lines = [
        "# M06 — Smart Turn v3.2 standalone quality",
        "",
        "Positive class: `COMPLETE`",
        "",
        "## Classification",
        "",
        "| Samples | Correct | Accuracy | Precision | Recall | F1 | FPR | FNR |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            "| %d | %d | %.2f%% | %.2f%% | %.2f%% | %.2f%% | %.2f%% | %.2f%% |"
            % (
                s["samples"],
                s["correct_samples"],
                s["accuracy"] * 100.0,
                s["precision"] * 100.0,
                s["recall"] * 100.0,
                s["f1"] * 100.0,
                s["fpr"] * 100.0,
                s["fnr"] * 100.0,
            )
        ),
        "",
        "## Confusion matrix",
        "",
        "```text",
        "                 Pred COMPLETE   Pred INCOMPLETE",
        "Truth COMPLETE       %3d               %3d"
        % (
            s["tp"],
            s["fn"],
        ),
        "Truth INCOMPLETE     %3d               %3d"
        % (
            s["fp"],
            s["tn"],
        ),
        "```",
        "",
        "FP = INCOMPLETE predicted COMPLETE -> premature turn cut.",
        "",
        "FN = COMPLETE predicted INCOMPLETE -> unnecessary turn hold.",
        "",
        "## Latency",
        "",
        "| Metric | Mean | Median | p95 | Max |",
        "|---|---:|---:|---:|---:|",
    ]

    for key, label in (
        (
            "audio_prep_ms",
            "Audio prep",
        ),
        (
            "feature_ms",
            "Feature",
        ),
        (
            "infer_ms",
            "Inference",
        ),
        (
            "total_ms",
            "TOTAL",
        ),
        (
            "load_ms",
            "Model load",
        ),
    ):
        lines.append(
            "| %s | %s ms | %s ms | %s ms | %s ms |"
            % (
                label,
                fnum(
                    s[
                        key
                        + "_mean"
                    ],
                    2,
                ),
                fnum(
                    s[
                        key
                        + "_median"
                    ],
                    2,
                ),
                fnum(
                    s[
                        key
                        + "_p95"
                    ],
                    2,
                ),
                fnum(
                    s[
                        key
                        + "_max"
                    ],
                    2,
                ),
            )
        )

    lines += [
        "",
        "## Fixed configuration",
        "",
        "```text",
        "Threshold : %.3f"
        % s["threshold"],
        "Threads   : %d"
        % s["threads"],
        "Model     : %.2f MB"
        % s["model_size_mb"],
        "```",
        "",
        "`TOTAL` = audio preparation + feature extraction + ONNX inference.",
        "",
        "`Model load` is reported separately because the production SmartTurnRuntime is resident and does not reload the model on every turn.",
        "",
    ]

    return "\n".join(lines)


def self_test():
    text = (
        "SMART_TURN_RESULT "
        "probability=0.944584 "
        "decision=COMPLETE "
        "threshold=0.5 "
        "load_ms=412.665 "
        "audio_prep_ms=1.507 "
        "feature_ms=1329.87 "
        "infer_ms=326.245 "
        "total_ms=1657.62 "
        "samples=256000"
    )

    parsed = parse_probe_output(
        text
    )

    assert (
        parsed["decision"]
        == "COMPLETE"
    )

    assert abs(
        parsed["probability"]
        - 0.944584
    ) < 1e-9

    rows = [
        {
            "truth_complete": True,
            "predicted_complete": True,
            "probability": 0.9,
            "load_ms": 1,
            "audio_prep_ms": 1,
            "feature_ms": 1,
            "infer_ms": 1,
            "total_ms": 3,
            "wall_s": 0.1,
        },
        {
            "truth_complete": False,
            "predicted_complete": True,
            "probability": 0.8,
            "load_ms": 1,
            "audio_prep_ms": 1,
            "feature_ms": 1,
            "infer_ms": 1,
            "total_ms": 3,
            "wall_s": 0.1,
        },
    ]

    meta = {
        "config": CONFIG_KEY,
        "label":
            "Smart Turn v3.2",
        "threshold": 0.5,
        "threads": 4,
        "model_size_mb": 1.0,
    }

    s = summary_for_config(
        rows,
        meta,
    )

    assert s["tp"] == 1
    assert s["fp"] == 1
    assert s["tn"] == 0
    assert s["fn"] == 0

    print("SELF TEST PASS")


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument(
        "--manifest",
        default=str(
            DEFAULT_MANIFEST
        ),
    )

    ap.add_argument(
        "--probe",
        default=str(
            DEFAULT_PROBE
        ),
    )

    ap.add_argument(
        "--model",
        default=str(
            DEFAULT_MODEL
        ),
    )

    ap.add_argument(
        "--output-root",
        default=str(
            DEFAULT_OUTPUT_ROOT
        ),
    )

    ap.add_argument(
        "--threshold",
        type=float,
        default=0.5,
    )

    ap.add_argument(
        "--threads",
        type=int,
        default=4,
    )

    ap.add_argument(
        "--timeout",
        type=float,
        default=30.0,
    )

    ap.add_argument(
        "--limit-per-class",
        type=int,
        default=0,
    )

    ap.add_argument(
        "--validate-dataset",
        action="store_true",
    )

    ap.add_argument(
        "--self-test",
        action="store_true",
    )

    args = ap.parse_args()

    if args.self_test:
        self_test()
        return

    manifest = Path(
        args.manifest
    ).resolve()

    if not manifest.is_file():
        raise RuntimeError(
            "Manifest not found: %s"
            % manifest
        )

    if args.validate_dataset:
        validate_dataset(
            manifest
        )
        return

    probe = Path(
        args.probe
    ).resolve()

    model = Path(
        args.model
    ).resolve()

    if not probe.is_file():
        raise RuntimeError(
            "Probe not found: %s"
            % probe
        )

    if not os.access(
        str(probe),
        os.X_OK,
    ):
        raise RuntimeError(
            "Probe is not executable: %s"
            % probe
        )

    if not model.is_file():
        raise RuntimeError(
            "Model not found: %s"
            % model
        )

    items = load_dataset(
        manifest,
        args.limit_per_class,
    )

    if not items:
        raise RuntimeError(
            "No benchmark samples"
        )

    run_dir = (
        Path(args.output_root)
        .resolve()
        / now_id()
    )

    config_dir = (
        run_dir
        / CONFIG_KEY
    )

    config_dir.mkdir(
        parents=True
    )

    source_meta = {}

    source_meta_path = (
        manifest.parent
        / "source.json"
    )

    if source_meta_path.is_file():
        try:
            source_meta = json.loads(
                source_meta_path.read_text()
            )
        except Exception:
            source_meta = {}

    meta = {
        "config": CONFIG_KEY,
        "label":
            "Smart Turn v3.2",
        "threshold":
            args.threshold,
        "threads":
            args.threads,
        "model_path":
            str(model),
        "model_size_mb": (
            model.stat().st_size
            / (
                1024.0
                * 1024.0
            )
        ),
        "probe_path":
            str(probe),
        "manifest":
            str(manifest),
        "dataset_revision":
            source_meta.get(
                "revision"
            ),
        "git_commit":
            git_commit(),
        "git_status_short":
            git_status_short(),
        "platform":
            platform.platform(),
        "python":
            sys.version,
    }

    (
        config_dir
        / "config_metadata.json"
    ).write_text(
        json.dumps(
            meta,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    samples_path = (
        run_dir
        / "samples.jsonl"
    )

    print(
        "=========================================="
    )
    print(
        " M06 Smart Turn Quality Benchmark"
    )
    print(
        "=========================================="
    )
    print(
        "Samples   : %d"
        % len(items)
    )
    print(
        "Threshold : %s"
        % args.threshold
    )
    print(
        "Threads   : %d"
        % args.threads
    )
    print(
        "Result    : %s"
        % run_dir
    )
    print("")

    rows = []

    with samples_path.open(
        "w"
    ) as fout:
        for index, item in enumerate(
            items,
            1,
        ):
            result = run_probe(
                probe=probe,
                model=model,
                wav=item["wav"],
                threshold=
                    args.threshold,
                threads=args.threads,
                timeout=args.timeout,
            )

            predicted_complete = (
                result["decision"]
                == "COMPLETE"
            )

            correct = (
                predicted_complete
                == item[
                    "truth_complete"
                ]
            )

            row = {
                "config":
                    CONFIG_KEY,
                "sample_id":
                    item["sample_id"],
                "audio_file":
                    item["audio_file"],
                "truth_complete":
                    item[
                        "truth_complete"
                    ],
                "truth_label":
                    item[
                        "truth_label"
                    ],
                "predicted_complete":
                    predicted_complete,
                "prediction":
                    result[
                        "decision"
                    ],
                "correct": correct,
                "probability":
                    result[
                        "probability"
                    ],
                "threshold":
                    result[
                        "threshold"
                    ],
                "load_ms":
                    result[
                        "load_ms"
                    ],
                "audio_prep_ms":
                    result[
                        "audio_prep_ms"
                    ],
                "feature_ms":
                    result[
                        "feature_ms"
                    ],
                "infer_ms":
                    result[
                        "infer_ms"
                    ],
                "total_ms":
                    result[
                        "total_ms"
                    ],
                "wall_s":
                    result[
                        "wall_s"
                    ],
                "samples":
                    result[
                        "samples"
                    ],
                "duration_s":
                    item[
                        "duration_s"
                    ],
                "dataset":
                    item[
                        "dataset"
                    ],
            }

            rows.append(row)

            fout.write(
                json.dumps(
                    row,
                    sort_keys=True,
                )
                + "\n"
            )

            fout.flush()

            print(
                "[%02d/%02d] %-10s -> %-10s "
                "p=%.4f total=%.1f ms %s"
                % (
                    index,
                    len(items),
                    item[
                        "truth_label"
                    ],
                    result[
                        "decision"
                    ],
                    result[
                        "probability"
                    ],
                    result[
                        "total_ms"
                    ],
                    (
                        "PASS"
                        if correct
                        else "FAIL"
                    ),
                )
            )

    summary = {
        CONFIG_KEY:
            summary_for_config(
                rows,
                meta,
            )
    }

    (
        run_dir
        / "summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    summary_md = render_summary(
        summary
    )

    (
        run_dir
        / "summary.md"
    ).write_text(
        summary_md
    )

    print("")
    print(
        "=========================================="
    )
    print(
        " M06 BENCHMARK DONE"
    )
    print(
        "=========================================="
    )
    print(
        "Result: %s"
        % run_dir
    )
    print("")
    print(summary_md)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\nInterrupted.",
            file=sys.stderr,
        )
        sys.exit(130)
    except Exception as exc:
        print(
            "ERROR: %s" % exc,
            file=sys.stderr,
        )
        sys.exit(1)
