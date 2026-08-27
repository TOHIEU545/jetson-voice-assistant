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

APP_DIR = os.path.join(
    PROJECT_ROOT,
    "app",
)

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from core.conversation import ConversationManager


def main():
    manager = ConversationManager(
        initial_history=[
            {
                "role": "system",
                "content": "You are EmbedAI.",
            }
        ],
        max_turns=2,
    )

    # --------------------------------------------------------
    # Turn 1: current user is sent to LLM but not committed yet.
    # --------------------------------------------------------

    messages = manager.start_turn(
        turn_id=1,
        text="Question 1",
    )

    assert [
        item["role"]
        for item in messages
    ] == [
        "system",
        "user",
    ]

    assert len(manager.history) == 1
    assert manager.turn_count == 0
    assert manager.assistant_state == "generating"

    manager.commit_turn(
        turn_id=1,
        assistant_text="Answer 1",
    )

    assert manager.turn_count == 1
    assert manager.assistant_state == "idle"

    # --------------------------------------------------------
    # Turns 2 and 3.
    #
    # max_turns=2 means turn 1 must disappear as a whole pair.
    # --------------------------------------------------------

    manager.start_turn(
        turn_id=2,
        text="Question 2",
    )
    manager.commit_turn(
        turn_id=2,
        assistant_text="Answer 2",
    )

    manager.start_turn(
        turn_id=3,
        text="Question 3",
    )
    manager.commit_turn(
        turn_id=3,
        assistant_text="Answer 3",
    )

    history = manager.history

    assert [
        item["role"]
        for item in history
    ] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
    ]

    contents = [
        item["content"]
        for item in history
    ]

    assert "Question 1" not in contents
    assert "Answer 1" not in contents

    assert "Question 2" in contents
    assert "Answer 2" in contents

    assert "Question 3" in contents
    assert "Answer 3" in contents

    assert manager.turn_count == 2

    # --------------------------------------------------------
    # Failed turn must not pollute committed history.
    # --------------------------------------------------------

    history_before_abort = manager.history

    manager.start_turn(
        turn_id=4,
        text="This request will fail",
    )

    manager.abort_turn(
        turn_id=4,
        reason="test failure",
    )

    assert manager.history == history_before_abort
    assert manager.turn_count == 2
    assert manager.current_turn is None
    assert manager.assistant_state == "idle"

    print("PASS: ConversationManager")
    print("bounded turns:", manager.turn_count)
    print(
        "history roles:",
        [
            item["role"]
            for item in manager.history
        ],
    )


if __name__ == "__main__":
    main()
