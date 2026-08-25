#!/usr/bin/env python3

import os
from datetime import datetime


APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)


# ============================================================
# Speech runtime
# ============================================================

WHISPER_SHERPA_BIN = os.path.join(
    PROJECT_ROOT,
    "runtime",
    "sherpa-onnx",
    "build",
    "bin",
    "sherpa-onnx-vad-alsa-offline-asr",
)

STREAMING_SHERPA_BIN = os.path.join(
    PROJECT_ROOT,
    "runtime",
    "sherpa-onnx",
    "build",
    "bin",
    "sherpa-onnx-vad-alsa-streaming-asr",
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


# ============================================================
# STT BACKEND
# ============================================================

STT_BACKEND = os.environ.get(
    "VOICE_ASSISTANT_STT",
    "whisper",
).strip().lower()

SUPPORTED_STT_BACKENDS = (
    "whisper",
    "zipformer_20m",
    "zipformer_2023_06_21",
)

if STT_BACKEND not in SUPPORTED_STT_BACKENDS:
    raise RuntimeError(
        "Unsupported VOICE_ASSISTANT_STT={!r}. Supported: {}".format(
            STT_BACKEND,
            ", ".join(SUPPORTED_STT_BACKENDS),
        )
    )

ZIPFORMER_20M_DIR = os.path.join(
    PROJECT_ROOT,
    "models",
    "stt",
    "sherpa-onnx-streaming-zipformer-en-20M-2023-02-17",
)

ZIPFORMER_2023_06_21_DIR = os.path.join(
    PROJECT_ROOT,
    "models",
    "stt",
    "sherpa-onnx-streaming-zipformer-en-2023-06-21",
)

GTCRN_MODEL = os.path.join(
    PROJECT_ROOT,
    "models",
    "enhancement",
    "gtcrn_simple.onnx",
)

SMART_TURN_MODEL = os.path.join(
    PROJECT_ROOT,
    "models",
    "turn",
    "smart-turn-v3.2-cpu-opset16-ir8-clean.onnx",
)

SMART_TURN_THRESHOLD = 0.5
SMART_TURN_NUM_THREADS = 4

# Default: GTCRN OFF
#
# Enable:
#   VOICE_ASSISTANT_GTCRN=1 python3 voice_assistant.py
#
# Disable:
#   python3 voice_assistant.py
# or:
#   VOICE_ASSISTANT_GTCRN=0 python3 voice_assistant.py
ENABLE_GTCRN = (
    os.environ.get("VOICE_ASSISTANT_GTCRN", "0") == "1"
)

# Default: Smart Turn OFF
#
# Enable:
#   VOICE_ASSISTANT_SMART_TURN=1 python3 voice_assistant.py
#
# Disable:
#   python3 voice_assistant.py
# or:
#   VOICE_ASSISTANT_SMART_TURN=0 python3 voice_assistant.py
ENABLE_SMART_TURN = (
    os.environ.get("VOICE_ASSISTANT_SMART_TURN", "0") == "1"
)

# Phase 8 speculative execution.
#
# It is deliberately effective only when Smart Turn is enabled.
#
# Default:
#   SMART_TURN=0 / SPECULATIVE=0
#
# Phase 7C compatibility:
#   SMART_TURN=1 / SPECULATIVE=0
#
# Phase 8:
#   SMART_TURN=1 / SPECULATIVE=1
ENABLE_SPECULATIVE_TURN = (
    ENABLE_SMART_TURN
    and os.environ.get(
        "VOICE_ASSISTANT_SPECULATIVE",
        "0",
    ) == "1"
)

# Phase 9 barge-in cancellation.
#
# Default: ON
#
# Enable:
#   VOICE_ASSISTANT_BARGE_IN=1
#
# Disable:
#   VOICE_ASSISTANT_BARGE_IN=0
#
# Keep ON by default to preserve the existing Phase 9 behavior.
ENABLE_BARGE_IN = (
    os.environ.get("VOICE_ASSISTANT_BARGE_IN", "1") == "1"
)

MIC_DEVICE = os.environ.get(
    "VOICE_ASSISTANT_MIC_DEVICE",
    "plughw:2,0",
).strip()


def build_speech_command():
    """Build the C++ speech runtime command for the selected STT backend."""

    # Current Smart Turn / Speculative integration belongs to
    # the Whisper offline runtime only.
    if STT_BACKEND != "whisper" and ENABLE_SMART_TURN:
        raise RuntimeError(
            "Smart Turn is currently supported only "
            "with VOICE_ASSISTANT_STT=whisper"
        )

    if STT_BACKEND == "whisper":
        command = [
            WHISPER_SHERPA_BIN,

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
        ]

    else:
        if STT_BACKEND == "zipformer_20m":
            model_dir = ZIPFORMER_20M_DIR
        else:
            model_dir = ZIPFORMER_2023_06_21_DIR

        command = [
            STREAMING_SHERPA_BIN,

            "--silero-vad-model=" + VAD_MODEL,

            "--tokens=" + os.path.join(
                model_dir,
                "tokens.txt",
            ),
            "--encoder=" + os.path.join(
                model_dir,
                "encoder-epoch-99-avg-1.onnx",
            ),
            "--decoder=" + os.path.join(
                model_dir,
                "decoder-epoch-99-avg-1.onnx",
            ),
            "--joiner=" + os.path.join(
                model_dir,
                "joiner-epoch-99-avg-1.onnx",
            ),

            "--provider=cpu",
            "--vad-provider=cpu",

            "--num-threads=2",
            "--vad-num-threads=1",

            "--silero-vad-threshold=0.5",
            "--silero-vad-max-speech-duration=60",
        ]

    if ENABLE_GTCRN:
        command.append(
            "--speech-denoiser-gtcrn-model=" + GTCRN_MODEL
        )

    if ENABLE_SMART_TURN:
        command.extend([
            "--smart-turn-model=" + SMART_TURN_MODEL,
            "--smart-turn-threshold="
            + str(SMART_TURN_THRESHOLD),
            "--smart-turn-num-threads="
            + str(SMART_TURN_NUM_THREADS),
        ])

    if ENABLE_SPECULATIVE_TURN:
        command.append(
            "--smart-turn-speculative=1"
        )

    command.append(MIC_DEVICE)

    return command


# ============================================================
# LLM
# ============================================================

LLM_MODE = os.environ.get(
    "LLM_MODE",
    "local",
).strip().lower()

if LLM_MODE == "remote":
    remote_llm_url = os.environ.get(
        "REMOTE_LLM_URL",
        "",
    ).strip().rstrip("/")

    if not remote_llm_url:
        raise RuntimeError(
            "REMOTE_LLM_URL is required when LLM_MODE=remote"
        )

    LLM_BASE_URL = (
        remote_llm_url + "/v1/chat/completions"
    )

    LLM_MODEL = os.environ.get(
        "REMOTE_LLM_MODEL",
        "",
    ).strip() or None

    LLM_API_KEY = os.environ.get(
        "REMOTE_LLM_API_KEY",
        "",
    ).strip() or None

elif LLM_MODE == "local":
    LLM_BASE_URL = (
        "http://127.0.0.1:8080/v1/chat/completions"
    )

    LLM_MODEL = None
    LLM_API_KEY = None

else:
    raise RuntimeError(
        "LLM_MODE must be 'local' or 'remote'"
    )

# Backward-compatible alias for older benchmark tools.
LLM_URL = LLM_BASE_URL
LLM_MAX_TOKENS = 128
LLM_TEMPERATURE = 0.5
MAX_CONVERSATION_TURNS = 6


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