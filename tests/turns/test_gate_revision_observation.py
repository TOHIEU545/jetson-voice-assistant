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


from core.revisions import RevisionTracker
from handlers.transcript_gate import TranscriptGateHandler


def make_turn(turn_id, revision, text):
    return {
        "turn_id": turn_id,
        "revision": revision,
        "runtime_index": revision,
        "text": text,
        "transcript_queue_enter": None,
    }


def main():
    transcript_queue = queue.Queue()
    valid_turn_queue = queue.Queue()
    output_queue = queue.Queue()

    stop_event = threading.Event()
    tracker = RevisionTracker()

    gate = TranscriptGateHandler(
        transcript_queue=transcript_queue,
        valid_turn_queue=valid_turn_queue,
        stop_event=stop_event,
        output_event_queue=output_queue,
        revision_tracker=tracker,
    )

    gate.start()

    # rev0 accepted.
    transcript_queue.put(
        make_turn(
            turn_id=7,
            revision=0,
            text="Explain UART",
        )
    )

    transcript_queue.join()

    assert tracker.latest_revision(7) == 0
    assert valid_turn_queue.qsize() == 1

    # rev1 arrives while rev0 could already be generating.
    transcript_queue.put(
        make_turn(
            turn_id=7,
            revision=1,
            text="Explain UART and compare it with SPI",
        )
    )

    transcript_queue.join()

    # Critical Phase 8B property:
    # rev1 is known even though nobody has dequeued it yet.
    assert tracker.latest_revision(7) == 1
    assert tracker.is_stale(7, 0)
    assert not tracker.is_stale(7, 1)

    assert valid_turn_queue.qsize() == 2

    # A rejected transcript must NOT advance revision state.
    transcript_queue.put(
        make_turn(
            turn_id=7,
            revision=2,
            text="(buzzing)",
        )
    )

    transcript_queue.join()

    assert tracker.latest_revision(7) == 1
    assert valid_turn_queue.qsize() == 2

    stop_event.set()
    gate.join(timeout=2.0)

    assert not gate.is_alive()
    assert gate.error is None

    print("PASS: Phase 8B gate revision observation")
    print("rev1 observed before LLM dequeue: PASS")
    print("rev0 becomes stale immediately: PASS")
    print("dropped rev does not invalidate active turn: PASS")


if __name__ == "__main__":
    main()
