#!/usr/bin/env python3

import io
import json
import os
import queue
import sys
import tempfile
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


from core.conversation import ConversationManager
from handlers.llm import LLMHandler
from handlers.response import ResponseProcessor
from handlers.transcript_gate import TranscriptGateHandler


class FakeResponse(object):

    def __init__(self):
        self.lines = [
            (
                b'data: {"choices":[{"delta":'
                b'{"content":"Test response."}}]}\n'
            ),
            b'data: [DONE]\n',
        ]

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


def fake_urlopen(request):
    return FakeResponse()


def make_turn(turn_id, text):
    now = time.perf_counter()

    return {
        "turn_id": turn_id,
        "runtime_index": 100 + turn_id,
        "text": text,

        "t2": now,

        "vad_s": 0.500,
        "stt_s": 1.600,
        "vad_stt_total_s": 2.100,

        "transcript_queue_enter": now,
        "transcript_queue_leave": None,

        "valid_turn_queue_enter": None,
        "valid_turn_queue_leave": None,

        "transcript_queue_depth_at_enqueue": 1,

        "gate_processing_s": None,
        "llm_processing_s": None,

        "t3": None,
        "t4": None,
        "t5": None,
    }


def main():
    transcript_queue = queue.Queue()
    valid_turn_queue = queue.Queue()
    output_queue = queue.Queue()

    stop_event = threading.Event()

    console = io.StringIO()

    with tempfile.TemporaryDirectory() as tmpdir:

        response = ResponseProcessor(
            output_queue=output_queue,
            stop_event=stop_event,
            conversation_log_path=os.path.join(
                tmpdir,
                "conversation.txt",
            ),
            benchmark_log_path=os.path.join(
                tmpdir,
                "python.jsonl",
            ),
            full_pipeline_log_path=os.path.join(
                tmpdir,
                "full.jsonl",
            ),
            output_stream=console,
        )

        conversation_manager = ConversationManager(
            initial_history=[
                {
                    "role": "system",
                    "content": "Test system prompt.",
                }
            ],
            max_turns=6,
        )

        llm = LLMHandler(
            valid_turn_queue=valid_turn_queue,
            llm_output_queue=output_queue,
            stop_event=stop_event,
            llm_url=(
                "http://127.0.0.1:8080/"
                "v1/chat/completions"
            ),
            conversation_manager=conversation_manager,
            urlopen_func=fake_urlopen,
        )

        gate = TranscriptGateHandler(
            transcript_queue=transcript_queue,
            valid_turn_queue=valid_turn_queue,
            stop_event=stop_event,
            output_event_queue=output_queue,
        )

        response.start()
        llm.start()
        gate.start()

        # Valid.
        transcript_queue.put(
            make_turn(
                0,
                "What is UART?",
            )
        )

        # Gate drop.
        transcript_queue.put(
            make_turn(
                1,
                "(buzzing)",
            )
        )

        # Valid while previous LLM work may still exist.
        transcript_queue.put(
            make_turn(
                2,
                "What is SPI?",
            )
        )

        # Same graceful drain order as production.
        transcript_queue.join()
        valid_turn_queue.join()
        output_queue.join()

        stop_event.set()

        gate.join(timeout=2.0)
        llm.join(timeout=2.0)
        response.join(timeout=2.0)

        assert not gate.is_alive()
        assert not llm.is_alive()
        assert not response.is_alive()

        assert gate.error is None
        assert llm.error is None
        assert response.error is None

        assert gate.accepted_count == 2
        assert gate.dropped_count == 1

        assert llm.completed_count == 2
        assert llm.failed_count == 0

        benchmark_path = os.path.join(
            tmpdir,
            "python.jsonl",
        )

        with open(benchmark_path, "r") as f:
            benchmark_rows = [
                json.loads(line)
                for line in f
                if line.strip()
            ]

        assert len(benchmark_rows) == 2

        for row in benchmark_rows:
            assert row["turn_id"] in (0, 2)

            assert (
                row["transcript_queue_wait_ms"]
                is not None
            )

            assert (
                row["valid_turn_queue_wait_ms"]
                is not None
            )

            assert (
                row["valid_turn_queue_depth_at_enqueue"]
                is not None
            )

        terminal = console.getvalue()

        assert "You: What is UART?" in terminal
        assert "You: What is SPI?" in terminal

        assert (
            '[GATE] DROP [whisper_annotation]'
            in terminal
        )

    print("PASS: Phase 4 Python pipeline integration")
    print(
        "transcript_queue -> Gate -> "
        "valid_turn_queue -> LLM -> output_queue"
    )
    print("valid turns: 2")
    print("gate drops: 1")
    print("graceful queue drain: PASS")
    print("queue metrics: PASS")


if __name__ == "__main__":
    main()
