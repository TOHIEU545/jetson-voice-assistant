#!/usr/bin/env python3

import os
import sys


PROJECT_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
    )
)

APP_DIR = os.path.join(PROJECT_ROOT, "app")

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from core.messages import (
    TURN_COMPLETION_SMART_TURN_FALLBACK,
    TURN_ID_SOURCE_SPEECH_RUNTIME,
)
from handlers.speech_runtime import SpeechRuntimeParser


def main():
    parser = SpeechRuntimeParser()

    # Smart Turn inference failed.
    # C++ contract: fail open and continue to Whisper.
    assert parser.feed_line(
        "[SMART_TURN] "
        "turn_id=5 "
        "candidate_id=5 "
        "segment_count=1 "
        "decision=ERROR "
        "fallback=WHISPER\n"
    ) is None

    assert parser.feed_line(
        "3: What is UART?\n"
    ) is None

    assert parser.feed_line(
        "[LATENCY] VAD   : 0.500 s\n"
    ) is None

    assert parser.feed_line(
        "[LATENCY] STT   : 1.700 s\n"
    ) is None

    completed = parser.feed_line(
        "[LATENCY] TOTAL : 2.200 s\n"
    )

    assert completed is not None

    assert completed["turn_id"] == 5
    assert completed["revision"] == 0
    assert completed["segment_count"] == 1

    assert (
        completed["turn_id_source"]
        == TURN_ID_SOURCE_SPEECH_RUNTIME
    )

    assert (
        completed["completion_source"]
        == TURN_COMPLETION_SMART_TURN_FALLBACK
    )

    assert completed["text"] == "What is UART?"

    assert completed["smart_turn_complete"] is None
    assert completed["smart_turn_score"] is None
    assert completed["smart_turn_decision"] == "ERROR"

    evaluations = completed[
        "smart_turn_evaluations"
    ]

    assert len(evaluations) == 1
    assert evaluations[0]["decision"] == "ERROR"

    print("PASS: Phase 7C Smart Turn fallback")
    print("Smart Turn ERROR -> Whisper: PASS")
    print("turn identity preservation: PASS")


if __name__ == "__main__":
    main()
