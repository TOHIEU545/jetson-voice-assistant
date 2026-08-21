#!/usr/bin/env python3

import time


TURN_STATE_OPEN = "open"
TURN_STATE_WAITING_CONTINUATION = "waiting_continuation"
TURN_STATE_COMPLETE = "complete"

TURN_ID_SOURCE_PYTHON_TRANSCRIPT = "python_transcript"
TURN_ID_SOURCE_SPEECH_RUNTIME = "speech_runtime"

TURN_COMPLETION_LEGACY_VAD = "legacy_vad"
TURN_COMPLETION_SMART_TURN = "smart_turn"

VALID_TURN_STATES = (
    TURN_STATE_OPEN,
    TURN_STATE_WAITING_CONTINUATION,
    TURN_STATE_COMPLETE,
)


def create_transcript_turn(
    turn_id,
    runtime_index,
    text,
    t2=None,
    revision=0,
    turn_state=TURN_STATE_COMPLETE,
    turn_id_source=TURN_ID_SOURCE_PYTHON_TRANSCRIPT,
    completion_source=TURN_COMPLETION_LEGACY_VAD,
    segment_count=1,
):
    """
    Create one Python pipeline turn.

    Phase 7 lifecycle contract:

        turn_id
            Logical conversational turn identity.

        revision
            Version of that logical turn.

        turn_state
            open / waiting_continuation / complete

    Current compatibility mode:

        turn_id_source    = python_transcript
        revision          = 0
        turn_state        = complete
        completion_source = legacy_vad

    This preserves the current production behavior until the C++
    speech runtime exposes true Smart-Turn-aware turn identity.
    """

    if t2 is None:
        t2 = time.perf_counter()

    if revision < 0:
        raise ValueError(
            "revision must be >= 0"
        )

    if turn_state not in VALID_TURN_STATES:
        raise ValueError(
            "invalid turn_state: %s" % turn_state
        )

    if segment_count < 1:
        raise ValueError(
            "segment_count must be >= 1"
        )

    return {
        "turn_id": turn_id,
        "revision": revision,
        "turn_state": turn_state,
        "turn_id_source": turn_id_source,
        "completion_source": completion_source,
        "segment_count": segment_count,

        "runtime_index": runtime_index,
        "text": text,
        "t2": t2,

        "vad_s": None,
        "stt_s": None,
        "vad_stt_total_s": None,

        # Phase 7 Smart Turn metrics.
        #
        # They remain None while running the legacy
        # VAD -> Whisper path.
        "smart_turn_complete": None,
        "smart_turn_score": None,
        "smart_turn_inference_s": None,

        "transcript_queue_enter": None,
        "transcript_queue_leave": None,

        "valid_turn_queue_enter": None,
        "valid_turn_queue_leave": None,

        "gate_processing_s": None,
        "llm_processing_s": None,

        "t3": None,
        "t4": None,
        "t5": None,
    }


def turn_revision_key(turn):
    """
    Stable identity used by later stale-output/cancellation logic.
    """
    return (
        turn["turn_id"],
        turn.get("revision", 0),
    )


def is_complete_transcript_turn(turn):
    if turn is None:
        return False

    turn_state = turn.get(
        "turn_state",
        TURN_STATE_COMPLETE,
    )

    return (
        turn_state == TURN_STATE_COMPLETE
        and turn.get("vad_s") is not None
        and turn.get("stt_s") is not None
        and turn.get("vad_stt_total_s") is not None
    )
