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

APP_DIR = os.path.join(PROJECT_ROOT, "app")

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from core.cancellation import (
    GenerationCancellationController,
)
from core.conversation import ConversationManager
from core.revisions import RevisionTracker
from handlers.llm import LLMHandler
from handlers.speech_runtime import SpeechRuntimeHandler


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

        self.continue_event.wait(timeout=2.0)

        yield "response "
        yield "that should be cancelled"


def make_turn():
    now = time.perf_counter()

    return {
        "turn_id": 7,
        "revision": 0,
        "turn_state": "complete",
        "turn_id_source": "test",
        "completion_source": "test",
        "segment_count": 1,

        "runtime_index": 42,
        "text": "Explain UART.",

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

    cancellation_controller = (
        GenerationCancellationController()
    )

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

    llm_handler = LLMHandler(
        valid_turn_queue=valid_turn_queue,
        llm_output_queue=llm_output_queue,
        stop_event=stop_event,
        conversation_manager=conversation_manager,
        backend=backend,
        revision_tracker=revision_tracker,
        cancellation_controller=cancellation_controller,
    )

    # Chỉ dùng bridge event của SpeechRuntimeHandler,
    # không start subprocess trong unit test.
    speech_runtime = SpeechRuntimeHandler(
        command=[],
        transcript_queue=queue.Queue(),
        stop_event=stop_event,
        cancellation_controller=cancellation_controller,
    )

    llm_handler.start()

    valid_turn_queue.put(make_turn())

    # Đợi LLM bắt đầu stream.
    assert first_token_event.wait(timeout=2.0)

    active = cancellation_controller.active_snapshot()

    assert active is not None
    assert active["turn_id"] == 7
    assert active["revision"] == 0
    assert active["cancelled"] is False

    # Giả lập event tương lai từ C++ VAD frontend.
    consumed = speech_runtime._handle_runtime_event_line(
        "[SPEECH_STARTED]"
    )

    assert consumed is True
    assert speech_runtime.speech_started_count == 1

    interrupted = speech_runtime.last_interruption

    assert interrupted is not None
    assert interrupted["reason"] == "barge_in"
    assert interrupted["cancelled"] is True

    # Cho fake backend chạy tiếp.
    # LLMHandler phải phát hiện cancel trước khi commit.
    continue_event.set()

    valid_turn_queue.join()

    stop_event.set()
    llm_handler.join(timeout=2.0)

    assert not llm_handler.is_alive()
    assert llm_handler.error is None

    assert llm_handler.completed_count == 0
    assert llm_handler.failed_count == 0
    assert llm_handler.cancelled_count == 1

    # Response bị cancel không được vào history.
    assert conversation_manager.turn_count == 0

    assert conversation_manager.history == [
        {
            "role": "system",
            "content": "You are EmbedAI.",
        }
    ]

    # Scope phải được release sau generation.
    assert (
        cancellation_controller.active_snapshot()
        is None
    )

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
        "turn_cancelled",
    ]

    cancelled = events[-1]

    assert cancelled["turn_id"] == 7
    assert cancelled["revision"] == 0
    assert cancelled["reason"] == "barge_in"

    assert (
        cancelled["cancel_detection_ms"]
        is not None
    )

    assert (
        cancelled["cancel_detection_ms"]
        >= 0.0
    )

    # Nếu speech_started xảy ra khi idle,
    # nó không được poison generation tương lai.
    idle_result = cancellation_controller.cancel_active(
        reason="barge_in"
    )

    assert idle_result is None

    # BARGE-IN OFF:
    # speech_started vẫn được consume nhưng không được
    # cancel generation.
    disabled_runtime = SpeechRuntimeHandler(
        command=[],
        transcript_queue=queue.Queue(),
        stop_event=stop_event,
        cancellation_controller=cancellation_controller,
        enable_barge_in=False,
    )

    consumed = disabled_runtime._handle_runtime_event_line(
        "[SPEECH_STARTED]"
    )

    assert consumed is True
    assert disabled_runtime.speech_started_count == 1
    assert disabled_runtime.last_interruption is None
    assert cancellation_controller.active_snapshot() is None

    print("PASS: Phase 9 barge-in infrastructure")
    print("speech_started bridge: PASS")
    print("active LLM cancellation: PASS")
    print("history protection: PASS")
    print("cancellation scope cleanup: PASS")
    print("idle speech event safety: PASS")
    print("barge-in feature flag OFF: PASS")
    print(
        "cancel detection ms:",
        cancelled["cancel_detection_ms"],
    )


if __name__ == "__main__":
    main()
