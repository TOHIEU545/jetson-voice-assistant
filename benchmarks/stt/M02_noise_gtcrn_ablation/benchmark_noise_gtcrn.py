#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M02 - Noisy speech GTCRN ablation benchmark.

Fixed backend:
    Zipformer 2023-06-21

Compared configurations:
    A. GTCRN OFF
    B. GTCRN ON

Input path:
    noisy WAV
      -> ALSA Loopback
      -> current project speech runtime
      -> optional GTCRN
      -> Silero VAD
      -> current optimized streaming Zipformer pipeline
      -> transcript + latency instrumentation

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
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "logs" / "benchmarks" / "stt" / "M02_noise_gtcrn_ablation"

STT_BACKEND = "zipformer_2023_06_21"

CONFIGS = {
    "gtcrn_off": {
        "label": "Zipformer 2023-06-21 + GTCRN OFF",
        "gtcrn": False,
    },
    "gtcrn_on": {
        "label": "Zipformer 2023-06-21 + GTCRN ON",
        "gtcrn": True,
    },
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
            "Cannot identify transcript column. Headers: %s" % ", ".join(headers)
        )

    refs = {}
    for wav in wavs:
        match = None
        for row in rows:
            values = [(v or "").strip() for v in row.values()]
            if wav.stem in values or wav.name in values:
                match = row
                break

        if match is None:
            for row in rows:
                values = [(v or "").strip() for v in row.values()]
                if any(wav.stem in v for v in values):
                    match = row
                    break

        if match is None:
            raise RuntimeError("No manifest row for %s" % wav.name)

        ref = (match.get(reference_field) or "").strip()
        if not ref:
            raise RuntimeError("Empty reference for %s" % wav.name)

        refs[wav.stem] = ref

    return refs, reference_field, headers


def build_project_speech_command(gtcrn_enabled, capture_device):
    env = os.environ.copy()
    env.update({
        "VOICE_ASSISTANT_STT": STT_BACKEND,
        "VOICE_ASSISTANT_GTCRN": "1" if gtcrn_enabled else "0",
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
            "Cannot build speech command.\nstdout:\n%s\nstderr:\n%s" % (out, err)
        )

    try:
        cmd = json.loads(out.splitlines()[-1])
    except Exception:
        raise RuntimeError("Invalid build_speech_command output:\n%s" % out)

    if not isinstance(cmd, list) or not cmd:
        raise RuntimeError("build_speech_command() did not return a command list")

    has_gtcrn = any(
        str(arg).startswith("--speech-denoiser-gtcrn-model=")
        for arg in cmd
    )

    if gtcrn_enabled and not has_gtcrn:
        raise RuntimeError("GTCRN ON requested but GTCRN argument is missing")

    if not gtcrn_enabled and has_gtcrn:
        raise RuntimeError("GTCRN OFF requested but GTCRN argument is present")

    return [str(x) for x in cmd], env


def command_model_inventory(command):
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
    with open("/proc/%d/stat" % int(pid), "r") as f:
        fields = f.read().split()

    ticks = int(fields[13]) + int(fields[14])

    rss_kb = 0
    with open("/proc/%d/status" % int(pid), "r") as f:
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
        if self.thread:
            self.thread.join(timeout=1.0)

    def stats(self, start_t, end_t):
        ss = [s for s in self.samples if start_t <= s["t"] <= end_t]

        if not ss:
            return {
                "cpu_avg_pct": None,
                "cpu_peak_pct": None,
                "rss_avg_mb": None,
                "rss_peak_mb": None,
            }

        cpus = [
            s["cpu_pct"]
            for s in ss
            if s["cpu_pct"] is not None and s["cpu_pct"] >= 0
        ]
        rss = [s["rss_kb"] / 1024.0 for s in ss]

        cpu_avg = None
        dt = ss[-1]["t"] - ss[0]["t"]
        if dt > 0:
            cpu_seconds = (ss[-1]["ticks"] - ss[0]["ticks"]) / self.clk_tck
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
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


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

        try:
            ts, line = reader.get(0.5)
        except queue.Empty:
            continue

        if "[READY]" in line:
            return ts

    raise RuntimeError("Timed out waiting for [READY]")


def play_wav(playback_device, wav_path):
    cmd = ["aplay", "-q", "-D", playback_device, str(wav_path)]

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
    seen = []

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                "Speech runtime exited during turn, status=%s" % proc.returncode
            )

        try:
            ts, line = reader.get(0.5)
        except queue.Empty:
            continue

        seen.append(line)

        hyp = parse_transcript_line(line)
        if hyp is not None and hyp != "":
            transcript = hyp
            transcript_t = ts

        key, value = parse_latency_line(line)
        if key:
            latency[key] = value

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
            }

    raise RuntimeError(
        "Timed out waiting for transcript/latency.\nLast lines:\n%s"
        % "\n".join(seen[-30:])
    )


def read_temperatures():
    temps = {}
    base = Path("/sys/class/thermal")

    if not base.exists():
        return temps

    for zone in sorted(base.glob("thermal_zone*")):
        try:
            name = (zone / "type").read_text().strip()
            raw = float((zone / "temp").read_text().strip())
            temps[name] = raw / 1000.0 if raw > 200 else raw
        except Exception:
            pass

    return temps


def system_snapshot():
    data = {
        "platform": platform.platform(),
        "python": sys.version,
        "git_commit": git_commit(),
        "git_status_short": git_status_short(),
        "temperatures_c": read_temperatures(),
    }

    p = Path("/etc/nv_tegra_release")
    if p.exists():
        try:
            data["nv_tegra_release"] = p.read_text().strip()
        except Exception:
            pass

    for label, cmd in [
        ("nvpmodel", ["nvpmodel", "-q"]),
        ("jetson_clocks", ["jetson_clocks", "--show"]),
        ("free_m", ["free", "-m"]),
        ("uname", ["uname", "-a"]),
    ]:
        rc, out, err = run_text(cmd, timeout=10)
        data[label] = {
            "status": rc,
            "stdout": out,
            "stderr": err,
        }

    return data


def check_loopback():
    cards = Path("/proc/asound/cards")

    if not cards.exists() or "Loopback" not in cards.read_text():
        raise RuntimeError(
            "ALSA Loopback is not loaded. Run M01 prepare_alsa_loopback.sh first."
        )


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


def run_config(
    config_key,
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
    cfg = CONFIGS[config_key]
    cfg_dir = run_dir / config_key
    cfg_dir.mkdir(parents=True, exist_ok=True)

    command, env = build_project_speech_command(
        cfg["gtcrn"],
        capture_device,
    )
    inventory = command_model_inventory(command)

    (cfg_dir / "command.txt").write_text(
        " ".join(shlex.quote(x) for x in command) + "\n"
    )

    raw_file = (cfg_dir / "runtime.log").open("w")

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

        reader.drain()

        for idx, wav_path in enumerate(wavs, 1):
            reader.drain()

            reference = refs[wav_path.stem]
            duration = wav_duration(wav_path)

            print(
                "[%s %d/%d] %s"
                % (config_key, idx, len(wavs), wav_path.name)
            )

            turn_start = time.monotonic()

            playback_start, playback_end = play_wav(
                playback_device,
                wav_path,
            )

            result = wait_turn_result(
                reader,
                proc,
                playback_end,
                turn_timeout,
            )

            turn_end = time.monotonic()
            resource = sampler.stats(turn_start, turn_end)

            dist, ref_words = word_distance(
                reference,
                result["hypothesis"],
            )

            row = {
                "config": config_key,
                "config_label": cfg["label"],
                "gtcrn": cfg["gtcrn"],
                "stt_backend": STT_BACKEND,
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
                "audio_duration_s": duration,
                "playback_wall_s": playback_end - playback_start,
                "vad_latency_s": result["vad_latency_s"],
                "stt_latency_s": result["stt_latency_s"],
                "total_latency_s": result["total_latency_s"],
                "wall_end_to_transcript_s": result["wall_end_to_transcript_s"],
                "turn_wall_s": turn_end - turn_start,
                "cpu_avg_pct": resource["cpu_avg_pct"],
                "cpu_peak_pct": resource["cpu_peak_pct"],
                "rss_avg_mb": resource["rss_avg_mb"],
                "rss_peak_mb": resource["rss_peak_mb"],
            }

            rows.append(row)

            print(
                "  hyp=%r | WER=%s | VAD=%ss | STT=%ss | TOTAL=%ss "
                "| CPUavg=%s%% | RSSpeak=%s MB"
                % (
                    row["hypothesis"],
                    fnum(row["wer"]),
                    fnum(row["vad_latency_s"]),
                    fnum(row["stt_latency_s"]),
                    fnum(row["total_latency_s"]),
                    fnum(row["cpu_avg_pct"], 1),
                    fnum(row["rss_peak_mb"], 1),
                )
            )

            time.sleep(settle_seconds)

        cfg_meta = {
            "config": config_key,
            "label": cfg["label"],
            "gtcrn": cfg["gtcrn"],
            "stt_backend": STT_BACKEND,
            "command": command,
            "model_files": inventory["files"],
            "onnx_size_mb": inventory["onnx_size_mb"],
            "startup_ready_s": startup_ready_s,
            "idle_cpu_avg_pct": idle_stats["cpu_avg_pct"],
            "idle_cpu_peak_pct": idle_stats["cpu_peak_pct"],
            "idle_rss_avg_mb": idle_stats["rss_avg_mb"],
            "idle_rss_peak_mb": idle_stats["rss_peak_mb"],
            "temperature_after_config_c": read_temperatures(),
            "samples": len(rows),
        }

        (cfg_dir / "config_metadata.json").write_text(
            json.dumps(cfg_meta, indent=2, sort_keys=True)
        )

        return rows, cfg_meta

    finally:
        stop_runtime(proc)
        sampler.stop()
        raw_file.close()


def summary_for_config(rows, cfg_meta):
    def vals(name):
        return [
            float(r[name])
            for r in rows
            if r.get(name) is not None
        ]

    total_words = sum(int(r["reference_words"]) for r in rows)
    total_edits = sum(int(r["word_edit_distance"]) for r in rows)

    out = {
        "config": cfg_meta["config"],
        "label": cfg_meta["label"],
        "gtcrn": cfg_meta["gtcrn"],
        "samples": len(rows),
        "corpus_wer": (
            total_edits / float(total_words)
            if total_words else 0.0
        ),
        "exact_matches": sum(1 for r in rows if r["exact_match"]),
        "onnx_size_mb": cfg_meta["onnx_size_mb"],
        "startup_ready_s": cfg_meta["startup_ready_s"],
        "idle_cpu_avg_pct": cfg_meta["idle_cpu_avg_pct"],
        "idle_cpu_peak_pct": cfg_meta["idle_cpu_peak_pct"],
        "idle_rss_avg_mb": cfg_meta["idle_rss_avg_mb"],
        "idle_rss_peak_mb": cfg_meta["idle_rss_peak_mb"],
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
        out[name + "_mean"] = statistics.mean(vv) if vv else None
        out[name + "_median"] = statistics.median(vv) if vv else None
        out[name + "_p95"] = percentile(vv, 0.95)
        out[name + "_max"] = max(vv) if vv else None

    return out


def paired_effect(rows):
    by_cfg = {}
    for key in CONFIGS:
        by_cfg[key] = {
            r["sample_id"]: r
            for r in rows
            if r["config"] == key
        }

    common = sorted(
        set(by_cfg["gtcrn_off"]).intersection(by_cfg["gtcrn_on"])
    )

    improved = 0
    worsened = 0
    unchanged = 0
    pairs = []

    for sid in common:
        off = by_cfg["gtcrn_off"][sid]
        on = by_cfg["gtcrn_on"][sid]

        delta_wer = float(on["wer"]) - float(off["wer"])

        if delta_wer < -1e-12:
            improved += 1
            status = "improved"
        elif delta_wer > 1e-12:
            worsened += 1
            status = "worsened"
        else:
            unchanged += 1
            status = "unchanged"

        pairs.append({
            "sample_id": sid,
            "reference": off["reference"],
            "gtcrn_off_hypothesis": off["hypothesis"],
            "gtcrn_on_hypothesis": on["hypothesis"],
            "gtcrn_off_wer": off["wer"],
            "gtcrn_on_wer": on["wer"],
            "delta_wer_on_minus_off": delta_wer,
            "status": status,
        })

    return {
        "paired_samples": len(common),
        "improved_samples": improved,
        "worsened_samples": worsened,
        "unchanged_samples": unchanged,
        "samples": pairs,
    }


def render_summary(summary, effect):
    off = summary.get("gtcrn_off")
    on = summary.get("gtcrn_on")

    lines = [
        "# M02 — Noise + GTCRN Ablation",
        "",
        "Fixed STT backend: `Zipformer 2023-06-21`",
        "",
        "## Accuracy + realtime latency",
        "",
        "| Config | Corpus WER | Exact | VAD mean | VAD p95 | STT mean | STT p95 | TOTAL mean | TOTAL p95 | Wall mean |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for key in ("gtcrn_off", "gtcrn_on"):
        s = summary.get(key)
        if not s:
            continue

        lines.append(
            "| %s | %s | %d/%d | %s s | %s s | %s s | %s s | %s s | %s s | %s s |"
            % (
                "GTCRN OFF" if key == "gtcrn_off" else "GTCRN ON",
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
            )
        )

    lines += [
        "",
        "## Resource",
        "",
        "| Config | ONNX size | Ready | Idle CPU | Idle RSS | Active CPU mean | Active CPU peak | Peak RSS |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for key in ("gtcrn_off", "gtcrn_on"):
        s = summary.get(key)
        if not s:
            continue

        lines.append(
            "| %s | %s MB | %s s | %s%% | %s MB | %s%% | %s%% | %s MB |"
            % (
                "GTCRN OFF" if key == "gtcrn_off" else "GTCRN ON",
                fnum(s["onnx_size_mb"], 1),
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
        "## Paired sample effect",
        "",
        "- Improved with GTCRN: %d/%d"
        % (effect["improved_samples"], effect["paired_samples"]),
        "- Worsened with GTCRN: %d/%d"
        % (effect["worsened_samples"], effect["paired_samples"]),
        "- Unchanged: %d/%d"
        % (effect["unchanged_samples"], effect["paired_samples"]),
    ]

    if off and on:
        lines += [
            "",
            "## GTCRN ON - OFF delta",
            "",
            "```text",
            "WER delta          : %+.4f"
            % (on["corpus_wer"] - off["corpus_wer"]),
            "Exact delta        : %+d"
            % (on["exact_matches"] - off["exact_matches"]),
            "TOTAL mean delta   : %+.1f ms"
            % ((on["total_latency_s_mean"] - off["total_latency_s_mean"]) * 1000.0),
            "TOTAL p95 delta    : %+.1f ms"
            % ((on["total_latency_s_p95"] - off["total_latency_s_p95"]) * 1000.0),
            "Active CPU delta   : %+.1f percentage-points"
            % (on["cpu_avg_pct_mean"] - off["cpu_avg_pct_mean"]),
            "Peak RSS delta     : %+.1f MB"
            % (on["rss_peak_mb_max"] - off["rss_peak_mb_max"]),
            "```",
        ]

    lines += [
        "",
        "`TOTAL` remains the main speech-end -> transcript realtime metric.",
        "The benchmark uses the same noisy WAV for both configurations and changes only GTCRN OFF/ON.",
        "",
    ]

    return "\n".join(lines)


def self_test():
    assert parse_transcript_line("0: PLEASE CALL STELLA") == "PLEASE CALL STELLA"
    assert parse_latency_line("[LATENCY] VAD : 0.500 s") == ("vad_latency_s", 0.5)
    assert parse_latency_line("[LATENCY] STT : 0.107 s") == ("stt_latency_s", 0.107)
    assert parse_latency_line("[LATENCY] TOTAL : 0.607 s") == ("total_latency_s", 0.607)
    assert exact_match("Please call Stella.", "PLEASE CALL STELLA")
    assert abs(sample_wer("Please call Stella.", "PLEASE CALL STELLA")) < 1e-12

    print("SELF-TEST PASS")


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--condition", choices=["noisy"], default="noisy")
    ap.add_argument("--limit", type=int, default=0, help="0 = all WAVs")
    ap.add_argument(
        "--order",
        default="gtcrn_off,gtcrn_on",
        help="gtcrn_off,gtcrn_on or gtcrn_on,gtcrn_off",
    )
    ap.add_argument("--dataset-dir", default=str(DEFAULT_DATASET))
    ap.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    ap.add_argument("--playback-device", default="plughw:Loopback,0,0")
    ap.add_argument("--capture-device", default="plughw:Loopback,1,0")
    ap.add_argument("--ready-timeout", type=float, default=60.0)
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

    order = [x.strip() for x in args.order.split(",") if x.strip()]
    if sorted(order) != sorted(CONFIGS.keys()) or len(order) != 2:
        raise RuntimeError(
            "--order must be gtcrn_off,gtcrn_on or gtcrn_on,gtcrn_off"
        )

    dataset = Path(args.dataset_dir).resolve()
    condition_dir = dataset / "noisy"
    manifest = dataset / "manifest.tsv"

    if not condition_dir.is_dir():
        raise RuntimeError("Noisy dataset dir not found: %s" % condition_dir)
    if not manifest.is_file():
        raise RuntimeError("Manifest not found: %s" % manifest)

    wavs = sorted(condition_dir.glob("*.wav"))
    if args.limit > 0:
        wavs = wavs[:args.limit]

    if not wavs:
        raise RuntimeError("No WAV files found in %s" % condition_dir)

    refs, reference_field, manifest_headers = load_manifest(manifest, wavs)

    check_loopback()

    run_id = args.run_id or now_id()
    output_root = Path(args.output_root).resolve()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "run_id": run_id,
        "created_local": datetime.datetime.now().isoformat(),
        "benchmark": "M02_noise_gtcrn_ablation",
        "stt_backend": STT_BACKEND,
        "condition": "noisy",
        "dataset_dir": str(dataset),
        "manifest_reference_field": reference_field,
        "manifest_headers": manifest_headers,
        "samples_per_config": len(wavs),
        "order": order,
        "smart_turn": False,
        "speculative": False,
        "barge_in": True,
        "playback_device": args.playback_device,
        "capture_device": args.capture_device,
        "system_before": system_snapshot(),
    }

    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True)
    )

    all_rows = []
    config_meta = {}

    samples_path = run_dir / "samples.jsonl"

    with samples_path.open("w") as jf:
        for index, config_key in enumerate(order):
            print("")
            print("========================================")
            print(CONFIGS[config_key]["label"])
            print("========================================")

            rows, meta = run_config(
                config_key=config_key,
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

            config_meta[config_key] = meta
            all_rows.extend(rows)

            for row in rows:
                jf.write(json.dumps(row, sort_keys=True) + "\n")
            jf.flush()

            if index != len(order) - 1:
                print("Cooldown %.1f s..." % args.cooldown_seconds)
                time.sleep(args.cooldown_seconds)

    summary = {}
    for config_key in CONFIGS:
        rows = [r for r in all_rows if r["config"] == config_key]
        summary[config_key] = summary_for_config(
            rows,
            config_meta[config_key],
        )

    effect = paired_effect(all_rows)

    metadata["system_after"] = system_snapshot()
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True)
    )

    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True)
    )

    (run_dir / "paired_effect.json").write_text(
        json.dumps(effect, indent=2, sort_keys=True)
    )

    summary_md = render_summary(summary, effect)
    (run_dir / "summary.md").write_text(summary_md)

    print("")
    print("========================================")
    print("M02 BENCHMARK DONE")
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
