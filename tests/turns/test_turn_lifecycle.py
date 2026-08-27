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


from core.conversation import ConversationManager
from core.messages import (
    TURN_COMPLETION_LEGACY_VAD,
    TURN_STATE_COMPLETE,
    TURN_STATE_WAITING_CONTINUATION,
    create_transcript_turn,
    is_complete_transcript_turn,
    turn_revision_key,
)


def main():
    # --------------------------------------------------------
    # Current production compatibility contract.
    # --------------------------------------------------------

    turn = create_transcript_turn(
        turn_id=7,
        runtime_index=42,
        text="Explain SPI.",
    )

    assert turn["revision"] == 0
    assert turn["turn_state"] == TURN_STATE_COMPLETE

    assert (
        turn["completion_source"]
        == TURN_COMPLETION_LEGACY_VAD
    )

    assert turn["segment_count"] == 1

    assert turn["smart_turn_complete"] is None
    assert turn["smart_turn_score"] is None
    assert turn["smart_turn_inference_s"] is None

    assert turn_revision_key(turn) == (7, 0)

    turn["vad_s"] = 0.5
    turn["stt_s"] = 1.5
    turn["vad_stt_total_s"] = 2.0

    assert is_complete_transcript_turn(turn)

    # --------------------------------------------------------
    # Future Smart Turn incomplete/reopen contract.
    # --------------------------------------------------------

    waiting = create_transcript_turn(
        turn_id=8,
        revision=1,
        runtime_index=43,
        text="",
        turn_state=TURN_STATE_WAITING_CONTINUATION,
        segment_count=2,
    )

    waiting["vad_s"] = 0.5
    waiting["stt_s"] = 1.0
    waiting["vad_stt_total_s"] = 1.5

    assert turn_revision_key(waiting) == (8, 1)

    # Even with latency fields, an incomplete logical turn must
    # not be considered a completed transcript turn.
    assert not is_complete_transcript_turn(waiting)

    # --------------------------------------------------------
    # ConversationManager must protect active revision.
    # --------------------------------------------------------

    manager = ConversationManager(
        initial_history=[
            {
                "role": "system",
                "content": "You are EmbedAI.",
            }
        ],
        max_turns=6,
    )

    manager.start_turn(
        turn_id=10,
        revision=2,
        text="What is UART?",
    )

    snapshot = manager.snapshot()

    assert snapshot["current_turn"]["turn_id"] == 10
    assert snapshot["current_turn"]["revision"] == 2

    mismatch_rejected = False

    try:
        manager.commit_turn(
            turn_id=10,
            revision=1,
            assistant_text="Wrong revision",
        )
    except RuntimeError:
        mismatch_rejected = True

    assert mismatch_rejected

    # Correct revision can still finish the active turn.
    manager.commit_turn(
        turn_id=10,
        revision=2,
        assistant_text="UART is a serial interface.",
    )

    assert manager.current_turn is None
    assert manager.turn_count == 1

    print("PASS: Phase 7 turn lifecycle foundation")
    print("turn_id + revision contract: PASS")
    print("turn_state contract: PASS")
    print("legacy VAD compatibility: PASS")
    print("revision mismatch protection: PASS")


if __name__ == "__main__":
    main()
