#!/usr/bin/env python3

import queue
import signal
import threading

from config import (
    INITIAL_HISTORY,
    LLM_MODE,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_API_KEY,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_URL,
    MAX_CONVERSATION_TURNS,
    PROJECT_ROOT,
    build_speech_command,
    create_session_paths,
)

from handlers.llm import LLMHandler
from handlers.response import ResponseProcessor
from handlers.speech_runtime import SpeechRuntimeHandler
from handlers.transcript_gate import TranscriptGateHandler
from backends.llm import create_llm_backend
from core.conversation import ConversationManager
from core.cancellation import GenerationCancellationController
from core.revisions import RevisionTracker


def build_banner(session_paths):
    return (
        "===================================\n"
        " Jetson Voice Assistant\n"
        " Mic -> VAD -> Whisper -> Gemma\n"
        " Phase 4 handlers/queues: ON\n"
        " Conversation history: ON\n"
        "===================================\n"
        "Project: {}\n"
        "Log: {}\n"
        "Benchmark: {}\n"
        "Full pipeline: {}\n"
        "\n"
        "Speak...\n\n"
    ).format(
        PROJECT_ROOT,
        session_paths["conversation_log"],
        session_paths["benchmark_log"],
        session_paths["full_pipeline_log"],
    )


def main():
    session_paths = create_session_paths()

    stop_event = threading.Event()

    revision_tracker = RevisionTracker()
    cancellation_controller = GenerationCancellationController()

    conversation_manager = ConversationManager(
        initial_history=INITIAL_HISTORY,
        max_turns=MAX_CONVERSATION_TURNS,
    )

    # Phase 4 queues.
    #
    # C++ speech_queue already exists inside the sherpa runtime.
    # Python starts from transcript_queue.
    transcript_queue = queue.Queue()
    valid_turn_queue = queue.Queue()
    llm_output_queue = queue.Queue()

    response_processor = ResponseProcessor(
        output_queue=llm_output_queue,
        stop_event=stop_event,
        conversation_log_path=(
            session_paths["conversation_log"]
        ),
        benchmark_log_path=(
            session_paths["benchmark_log"]
        ),
        full_pipeline_log_path=(
            session_paths["full_pipeline_log"]
        ),
        session_start=session_paths["session_start"],
    )

    llm_backend = create_llm_backend(
        mode=LLM_MODE,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
    )

    llm_handler = LLMHandler(
        valid_turn_queue=valid_turn_queue,
        llm_output_queue=llm_output_queue,
        stop_event=stop_event,
        backend=llm_backend,
        conversation_manager=conversation_manager,
        revision_tracker=revision_tracker,
        cancellation_controller=cancellation_controller,
        max_tokens=LLM_MAX_TOKENS,
        temperature=LLM_TEMPERATURE,
    )

    transcript_gate_handler = TranscriptGateHandler(
        transcript_queue=transcript_queue,
        valid_turn_queue=valid_turn_queue,
        stop_event=stop_event,
        output_event_queue=llm_output_queue,
    )

    speech_runtime_handler = SpeechRuntimeHandler(
        command=build_speech_command(),
        transcript_queue=transcript_queue,
        stop_event=stop_event,
        cancellation_controller=cancellation_controller,
    )

    # Start downstream first so every producer already has
    # a live consumer before it begins emitting data.
    response_processor.start()
    llm_handler.start()
    transcript_gate_handler.start()

    llm_output_queue.put({
        "type": "status",
        "text": build_banner(session_paths),
    })

    speech_runtime_handler.start()

    graceful_shutdown = True

    try:
        while speech_runtime_handler.is_alive():

            # stop_event is reserved for handler-level errors.
            if stop_event.wait(timeout=0.2):
                graceful_shutdown = False
                break

    except KeyboardInterrupt:
        # First Ctrl+C requests graceful shutdown.
        #
        # Ignore additional Ctrl+C while queues are draining so a
        # second SIGINT cannot interrupt Queue.join().
        graceful_shutdown = True

        signal.signal(
            signal.SIGINT,
            signal.SIG_IGN,
        )

    finally:
        # ----------------------------------------------------
        # 1. Stop C++ speech runtime.
        #
        # SpeechRuntimeHandler.stop() sends SIGINT first so the
        # Phase-3 C++ worker can drain its own speech_queue.
        # ----------------------------------------------------

        speech_runtime_handler.stop()
        speech_runtime_handler.join(timeout=35.0)

        if speech_runtime_handler.is_alive():
            graceful_shutdown = False
            stop_event.set()

        # ----------------------------------------------------
        # 2. Gracefully drain Python pipeline.
        #
        # IMPORTANT:
        # Do not set stop_event before these joins.
        #
        # transcript_queue.join():
        #     Gate has consumed every transcript.
        #
        # valid_turn_queue.join():
        #     LLM has completed every accepted turn.
        #
        # llm_output_queue.join():
        #     ResponseProcessor has written every event/log.
        # ----------------------------------------------------

        if graceful_shutdown and not stop_event.is_set():

            transcript_queue.join()
            valid_turn_queue.join()
            llm_output_queue.join()

            llm_output_queue.put({
                "type": "status",
                "text": "\nVoice Assistant stopped.\n",
            })

            llm_output_queue.join()

        # Now queues are drained. Workers may safely leave their
        # timeout loops.
        stop_event.set()

        transcript_gate_handler.join(timeout=2.0)
        llm_handler.join(timeout=2.0)
        response_processor.join(timeout=2.0)

        errors = []

        for handler in (
            speech_runtime_handler,
            transcript_gate_handler,
            llm_handler,
            response_processor,
        ):
            if handler.error is not None:
                errors.append(
                    "{}: {}".format(
                        handler.name,
                        handler.error,
                    )
                )

        if errors:
            raise RuntimeError(
                "Phase-4 handler failure: "
                + " | ".join(errors)
            )


if __name__ == "__main__":
    main()
