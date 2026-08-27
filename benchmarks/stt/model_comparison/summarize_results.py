#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Rebuild summary.md/summary.json from a pipeline benchmark run."""

from __future__ import print_function

import argparse
import json
import math
import statistics
from pathlib import Path


MODEL_ORDER = [
    "whisper",
    "zipformer_20m",
    "zipformer_2023_06_21",
]


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
    return values[lo] * (hi - k) + values[hi] * (k - lo)


def fnum(v, digits=3):
    if v is None:
        return "-"
    return ("%." + str(digits) + "f") % v


def summarize(rows, model_meta):
    summary = {}

    for key in MODEL_ORDER:
        rr = [r for r in rows if r.get("model") == key]
        if not rr:
            continue

        meta = model_meta.get(key, {})

        def vals(name):
            return [
                float(r[name])
                for r in rr
                if r.get(name) is not None
            ]

        ref_words = sum(int(r.get("reference_words", 0)) for r in rr)
        edits = sum(int(r.get("word_edit_distance", 0)) for r in rr)

        s = {
            "model": key,
            "label": rr[0].get("model_label", key),
            "samples": len(rr),
            "corpus_wer": edits / float(ref_words) if ref_words else 0.0,
            "exact_matches": sum(1 for r in rr if r.get("exact_match")),
            "model_onnx_size_mb": meta.get("model_onnx_size_mb"),
            "startup_ready_s": meta.get("startup_ready_s"),
            "idle_cpu_avg_pct": meta.get("idle_cpu_avg_pct"),
            "idle_cpu_peak_pct": meta.get("idle_cpu_peak_pct"),
            "idle_rss_avg_mb": meta.get("idle_rss_avg_mb"),
            "idle_rss_peak_mb": meta.get("idle_rss_peak_mb"),
        }

        for name in (
            "vad_latency_s",
            "stt_latency_s",
            "total_latency_s",
            "wall_end_to_transcript_s",
            "cpu_avg_pct",
            "cpu_peak_pct",
            "rss_peak_mb",
        ):
            vv = vals(name)
            s[name + "_mean"] = statistics.mean(vv) if vv else None
            s[name + "_median"] = statistics.median(vv) if vv else None
            s[name + "_p95"] = percentile(vv, 0.95)
            s[name + "_max"] = max(vv) if vv else None

        summary[key] = s

    return summary


def render(summary):
    lines = [
        "# STT Pipeline Model Comparison — CLEAN",
        "",
        "## Accuracy + realtime latency",
        "",
        "| Model | Corpus WER | Exact | VAD mean | VAD p95 | STT mean | STT p95 | TOTAL mean | TOTAL p95 | Wall mean | Wall p95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for key in MODEL_ORDER:
        s = summary.get(key)
        if not s:
            continue
        lines.append(
            "| %s | %s | %d/%d | %s s | %s s | %s s | %s s | %s s | %s s | %s s | %s s |"
            % (
                s["label"],
                fnum(s["corpus_wer"], 4),
                s["exact_matches"], s["samples"],
                fnum(s["vad_latency_s_mean"]),
                fnum(s["vad_latency_s_p95"]),
                fnum(s["stt_latency_s_mean"]),
                fnum(s["stt_latency_s_p95"]),
                fnum(s["total_latency_s_mean"]),
                fnum(s["total_latency_s_p95"]),
                fnum(s["wall_end_to_transcript_s_mean"]),
                fnum(s["wall_end_to_transcript_s_p95"]),
            )
        )

    lines += [
        "",
        "## Resource + startup",
        "",
        "| Model | ONNX size | Ready time | Idle CPU | Idle RSS | Active CPU mean | Active CPU peak | Peak RSS |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for key in MODEL_ORDER:
        s = summary.get(key)
        if not s:
            continue
        lines.append(
            "| %s | %s MB | %s s | %s%% | %s MB | %s%% | %s%% | %s MB |"
            % (
                s["label"],
                fnum(s["model_onnx_size_mb"], 1),
                fnum(s["startup_ready_s"]),
                fnum(s["idle_cpu_avg_pct"], 1),
                fnum(s["idle_rss_avg_mb"], 1),
                fnum(s["cpu_avg_pct_mean"], 1),
                fnum(s["cpu_peak_pct_max"], 1),
                fnum(s["rss_peak_mb_max"], 1),
            )
        )

    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()

    rows = []
    with (run_dir / "samples.jsonl").open("r") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    model_meta = {}
    for key in MODEL_ORDER:
        p = run_dir / key / "model_metadata.json"
        if p.is_file():
            model_meta[key] = json.loads(p.read_text())

    summary = summarize(rows, model_meta)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True)
    )

    text = render(summary)
    (run_dir / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
