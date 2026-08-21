#!/usr/bin/env python3

import os
from datetime import datetime


APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)


# ============================================================
# Speech runtime
# ============================================================

SHERPA_BIN = os.path.join(
    PROJECT_ROOT,
    "runtime",
    "sherpa-onnx",
    "build",
    "bin",
    "sherpa-onnx-vad-alsa-offline-asr",
)

VAD_MODEL = os.path.join(
    PROJECT_ROOT,
    "models",
    "vad",
    "silero_vad.onnx",
)

WHISPER_DIR = os.path.join(
    PROJECT_ROOT,
    "models",
    "stt",
    "whisper-tiny.en",
)

WHISPER_ENCODER = os.path.join(
    WHISPER_DIR,
    "tiny.en-encoder.onnx",
)

WHISPER_DECODER = os.path.join(
    WHISPER_DIR,
    "tiny.en-decoder.onnx",
)

WHISPER_TOKENS = os.path.join(
    WHISPER_DIR,
    "tiny.en-tokens.txt",
)

MIC_DEVICE = "plughw:2,0"


def build_speech_command():
    return [
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
# LLM
# ============================================================

LLM_URL = "http://127.0.0.1:8080/v1/chat/completions"

LLM_MAX_TOKENS = 128
LLM_TEMPERATURE = 0.5


INITIAL_HISTORY = [
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
        ),
    }
]


# ============================================================
# Session output paths
# ============================================================

def create_session_paths(session_start=None):
    if session_start is None:
        session_start = datetime.now()

    conversation_dir = os.path.join(
        PROJECT_ROOT,
        "logs",
        "conversations",
    )

    benchmark_dir = os.path.join(
        PROJECT_ROOT,
        "logs",
        "benchmarks",
        "python_llm_latency",
    )

    full_pipeline_dir = os.path.join(
        PROJECT_ROOT,
        "logs",
        "benchmarks",
        "full_pipeline_latency",
    )

    os.makedirs(conversation_dir, exist_ok=True)
    os.makedirs(benchmark_dir, exist_ok=True)
    os.makedirs(full_pipeline_dir, exist_ok=True)

    conversation_file = os.path.join(
        conversation_dir,
        session_start.strftime(
            "%Y-%m-%d_%H-%M-%S.txt"
        ),
    )

    benchmark_file = os.path.join(
        benchmark_dir,
        session_start.strftime(
            "python_llm_latency_%Y-%m-%d_%H-%M-%S.jsonl"
        ),
    )

    full_pipeline_file = os.path.join(
        full_pipeline_dir,
        session_start.strftime(
            "full_pipeline_latency_%Y-%m-%d_%H-%M-%S.jsonl"
        ),
    )

    return {
        "session_start": session_start,
        "conversation_log": conversation_file,
        "benchmark_log": benchmark_file,
        "full_pipeline_log": full_pipeline_file,
    }
