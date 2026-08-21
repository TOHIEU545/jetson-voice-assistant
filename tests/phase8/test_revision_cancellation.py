#!/usr/bin/env python3

import os
import queue
import sys
import threading
import time


PROJECT_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
    )
)

APP_DIR = os.path.join(
    PROJECT_ROOT,
    "app",
)

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from core.conversation import ConversationManager
from core.revisions import RevisionTracker
from handlers.llm import LLMHandler


class ControlledBackend(object):

    def __init__(
        self,
        first_token_event,
        continue_event,
    ):
        self.first_token_event = first_token_event
        self.continue_event = continue_event

    def stream_generate(
        self,
        messages,
        max_tokens,
        temperature,
    ):
        yield "old "

        self.first_token_event.set()

        # Keep rev 0 alive long enough for the test to
        # publish rev 1.
        self.continue_event.wait(timeout=2.0)

        yield "stale "

        yield "answer"


def make_turn(
    turn_id,
    revision,
    text,
):
    now = time.perf_counter()

    return {
        "turn_id": turn_id,
        "revision": revision,
        "turn_state": "complete",
        "turn_id_source": "test",
        "completion_source": "test",
        "segment_count": 1,

        "runtime_index": 42,
        "text": text,

        "t2": now,

        "vad_s": 0.5,
        "stt_s": 1.0,
        "vad_stt_total_s": 1.5,

        "smart_turn_complete": None,
        "smart_turn_score": None,
        "smart_turn_inference_s": None,

        "transcript_queue_enter": now,
        "transcript_queue_leave": now,

        "valid_turn_queue_enter": now,
        "valid_turn_queue_leave": None,

        "gate_processing_s": 0.0,
        "llm_processing_s": None,

        "t3": None,
        "t4": None,
        "t5": None,
    }


def main():
    valid_turn_queue = queue.Queue()
    llm_output_queue = queue.Queue()
    stop_event = threading.Event()

    revision_tracker = RevisionTracker()

    conversation_manager = ConversationManager(
        initial_history=[
            {
                "role": "system",
                "content": "You are EmbedAI.",
            }
        ],
        max_turns=6,
    )

    first_token_event = threading.Event()
    continue_event = threading.Event()

    backend = ControlledBackend(
        first_token_event=first_token_event,
        continue_event=continue_event,
    )

    handler = LLMHandler(
        valid_turn_queue=valid_turn_queue,
        llm_output_queue=llm_output_queue,
        stop_event=stop_event,
        conversation_manager=conversation_manager,
        backend=backend,
        revision_tracker=revision_tracker,
    )

    handler.start()

    rev0 = make_turn(
        turn_id=7,
        revision=0,
        text="Can you explain...",
    )

    valid_turn_queue.put(rev0)

    # Wait until rev 0 has started streaming.
    assert first_token_event.wait(timeout=2.0)

    # Simulate Smart Turn / realtime frontend discovering
    # a newer version of the SAME logical user turn.
    advanced = revision_tracker.observe(
        turn_id=7,
        revision=1,
    )

    assert advanced is True

    continue_event.set()

    valid_turn_queue.join()

    stop_event.set()
    handler.join(timeout=2.0)

    assert not handler.is_alive()
    assert handler.error is None

    assert handler.completed_count == 0
    assert handler.failed_count == 0
    assert handler.cancelled_count == 1

    # Stale turn must never enter committed history.
    assert conversation_manager.turn_count == 0

    assert conversation_manager.history == [
        {
            "role": "system",
            "content": "You are EmbedAI.",
        }
    ]

    events = []

    while not llm_output_queue.empty():
        events.append(
            llm_output_queue.get_nowait()
        )

    event_types = [
        event["type"]
        for event in events
    ]

    assert event_types[0] == "turn_start"
    assert "token" in event_types
    assert event_types[-1] == "turn_cancelled"

    cancelled = events[-1]

    assert cancelled["turn_id"] == 7
    assert cancelled["revision"] == 0
    assert cancelled["latest_revision"] == 1
    assert cancelled["reason"] == "stale_revision"

    assert "turn_done" not in event_types
    assert "llm_error" not in event_types

    print("PASS: Phase 8 revision cancellation")
    print("rev 0 generation started: PASS")
    print("rev 1 invalidates rev 0: PASS")
    print("stale token stream cancelled: PASS")
    print("stale history commit prevented: PASS")
    print("turn_cancelled event: PASS")


if __name__ == "__main__":
    main()
