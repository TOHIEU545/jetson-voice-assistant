#!/usr/bin/env python3
from __future__ import print_function

import argparse
import json
import math
import statistics
from pathlib import Path


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--summary-json", required=True)
    ap.add_argument("--summary-md", required=True)
    return ap.parse_args()


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * p
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return values[lo]
    frac = pos - lo
    return values[lo] * (1.0 - frac) + values[hi] * frac


def stats(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None}
    return {
        "count": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
        "p95": percentile(values, 0.95), "min": min(values), "max": max(values),
    }


def fmt(value, digits=3):
    if value is None:
        return "-"
    return ("{:." + str(digits) + "f}").format(value)


def flatten_latency(rows):
    out = []
    for row in rows:
        out.extend(row.get("latency_total_s", []))
    return out


def flatten_smart_metric(rows, key):
    out = []
    for row in rows:
        for decision in row.get("smart_turn_decisions", []):
            if key in decision:
                out.append(float(decision[key]))
    return out


def summarize_mode(rows):
    single = sum(1 for r in rows if r["turn_result"] == "SINGLE_TURN")
    false_cutoff = sum(1 for r in rows if r["turn_result"] == "FALSE_CUTOFF")
    eot_miss = sum(1 for r in rows if r["turn_result"] == "EOT_MISS")
    extra = sum(max(0, int(r["transcript_count"]) - 1) for r in rows)
    return {
        "cases": len(rows),
        "single_turn_cases": single,
        "false_cutoff_cases": false_cutoff,
        "eot_miss_cases": eot_miss,
        "extra_transcripts": extra,
        "transcripts_total": sum(int(r["transcript_count"]) for r in rows),
        "speech_started_total": sum(int(r["speech_started_count"]) for r in rows),
        "endpoint_latency_s": stats(flatten_latency(rows)),
        "runtime_ready_ms": stats([r.get("runtime_ready_ms") for r in rows]),
    }


def main():
    args = parse_args()
    rows = []
    with Path(args.results).open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    off = [r for r in rows if r["mode"] == "off"]
    on = [r for r in rows if r["mode"] == "on"]
    if len(off) != 20 or len(on) != 20:
        raise RuntimeError("Expected 20 OFF + 20 ON rows, got OFF={} ON={}".format(len(off), len(on)))

    off_s = summarize_mode(off)
    on_s = summarize_mode(on)
    off_false, on_false = off_s["false_cutoff_cases"], on_s["false_cutoff_cases"]
    reduction = ((off_false - on_false) * 100.0 / off_false) if off_false > 0 else None

    smart_candidates = sum(int(r.get("smart_turn_candidate_count", 0)) for r in on)
    smart_complete = sum(int(r.get("smart_turn_complete_count", 0)) for r in on)
    smart_incomplete = sum(int(r.get("smart_turn_incomplete_count", 0)) for r in on)
    model_load = [r.get("smart_turn_model_load_ms") for r in on if r.get("smart_turn_model_load_ms") is not None]

    summary = {
        "benchmark": "M07_smart_turn_zipformer",
        "cases": 20,
        "off": off_s,
        "on": on_s,
        "comparison": {
            "false_cutoff_case_reduction_pct": reduction,
            "false_cutoff_cases_delta": on_false - off_false,
            "eot_miss_cases_delta": on_s["eot_miss_cases"] - off_s["eot_miss_cases"],
        },
        "smart_turn": {
            "candidate_count": smart_candidates,
            "complete_count": smart_complete,
            "incomplete_count": smart_incomplete,
            "audio_prep_ms": stats(flatten_smart_metric(on, "audio_prep_ms")),
            "feature_ms": stats(flatten_smart_metric(on, "feature_ms")),
            "infer_ms": stats(flatten_smart_metric(on, "infer_ms")),
            "total_ms": stats(flatten_smart_metric(on, "total_ms")),
            "score": stats(flatten_smart_metric(on, "score")),
            "model_load_ms": stats(model_load),
        },
    }

    Path(args.summary_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    lines = [
        "# M07 Smart Turn + Zipformer Benchmark", "",
        "Fixed input: 20 prepared English LiveKit EoT turns.", "",
        "## Endpointing summary", "",
        "| Metric | Smart Turn OFF | Smart Turn ON |",
        "|---|---:|---:|",
        "| Cases | {} | {} |".format(off_s["cases"], on_s["cases"]),
        "| Single logical turn | {} | {} |".format(off_s["single_turn_cases"], on_s["single_turn_cases"]),
        "| False-cutoff cases (>1 transcript) | {} | {} |".format(off_s["false_cutoff_cases"], on_s["false_cutoff_cases"]),
        "| EOT-miss cases (0 transcript) | {} | {} |".format(off_s["eot_miss_cases"], on_s["eot_miss_cases"]),
        "| Extra transcripts | {} | {} |".format(off_s["extra_transcripts"], on_s["extra_transcripts"]),
        "| Endpoint TOTAL mean (s) | {} | {} |".format(fmt(off_s["endpoint_latency_s"]["mean"]), fmt(on_s["endpoint_latency_s"]["mean"])),
        "| Endpoint TOTAL p95 (s) | {} | {} |".format(fmt(off_s["endpoint_latency_s"]["p95"]), fmt(on_s["endpoint_latency_s"]["p95"])),
        "", "## Comparison", "",
        "- False-cutoff case reduction: {}%".format(fmt(reduction, 1)),
        "- EOT-miss delta (ON - OFF): {}".format(summary["comparison"]["eot_miss_cases_delta"]),
        "", "## Smart Turn integrated cost", "",
        "- Candidates: {} (INCOMPLETE {}, COMPLETE {})".format(smart_candidates, smart_incomplete, smart_complete),
        "- Smart Turn total mean: {} ms".format(fmt(summary["smart_turn"]["total_ms"]["mean"])),
        "- Feature extraction mean: {} ms".format(fmt(summary["smart_turn"]["feature_ms"]["mean"])),
        "- Inference mean: {} ms".format(fmt(summary["smart_turn"]["infer_ms"]["mean"])),
        "- Resident model load mean: {} ms".format(fmt(summary["smart_turn"]["model_load_ms"]["mean"])),
        "", "## Per-case outcome", "",
        "| ID | OFF transcripts | OFF result | ON transcripts | ON result | ST candidates |",
        "|---|---:|---|---:|---|---:|",
    ]

    on_by_id = {r["id"]: r for r in on}
    for o in off:
        n = on_by_id[o["id"]]
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            o["id"], o["transcript_count"], o["turn_result"], n["transcript_count"], n["turn_result"], n["smart_turn_candidate_count"]))
    lines += ["", "Interpretation: each dataset row is one complete user turn. More than one transcript is a premature split; zero transcripts after playback is an EOT miss.", ""]
    Path(args.summary_md).write_text("\n".join(lines))

    print("==========================================")
    print(" M07 SUMMARY")
    print("==========================================")
    print("OFF: single={} false_cutoff={} eot_miss={} extra_transcripts={}".format(off_s["single_turn_cases"], off_s["false_cutoff_cases"], off_s["eot_miss_cases"], off_s["extra_transcripts"]))
    print(" ON: single={} false_cutoff={} eot_miss={} extra_transcripts={}".format(on_s["single_turn_cases"], on_s["false_cutoff_cases"], on_s["eot_miss_cases"], on_s["extra_transcripts"]))
    print("False-cutoff reduction: {}%".format(fmt(reduction, 1)))
    print("Endpoint TOTAL mean: OFF={}s ON={}s".format(fmt(off_s["endpoint_latency_s"]["mean"]), fmt(on_s["endpoint_latency_s"]["mean"])))
    print("Smart Turn: candidates={} total_mean={}ms feature_mean={}ms infer_mean={}ms".format(smart_candidates, fmt(summary["smart_turn"]["total_ms"]["mean"]), fmt(summary["smart_turn"]["feature_ms"]["mean"]), fmt(summary["smart_turn"]["infer_ms"]["mean"])))
    print("Summary MD: {}".format(args.summary_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
