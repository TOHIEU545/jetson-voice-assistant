#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STT pipeline comparison for jetson-voice-assistant.

This benchmark compares the three STT backends THROUGH THE PROJECT'S
CURRENT SPEECH RUNTIME ARCHITECTURE:

fixed WAV
  -> ALSA Loopback
  -> current app.config build_speech_command()
  -> Silero VAD
  -> backend-specific runtime architecture
  -> transcript + project latency instrumentation

Whisper path:
  VAD -> resident offline STT worker -> Whisper

Zipformer path:
  VAD -> rolling pre-roll / speech gating -> streaming Zipformer

GTCRN, Smart Turn and Speculative are intentionally OFF in this benchmark.

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
import queue
import re
import shlex
import signal
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

MODEL_ORDER = [
    "whisper",
    "zipformer_20m",
    "zipformer_2023_06_21",
]

MODEL_LABELS = {
    "whisper": "Whisper Tiny.en",
    "zipformer_20m": "Zipformer 20M 2023-02-17",
    "zipformer_2023_06_21": "Zipformer 2023-06-21",
}

REFERENCE_KEYS = (
    "reference", "transcript", "text", "ground_truth", "groundtruth",
    "sentence", "clean_text", "target",
)


def now_id():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


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
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out.strip(), err.strip()
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return 124, out.strip(), err.strip()
    except Exception as exc:
        return 127, "", str(exc)


def git_commit():
    rc, out, _ = run_text(["git", "rev-parse", "HEAD"])
    return out if rc == 0 else "unknown"


def git_status_short():
    rc, out, _ = run_text(["git", "status", "--short"])
    return out if rc == 0 else "unknown"


def wav_duration(path):
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def normalize_text(text):
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def word_distance(reference, hypothesis):
    ref = normalize_text(reference).split()
    hyp = normalize_text(hypothesis).split()

    previous = list(range(len(hyp) + 1))
    for i, rw in enumerate(ref, 1):
        current = [i]
        for j, hw in enumerate(hyp, 1):
            ins = current[j - 1] + 1
            delete = previous[j] + 1
            sub = previous[j - 1] + (0 if rw == hw else 1)
            current.append(min(ins, delete, sub))
        previous = current

    return previous[-1], len(ref)


def sample_wer(reference, hypothesis):
    dist, words = word_distance(reference, hypothesis)
    if words == 0:
        return 0.0 if not normalize_text(hypothesis) else 1.0
    return dist / float(words)


def exact_match(reference, hypothesis):
    return normalize_text(reference) == normalize_text(hypothesis)


def load_manifest(manifest_path, wavs):
    with manifest_path.open("r", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        headers = list(reader.fieldnames or [])
        rows = list(reader)

    if not headers:
        raise RuntimeError("manifest.tsv has no header")

    lower = {h.lower().strip(): h for h in headers}
    reference_field = None
    for key in REFERENCE_KEYS:
        if key in lower:
            reference_field = lower[key]
            break

    if reference_field is None:
        for h in headers:
            lh = h.lower()
            if "path" in lh or "file" in lh or lh in ("id", "utt_id", "sample_id"):
                continue
            values = [(r.get(h) or "").strip() for r in rows[:8]]
            if any(" " in v for v in values):
                reference_field = h
                break

    if reference_field is None:
        raise RuntimeError(
            "Cannot identify reference transcript column. Headers: %s"
            % ", ".join(headers)
        )

    result = {}
    for wav in wavs:
        stem = wav.stem
        match = None

        for row in rows:
            vals = [(v or "").strip() for v in row.values()]
            if stem in vals or wav.name in vals:
                match = row
                break

        if match is None:
            for row in rows:
                vals = [(v or "").strip() for v in row.values()]
                if any(stem in v for v in vals):
                    match = row
                    break

        if match is None:
            raise RuntimeError("No manifest row for %s" % wav.name)

        ref = (match.get(reference_field) or "").strip()
        if not ref:
            raise RuntimeError("Empty reference for %s" % wav.name)

        result[stem] = ref

    return result, reference_field, headers


def build_project_speech_command(model_key, capture_device):
    """
    Ask the project's current app.config.py to build the exact runtime command.
    This avoids duplicating model paths, thread counts, providers, etc.
    """
    env = os.environ.copy()
    env.update({
        "VOICE_ASSISTANT_STT": model_key,
        "VOICE_ASSISTANT_GTCRN": "0",
        "VOICE_ASSISTANT_SMART_TURN": "0",
        "VOICE_ASSISTANT_SPECULATIVE": "0",
        "VOICE_ASSISTANT_BARGE_IN": "1",
        "VOICE_ASSISTANT_MIC_DEVICE": capture_device,
    })

    code = (
        "import json\n"
        "from app.config import build_speech_command\n"
        "print(json.dumps(build_speech_command()))\n"
    )

    rc, out, err = run_text([sys.executable, "-c", code], env=env, timeout=15)
    if rc != 0:
        raise RuntimeError(
            "Cannot build speech command for %s.\nstdout:\n%s\nstderr:\n%s"
            % (model_key, out, err)
        )

    try:
        cmd = json.loads(out.splitlines()[-1])
    except Exception:
        raise RuntimeError("Invalid build_speech_command output:\n%s" % out)

    if not isinstance(cmd, list) or not cmd:
        raise RuntimeError("build_speech_command() did not return a command list")

    return [str(x) for x in cmd], env



def command_model_inventory(command):
    """Collect model/support files referenced by the project-generated command."""
    files = []
    onnx_bytes = 0

    for arg in command:
        if "=" not in arg:
            continue
        value = arg.split("=", 1)[1]
        p = Path(value)
        if not p.is_file():
            continue
        if p.suffix.lower() not in (".onnx", ".txt"):
            continue

        size = p.stat().st_size
        files.append({
            "path": str(p),
            "size_bytes": size,
        })
        if p.suffix.lower() == ".onnx":
            onnx_bytes += size

    return {
        "files": files,
        "onnx_size_mb": onnx_bytes / (1024.0 * 1024.0),
    }


def read_proc_ticks_rss(pid):
    stat_path = "/proc/%d/stat" % int(pid)
    status_path = "/proc/%d/status" % int(pid)

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


class ResourceSampler(object):
    def __init__(self, pid, interval=0.05):
        self.pid = int(pid)
        self.interval = float(interval)
        self.clk_tck = float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
        self.stop_event = threading.Event()
        self.samples = []
        self.thread = None

    def _loop(self):
        prev_ticks = None
        prev_time = None

        while not self.stop_event.is_set():
            ts = time.monotonic()
            try:
                ticks, rss_kb = read_proc_ticks_rss(self.pid)
            except Exception:
                break

            cpu_pct = None
            if prev_ticks is not None and prev_time is not None:
                dt = ts - prev_time
                if dt > 0:
                    cpu_pct = ((ticks - prev_ticks) / self.clk_tck) / dt * 100.0

            self.samples.append({
                "t": ts,
                "ticks": ticks,
                "rss_kb": rss_kb,
                "cpu_pct": cpu_pct,
            })

            prev_ticks = ticks
            prev_time = ts
            time.sleep(self.interval)

    def start(self):
        self.thread = threading.Thread(target=self._loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)

    def window(self, start_t, end_t):
        return [s for s in self.samples if start_t <= s["t"] <= end_t]

    def stats(self, start_t, end_t):
        ss = self.window(start_t, end_t)
        if not ss:
            return {
                "cpu_avg_pct": None,
                "cpu_peak_pct": None,
                "rss_avg_mb": None,
                "rss_peak_mb": None,
            }

        cpus = [s["cpu_pct"] for s in ss if s["cpu_pct"] is not None and s["cpu_pct"] >= 0]
        rss = [s["rss_kb"] / 1024.0 for s in ss]

        # Prefer CPU time delta over arithmetic mean of sampled percentages.
        cpu_avg = None
        first = ss[0]
        last = ss[-1]
        dt = last["t"] - first["t"]
        if dt > 0:
            cpu_seconds = (last["ticks"] - first["ticks"]) / self.clk_tck
            cpu_avg = cpu_seconds / dt * 100.0

        return {
            "cpu_avg_pct": cpu_avg,
            "cpu_peak_pct": max(cpus) if cpus else None,
            "rss_avg_mb": statistics.mean(rss) if rss else None,
            "rss_peak_mb": max(rss) if rss else None,
        }


class RuntimeReader(object):
    def __init__(self, proc, raw_file):
        self.proc = proc
        self.raw_file = raw_file
        self.q = queue.Queue()
        self.thread = None

    def _loop(self):
        for raw in self.proc.stdout:
            line = raw.rstrip("\n")
            self.raw_file.write(line + "\n")
            self.raw_file.flush()
            self.q.put((time.monotonic(), line))

    def start(self):
        self.thread = threading.Thread(target=self._loop)
        self.thread.daemon = True
        self.thread.start()

    def get(self, timeout):
        return self.q.get(timeout=timeout)

    def drain(self):
        items = []
        while True:
            try:
                items.append(self.q.get_nowait())
            except queue.Empty:
                break
        return items


def parse_latency_line(line):
    if "[LATENCY]" not in line.upper():
        return None, None

    matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*s\b", line, flags=re.I)
    if not matches:
        return None, None

    value = float(matches[-1])
    upper = line.upper()

    if "TOTAL" in upper or "VAD + STT" in upper or "T0->T2" in upper:
        return "total_latency_s", value

    if "STT" in upper or "T1->T2" in upper:
        return "stt_latency_s", value

    if "VAD" in upper or "T0->T1" in upper:
        return "vad_latency_s", value

    return None, None


def parse_transcript_line(line):
    # Current C++ speech runtime contract: "<index>: <transcript>"
    m = re.match(r"^\s*\d+\s*:\s*(.*?)\s*$", line)
    if m:
        return m.group(1).strip()
    return None


def wait_ready(reader, proc, timeout_s):
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                "Speech runtime exited before [READY], status=%s" % proc.returncode
            )

        remaining = max(0.05, deadline - time.monotonic())
        try:
            ts, line = reader.get(min(0.5, remaining))
        except queue.Empty:
            continue

        if "[READY]" in line:
            return ts

    raise RuntimeError("Timed out waiting for [READY]")


def play_wav(playback_device, wav_path):
    cmd = [
        "aplay",
        "-q",
        "-D", playback_device,
        str(wav_path),
    ]

    start = time.monotonic()
    rc, out, err = run_text(cmd)
    end = time.monotonic()

    if rc != 0:
        raise RuntimeError(
            "aplay failed for %s (status=%d)\n%s\n%s"
            % (wav_path.name, rc, out, err)
        )

    return start, end


def wait_turn_result(reader, proc, playback_end_t, timeout_s):
    deadline = time.monotonic() + timeout_s

    transcript = None
    transcript_t = None
    latency = {
        "vad_latency_s": None,
        "stt_latency_s": None,
        "total_latency_s": None,
    }
    seen_lines = []

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                "Speech runtime exited during turn, status=%s" % proc.returncode
            )

        remaining = max(0.05, deadline - time.monotonic())
        try:
            ts, line = reader.get(min(0.5, remaining))
        except queue.Empty:
            continue

        seen_lines.append(line)

        hyp = parse_transcript_line(line)
        if hyp is not None and hyp != "":
            transcript = hyp
            transcript_t = ts

        key, value = parse_latency_line(line)
        if key is not None:
            latency[key] = value

        # Current runtime emits transcript and all three latency values per turn.
        if (
            transcript is not None
            and latency["vad_latency_s"] is not None
            and latency["stt_latency_s"] is not None
            and latency["total_latency_s"] is not None
        ):
            return {
                "hypothesis": transcript,
                "transcript_t": transcript_t,
                "vad_latency_s": latency["vad_latency_s"],
                "stt_latency_s": latency["stt_latency_s"],
                "total_latency_s": latency["total_latency_s"],
                "wall_end_to_transcript_s": (
                    transcript_t - playback_end_t
                    if transcript_t is not None else None
                ),
                "seen_lines": seen_lines,
            }

    raise RuntimeError(
        "Timed out waiting for transcript/latency.\nLast runtime lines:\n%s"
        % "\n".join(seen_lines[-30:])
    )


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


def fnum(value, digits=3):
    if value is None:
        return "-"
    return ("%." + str(digits) + "f") % value


def read_temperatures():
    temps = {}
    base = Path("/sys/class/thermal")
    if not base.exists():
        return temps

    for zone in sorted(base.glob("thermal_zone*")):
        try:
            name = (zone / "type").read_text().strip()
            raw = float((zone / "temp").read_text().strip())
            c = raw / 1000.0 if raw > 200 else raw
            temps[name] = c
        except Exception:
            pass

    return temps


def system_snapshot():
    snapshot = {
        "platform": platform.platform(),
        "python": sys.version,
        "git_commit": git_commit(),
        "git_status_short": git_status_short(),
        "temperatures_c": read_temperatures(),
    }

    p = Path("/etc/nv_tegra_release")
    if p.exists():
        try:
            snapshot["nv_tegra_release"] = p.read_text().strip()
        except Exception:
            pass

    for label, cmd in [
        ("nvpmodel", ["nvpmodel", "-q"]),
        ("jetson_clocks", ["jetson_clocks", "--show"]),
        ("free_m", ["free", "-m"]),
        ("uname", ["uname", "-a"]),
    ]:
        rc, out, err = run_text(cmd, timeout=10)
        snapshot[label] = {
            "status": rc,
            "stdout": out,
            "stderr": err,
        }

    return snapshot


def check_loopback(playback_device, capture_device):
    if shutil_which("aplay") is None:
        raise RuntimeError("aplay is not installed")

    cards = Path("/proc/asound/cards")
    if not cards.exists() or "Loopback" not in cards.read_text():
        raise RuntimeError(
            "ALSA Loopback is not loaded. Run: sudo modprobe snd-aloop"
        )

    # Best-effort visibility only. Actual validity is proven when aplay/runtime open them.
    return {
        "playback_device": playback_device,
        "capture_device": capture_device,
        "cards": cards.read_text(),
    }


def shutil_which(cmd):
    # Python 3.6-safe tiny which helper without adding another dependency.
    path = os.environ.get("PATH", "")
    for folder in path.split(os.pathsep):
        candidate = os.path.join(folder, cmd)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def stop_runtime(proc):
    if proc.poll() is not None:
        return

    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10)
        return
    except Exception:
        pass

    try:
        proc.terminate()
        proc.wait(timeout=3)
        return
    except Exception:
        pass

    try:
        proc.kill()
    except Exception:
        pass


def run_model(
    model_key,
    wavs,
    refs,
    run_dir,
    playback_device,
    capture_device,
    ready_timeout,
    turn_timeout,
    idle_seconds,
    settle_seconds,
):
    label = MODEL_LABELS[model_key]
    model_dir = run_dir / model_key
    model_dir.mkdir(parents=True, exist_ok=True)

    command, env = build_project_speech_command(model_key, capture_device)
    model_inventory = command_model_inventory(command)

    (model_dir / "command.txt").write_text(
        " ".join(shlex.quote(x) for x in command) + "\n"
    )

    raw_path = model_dir / "runtime.log"
    raw_file = raw_path.open("w")

    start_t = time.monotonic()
    proc = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )

    sampler = ResourceSampler(proc.pid, interval=0.05)
    sampler.start()

    reader = RuntimeReader(proc, raw_file)
    reader.start()

    rows = []

    try:
        ready_t = wait_ready(reader, proc, ready_timeout)
        startup_ready_s = ready_t - start_t

        idle_start = time.monotonic()
        time.sleep(idle_seconds)
        idle_end = time.monotonic()
        idle_stats = sampler.stats(idle_start, idle_end)

        # Remove harmless startup chatter that arrived after [READY].
        reader.drain()

        for idx, wav_path in enumerate(wavs, 1):
            reader.drain()

            reference = refs[wav_path.stem]
            audio_duration_s = wav_duration(wav_path)

            print(
                "[%s %d/%d] %s"
                % (model_key, idx, len(wavs), wav_path.name)
            )

            turn_start_t = time.monotonic()
            playback_start_t, playback_end_t = play_wav(
                playback_device, wav_path
            )

            result = wait_turn_result(
                reader,
                proc,
                playback_end_t,
                turn_timeout,
            )
            turn_end_t = time.monotonic()

            resource = sampler.stats(turn_start_t, turn_end_t)

            dist, ref_words = word_distance(reference, result["hypothesis"])

            row = {
                "model": model_key,
                "model_label": label,
                "sample_id": wav_path.stem,
                "wav": str(wav_path.relative_to(REPO_ROOT)),
                "reference": reference,
                "hypothesis": result["hypothesis"],
                "reference_normalized": normalize_text(reference),
                "hypothesis_normalized": normalize_text(result["hypothesis"]),
                "exact_match": exact_match(reference, result["hypothesis"]),
                "word_edit_distance": dist,
                "reference_words": ref_words,
                "wer": sample_wer(reference, result["hypothesis"]),
                "audio_duration_s": audio_duration_s,
                "playback_wall_s": playback_end_t - playback_start_t,
                "vad_latency_s": result["vad_latency_s"],
                "stt_latency_s": result["stt_latency_s"],
                "total_latency_s": result["total_latency_s"],
                "wall_end_to_transcript_s": result["wall_end_to_transcript_s"],
                "turn_wall_s": turn_end_t - turn_start_t,
                "cpu_avg_pct": resource["cpu_avg_pct"],
                "cpu_peak_pct": resource["cpu_peak_pct"],
                "rss_avg_mb": resource["rss_avg_mb"],
                "rss_peak_mb": resource["rss_peak_mb"],
                "runtime_exit_status": proc.poll(),
            }

            rows.append(row)

            print(
                "  hyp=%r | WER=%s | VAD=%ss | STT=%ss | TOTAL=%ss "
                "| wall-after-audio=%ss | CPUavg=%s%% | RSSpeak=%s MB"
                % (
                    row["hypothesis"],
                    fnum(row["wer"], 3),
                    fnum(row["vad_latency_s"]),
                    fnum(row["stt_latency_s"]),
                    fnum(row["total_latency_s"]),
                    fnum(row["wall_end_to_transcript_s"]),
                    fnum(row["cpu_avg_pct"], 1),
                    fnum(row["rss_peak_mb"], 1),
                )
            )

            time.sleep(settle_seconds)

        model_meta = {
            "model": model_key,
            "model_label": label,
            "command": command,
            "model_files": model_inventory["files"],
            "model_onnx_size_mb": model_inventory["onnx_size_mb"],
            "startup_ready_s": startup_ready_s,
            "idle_seconds": idle_seconds,
            "idle_cpu_avg_pct": idle_stats["cpu_avg_pct"],
            "idle_cpu_peak_pct": idle_stats["cpu_peak_pct"],
            "idle_rss_avg_mb": idle_stats["rss_avg_mb"],
            "idle_rss_peak_mb": idle_stats["rss_peak_mb"],
            "temperature_after_model_c": read_temperatures(),
            "samples": len(rows),
        }

        (model_dir / "model_metadata.json").write_text(
            json.dumps(model_meta, indent=2, sort_keys=True)
        )

        return rows, model_meta

    finally:
        stop_runtime(proc)
        sampler.stop()
        raw_file.close()


def summary_for_model(rows, model_meta):
    def values(name):
        return [
            float(r[name])
            for r in rows
            if r.get(name) is not None
        ]

    total_ref_words = sum(int(r["reference_words"]) for r in rows)
    total_edits = sum(int(r["word_edit_distance"]) for r in rows)
    corpus_wer = (
        total_edits / float(total_ref_words)
        if total_ref_words else 0.0
    )

    out = {
        "model": model_meta["model"],
        "label": model_meta["model_label"],
        "samples": len(rows),
        "corpus_wer": corpus_wer,
        "mean_sample_wer": (
            statistics.mean(values("wer")) if values("wer") else None
        ),
        "exact_matches": sum(1 for r in rows if r["exact_match"]),
        "model_onnx_size_mb": model_meta.get("model_onnx_size_mb"),
        "startup_ready_s": model_meta["startup_ready_s"],
        "idle_cpu_avg_pct": model_meta["idle_cpu_avg_pct"],
        "idle_cpu_peak_pct": model_meta["idle_cpu_peak_pct"],
        "idle_rss_avg_mb": model_meta["idle_rss_avg_mb"],
        "idle_rss_peak_mb": model_meta["idle_rss_peak_mb"],
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
        vv = values(name)
        out[name + "_mean"] = statistics.mean(vv) if vv else None
        out[name + "_median"] = statistics.median(vv) if vv else None
        out[name + "_p95"] = percentile(vv, 0.95)
        out[name + "_max"] = max(vv) if vv else None

    return out


def render_summary(summary):
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
                s["exact_matches"],
                s["samples"],
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

    lines += [
        "",
        "### Metric meaning",
        "",
        "- `VAD`: speech-end -> VAD endpoint; directly affects perceived wait.",
        "- `STT`: VAD endpoint -> final transcript.",
        "- `TOTAL`: speech-end -> final transcript; main speech-front-end realtime metric.",
        "- `Wall after audio`: measured independently from `aplay` completion -> transcript line.",
        "- `Idle CPU/RSS`: resident runtime cost while waiting for speech.",
        "- `Active CPU/Peak RSS`: resource cost while processing a turn.",
        "- CPU may exceed 100% because one process can consume more than one CPU core.",
        "",
        "The benchmark runs the exact command produced by current `app.config.build_speech_command()`.",
        "GTCRN/Smart Turn/Speculative are OFF; ALSA Loopback provides deterministic fixed WAV input.",
        "",
    ]

    return "\n".join(lines)


def self_test():
    tests = [
        ("[LATENCY] VAD T0->T1 : 0.500 s", ("vad_latency_s", 0.5)),
        ("[LATENCY] STT T1->T2 : 0.107 s", ("stt_latency_s", 0.107)),
        ("[LATENCY] TOTAL T0->T2 : 0.607 s", ("total_latency_s", 0.607)),
        ("[LATENCY] VAD + STT T0->T2 : 0.607 s", ("total_latency_s", 0.607)),
    ]

    for line, expected in tests:
        got = parse_latency_line(line)
        if got != expected:
            raise RuntimeError(
                "Latency parser self-test failed: %r -> %r != %r"
                % (line, got, expected)
            )

    if parse_transcript_line("0: PLEASE CALL STELLA") != "PLEASE CALL STELLA":
        raise RuntimeError("Transcript parser self-test failed")

    if not exact_match("Please call Stella.", "PLEASE CALL STELLA"):
        raise RuntimeError("Normalization self-test failed")

    if abs(sample_wer("Please call Stella.", "PLEASE CALL STELLA")) > 1e-9:
        raise RuntimeError("WER self-test failed")

    print("SELF-TEST PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", choices=["clean", "noisy"], default="clean")
    ap.add_argument("--limit", type=int, default=0, help="0 = all WAVs")
    ap.add_argument(
        "--models",
        default="all",
        help="all or comma-separated: " + ",".join(MODEL_ORDER),
    )
    ap.add_argument("--dataset-dir", default=str(DEFAULT_DATASET))
    ap.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    ap.add_argument("--playback-device", default="plughw:Loopback,0,0")
    ap.add_argument("--capture-device", default="plughw:Loopback,1,0")
    ap.add_argument("--ready-timeout", type=float, default=45.0)
    ap.add_argument("--turn-timeout", type=float, default=30.0)
    ap.add_argument("--idle-seconds", type=float, default=2.0)
    ap.add_argument("--settle-seconds", type=float, default=0.35)
    ap.add_argument("--cooldown-seconds", type=float, default=5.0)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return

    dataset = Path(args.dataset_dir).resolve()
    condition_dir = dataset / args.condition
    manifest = dataset / "manifest.tsv"

    if not condition_dir.is_dir():
        raise RuntimeError("Dataset condition dir not found: %s" % condition_dir)
    if not manifest.is_file():
        raise RuntimeError("Manifest not found: %s" % manifest)

    if args.models == "all":
        models = list(MODEL_ORDER)
    else:
        models = [x.strip() for x in args.models.split(",") if x.strip()]
        unknown = [x for x in models if x not in MODEL_ORDER]
        if unknown:
            raise RuntimeError("Unknown model(s): %s" % ", ".join(unknown))

    wavs = sorted(condition_dir.glob("*.wav"))
    if args.limit > 0:
        wavs = wavs[:args.limit]
    if not wavs:
        raise RuntimeError("No WAV files found in %s" % condition_dir)

    refs, ref_field, manifest_headers = load_manifest(manifest, wavs)

    loopback = check_loopback(args.playback_device, args.capture_device)

    run_id = args.run_id or now_id()
    output_root = Path(args.output_root).resolve()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "run_id": run_id,
        "created_local": datetime.datetime.now().isoformat(),
        "scope": "speech pipeline STT backend comparison",
        "condition": args.condition,
        "dataset_dir": str(dataset),
        "manifest_reference_field": ref_field,
        "manifest_headers": manifest_headers,
        "models": models,
        "samples_per_model": len(wavs),
        "gtcrn": False,
        "smart_turn": False,
        "speculative": False,
        "barge_in": True,
        "playback_device": args.playback_device,
        "capture_device": args.capture_device,
        "loopback_cards": loopback["cards"],
        "system_before": system_snapshot(),
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True)
    )

    all_rows = []
    model_meta_all = {}

    samples_path = run_dir / "samples.jsonl"
    with samples_path.open("w") as jf:
        for model_index, model_key in enumerate(models):
            print("\n========================================")
            print("MODEL:", MODEL_LABELS[model_key])
            print("========================================")

            rows, model_meta = run_model(
                model_key=model_key,
                wavs=wavs,
                refs=refs,
                run_dir=run_dir,
                playback_device=args.playback_device,
                capture_device=args.capture_device,
                ready_timeout=args.ready_timeout,
                turn_timeout=args.turn_timeout,
                idle_seconds=args.idle_seconds,
                settle_seconds=args.settle_seconds,
            )

            model_meta_all[model_key] = model_meta
            all_rows.extend(rows)

            for row in rows:
                jf.write(json.dumps(row, sort_keys=True) + "\n")
            jf.flush()

            if model_index != len(models) - 1:
                print("Cooldown %.1f s..." % args.cooldown_seconds)
                time.sleep(args.cooldown_seconds)

    summary = {}
    for model_key in models:
        rows = [r for r in all_rows if r["model"] == model_key]
        summary[model_key] = summary_for_model(
            rows,
            model_meta_all[model_key],
        )

    metadata["system_after"] = system_snapshot()
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True)
    )

    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True)
    )

    summary_md = render_summary(summary)
    (run_dir / "summary.md").write_text(summary_md)

    print("\n========================================")
    print("BENCHMARK DONE")
    print("========================================")
    print("Result:", run_dir)
    print("")
    print(summary_md)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
