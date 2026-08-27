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


from core.conversation import ConversationManager


def main():
    manager = ConversationManager(
        initial_history=[
            {
                "role": "system",
                "content": "test",
            }
        ],
        max_turns=6,
    )

    manager.start_turn(
        turn_id=5,
        revision=0,
        text="Explain UART",
    )

    manager.commit_turn(
        turn_id=5,
        revision=0,
        assistant_text="Old answer",
    )

    assert manager.turn_count == 1

    manager.start_turn(
        turn_id=5,
        revision=1,
        text="Explain UART and SPI",
    )

    manager.commit_turn(
        turn_id=5,
        revision=1,
        assistant_text="New answer",
    )

    assert manager.turn_count == 1

    history = manager.history

    assert history[-2]["content"] == (
        "Explain UART and SPI"
    )

    assert history[-1]["content"] == (
        "New answer"
    )

    snapshot = manager.snapshot()

    assert snapshot["current_turn"] is None
    assert snapshot["assistant_state"] == "idle"

    print("PASS: Phase 8B revision supersede")
    print("rev1 replaces committed rev0: PASS")
    print("history duplication prevented: PASS")


if __name__ == "__main__":
    main()
