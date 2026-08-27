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
    TURN_COMPLETION_LEGACY_VAD,
    TURN_COMPLETION_SMART_TURN,
    TURN_ID_SOURCE_SPEECH_RUNTIME,
)
from handlers.speech_runtime import SpeechRuntimeParser


def main():
    parser = SpeechRuntimeParser()

    # --------------------------------------------------------
    # Candidate 1:
    # Smart Turn decides that the user has NOT finished.
    # No transcript must be emitted.
    # --------------------------------------------------------

    result = parser.feed_line(
        "[SMART_TURN] "
        "turn_id=10 "
        "candidate_id=10 "
        "segment_count=1 "
        "audio_prep_ms=2.000 "
        "feature_ms=1330.000 "
        "infer_ms=320.000 "
        "total_ms=1652.000 "
        "score=0.210000 "
        "decision=INCOMPLETE\n"
    )

    assert result is None

    # C++ also emits this lifecycle/debug line.
    # Python parser is intentionally allowed to ignore it.
    result = parser.feed_line(
        "[SMART_TURN] "
        "turn_id=10 "
        "state=WAITING_CONTINUATION "
        "segment_count=1 "
        "held_samples=42000\n"
    )

    assert result is None

    # --------------------------------------------------------
    # Candidate 2:
    # New VAD segment is merged with held audio.
    # Smart Turn now decides COMPLETE.
    # --------------------------------------------------------

    result = parser.feed_line(
        "[SMART_TURN] "
        "turn_id=10 "
        "candidate_id=11 "
        "segment_count=2 "
        "audio_prep_ms=2.100 "
        "feature_ms=1328.000 "
        "infer_ms=319.000 "
        "total_ms=1649.100 "
        "score=0.910000 "
        "decision=COMPLETE\n"
    )

    assert result is None

    # --------------------------------------------------------
    # Whisper finally runs on the merged logical turn.
    # --------------------------------------------------------

    assert parser.feed_line(
        "7: Can you explain UART interrupts?\n"
    ) is None

    assert parser.feed_line(
        "[LATENCY] VAD   : 0.500 s\n"
    ) is None

    assert parser.feed_line(
        "[LATENCY] STT   : 2.400 s\n"
    ) is None

    completed = parser.feed_line(
        "[LATENCY] TOTAL : 2.900 s\n"
    )

    assert completed is not None

    # --------------------------------------------------------
    # Logical turn identity
    # --------------------------------------------------------

    assert completed["turn_id"] == 10

    # 2 merged speech segments -> revision 1.
    assert completed["revision"] == 1

    assert (
        completed["turn_id_source"]
        == TURN_ID_SOURCE_SPEECH_RUNTIME
    )

    assert (
        completed["completion_source"]
        == TURN_COMPLETION_SMART_TURN
    )

    assert completed["segment_count"] == 2

    # --------------------------------------------------------
    # Transcript
    # --------------------------------------------------------

    assert completed["runtime_index"] == 7

    assert (
        completed["text"]
        == "Can you explain UART interrupts?"
    )

    # --------------------------------------------------------
    # Smart Turn final decision
    # --------------------------------------------------------

    assert completed["smart_turn_complete"] is True
    assert completed["smart_turn_decision"] == "COMPLETE"

    assert abs(
        completed["smart_turn_score"] - 0.91
    ) < 1e-9

    assert abs(
        completed["smart_turn_audio_prep_s"] - 0.0021
    ) < 1e-9

    assert abs(
        completed["smart_turn_feature_s"] - 1.328
    ) < 1e-9

    assert abs(
        completed["smart_turn_inference_s"] - 0.319
    ) < 1e-9

    assert abs(
        completed["smart_turn_total_s"] - 1.6491
    ) < 1e-9

    # Both Smart Turn evaluations must be retained.
    evaluations = completed[
        "smart_turn_evaluations"
    ]

    assert len(evaluations) == 2

    assert (
        evaluations[0]["decision"]
        == "INCOMPLETE"
    )

    assert (
        evaluations[1]["decision"]
        == "COMPLETE"
    )

    assert evaluations[0]["segment_count"] == 1
    assert evaluations[1]["segment_count"] == 2

    # --------------------------------------------------------
    # Existing VAD/STT latency contract
    # --------------------------------------------------------

    assert completed["vad_s"] == 0.500
    assert completed["stt_s"] == 2.400
    assert completed["vad_stt_total_s"] == 2.900

    # --------------------------------------------------------
    # Legacy path must still work after a Smart Turn turn.
    # Parser must continue IDs without collision.
    # --------------------------------------------------------

    assert parser.feed_line(
        "8: What is SPI?\n"
    ) is None

    assert parser.feed_line(
        "[LATENCY] VAD   : 0.500 s\n"
    ) is None

    assert parser.feed_line(
        "[LATENCY] STT   : 1.500 s\n"
    ) is None

    legacy = parser.feed_line(
        "[LATENCY] TOTAL : 2.000 s\n"
    )

    assert legacy is not None

    assert legacy["turn_id"] == 11
    assert legacy["revision"] == 0

    assert (
        legacy["completion_source"]
        == TURN_COMPLETION_LEGACY_VAD
    )

    assert legacy["smart_turn_complete"] is None
    assert legacy["smart_turn_score"] is None

    print(
        "PASS: Phase 7C Smart Turn runtime parser"
    )
    print(
        "INCOMPLETE -> COMPLETE merge metadata: PASS"
    )
    print(
        "runtime turn_id propagation: PASS"
    )
    print(
        "Smart Turn metrics propagation: PASS"
    )
    print(
        "legacy OFF compatibility: PASS"
    )


if __name__ == "__main__":
    main()
