#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Rebuild M02 summary from samples.jsonl and config metadata."""

from __future__ import print_function

import argparse
import json
import math
import statistics
from pathlib import Path


CONFIGS = ("gtcrn_off", "gtcrn_on")


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


def summary_for_config(rows, meta):
    def vals(name):
        return [
            float(r[name])
            for r in rows
            if r.get(name) is not None
        ]

    words = sum(int(r["reference_words"]) for r in rows)
    edits = sum(int(r["word_edit_distance"]) for r in rows)

    s = {
        "config": meta["config"],
        "label": meta["label"],
        "gtcrn": meta["gtcrn"],
        "samples": len(rows),
        "corpus_wer": edits / float(words) if words else 0.0,
        "exact_matches": sum(1 for r in rows if r["exact_match"]),
        "onnx_size_mb": meta.get("onnx_size_mb"),
        "startup_ready_s": meta.get("startup_ready_s"),
        "idle_cpu_avg_pct": meta.get("idle_cpu_avg_pct"),
        "idle_rss_avg_mb": meta.get("idle_rss_avg_mb"),
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

    return s


def paired_effect(rows):
    maps = {}
    for key in CONFIGS:
        maps[key] = {
            r["sample_id"]: r
            for r in rows
            if r["config"] == key
        }

    common = sorted(set(maps["gtcrn_off"]).intersection(maps["gtcrn_on"]))

    result = {
        "paired_samples": len(common),
        "improved_samples": 0,
        "worsened_samples": 0,
        "unchanged_samples": 0,
        "samples": [],
    }

    for sid in common:
        off = maps["gtcrn_off"][sid]
        on = maps["gtcrn_on"][sid]
        delta = float(on["wer"]) - float(off["wer"])

        if delta < -1e-12:
            status = "improved"
            result["improved_samples"] += 1
        elif delta > 1e-12:
            status = "worsened"
            result["worsened_samples"] += 1
        else:
            status = "unchanged"
            result["unchanged_samples"] += 1

        result["samples"].append({
            "sample_id": sid,
            "reference": off["reference"],
            "gtcrn_off_hypothesis": off["hypothesis"],
            "gtcrn_on_hypothesis": on["hypothesis"],
            "gtcrn_off_wer": off["wer"],
            "gtcrn_on_wer": on["wer"],
            "delta_wer_on_minus_off": delta,
            "status": status,
        })

    return result


def render(summary, effect):
    lines = [
        "# M02 — Noise + GTCRN Ablation",
        "",
        "Fixed STT backend: `Zipformer 2023-06-21`",
        "",
        "## Accuracy + realtime latency",
        "",
        "| Config | Corpus WER | Exact | VAD mean | STT mean | STT p95 | TOTAL mean | TOTAL p95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for key in CONFIGS:
        s = summary[key]
        lines.append(
            "| %s | %s | %d/%d | %s s | %s s | %s s | %s s | %s s |"
            % (
                "GTCRN OFF" if key == "gtcrn_off" else "GTCRN ON",
                fnum(s["corpus_wer"], 4),
                s["exact_matches"], s["samples"],
                fnum(s["vad_latency_s_mean"]),
                fnum(s["stt_latency_s_mean"]),
                fnum(s["stt_latency_s_p95"]),
                fnum(s["total_latency_s_mean"]),
                fnum(s["total_latency_s_p95"]),
            )
        )

    lines += [
        "",
        "## Resource",
        "",
        "| Config | Ready | Idle CPU | Idle RSS | Active CPU | CPU peak | Peak RSS |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for key in CONFIGS:
        s = summary[key]
        lines.append(
            "| %s | %s s | %s%% | %s MB | %s%% | %s%% | %s MB |"
            % (
                "GTCRN OFF" if key == "gtcrn_off" else "GTCRN ON",
                fnum(s["startup_ready_s"]),
                fnum(s["idle_cpu_avg_pct"], 1),
                fnum(s["idle_rss_avg_mb"], 1),
                fnum(s["cpu_avg_pct_mean"], 1),
                fnum(s["cpu_peak_pct_max"], 1),
                fnum(s["rss_peak_mb_max"], 1),
            )
        )

    off = summary["gtcrn_off"]
    on = summary["gtcrn_on"]

    lines += [
        "",
        "## Paired effect",
        "",
        "- Improved: %d/%d" % (
            effect["improved_samples"], effect["paired_samples"]
        ),
        "- Worsened: %d/%d" % (
            effect["worsened_samples"], effect["paired_samples"]
        ),
        "- Unchanged: %d/%d" % (
            effect["unchanged_samples"], effect["paired_samples"]
        ),
        "",
        "## GTCRN ON - OFF delta",
        "",
        "```text",
        "WER delta        : %+.4f" % (
            on["corpus_wer"] - off["corpus_wer"]
        ),
        "Exact delta      : %+d" % (
            on["exact_matches"] - off["exact_matches"]
        ),
        "TOTAL mean delta : %+.1f ms" % (
            (on["total_latency_s_mean"] - off["total_latency_s_mean"])
            * 1000.0
        ),
        "TOTAL p95 delta  : %+.1f ms" % (
            (on["total_latency_s_p95"] - off["total_latency_s_p95"])
            * 1000.0
        ),
        "Active CPU delta : %+.1f pp" % (
            on["cpu_avg_pct_mean"] - off["cpu_avg_pct_mean"]
        ),
        "Peak RSS delta   : %+.1f MB" % (
            on["rss_peak_mb_max"] - off["rss_peak_mb_max"]
        ),
        "```",
        "",
    ]

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()

    rows = []
    with (run_dir / "samples.jsonl").open("r") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    metas = {}
    for key in CONFIGS:
        metas[key] = json.loads(
            (run_dir / key / "config_metadata.json").read_text()
        )

    summary = {}
    for key in CONFIGS:
        rr = [r for r in rows if r["config"] == key]
        summary[key] = summary_for_config(rr, metas[key])

    effect = paired_effect(rows)

    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True)
    )
    (run_dir / "paired_effect.json").write_text(
        json.dumps(effect, indent=2, sort_keys=True)
    )

    text = render(summary, effect)
    (run_dir / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
