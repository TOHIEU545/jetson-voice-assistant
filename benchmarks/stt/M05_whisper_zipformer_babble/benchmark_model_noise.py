#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
M05 - Whisper Tiny.en vs Zipformer 2023-06-21 under severe Babble noise.

Compared STT backends:
    A. Whisper Tiny.en
    B. Zipformer 2023-06-21

Input:
    VoiceBank clean speech
      + MS-SNSD Babble noise
      + controlled SNR: 5 / 0 dB
      -> ALSA Loopback
      -> current app.config build_speech_command()
      -> Silero VAD
      -> backend-specific production speech runtime
      -> transcript + latency/resource instrumentation

GTCRN, Smart Turn and Speculative are intentionally OFF.
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

DEFAULT_DATASET = REPO_ROOT / "data" / "stt" / "ms_snsd" / "mixed" / "voicebank_prepared_15" / "babble"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "logs" / "benchmarks" / "stt" / "M05_whisper_zipformer_babble"

CONFIGS = {
    "whisper": {
        "label": "Whisper Tiny.en",
        "backend": "whisper",
    },
    "zipformer_2023_06_21": {
        "label": "Zipformer 2023-06-21",
        "backend": "zipformer_2023_06_21",
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



def load_dataset(manifest_path, snr_levels, limit_per_snr=0):
    with manifest_path.open("r", newline="") as f:
        reader = csv.DictReader(
            f,
            delimiter="\t",
        )
        headers = list(reader.fieldnames or [])
        rows = list(reader)

    if not headers:
        raise RuntimeError(
            "manifest.tsv has no header"
        )

    required = {
        "sample_id",
        "reference",
        "snr_db",
        "noise_type",
        "mixed_file",
        "measured_snr_db",
    }

    missing = required - set(headers)

    if missing:
        raise RuntimeError(
            "M05 manifest missing columns: %s"
            % ", ".join(sorted(missing))
        )

    selected = set(int(x) for x in snr_levels)

    items = []

    for row in rows:
        sample_id = (
            row.get("sample_id") or ""
        ).strip()

        reference = (
            row.get("reference") or ""
        ).strip()

        if not sample_id:
            raise RuntimeError(
                "Empty sample_id in manifest"
            )

        if not reference:
            raise RuntimeError(
                "Empty reference for %s"
                % sample_id
            )

        try:
            snr_db = int(
                row["snr_db"]
            )
        except Exception:
            raise RuntimeError(
                "Invalid snr_db for %s: %r"
                % (
                    sample_id,
                    row.get("snr_db"),
                )
            )

        if selected and snr_db not in selected:
            continue

        mixed_file = (
            row.get("mixed_file") or ""
        ).strip()

        wav_path = (
            REPO_ROOT / mixed_file
        ).resolve()

        if not wav_path.is_file():
            raise RuntimeError(
                "Mixed WAV not found: %s"
                % wav_path
            )

        try:
            measured_snr_db = float(
                row["measured_snr_db"]
            )
        except Exception:
            raise RuntimeError(
                "Invalid measured_snr_db for %s"
                % sample_id
            )

        items.append({
            "sample_id": sample_id,
            "sample_key": "%s@snr%d"
            % (
                sample_id,
                snr_db,
            ),
            "reference": reference,
            "snr_db": snr_db,
            "measured_snr_db":
                measured_snr_db,
            "noise_type": (
                row.get("noise_type") or ""
            ).strip(),
            "wav": wav_path,
        })

    items.sort(
        key=lambda item: (
            -item["snr_db"],
            item["sample_id"],
        )
    )

    if limit_per_snr > 0:
        limited = []
        counts = {}

        for item in items:
            snr_db = item["snr_db"]

            count = counts.get(
                snr_db,
                0,
            )

            if count >= limit_per_snr:
                continue

            limited.append(item)
            counts[snr_db] = count + 1

        items = limited

    if not items:
        raise RuntimeError(
            "No M05 samples selected"
        )

    return items, headers


def build_project_speech_command(model_key, capture_device):
    """Build the exact project runtime command for one STT backend."""
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

    has_gtcrn = any(
        str(arg).startswith("--speech-denoiser-gtcrn-model=")
        for arg in cmd
    )
    if has_gtcrn:
        raise RuntimeError("M05 requires GTCRN OFF, but GTCRN argument is present")

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
    items,
    run_dir,
    playback_device,
    capture_device,
    ready_timeout,
    turn_timeout,
    idle_seconds,
    settle_seconds,
):
    cfg = CONFIGS[config_key]

    cfg_dir = (
        run_dir / config_key
    )

    cfg_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    command, env = (
        build_project_speech_command(
            cfg["backend"],
            capture_device,
        )
    )

    inventory = command_model_inventory(
        command
    )

    (cfg_dir / "command.txt").write_text(
        " ".join(
            shlex.quote(x)
            for x in command
        )
        + "\n"
    )

    raw_file = (
        cfg_dir / "runtime.log"
    ).open("w")

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

    sampler = ResourceSampler(
        proc.pid,
        interval=0.05,
    )
    sampler.start()

    reader = RuntimeReader(
        proc,
        raw_file,
    )
    reader.start()

    rows = []

    try:
        ready_t = wait_ready(
            reader,
            proc,
            ready_timeout,
        )

        startup_ready_s = (
            ready_t - start_t
        )

        idle_start = time.monotonic()

        time.sleep(
            idle_seconds
        )

        idle_end = time.monotonic()

        idle_stats = sampler.stats(
            idle_start,
            idle_end,
        )

        reader.drain()

        for idx, item in enumerate(
            items,
            1,
        ):
            reader.drain()

            wav_path = item["wav"]
            reference = item["reference"]
            snr_db = item["snr_db"]

            duration = wav_duration(
                wav_path
            )

            print(
                "[%s %d/%d] SNR=%d dB | %s"
                % (
                    config_key,
                    idx,
                    len(items),
                    snr_db,
                    wav_path.name,
                )
            )

            turn_start = (
                time.monotonic()
            )

            (
                playback_start,
                playback_end,
            ) = play_wav(
                playback_device,
                wav_path,
            )

            result = wait_turn_result(
                reader,
                proc,
                playback_end,
                turn_timeout,
            )

            turn_end = (
                time.monotonic()
            )

            resource = sampler.stats(
                turn_start,
                turn_end,
            )

            dist, ref_words = (
                word_distance(
                    reference,
                    result["hypothesis"],
                )
            )

            row = {
                "config":
                    config_key,

                "config_label":
                    cfg["label"],

                "gtcrn":
                    False,

                "stt_backend":
                    cfg["backend"],

                "sample_id":
                    item["sample_id"],

                "sample_key":
                    item["sample_key"],

                "snr_db":
                    snr_db,

                "measured_snr_db":
                    item[
                        "measured_snr_db"
                    ],

                "noise_type":
                    item[
                        "noise_type"
                    ],

                "wav":
                    str(
                        wav_path.relative_to(
                            REPO_ROOT
                        )
                    ),

                "reference":
                    reference,

                "hypothesis":
                    result["hypothesis"],

                "reference_normalized":
                    normalize_text(
                        reference
                    ),

                "hypothesis_normalized":
                    normalize_text(
                        result[
                            "hypothesis"
                        ]
                    ),

                "exact_match":
                    exact_match(
                        reference,
                        result[
                            "hypothesis"
                        ],
                    ),

                "word_edit_distance":
                    dist,

                "reference_words":
                    ref_words,

                "wer":
                    sample_wer(
                        reference,
                        result[
                            "hypothesis"
                        ],
                    ),

                "audio_duration_s":
                    duration,

                "playback_wall_s":
                    (
                        playback_end
                        - playback_start
                    ),

                "vad_latency_s":
                    result[
                        "vad_latency_s"
                    ],

                "stt_latency_s":
                    result[
                        "stt_latency_s"
                    ],

                "total_latency_s":
                    result[
                        "total_latency_s"
                    ],

                "wall_end_to_transcript_s":
                    result[
                        "wall_end_to_transcript_s"
                    ],

                "turn_wall_s":
                    (
                        turn_end
                        - turn_start
                    ),

                "cpu_avg_pct":
                    resource[
                        "cpu_avg_pct"
                    ],

                "cpu_peak_pct":
                    resource[
                        "cpu_peak_pct"
                    ],

                "rss_avg_mb":
                    resource[
                        "rss_avg_mb"
                    ],

                "rss_peak_mb":
                    resource[
                        "rss_peak_mb"
                    ],
            }

            rows.append(row)

            print(
                "  hyp=%r | WER=%s | "
                "VAD=%ss | STT=%ss | "
                "TOTAL=%ss | "
                "CPUavg=%s%% | "
                "RSSpeak=%s MB"
                % (
                    row["hypothesis"],
                    fnum(
                        row["wer"]
                    ),
                    fnum(
                        row[
                            "vad_latency_s"
                        ]
                    ),
                    fnum(
                        row[
                            "stt_latency_s"
                        ]
                    ),
                    fnum(
                        row[
                            "total_latency_s"
                        ]
                    ),
                    fnum(
                        row[
                            "cpu_avg_pct"
                        ],
                        1,
                    ),
                    fnum(
                        row[
                            "rss_peak_mb"
                        ],
                        1,
                    ),
                )
            )

            time.sleep(
                settle_seconds
            )

        cfg_meta = {
            "config":
                config_key,

            "label":
                cfg["label"],

            "gtcrn":
                False,

            "stt_backend":
                cfg["backend"],

            "command":
                command,

            "model_files":
                inventory["files"],

            "onnx_size_mb":
                inventory[
                    "onnx_size_mb"
                ],

            "startup_ready_s":
                startup_ready_s,

            "idle_cpu_avg_pct":
                idle_stats[
                    "cpu_avg_pct"
                ],

            "idle_cpu_peak_pct":
                idle_stats[
                    "cpu_peak_pct"
                ],

            "idle_rss_avg_mb":
                idle_stats[
                    "rss_avg_mb"
                ],

            "idle_rss_peak_mb":
                idle_stats[
                    "rss_peak_mb"
                ],

            "temperature_after_config_c":
                read_temperatures(),

            "samples":
                len(rows),
        }

        (
            cfg_dir
            / "config_metadata.json"
        ).write_text(
            json.dumps(
                cfg_meta,
                indent=2,
                sort_keys=True,
            )
        )

        return rows, cfg_meta

    finally:
        stop_runtime(proc)
        sampler.stop()
        raw_file.close()



def metrics_for_rows(rows):
    def vals(name):
        return [
            float(r[name])
            for r in rows
            if r.get(name) is not None
        ]

    total_words = sum(
        int(r["reference_words"])
        for r in rows
    )

    total_edits = sum(
        int(r["word_edit_distance"])
        for r in rows
    )

    out = {
        "samples":
            len(rows),

        "corpus_wer":
            (
                total_edits
                / float(total_words)
                if total_words
                else 0.0
            ),

        "exact_matches":
            sum(
                1
                for r in rows
                if r["exact_match"]
            ),
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
        values = vals(name)

        out[name + "_mean"] = (
            statistics.mean(values)
            if values
            else None
        )

        out[name + "_median"] = (
            statistics.median(values)
            if values
            else None
        )

        out[name + "_p95"] = (
            percentile(
                values,
                0.95,
            )
        )

        out[name + "_max"] = (
            max(values)
            if values
            else None
        )

    return out


def summary_for_config(
    rows,
    cfg_meta,
):
    out = metrics_for_rows(
        rows
    )

    out.update({
        "config":
            cfg_meta["config"],

        "label":
            cfg_meta["label"],

        "gtcrn":
            False,

        "stt_backend":
            cfg_meta["stt_backend"],

        "onnx_size_mb":
            cfg_meta.get(
                "onnx_size_mb"
            ),

        "startup_ready_s":
            cfg_meta.get(
                "startup_ready_s"
            ),

        "idle_cpu_avg_pct":
            cfg_meta.get(
                "idle_cpu_avg_pct"
            ),

        "idle_cpu_peak_pct":
            cfg_meta.get(
                "idle_cpu_peak_pct"
            ),

        "idle_rss_avg_mb":
            cfg_meta.get(
                "idle_rss_avg_mb"
            ),

        "idle_rss_peak_mb":
            cfg_meta.get(
                "idle_rss_peak_mb"
            ),
    })

    by_snr = {}

    snrs = sorted(
        set(
            int(r["snr_db"])
            for r in rows
        ),
        reverse=True,
    )

    for snr_db in snrs:
        subset = [
            r
            for r in rows
            if int(r["snr_db"])
            == snr_db
        ]

        by_snr[
            str(snr_db)
        ] = metrics_for_rows(
            subset
        )

    out["by_snr"] = by_snr

    return out


def paired_effect(rows):
    """Pair same sample/SNR across both models and compare per-sample WER."""
    maps = {}
    for key in CONFIGS:
        maps[key] = {
            (r["sample_id"], int(r["snr_db"])): r
            for r in rows
            if r["config"] == key
        }

    common = sorted(
        set(maps["whisper"]).intersection(maps["zipformer_2023_06_21"]),
        key=lambda item: (-item[1], item[0]),
    )

    result = {
        "paired_samples": 0,
        "whisper_better_samples": 0,
        "zipformer_better_samples": 0,
        "same_samples": 0,
        "by_snr": {},
        "samples": [],
    }

    for sample_id, snr_db in common:
        whisper = maps["whisper"][(sample_id, snr_db)]
        zipformer = maps["zipformer_2023_06_21"][(sample_id, snr_db)]
        delta = float(whisper["wer"]) - float(zipformer["wer"])

        if delta < -1e-12:
            status = "whisper_better"
        elif delta > 1e-12:
            status = "zipformer_better"
        else:
            status = "same"

        result["paired_samples"] += 1
        result[status + "_samples"] += 1

        snr_key = str(snr_db)
        if snr_key not in result["by_snr"]:
            result["by_snr"][snr_key] = {
                "paired_samples": 0,
                "whisper_better_samples": 0,
                "zipformer_better_samples": 0,
                "same_samples": 0,
            }
        bucket = result["by_snr"][snr_key]
        bucket["paired_samples"] += 1
        bucket[status + "_samples"] += 1

        result["samples"].append({
            "sample_id": sample_id,
            "sample_key": "%s@snr%d" % (sample_id, snr_db),
            "snr_db": snr_db,
            "reference": whisper["reference"],
            "whisper_hypothesis": whisper["hypothesis"],
            "zipformer_hypothesis": zipformer["hypothesis"],
            "whisper_wer": whisper["wer"],
            "zipformer_wer": zipformer["wer"],
            "delta_wer_whisper_minus_zipformer": delta,
            "status": status,
        })

    return result


def render_summary(summary, effect):
    whisper = summary["whisper"]
    zipformer = summary["zipformer_2023_06_21"]

    snrs = sorted(
        set(int(x) for x in whisper["by_snr"]).intersection(
            int(x) for x in zipformer["by_snr"]
        ),
        reverse=True,
    )

    lines = [
        "# M05 — Whisper vs Zipformer under severe Babble noise",
        "",
        "GTCRN: `OFF`",
        "",
        "Noise: `MS-SNSD Babble`",
        "",
        "## Accuracy by SNR",
        "",
        "| SNR | Whisper WER | Zipformer WER | Whisper-Zipformer | Exact Whisper | Exact Zipformer | TOTAL mean Whisper | TOTAL mean Zipformer | TOTAL p95 Whisper | TOTAL p95 Zipformer |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for snr_db in snrs:
        w = whisper["by_snr"][str(snr_db)]
        z = zipformer["by_snr"][str(snr_db)]
        delta_pp = (w["corpus_wer"] - z["corpus_wer"]) * 100.0
        lines.append(
            "| %d dB | %.2f%% | %.2f%% | %+.2f pp | %d/%d | %d/%d | %s s | %s s | %s s | %s s |"
            % (
                snr_db,
                w["corpus_wer"] * 100.0,
                z["corpus_wer"] * 100.0,
                delta_pp,
                w["exact_matches"], w["samples"],
                z["exact_matches"], z["samples"],
                fnum(w["total_latency_s_mean"]),
                fnum(z["total_latency_s_mean"]),
                fnum(w["total_latency_s_p95"]),
                fnum(z["total_latency_s_p95"]),
            )
        )

    lines += [
        "",
        "Negative `Whisper-Zipformer` means Whisper has lower WER.",
        "",
        "## Overall",
        "",
        "| Model | Corpus WER | Exact | VAD mean | STT mean | TOTAL mean | TOTAL p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for key in ("whisper", "zipformer_2023_06_21"):
        current = summary[key]
        lines.append(
            "| %s | %.2f%% | %d/%d | %s s | %s s | %s s | %s s |"
            % (
                CONFIGS[key]["label"],
                current["corpus_wer"] * 100.0,
                current["exact_matches"], current["samples"],
                fnum(current["vad_latency_s_mean"]),
                fnum(current["stt_latency_s_mean"]),
                fnum(current["total_latency_s_mean"]),
                fnum(current["total_latency_s_p95"]),
            )
        )

    lines += [
        "",
        "## Resource",
        "",
        "| Model | ONNX size | Ready | Idle CPU | Idle RSS | Active CPU | CPU peak | Peak RSS |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for key in ("whisper", "zipformer_2023_06_21"):
        current = summary[key]
        lines.append(
            "| %s | %s MB | %s s | %s%% | %s MB | %s%% | %s%% | %s MB |"
            % (
                CONFIGS[key]["label"],
                fnum(current.get("onnx_size_mb"), 1),
                fnum(current.get("startup_ready_s")),
                fnum(current.get("idle_cpu_avg_pct"), 1),
                fnum(current.get("idle_rss_avg_mb"), 1),
                fnum(current.get("cpu_avg_pct_mean"), 1),
                fnum(current.get("cpu_peak_pct_max"), 1),
                fnum(current.get("rss_peak_mb_max"), 1),
            )
        )

    lines += [
        "",
        "## Paired effect",
        "",
        "```text",
        "ALL : Whisper better %d | Zipformer better %d | same %d | paired %d"
        % (
            effect["whisper_better_samples"],
            effect["zipformer_better_samples"],
            effect["same_samples"],
            effect["paired_samples"],
        ),
    ]

    for snr_db in snrs:
        bucket = effect["by_snr"].get(str(snr_db), {})
        lines.append(
            "%2d dB: Whisper better %d | Zipformer better %d | same %d | paired %d"
            % (
                snr_db,
                bucket.get("whisper_better_samples", 0),
                bucket.get("zipformer_better_samples", 0),
                bucket.get("same_samples", 0),
                bucket.get("paired_samples", 0),
            )
        )

    lines += [
        "```",
        "",
        "`TOTAL` is the main speech-end -> transcript realtime metric. `STT` is kept as a diagnostic metric because the two backends use different runtime architectures.",
        "",
    ]
    return "\n".join(lines)


def self_test():
    assert parse_transcript_line("0: PLEASE CALL STELLA") == "PLEASE CALL STELLA"
    assert parse_latency_line("[LATENCY] VAD : 0.500 s") == ("vad_latency_s", 0.5)
    assert exact_match("Please call Stella.", "PLEASE CALL STELLA")
    assert abs(sample_wer("Please call Stella.", "PLEASE CALL STELLA")) < 1e-12

    mock = []
    for config in ("whisper", "zipformer_2023_06_21"):
        for snr_db in (5, 0):
            mock.append({
                "config": config,
                "sample_id": "p232_001",
                "snr_db": snr_db,
                "reference": "Please call Stella.",
                "hypothesis": "PLEASE CALL STELLA",
                "wer": 0.0,
            })

    effect = paired_effect(mock)
    assert effect["paired_samples"] == 2
    assert set(effect["by_snr"]) == {"5", "0"}
    print("SELF-TEST PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snr", default="5,0", help="Comma-separated SNR levels, default: 5,0")
    ap.add_argument("--limit-per-snr", type=int, default=0, help="0 = all samples; 1 = smoke one sample per SNR")
    ap.add_argument(
        "--order",
        default="whisper,zipformer_2023_06_21",
        help="whisper,zipformer_2023_06_21 or zipformer_2023_06_21,whisper",
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
    ap.add_argument("--validate-dataset", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return

    snr_levels = [int(x.strip()) for x in args.snr.split(",") if x.strip()]
    if not snr_levels:
        raise RuntimeError("No SNR levels selected")

    order = [x.strip() for x in args.order.split(",") if x.strip()]
    if sorted(order) != sorted(CONFIGS.keys()) or len(order) != 2:
        raise RuntimeError(
            "--order must be whisper,zipformer_2023_06_21 or zipformer_2023_06_21,whisper"
        )

    dataset = Path(args.dataset_dir).resolve()
    manifest = dataset / "manifest.tsv"
    if not manifest.is_file():
        raise RuntimeError("Manifest not found: %s" % manifest)

    items, manifest_headers = load_dataset(manifest, snr_levels, args.limit_per_snr)
    counts = {}
    for item in items:
        snr_db = item["snr_db"]
        counts[snr_db] = counts.get(snr_db, 0) + 1

    if args.validate_dataset:
        print("========================================")
        print(" M05 DATASET VALIDATION")
        print("========================================")
        print("Dataset :", dataset)
        print("Samples :", len(items))
        for snr_db in sorted(counts, reverse=True):
            print("%2d dB   : %d" % (snr_db, counts[snr_db]))
        print("VALIDATION PASS")
        return

    check_loopback()

    run_id = args.run_id or now_id()
    output_root = Path(args.output_root).resolve()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "run_id": run_id,
        "created_local": datetime.datetime.now().isoformat(),
        "benchmark": "M05_whisper_zipformer_babble",
        "dataset_dir": str(dataset),
        "manifest_headers": manifest_headers,
        "snr_levels": snr_levels,
        "samples_per_snr": counts,
        "samples_per_model": len(items),
        "noise_types": sorted(set(item["noise_type"] for item in items)),
        "models": [CONFIGS[key]["backend"] for key in order],
        "order": order,
        "gtcrn": False,
        "smart_turn": False,
        "speculative": False,
        "barge_in": True,
        "playback_device": args.playback_device,
        "capture_device": args.capture_device,
        "system_before": system_snapshot(),
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))

    all_rows = []
    config_meta = {}
    samples_path = run_dir / "samples.jsonl"

    with samples_path.open("w") as jf:
        for index, config_key in enumerate(order):
            print()
            print("========================================")
            print(CONFIGS[config_key]["label"])
            print("========================================")

            rows, meta = run_config(
                config_key=config_key,
                items=items,
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
        summary[config_key] = summary_for_config(rows, config_meta[config_key])

    effect = paired_effect(all_rows)
    metadata["system_after"] = system_snapshot()
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    (run_dir / "paired_effect.json").write_text(json.dumps(effect, indent=2, sort_keys=True))

    summary_md = render_summary(summary, effect)
    (run_dir / "summary.md").write_text(summary_md)

    print()
    print("========================================")
    print("M05 BENCHMARK DONE")
    print("========================================")
    print("Result:", run_dir)
    print()
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
