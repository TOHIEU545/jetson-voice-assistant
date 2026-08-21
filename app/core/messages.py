#!/usr/bin/env python3

import time


def create_transcript_turn(
    turn_id,
    runtime_index,
    text,
    t2=None,
):
    """
    Create one Python pipeline turn.

    turn_id:
        Python-side monotonically increasing turn identity.

    runtime_index:
        Transcript index printed by the current sherpa runtime.

    These values are intentionally separate. The current C++ stdout
    contract does not expose the producer's internal VAD turn_id.
    """

    if t2 is None:
        t2 = time.perf_counter()

    return {
        "turn_id": turn_id,
        "runtime_index": runtime_index,
        "text": text,
        "t2": t2,

        "vad_s": None,
        "stt_s": None,
        "vad_stt_total_s": None,

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


def is_complete_transcript_turn(turn):
    return (
        turn is not None
        and turn.get("vad_s") is not None
        and turn.get("stt_s") is not None
        and turn.get("vad_stt_total_s") is not None
    )
