#!/usr/bin/env python3

import os
import queue
import sys
import threading


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


from handlers.transcript_gate import (
    TranscriptGateHandler,
    validate_transcript,
)


def make_turn(turn_id, text):
    return {
        "turn_id": turn_id,
        "runtime_index": turn_id,
        "text": text,
        "transcript_queue_enter": None,
        "transcript_queue_leave": None,
        "valid_turn_queue_enter": None,
        "gate_processing_s": None,
    }


def test_gate_rules():
    accepted, reason = validate_transcript(
        make_turn(0, "What is UART?")
    )
    assert accepted is True
    assert reason is None

    accepted, reason = validate_transcript(
        make_turn(1, "(buzzing)")
    )
    assert accepted is False
    assert reason == "whisper_annotation"

    accepted, reason = validate_transcript(
        make_turn(2, "[inaudible]")
    )
    assert accepted is False
    assert reason == "whisper_annotation"

    accepted, reason = validate_transcript(
        make_turn(3, "")
    )
    assert accepted is False
    assert reason == "empty"


def test_handler():
    transcript_queue = queue.Queue()
    valid_turn_queue = queue.Queue()

    stop_event = threading.Event()

    handler = TranscriptGateHandler(
        transcript_queue=transcript_queue,
        valid_turn_queue=valid_turn_queue,
        stop_event=stop_event,
    )

    handler.start()

    transcript_queue.put(
        make_turn(0, "What is a microcontroller?")
    )

    transcript_queue.put(
        make_turn(1, "(buzzing)")
    )

    transcript_queue.put(
        make_turn(2, "What is SPI?")
    )

    transcript_queue.join()

    stop_event.set()
    handler.join(timeout=2.0)

    assert not handler.is_alive()
    assert handler.error is None

    assert handler.accepted_count == 2
    assert handler.dropped_count == 1

    accepted = []

    while not valid_turn_queue.empty():
        accepted.append(valid_turn_queue.get_nowait())

    assert len(accepted) == 2

    assert accepted[0]["turn_id"] == 0
    assert accepted[0]["text"] == "What is a microcontroller?"

    assert accepted[1]["turn_id"] == 2
    assert accepted[1]["text"] == "What is SPI?"

    for turn in accepted:
        assert turn["transcript_queue_leave"] is not None
        assert turn["valid_turn_queue_enter"] is not None
        assert turn["gate_processing_s"] is not None


def main():
    test_gate_rules()
    test_handler()

    print("PASS: TranscriptGateHandler")
    print("valid transcript -> valid_turn_queue")
    print("Whisper annotation -> DROP")


if __name__ == "__main__":
    main()
