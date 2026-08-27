#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Rebuild human-readable summary from an existing samples.jsonl."""

from __future__ import print_function

import argparse
import json
import math
import statistics
from pathlib import Path


MODEL_ORDER = [
    "whisper_tiny_en",
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


def summarize(rows):
    out = {}
    for key in MODEL_ORDER:
        rr = [r for r in rows if r.get("model") == key]
        if not rr:
            continue

        def vals(name):
            return [float(r[name]) for r in rr if r.get(name) is not None]

        wers = vals("wer")
        decode = vals("decode_seconds")
        rtf = vals("rtf")
        cpu_avg = vals("cpu_avg_pct")
        cpu_peak = vals("cpu_peak_pct")
        rss = vals("rss_peak_mb")

        out[key] = {
            "label": rr[0].get("model_label", key),
            "samples": len(rr),
            "exact": sum(1 for r in rr if r.get("exact_match")),
            "wer": statistics.mean(wers) if wers else None,
            "decode_mean": statistics.mean(decode) if decode else None,
            "decode_median": statistics.median(decode) if decode else None,
            "decode_p95": percentile(decode, 0.95),
            "rtf_mean": statistics.mean(rtf) if rtf else None,
            "cpu_avg": statistics.mean(cpu_avg) if cpu_avg else None,
            "cpu_peak": max(cpu_peak) if cpu_peak else None,
            "rss_peak": max(rss) if rss else None,
            "errors": sum(1 for r in rr if r.get("exit_status") != 0),
        }
    return out


def render(summary):
    lines = [
        "# STT Model Comparison — CLEAN",
        "",
        "| Model | WER | Exact | Decode mean | Decode median | Decode p95 | RTF mean | CPU avg | CPU peak | Peak RSS | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in MODEL_ORDER:
        s = summary.get(key)
        if not s:
            continue
        lines.append(
            "| %s | %s | %d/%d | %s s | %s s | %s s | %s | %s%% | %s%% | %s MB | %d |"
            % (
                s["label"],
                fnum(s["wer"], 4),
                s["exact"], s["samples"],
                fnum(s["decode_mean"]),
                fnum(s["decode_median"]),
                fnum(s["decode_p95"]),
                fnum(s["rtf_mean"]),
                fnum(s["cpu_avg"], 1),
                fnum(s["cpu_peak"], 1),
                fnum(s["rss_peak"], 1),
                s["errors"],
            )
        )
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    samples = run_dir / "samples.jsonl"
    rows = []
    with samples.open("r") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    summary = summarize(rows)
    text = render(summary)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    (run_dir / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
