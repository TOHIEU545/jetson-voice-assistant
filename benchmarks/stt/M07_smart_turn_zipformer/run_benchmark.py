#!/usr/bin/env python3
from __future__ import print_function

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

TRANSCRIPT_RE = re.compile(r"^\s*(\d+):\s*(.*)$")
LATENCY_TOTAL_RE = re.compile(r"^\[LATENCY\]\s+TOTAL\s*:\s*([0-9.]+)\s+s")
SMART_DECISION_RE = re.compile(
    r"^\[SMART_TURN\]\s+turn_id=(\d+)\s+candidate_id=(\d+)\s+segment_count=(\d+).*?"
    r"audio_prep_ms=([0-9.]+)\s+feature_ms=([0-9.]+)\s+infer_ms=([0-9.]+)\s+"
    r"total_ms=([0-9.]+)\s+score=([0-9.]+)\s+decision=(COMPLETE|INCOMPLETE)"
)
SMART_LOAD_RE = re.compile(r"^\[SMART_TURN\]\s+Runtime ready\.\s+load_ms=([0-9.]+)")


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--playback-device", default="plughw:Loopback,0,0")
    ap.add_argument("--capture-device", default="plughw:Loopback,1,0")
    ap.add_argument("--ready-timeout", type=float, default=45.0)
    ap.add_argument("--max-post-audio-wait", type=float, default=45.0)
    return ap.parse_args()


def repo_root_from_script():
    return Path(__file__).resolve().parents[3]


def load_manifest(path):
    rows = []
    with path.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    if len(rows) != 20:
        raise RuntimeError("Expected exactly 20 M07 rows, got {}".format(len(rows)))
    ids = [str(r["id"]) for r in rows]
    if len(set(ids)) != len(ids):
        raise RuntimeError("Manifest contains duplicate IDs")
    return rows


def hold_durations(row):
    out = []
    for span in row.get("silence_spans", []):
        if span.get("label") == "hold":
            out.append(float(span["end"]) - float(span["start"]))
    return out


def eot_silence_duration(row):
    for span in reversed(row.get("silence_spans", [])):
        if span.get("label") == "eot":
            return float(span["end"]) - float(span["start"])
    return None


def build_speech_command(repo_root, mode, capture_device):
    env = os.environ.copy()
    env.update({
        "VOICE_ASSISTANT_STT": "zipformer_2023_06_21",
        "VOICE_ASSISTANT_SMART_TURN": "1" if mode == "on" else "0",
        "VOICE_ASSISTANT_SPECULATIVE": "0",
        "VOICE_ASSISTANT_GTCRN": "0",
        "VOICE_ASSISTANT_MIC_DEVICE": capture_device,
    })
    code = 'import sys; sys.path.insert(0, "app"); import config; [print(x) for x in config.build_speech_command()]'
    proc = subprocess.Popen(
        [sys.executable, "-c", code], cwd=str(repo_root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError("Unable to build speech command for mode={}: {}".format(mode, stderr.strip()))
    command = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not command:
        raise RuntimeError("build_speech_command() returned an empty command")
    return command, env


def file_text(path):
    if not path.exists():
        return ""
    with path.open(errors="replace") as f:
        return f.read()


def tail_text(path, max_lines=80):
    return "\n".join(file_text(path).splitlines()[-max_lines:])


def wait_for_ready(proc, log_path, timeout):
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            raise RuntimeError("Speech runtime exited before READY (rc={}):\n{}".format(proc.returncode, tail_text(log_path)))
        if "[READY]" in file_text(log_path):
            return (time.time() - start) * 1000.0
        time.sleep(0.2)
    raise RuntimeError("Speech runtime did not become READY within {:.1f}s:\n{}".format(timeout, tail_text(log_path)))


def wait_until_log_quiet(proc, log_path, min_wait, quiet_seconds, max_wait):
    start = time.time()
    last_size = -1
    last_change = start
    while True:
        now = time.time()
        if proc.poll() is not None:
            return now - start
        try:
            size = log_path.stat().st_size
        except OSError:
            size = 0
        if size != last_size:
            last_size = size
            last_change = now
        elapsed = now - start
        if elapsed >= min_wait and now - last_change >= quiet_seconds:
            return elapsed
        if elapsed >= max_wait:
            return elapsed
        time.sleep(0.2)


def stop_runtime(proc):
    if proc.poll() is not None:
        return proc.returncode
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=10.0)
    except Exception:
        try:
            proc.terminate()
            proc.wait(timeout=5.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return proc.returncode


def parse_case_log(log_path):
    transcripts = []
    latency_total_s = []
    decisions = []
    speech_started = 0
    model_load_ms = None
    with log_path.open(errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("[SPEECH_STARTED]"):
                speech_started += 1
            m = TRANSCRIPT_RE.match(line)
            if m:
                transcripts.append({"index": int(m.group(1)), "text": m.group(2).strip()})
                continue
            m = LATENCY_TOTAL_RE.match(line)
            if m:
                latency_total_s.append(float(m.group(1)))
                continue
            m = SMART_LOAD_RE.match(line)
            if m:
                model_load_ms = float(m.group(1))
                continue
            m = SMART_DECISION_RE.match(line)
            if m:
                decisions.append({
                    "turn_id": int(m.group(1)), "candidate_id": int(m.group(2)),
                    "segment_count": int(m.group(3)), "audio_prep_ms": float(m.group(4)),
                    "feature_ms": float(m.group(5)), "infer_ms": float(m.group(6)),
                    "total_ms": float(m.group(7)), "score": float(m.group(8)),
                    "decision": m.group(9),
                })
    return {
        "speech_started_count": speech_started,
        "transcripts": transcripts,
        "transcript_count": len(transcripts),
        "latency_total_s": latency_total_s,
        "smart_turn_model_load_ms": model_load_ms,
        "smart_turn_decisions": decisions,
    }


def classify_turn_result(transcript_count):
    if transcript_count == 0:
        return "EOT_MISS"
    if transcript_count == 1:
        return "SINGLE_TURN"
    return "FALSE_CUTOFF"


def run_case(repo_root, manifest_dir, row, mode, output_dir, playback_device, capture_device, ready_timeout, max_post_audio_wait):
    case_id = str(row["id"])
    mode_dir = output_dir / "cases" / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    log_path = mode_dir / "{}.log".format(case_id)
    wav_path = manifest_dir / row["audio"]
    if not wav_path.is_file():
        raise RuntimeError("Missing WAV for {}: {}".format(case_id, wav_path))

    command, env = build_speech_command(repo_root, mode, capture_device)
    runtime_command = list(command)
    if shutil.which("stdbuf"):
        runtime_command = ["stdbuf", "-oL", "-eL"] + runtime_command

    log_fp = log_path.open("w")
    proc = None
    ready_ms = None
    playback_rc = None
    post_wait_s = None
    try:
        proc = subprocess.Popen(runtime_command, cwd=str(repo_root), env=env, stdout=log_fp, stderr=subprocess.STDOUT)
        ready_ms = wait_for_ready(proc, log_path, ready_timeout)
        playback_rc = subprocess.call(["aplay", "-q", "-D", playback_device, str(wav_path)])
        if playback_rc != 0:
            raise RuntimeError("aplay failed for {} mode={} rc={}".format(case_id, mode, playback_rc))
        if mode == "on":
            min_wait, quiet_seconds = 3.0, 2.8
        else:
            min_wait, quiet_seconds = 1.0, 1.8
        post_wait_s = wait_until_log_quiet(proc, log_path, min_wait, quiet_seconds, max_post_audio_wait)
    finally:
        if proc is not None:
            stop_runtime(proc)
        log_fp.close()

    parsed = parse_case_log(log_path)
    holds = hold_durations(row)
    decisions = parsed["smart_turn_decisions"]
    result = {
        "id": case_id,
        "mode": mode,
        "audio": str(wav_path),
        "duration_s": float(row["duration"]),
        "manifest_hold_count": len(holds),
        "manifest_max_hold_s": max(holds) if holds else 0.0,
        "manifest_eot_silence_s": eot_silence_duration(row),
        "runtime_ready_ms": ready_ms,
        "playback_rc": playback_rc,
        "post_audio_wait_s": post_wait_s,
        "speech_started_count": parsed["speech_started_count"],
        "transcript_count": parsed["transcript_count"],
        "transcripts": parsed["transcripts"],
        "turn_result": classify_turn_result(parsed["transcript_count"]),
        "latency_total_s": parsed["latency_total_s"],
        "smart_turn_model_load_ms": parsed["smart_turn_model_load_ms"],
        "smart_turn_candidate_count": len(decisions),
        "smart_turn_complete_count": sum(1 for d in decisions if d["decision"] == "COMPLETE"),
        "smart_turn_incomplete_count": sum(1 for d in decisions if d["decision"] == "INCOMPLETE"),
        "smart_turn_decisions": decisions,
        "log": str(log_path),
    }
    return result


def print_case_result(result):
    print("[{}] {} | hold={} max_hold={:.3f}s | transcripts={} | {}".format(
        result["mode"].upper(), result["id"], result["manifest_hold_count"],
        result["manifest_max_hold_s"], result["transcript_count"], result["turn_result"]))
    if result["mode"] == "on":
        print("     SmartTurn candidates={} INCOMPLETE={} COMPLETE={}".format(
            result["smart_turn_candidate_count"], result["smart_turn_incomplete_count"], result["smart_turn_complete_count"]))


def main():
    args = parse_args()
    repo_root = repo_root_from_script()
    manifest_path = Path(args.manifest).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_manifest(manifest_path)
    results_path = output_dir / "results.jsonl"

    print("Cases     : {}".format(len(rows)))
    print("Modes     : OFF, ON")
    print("Playback  : {}".format(args.playback_device))
    print("Capture   : {}".format(args.capture_device))
    print()

    with results_path.open("w") as out:
        for index, row in enumerate(rows, 1):
            print("==========================================")
            print(" Case {}/20: {}".format(index, row["id"]))
            print("==========================================")
            for mode in ("off", "on"):
                result = run_case(
                    repo_root, manifest_path.parent, row, mode, output_dir,
                    args.playback_device, args.capture_device,
                    args.ready_timeout, args.max_post_audio_wait)
                out.write(json.dumps(result, ensure_ascii=False) + "\n")
                out.flush()
                print_case_result(result)
                time.sleep(0.5)
            print()

    print("[OK] Raw results: {}".format(results_path))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[INTERRUPTED]", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print("[ERROR] {}".format(exc), file=sys.stderr)
        raise
