#!/usr/bin/env python3

import json
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

APP_DIR = os.path.join(PROJECT_ROOT, "app")

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from handlers.llm import LLMHandler


class FakeResponse(object):

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def __iter__(self):
        return iter(self.lines)


def make_turn():
    now = time.perf_counter()

    return {
        "turn_id": 7,
        "runtime_index": 42,
        "text": "What is UART?",

        "t2": now - 0.010,

        "vad_s": 0.500,
        "stt_s": 1.600,
        "vad_stt_total_s": 2.100,

        "transcript_queue_enter": now - 0.009,
        "transcript_queue_leave": now - 0.008,

        "valid_turn_queue_enter": now - 0.007,
        "valid_turn_queue_leave": None,

        "gate_processing_s": 0.0001,
        "llm_processing_s": None,

        "t3": None,
        "t4": None,
        "t5": None,
    }


def main():
    valid_turn_queue = queue.Queue()
    llm_output_queue = queue.Queue()
    stop_event = threading.Event()

    captured_request = {}

    def fake_urlopen(request):
        captured_request["body"] = json.loads(
            request.data.decode("utf-8")
        )

        return FakeResponse([
            (
                b'data: {"choices":[{"delta":'
                b'{"content":"UART "}}]}\n'
            ),
            (
                b'data: {"choices":[{"delta":'
                b'{"content":"is a serial interface."}}]}\n'
            ),
            b'data: [DONE]\n',
        ])

    initial_history = [
        {
            "role": "system",
            "content": "You are EmbedAI.",
        }
    ]

    handler = LLMHandler(
        valid_turn_queue=valid_turn_queue,
        llm_output_queue=llm_output_queue,
        stop_event=stop_event,
        llm_url=(
            "http://127.0.0.1:8080/"
            "v1/chat/completions"
        ),
        initial_history=initial_history,
        urlopen_func=fake_urlopen,
    )

    handler.start()

    turn = make_turn()

    valid_turn_queue.put(turn)

    valid_turn_queue.join()

    stop_event.set()

    handler.join(timeout=2.0)

    assert not handler.is_alive()
    assert handler.error is None

    assert handler.completed_count == 1
    assert handler.failed_count == 0

    # Verify request body.
    body = captured_request["body"]

    assert body["stream"] is True
    assert body["max_tokens"] == 128
    assert body["temperature"] == 0.5

    assert len(body["messages"]) == 2

    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"

    assert (
        body["messages"][1]["content"]
        == "What is UART?"
    )

    # Read output events.
    events = []

    while not llm_output_queue.empty():
        events.append(
            llm_output_queue.get_nowait()
        )

    event_types = [
        event["type"]
        for event in events
    ]

    assert event_types == [
        "turn_start",
        "token",
        "token",
        "turn_done",
    ]

    assert events[1]["text"] == "UART "
    assert events[2]["text"] == "is a serial interface."

    done = events[-1]

    assert (
        done["answer"]
        == "UART is a serial interface."
    )

    completed_turn = done["turn"]

    assert completed_turn["t3"] is not None
    assert completed_turn["t4"] is not None
    assert completed_turn["t5"] is not None

    assert (
        completed_turn["t3"]
        <= completed_turn["t4"]
        <= completed_turn["t5"]
    )

    assert (
        completed_turn["valid_turn_queue_leave"]
        is not None
    )

    assert (
        completed_turn["llm_processing_s"]
        is not None
    )

    # History should now be:
    # system -> user -> assistant
    assert len(handler.history) == 3

    assert handler.history[-1] == {
        "role": "assistant",
        "content": "UART is a serial interface.",
    }

    print("PASS: LLMHandler")
    print("valid_turn_queue -> streaming LLM")
    print("events:", event_types)
    print("answer:", done["answer"])
    print(
        "history roles:",
        [
            message["role"]
            for message in handler.history
        ],
    )


if __name__ == "__main__":
    main()
