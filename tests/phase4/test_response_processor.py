#!/usr/bin/env python3

import io
import json
import os
import queue
import sys
import tempfile
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


from handlers.response import ResponseProcessor


def main():
    output_queue = queue.Queue()
    stop_event = threading.Event()

    console = io.StringIO()

    with tempfile.TemporaryDirectory() as tmpdir:
        conversation_path = os.path.join(
            tmpdir,
            "conversation.txt",
        )

        benchmark_path = os.path.join(
            tmpdir,
            "python_llm.jsonl",
        )

        full_path = os.path.join(
            tmpdir,
            "full.jsonl",
        )

        processor = ResponseProcessor(
            output_queue=output_queue,
            stop_event=stop_event,
            conversation_log_path=conversation_path,
            benchmark_log_path=benchmark_path,
            full_pipeline_log_path=full_path,
            output_stream=console,
        )

        processor.start()

        turn = {
            "turn_id": 3,
            "runtime_index": 17,
            "text": "What is UART?",

            "t2": 10.000,
            "t3": 10.010,
            "t4": 10.810,
            "t5": 12.000,

            "vad_s": 0.500,
            "stt_s": 1.600,
            "vad_stt_total_s": 2.100,

            "transcript_queue_enter": 10.000,
            "transcript_queue_leave": 10.002,

            "valid_turn_queue_enter": 10.003,
            "valid_turn_queue_leave": 10.008,

            "gate_processing_s": 0.001,
            "llm_processing_s": 1.990,
        }

        output_queue.put({
            "type": "turn_start",
            "turn_id": 3,
            "runtime_index": 17,
            "text": "What is UART?",
        })

        output_queue.put({
            "type": "token",
            "turn_id": 3,
            "text": "UART ",
        })

        output_queue.put({
            "type": "token",
            "turn_id": 3,
            "text": "is serial.",
        })

        output_queue.put({
            "type": "turn_done",
            "turn_id": 3,
            "runtime_index": 17,
            "text": "What is UART?",
            "answer": "UART is serial.",
            "turn": turn,
        })

        output_queue.put({
            "type": "gate_drop",
            "turn_id": 4,
            "runtime_index": 18,
            "text": "(buzzing)",
            "reason": "whisper_annotation",
            "turn": {},
        })

        output_queue.join()

        stop_event.set()

        processor.join(timeout=2.0)

        assert not processor.is_alive()
        assert processor.error is None

        terminal = console.getvalue()

        assert "You: What is UART?" in terminal
        assert "Assistant: UART is serial." in terminal
        assert "[LATENCY] VAD" in terminal
        assert "[QUEUE] Transcript wait" in terminal
        assert "[GATE] DROP [whisper_annotation]" in terminal

        with open(benchmark_path, "r") as f:
            rows = [
                json.loads(line)
                for line in f
                if line.strip()
            ]

        assert len(rows) == 1

        row = rows[0]

        assert row["turn"] == 1
        assert row["turn_id"] == 3
        assert row["runtime_index"] == 17

        assert abs(
            row["transcript_queue_wait_ms"] - 2.0
        ) < 0.001

        assert abs(
            row["valid_turn_queue_wait_ms"] - 5.0
        ) < 0.001

        assert abs(
            row["gate_processing_ms"] - 1.0
        ) < 0.001

        with open(full_path, "r") as f:
            full_rows = [
                json.loads(line)
                for line in f
                if line.strip()
            ]

        assert len(full_rows) == 1

        full = full_rows[0]

        assert abs(
            full["speech_end_to_first_token_s"]
            - 2.910
        ) < 0.001

        assert abs(
            full["speech_end_to_last_token_s"]
            - 4.100
        ) < 0.001

        with open(conversation_path, "r") as f:
            conversation = f.read()

        assert "You: What is UART?" in conversation
        assert "Assistant: UART is serial." in conversation

        assert (
            '[GATE DROP] whisper_annotation: "(buzzing)"'
            in conversation
        )

    print("PASS: ResponseProcessor")
    print("stream events -> terminal/logs")
    print("baseline latency -> PASS")
    print("queue/worker metrics -> PASS")
    print("gate drop logging -> PASS")


if __name__ == "__main__":
    main()
