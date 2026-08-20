#!/usr/bin/env python3

import os
import re
import json
import subprocess
import time
import urllib.request
from datetime import datetime


# ============================================================
# Project paths
# ============================================================

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)

SHERPA_BIN = os.path.join(
    PROJECT_ROOT,
    "runtime",
    "sherpa-onnx",
    "build",
    "bin",
    "sherpa-onnx-vad-alsa-offline-asr"
)

VAD_MODEL = os.path.join(
    PROJECT_ROOT,
    "models",
    "vad",
    "silero_vad.onnx"
)

WHISPER_DIR = os.path.join(
    PROJECT_ROOT,
    "models",
    "stt",
    "whisper-tiny.en"
)

WHISPER_ENCODER = os.path.join(
    WHISPER_DIR,
    "tiny.en-encoder.onnx"
)

WHISPER_DECODER = os.path.join(
    WHISPER_DIR,
    "tiny.en-decoder.onnx"
)

WHISPER_TOKENS = os.path.join(
    WHISPER_DIR,
    "tiny.en-tokens.txt"
)

LLM_URL = "http://127.0.0.1:8080/v1/chat/completions"

MIC_DEVICE = "plughw:2,0"


# ============================================================
# Conversation log
# ============================================================

LOG_DIR = os.path.join(
    PROJECT_ROOT,
    "logs",
    "conversations"
)

os.makedirs(LOG_DIR, exist_ok=True)

session_start = datetime.now()

LOG_FILE = os.path.join(
    LOG_DIR,
    session_start.strftime("%Y-%m-%d_%H-%M-%S") + ".txt"
)

log_file = open(LOG_FILE, "w", buffering=1)

log_file.write("=" * 60 + "\n")
log_file.write(
    "Session started: "
    + session_start.strftime("%Y-%m-%d %H:%M:%S")
    + "\n"
)
log_file.write("=" * 60 + "\n\n")


# ============================================================
# Latency benchmark log
# ============================================================

BENCHMARK_DIR = os.path.join(
    PROJECT_ROOT,
    "logs",
    "benchmarks",
    "python_llm_latency"
)

os.makedirs(BENCHMARK_DIR, exist_ok=True)

BENCHMARK_FILE = os.path.join(
    BENCHMARK_DIR,
    session_start.strftime(
        "python_llm_latency_%Y-%m-%d_%H-%M-%S.jsonl"
    )
)

benchmark_file = open(BENCHMARK_FILE, "w", buffering=1)


# ============================================================
# Full-pipeline latency log
# ============================================================

FULL_PIPELINE_DIR = os.path.join(
    PROJECT_ROOT,
    "logs",
    "benchmarks",
    "full_pipeline_latency"
)

os.makedirs(FULL_PIPELINE_DIR, exist_ok=True)

FULL_PIPELINE_FILE = os.path.join(
    FULL_PIPELINE_DIR,
    session_start.strftime(
        "full_pipeline_latency_%Y-%m-%d_%H-%M-%S.jsonl"
    )
)

full_pipeline_file = open(
    FULL_PIPELINE_FILE,
    "w",
    buffering=1
)


# ============================================================
# VAD + Whisper
# ============================================================

cmd = [
    SHERPA_BIN,

    "--silero-vad-model=" + VAD_MODEL,

    "--whisper-encoder=" + WHISPER_ENCODER,
    "--whisper-decoder=" + WHISPER_DECODER,
    "--tokens=" + WHISPER_TOKENS,

    "--model-type=whisper",

    "--provider=cpu",
    "--vad-provider=cpu",

    "--num-threads=2",
    "--vad-num-threads=1",

    "--silero-vad-threshold=0.5",
    "--silero-vad-max-speech-duration=60",

    MIC_DEVICE,
]


# ============================================================
# Conversation history
# ============================================================

history = [
    {
        "role": "system",
        "content": (
            "You are EmbedAI, a voice assistant specialized in embedded systems. "
            "Keep normal conversation short and natural. "
            "For greetings or casual conversation, reply with only one short sentence. "
            "For simple technical questions, answer in 1 to 3 concise sentences. "
            "Explain the core idea first and use correct embedded terminology. "
            "Do not introduce yourself or list your capabilities unless explicitly asked. "
            "Do not repeat information unnecessarily. "
            "If the input is incomplete, unclear, corrupted, or looks like a speech recognition error, "
            "ask the user to repeat it instead of guessing. "
            "Your main domain is Embedded C/C++, STM32, ARM Cortex-M, bare-metal, RTOS, "
            "UART, SPI, I2C, CAN, device drivers, embedded Linux, bootloaders, and debugging."
        )
    }
]


# ============================================================
# UI
# ============================================================

print("===================================")
print(" Jetson Voice Assistant")
print(" Mic -> VAD -> Whisper -> Gemma")
print(" Conversation history: ON")
print("===================================")

print("Project:", PROJECT_ROOT)
print("Log:", LOG_FILE)
print("Benchmark:", BENCHMARK_FILE)
print("Full pipeline:", FULL_PIPELINE_FILE)
print()
print("Speak...")
print()


# ============================================================
# Start VAD + Whisper
# ============================================================

process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    universal_newlines=True,
    bufsize=1
)

turn_index = 0

# A completed Python/LLM turn waiting for the latency lines
# emitted by the sherpa C++ process.
pending_turn = None
pending_vad_latency = None
pending_stt_latency = None


try:
    for line in iter(process.stdout.readline, ""):

        line = line.strip()

        # ----------------------------------------------------
        # Latency lines emitted by the instrumented C++ binary
        #
        # [LATENCY] VAD   : ...
        # [LATENCY] STT   : ...
        # [LATENCY] TOTAL : ...
        # ----------------------------------------------------

        latency_match = re.match(
            r"^\[LATENCY\]\s+(VAD|STT|TOTAL)\s*:\s*"
            r"([0-9.]+)\s*s$",
            line
        )

        if latency_match:
            stage = latency_match.group(1)
            value = float(latency_match.group(2))

            if stage == "VAD":
                pending_vad_latency = value

            elif stage == "STT":
                pending_stt_latency = value

            elif stage == "TOTAL":
                vad_stt_total = value

                if pending_turn is not None:
                    full_record = dict(pending_turn)

                    full_record.update({
                        "vad_s": pending_vad_latency,
                        "stt_s": pending_stt_latency,
                        "vad_stt_total_s": vad_stt_total,

                        "speech_end_to_first_token_s":
                            vad_stt_total
                            + pending_turn[
                                "transcript_to_first_token_s"
                            ],

                        "speech_end_to_last_token_s":
                            vad_stt_total
                            + pending_turn[
                                "transcript_to_last_token_s"
                            ]
                    })

                    full_pipeline_file.write(
                        json.dumps(full_record) + "\n"
                    )

                    print()
                    print(
                        "[LATENCY] VAD          T0->T1 : {:.3f} s".format(
                            full_record["vad_s"]
                        )
                    )
                    print(
                        "[LATENCY] STT          T1->T2 : {:.3f} s".format(
                            full_record["stt_s"]
                        )
                    )
                    print(
                        "[LATENCY] VAD + STT    T0->T2 : {:.3f} s".format(
                            full_record["vad_stt_total_s"]
                        )
                    )
                    print(
                        "[LATENCY] Python       T2->T3 : {:.3f} s".format(
                            full_record["python_overhead_s"]
                        )
                    )
                    print(
                        "[LATENCY] LLM TTFT     T3->T4 : {:.3f} s".format(
                            full_record["llm_ttft_s"]
                        )
                    )
                    print(
                        "[LATENCY] LLM Gen      T4->T5 : {:.3f} s".format(
                            full_record["llm_generation_s"]
                        )
                    )
                    print("-------------------------------------------")
                    print(
                        "[FULL] Speech -> First T0->T4 : {:.3f} s".format(
                            full_record["speech_end_to_first_token_s"]
                        )
                    )
                    print(
                        "[FULL] Speech -> Last  T0->T5 : {:.3f} s".format(
                            full_record["speech_end_to_last_token_s"]
                        )
                    )
                    print("\nSpeak...")

                pending_turn = None
                pending_vad_latency = None
                pending_stt_latency = None

            continue

        # sherpa output:
        # 0: What is a microcontroller?
        match = re.match(r"^\d+:\s*(.+)$", line)

        if not match:
            continue

        # T2: final transcript has reached the Python application.
        t2 = time.perf_counter()

        text = match.group(1).strip()

        if not text:
            continue

        # Transcript Gate:
        # Whisper often emits (), [] or {} for non-speech/audio annotations.
        # For this assistant, treat any transcript containing these markers
        # as suspicious and do not send it to the LLM.
        if any(ch in text for ch in "()[]{}"):
            print('[GATE] DROP [whisper_annotation]: "{}"'.format(text))

            log_file.write(
                '[GATE DROP] whisper_annotation: "{}"\n'.format(text)
            )

            continue

        turn_index += 1

        # ---------------- User ----------------

        print("\nYou:", text)

        log_file.write("You: " + text + "\n")

        history.append({
            "role": "user",
            "content": text
        })

        # ---------------- LLM ----------------

        body = {
            "messages": history,
            "max_tokens": 128,
            "temperature": 0.5,
            "stream": True
        }

        request = urllib.request.Request(
            LLM_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        print("Assistant: ", end="", flush=True)

        # T3: client starts the LLM request.
        # urlopen() performs the actual HTTP send immediately after this.
        t3 = time.perf_counter()

        t4 = None
        t5 = None

        try:
            answer_parts = []

            with urllib.request.urlopen(request) as response:

                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()

                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()

                    if data == "[DONE]":
                        break

                    if not data:
                        continue

                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue

                    choices = chunk.get("choices", [])

                    if not choices:
                        continue

                    choice = choices[0]
                    token = ""

                    delta = choice.get("delta", {})

                    if isinstance(delta, dict):
                        token = delta.get("content") or ""

                    if not token:
                        token = choice.get("text") or ""

                    if token:
                        token_time = time.perf_counter()

                        # T4: first non-empty token received.
                        if t4 is None:
                            t4 = token_time

                        # T5 is continuously updated and therefore ends
                        # at the last non-empty token received.
                        t5 = token_time

                        print(token, end="", flush=True)
                        answer_parts.append(token)

            print()

            answer = "".join(answer_parts).strip()

            if answer:
                log_file.write("Assistant: " + answer + "\n\n")

                history.append({
                    "role": "assistant",
                    "content": answer
                })

            if t4 is not None and t5 is not None:
                python_overhead = t3 - t2
                llm_ttft = t4 - t3
                llm_generation = t5 - t4
                transcript_to_first = t4 - t2
                transcript_to_last = t5 - t2

                latency_record = {
                    "turn": turn_index,
                    "timestamp": datetime.now().isoformat(),
                    "transcript": text,

                    "python_overhead_s": python_overhead,
                    "llm_ttft_s": llm_ttft,
                    "llm_generation_s": llm_generation,

                    "transcript_to_first_token_s": transcript_to_first,
                    "transcript_to_last_token_s": transcript_to_last
                }

                benchmark_file.write(
                    json.dumps(latency_record) + "\n"
                )

                # sherpa prints its VAD/STT latency lines immediately
                # after the transcript. They remain buffered while the
                # Python process is waiting for the LLM response.
                # Save this turn so those lines can be associated with it.
                pending_turn = dict(latency_record)

            # Full latency summary is printed after the VAD/STT
            # measurements for this turn are received from sherpa.

        except Exception as e:

            print("\nLLM error:", e)

            log_file.write(
                "LLM error: " + str(e) + "\n\n"
            )


except KeyboardInterrupt:

    print("\n\nVoice Assistant stopped.")


finally:

    process.terminate()

    session_end = datetime.now()

    log_file.write("=" * 60 + "\n")
    log_file.write(
        "Session ended: "
        + session_end.strftime("%Y-%m-%d %H:%M:%S")
        + "\n"
    )
    log_file.write("=" * 60 + "\n")

    full_pipeline_file.close()
    benchmark_file.close()
    log_file.close()
