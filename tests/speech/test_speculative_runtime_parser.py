#!/usr/bin/env python3

import os
import sys


ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
    )
)

APP = os.path.join(ROOT, "app")

if APP not in sys.path:
    sys.path.insert(0, APP)


from core.messages import (
    TURN_COMPLETION_SMART_TURN,
    TURN_COMPLETION_SMART_TURN_SPECULATIVE,
    TURN_STATE_COMPLETE,
    TURN_STATE_WAITING_CONTINUATION,
)
from handlers.speech_runtime import SpeechRuntimeParser


def add_latency(parser, vad, stt, total):
    assert parser.feed_line(
        "[LATENCY] VAD   : {:.3f} s".format(vad)
    ) is None

    assert parser.feed_line(
        "[LATENCY] STT   : {:.3f} s".format(stt)
    ) is None

    return parser.feed_line(
        "[LATENCY] TOTAL : {:.3f} s".format(total)
    )


def main():
    parser = SpeechRuntimeParser()

    # rev0: Smart Turn says INCOMPLETE but speculative
    # mode lets Whisper run now.
    assert parser.feed_line(
        "[SMART_TURN] turn_id=10 candidate_id=10 "
        "segment_count=1 audio_prep_ms=2.000 "
        "feature_ms=1300.000 infer_ms=320.000 "
        "total_ms=1622.000 score=0.200000 "
        "decision=INCOMPLETE"
    ) is None

    assert parser.feed_line(
        "[SMART_TURN] turn_id=10 candidate_id=10 "
        "segment_count=1 revision=0 "
        "state=PROVISIONAL_TRANSCRIPT"
    ) is None

    assert parser.feed_line(
        "0: Explain UART"
    ) is None

    rev0 = add_latency(
        parser,
        0.500,
        1.500,
        2.000,
    )

    assert rev0 is not None
    assert rev0["turn_id"] == 10
    assert rev0["revision"] == 0

    assert (
        rev0["turn_state"]
        == TURN_STATE_WAITING_CONTINUATION
    )

    assert (
        rev0["completion_source"]
        == TURN_COMPLETION_SMART_TURN_SPECULATIVE
    )

    assert rev0["smart_turn_complete"] is False
    assert rev0["smart_turn_decision"] == "INCOMPLETE"

    # rev1: continuation is merged and becomes COMPLETE.
    assert parser.feed_line(
        "[SMART_TURN] turn_id=10 candidate_id=11 "
        "segment_count=2 audio_prep_ms=2.100 "
        "feature_ms=1310.000 infer_ms=321.000 "
        "total_ms=1633.100 score=0.950000 "
        "decision=COMPLETE"
    ) is None

    assert parser.feed_line(
        "1: Explain UART and compare it with SPI"
    ) is None

    rev1 = add_latency(
        parser,
        0.500,
        1.700,
        2.200,
    )

    assert rev1 is not None
    assert rev1["turn_id"] == 10
    assert rev1["revision"] == 1

    assert rev1["turn_state"] == TURN_STATE_COMPLETE

    assert (
        rev1["completion_source"]
        == TURN_COMPLETION_SMART_TURN
    )

    assert rev1["smart_turn_complete"] is True

    assert len(
        rev1["smart_turn_evaluations"]
    ) == 2

    print("PASS: Phase 8B speculative parser")
    print("INCOMPLETE -> rev0 dispatch: PASS")
    print("continuation -> rev1 COMPLETE: PASS")


if __name__ == "__main__":
    main()
