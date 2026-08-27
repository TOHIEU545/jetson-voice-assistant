#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Reproducible STT model comparison for jetson-voice-assistant.

Purpose:
- Compare the 3 STT backends already adopted by the project.
- Use fixed clean WAV input.
- Keep GTCRN/VAD/Smart Turn/Speculative out of this benchmark.
- Run the same CPU/provider/thread/greedy-search policy as current project config.

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
import re
import shlex
import statistics
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[3]

DEFAULT_DATASET = REPO_ROOT / "data" / "stt" / "voicebank_demand" / "prepared_15"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "logs" / "benchmarks" / "stt" / "model_comparison"

BIN_OFFLINE = REPO_ROOT / "runtime" / "sherpa-onnx" / "build" / "bin" / "sherpa-onnx-offline"
BIN_STREAMING = REPO_ROOT / "runtime" / "sherpa-onnx" / "build" / "bin" / "sherpa-onnx"

MODELS = {
    "whisper_tiny_en": {
        "label": "Whisper Tiny.en",
        "binary": BIN_OFFLINE,
        "args": [
            "--whisper-encoder=" + str(REPO_ROOT / "models/stt/whisper-tiny.en/tiny.en-encoder.onnx"),
            "--whisper-decoder=" + str(REPO_ROOT / "models/stt/whisper-tiny.en/tiny.en-decoder.onnx"),
            "--tokens=" + str(REPO_ROOT / "models/stt/whisper-tiny.en/tiny.en-tokens.txt"),
            "--provider=cpu",
            "--num-threads=2",
            "--debug=false",
            "--print-args=false",
        ],
    },
    "zipformer_20m": {
        "label": "Zipformer 20M 2023-02-17",
        "binary": BIN_STREAMING,
        "args": [
            "--tokens=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/tokens.txt"),
            "--encoder=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/encoder-epoch-99-avg-1.onnx"),
            "--decoder=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/decoder-epoch-99-avg-1.onnx"),
            "--joiner=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17/joiner-epoch-99-avg-1.onnx"),
            "--model-type=zipformer",
            "--provider=cpu",
            "--num-threads=2",
            "--decoding-method=greedy_search",
            "--enable-endpoint=false",
            "--debug=false",
            "--print-args=false",
        ],
    },
    "zipformer_2023_06_21": {
        "label": "Zipformer 2023-06-21",
        "binary": BIN_STREAMING,
        "args": [
            "--tokens=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-21/tokens.txt"),
            "--encoder=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-21/encoder-epoch-99-avg-1.onnx"),
            "--decoder=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-21/decoder-epoch-99-avg-1.onnx"),
            "--joiner=" + str(REPO_ROOT / "models/stt/sherpa-onnx-streaming-zipformer-en-2023-06-21/joiner-epoch-99-avg-1.onnx"),
            "--model-type=zipformer",
            "--provider=cpu",
            "--num-threads=2",
            "--decoding-method=greedy_search",
            "--enable-endpoint=false",
            "--debug=false",
            "--print-args=false",
        ],
    },
}

REFERENCE_KEYS = (
    "reference", "transcript", "text", "ground_truth", "groundtruth",
    "sentence", "clean_text", "target",
)


def run_text(cmd):
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        out, err = p.communicate()
        return p.returncode, out.strip(), err.strip()
    except Exception as exc:
        return 127, "", str(exc)


def git_commit():
    rc, out, _ = run_text(["git", "rev-parse", "HEAD"])
    return out if rc == 0 else "unknown"


def sherpa_version():
    binary = REPO_ROOT / "runtime/sherpa-onnx/build/bin/sherpa-onnx-version"
    if not binary.exists():
        return "unknown"
    rc, out, err = run_text([str(binary)])
    text = (out + "\n" + err).strip()
    return text if rc == 0 and text else "unknown"


def jetson_release():
    p = Path("/etc/nv_tegra_release")
    if p.exists():
        try:
            return p.read_text().strip()
        except Exception:
            pass
    return ""


def timestamp_id():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def wav_duration_seconds(path):
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def normalize_text(text):
    text = text.lower()
    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def levenshtein_words(ref_words, hyp_words):
    previous = list(range(len(hyp_words) + 1))
    for i, rw in enumerate(ref_words, 1):
        current = [i]
        for j, hw in enumerate(hyp_words, 1):
            ins = current[j - 1] + 1
            delete = previous[j] + 1
            sub = previous[j - 1] + (0 if rw == hw else 1)
            current.append(min(ins, delete, sub))
        previous = current
    return previous[-1]


def wer(reference, hypothesis):
    ref_words = normalize_text(reference).split()
    hyp_words = normalize_text(hypothesis).split()
    if not ref_words:
        return 0.0 if not hyp_words else 1.0
    return levenshtein_words(ref_words, hyp_words) / float(len(ref_words))


def exact_match(reference, hypothesis):
    return normalize_text(reference) == normalize_text(hypothesis)


def load_manifest(manifest_path, wav_paths):
    with manifest_path.open("r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if not reader.fieldnames:
            raise RuntimeError("manifest.tsv has no header")
        rows = list(reader)
        fieldnames = [x.strip() for x in reader.fieldnames]

    lower_to_original = {x.lower(): x for x in fieldnames}
    reference_field = None
    for key in REFERENCE_KEYS:
        if key in lower_to_original:
            reference_field = lower_to_original[key]
            break

    if reference_field is None:
        # Fallback: choose a non-path text-like column.
        for name in fieldnames:
            lname = name.lower()
            if "path" not in lname and "file" not in lname and lname not in ("id", "utt_id", "sample_id"):
                values = [(r.get(name) or "").strip() for r in rows[:5]]
                if any(" " in v for v in values):
                    reference_field = name
                    break

    if reference_field is None:
        raise RuntimeError(
            "Cannot identify reference transcript column. Manifest headers: %s"
            % ", ".join(fieldnames)
        )

    result = {}
    for wav in wav_paths:
        stem = wav.stem
        match = None

        # Strong match: any field equals stem or filename.
        for row in rows:
            values = [(v or "").strip() for v in row.values()]
            if stem in values or wav.name in values:
                match = row
                break

        # Path/string fallback.
        if match is None:
            for row in rows:
                values = [(v or "").strip() for v in row.values()]
                if any(stem in v for v in values):
                    match = row
                    break

        if match is None:
            raise RuntimeError("No manifest row found for %s" % wav.name)

        reference = (match.get(reference_field) or "").strip()
        if not reference:
            raise RuntimeError(
                "Empty reference for %s using column %s" % (wav.name, reference_field)
            )
        result[stem] = reference

    return result, reference_field, fieldnames


def parse_decode_metrics(text):
    elapsed = None
    rtf = None

    m = re.search(r"Elapsed seconds:\s*([0-9.]+)\s*s", text)
    if m:
        elapsed = float(m.group(1))

    m = re.search(r"Real time factor\s*\(RTF\):\s*([0-9.]+)\s*/\s*([0-9.]+)\s*=\s*([0-9.]+)", text)
    if m:
        rtf = float(m.group(3))

    return elapsed, rtf


def parse_transcript(text, wav_path):
    # Preferred: sherpa JSON result.
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and isinstance(obj.get("text"), str):
                    return obj["text"].strip()
            except Exception:
                pass

    # Common textual forms.
    regexes = [
        r'^\s*(?:text|result|transcript)\s*[:=]\s*(.+?)\s*$',
    ]
    for line in text.splitlines():
        for pat in regexes:
            m = re.match(pat, line, flags=re.I)
            if m:
                return m.group(1).strip()

    # Conservative fallback for online CLI plain-text output.
    reject_prefixes = (
        "num threads", "decoding method", "elapsed seconds", "real time factor",
        "command being timed", "user time", "system time", "percent of cpu",
        "maximum resident", "average ", "major ", "minor ", "voluntary ",
        "involuntary ", "swaps", "file system", "socket ", "signals ",
        "page size", "exit status", "started", "done",
    )
    wav_name = wav_path.name
    candidates = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        low = s.lower()
        if wav_name in s or s.endswith(".wav"):
            continue
        if s == "----":
            continue
        if any(low.startswith(p) for p in reject_prefixes):
            continue
        if s.startswith("[") and s.endswith("]"):
            continue
        if re.search(r"[A-Za-z]", s) and len(s) < 500:
            candidates.append(s)

    # Last plausible human-text line is usually the final hypothesis.
    return candidates[-1] if candidates else ""


class ProcMonitor(object):
    def __init__(self, pid, interval=0.05):
        self.pid = int(pid)
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.cpu_peak_pct = 0.0
        self.rss_peak_kb = 0
        self.cpu_seconds_last = 0.0
        self.clk_tck = float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
        self.prev_ticks = None
        self.prev_time = None

    def _read_stat(self):
        stat_path = "/proc/%d/stat" % self.pid
        status_path = "/proc/%d/status" % self.pid

        with open(stat_path, "r") as f:
            fields = f.read().split()
        ticks = int(fields[13]) + int(fields[14])

        rss_kb = 0
        with open(status_path, "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break

        return ticks, rss_kb

    def _loop(self):
        while not self.stop_event.is_set():
            now = time.time()
            try:
                ticks, rss_kb = self._read_stat()
            except Exception:
                break

            self.rss_peak_kb = max(self.rss_peak_kb, rss_kb)
            self.cpu_seconds_last = ticks / self.clk_tck

            if self.prev_ticks is not None and self.prev_time is not None:
                dt = now - self.prev_time
                if dt > 0:
                    cpu_pct = ((ticks - self.prev_ticks) / self.clk_tck) / dt * 100.0
                    if cpu_pct >= 0:
                        self.cpu_peak_pct = max(self.cpu_peak_pct, cpu_pct)

            self.prev_ticks = ticks
            self.prev_time = now
            time.sleep(self.interval)

    def start(self):
        self.thread = threading.Thread(target=self._loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)


def run_one(model_key, wav_path, reference, raw_dir):
    cfg = MODELS[model_key]
    cmd = [str(cfg["binary"])] + list(cfg["args"]) + [str(wav_path)]

    start = time.time()
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    mon = ProcMonitor(proc.pid)
    mon.start()
    stdout, stderr = proc.communicate()
    mon.stop()
    wall = time.time() - start

    combined = (stdout or "") + "\n" + (stderr or "")
    hypothesis = parse_transcript(combined, wav_path)
    decode_seconds, internal_rtf = parse_decode_metrics(combined)

    duration = wav_duration_seconds(wav_path)
    computed_rtf = (decode_seconds / duration) if decode_seconds is not None and duration > 0 else None
    cpu_avg_pct = (mon.cpu_seconds_last / wall * 100.0) if wall > 0 else 0.0

    raw_model_dir = raw_dir / model_key
    raw_model_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_model_dir / (wav_path.stem + ".txt")
    raw_path.write_text(
        "COMMAND:\n%s\n\nSTDOUT:\n%s\n\nSTDERR:\n%s\n"
        % (" ".join(shlex.quote(x) for x in cmd), stdout or "", stderr or "")
    )

    row = {
        "model": model_key,
        "model_label": cfg["label"],
        "sample_id": wav_path.stem,
        "wav": str(wav_path.relative_to(REPO_ROOT)),
        "reference": reference,
        "hypothesis": hypothesis,
        "reference_normalized": normalize_text(reference),
        "hypothesis_normalized": normalize_text(hypothesis),
        "exact_match": exact_match(reference, hypothesis) if hypothesis else False,
        "wer": wer(reference, hypothesis) if hypothesis else 1.0,
        "audio_duration_s": duration,
        "decode_seconds": decode_seconds,
        "rtf": internal_rtf if internal_rtf is not None else computed_rtf,
        "process_wall_seconds": wall,
        "cpu_avg_pct": cpu_avg_pct,
        "cpu_peak_pct": mon.cpu_peak_pct,
        "rss_peak_kb": mon.rss_peak_kb,
        "rss_peak_mb": mon.rss_peak_kb / 1024.0,
        "exit_status": proc.returncode,
        "parse_ok": bool(hypothesis),
        "raw_output": str(raw_path.relative_to(REPO_ROOT)),
    }
    return row


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


def summarize(rows):
    summary = {}
    for key in MODELS:
        subset = [r for r in rows if r["model"] == key]
        if not subset:
            continue

        def vals(name):
            return [float(r[name]) for r in subset if r.get(name) is not None]

        decode = vals("decode_seconds")
        rtf_vals = vals("rtf")
        cpu_avg = vals("cpu_avg_pct")
        cpu_peak = vals("cpu_peak_pct")
        rss = vals("rss_peak_mb")
        wers = vals("wer")
        wall = vals("process_wall_seconds")

        summary[key] = {
            "label": MODELS[key]["label"],
            "samples": len(subset),
            "exact_matches": sum(1 for r in subset if r["exact_match"]),
            "wer_mean": statistics.mean(wers) if wers else None,
            "decode_mean_s": statistics.mean(decode) if decode else None,
            "decode_median_s": statistics.median(decode) if decode else None,
            "decode_p95_s": percentile(decode, 0.95),
            "rtf_mean": statistics.mean(rtf_vals) if rtf_vals else None,
            "rtf_median": statistics.median(rtf_vals) if rtf_vals else None,
            "cpu_avg_mean_pct": statistics.mean(cpu_avg) if cpu_avg else None,
            "cpu_peak_max_pct": max(cpu_peak) if cpu_peak else None,
            "rss_peak_max_mb": max(rss) if rss else None,
            "process_wall_mean_s": statistics.mean(wall) if wall else None,
            "errors": sum(1 for r in subset if r["exit_status"] != 0),
            "parse_failures": sum(1 for r in subset if not r["parse_ok"]),
        }
    return summary


def fnum(value, digits=3):
    if value is None:
        return "-"
    return ("%." + str(digits) + "f") % value


def write_summary_md(path, summary):
    lines = [
        "# STT Model Comparison — CLEAN",
        "",
        "| Model | WER | Exact | Decode mean | Decode median | Decode p95 | RTF mean | CPU avg | CPU peak | Peak RSS | Errors |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in MODELS:
        s = summary.get(key)
        if not s:
            continue
        lines.append(
            "| %s | %s | %d/%d | %s s | %s s | %s s | %s | %s%% | %s%% | %s MB | %d |"
            % (
                s["label"],
                fnum(s["wer_mean"], 4),
                s["exact_matches"], s["samples"],
                fnum(s["decode_mean_s"]),
                fnum(s["decode_median_s"]),
                fnum(s["decode_p95_s"]),
                fnum(s["rtf_mean"]),
                fnum(s["cpu_avg_mean_pct"], 1),
                fnum(s["cpu_peak_max_pct"], 1),
                fnum(s["rss_peak_max_mb"], 1),
                s["errors"],
            )
        )
    lines += [
        "",
        "> CPU can exceed 100% because one process may use more than one CPU core.",
        "> `decode_*` and `rtf` prefer sherpa-onnx internal timing; process wall time includes model loading/startup and teardown.",
        "> Peak RSS/CPU are sampled from `/proc/<pid>` while the decoder process is alive.",
        "",
    ]
    path.write_text("\n".join(lines))


def validate_paths(dataset_dir, condition):
    missing = []

    condition_dir = dataset_dir / condition
    manifest = dataset_dir / "manifest.tsv"
    if not condition_dir.is_dir():
        missing.append(str(condition_dir))
    if not manifest.is_file():
        missing.append(str(manifest))

    for key, cfg in MODELS.items():
        if not cfg["binary"].is_file():
            missing.append(str(cfg["binary"]))
        for arg in cfg["args"]:
            if "=" in arg:
                value = arg.split("=", 1)[1]
                if value.startswith(str(REPO_ROOT)) and not Path(value).is_file():
                    missing.append(value)

    if missing:
        raise RuntimeError("Missing required path(s):\n- " + "\n- ".join(sorted(set(missing))))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--condition", choices=["clean", "noisy"], default="clean")
    parser.add_argument(
        "--models",
        default="all",
        help="all or comma separated: " + ",".join(MODELS.keys()),
    )
    parser.add_argument("--limit", type=int, default=0, help="0 = all WAV files")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir).resolve()
    output_root = Path(args.output_root).resolve()

    validate_paths(dataset_dir, args.condition)

    if args.models == "all":
        model_keys = list(MODELS.keys())
    else:
        model_keys = [x.strip() for x in args.models.split(",") if x.strip()]
        unknown = [x for x in model_keys if x not in MODELS]
        if unknown:
            raise RuntimeError("Unknown model(s): %s" % ", ".join(unknown))

    wavs = sorted((dataset_dir / args.condition).glob("*.wav"))
    if args.limit > 0:
        wavs = wavs[:args.limit]
    if not wavs:
        raise RuntimeError("No WAV files found")

    refs, ref_field, manifest_headers = load_manifest(dataset_dir / "manifest.tsv", wavs)

    run_id = args.run_id or timestamp_id()
    run_dir = output_root / run_id
    raw_dir = run_dir / "raw"
    run_dir.mkdir(parents=True, exist_ok=False)
    raw_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "run_id": run_id,
        "created_local": datetime.datetime.now().isoformat(),
        "git_commit": git_commit(),
        "repo_root": str(REPO_ROOT),
        "condition": args.condition,
        "dataset_dir": str(dataset_dir),
        "manifest_reference_field": ref_field,
        "manifest_headers": manifest_headers,
        "models": model_keys,
        "num_wavs": len(wavs),
        "provider": "cpu",
        "num_threads": 2,
        "decoding_method": "greedy_search",
        "precision": "FP32 / non-int8 model files",
        "gtcrn": False,
        "vad": False,
        "smart_turn": False,
        "speculative": False,
        "python": sys.version,
        "platform": platform.platform(),
        "jetson_release": jetson_release(),
        "sherpa_onnx_version": sherpa_version(),
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))

    samples_path = run_dir / "samples.jsonl"
    rows = []

    total_jobs = len(model_keys) * len(wavs)
    job_idx = 0

    with samples_path.open("w") as jf:
        for model_key in model_keys:
            print("\n=== %s ===" % MODELS[model_key]["label"])
            for wav_path in wavs:
                job_idx += 1
                print("[%d/%d] %s" % (job_idx, total_jobs, wav_path.name))
                row = run_one(model_key, wav_path, refs[wav_path.stem], raw_dir)
                rows.append(row)
                jf.write(json.dumps(row, sort_keys=True) + "\n")
                jf.flush()

                print(
                    "  hyp=%r | WER=%.3f | decode=%s | RTF=%s | CPUavg=%.1f%% | RSS=%.1f MB | exit=%d"
                    % (
                        row["hypothesis"],
                        row["wer"],
                        fnum(row["decode_seconds"]),
                        fnum(row["rtf"]),
                        row["cpu_avg_pct"],
                        row["rss_peak_mb"],
                        row["exit_status"],
                    )
                )

    summary = summarize(rows)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    write_summary_md(run_dir / "summary.md", summary)

    print("\n=== DONE ===")
    print("Result:", run_dir)
    print("")
    print((run_dir / "summary.md").read_text())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
