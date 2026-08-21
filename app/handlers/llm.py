#!/usr/bin/env python3

import queue
import threading
import time


class LLMHandler(threading.Thread):
    """
    Consume valid turns and coordinate streaming LLM generation.

    Phase 8A:
        - turn_id + revision propagation
        - stale revision detection
        - cooperative speculative-generation cancellation

    Cancellation is cooperative:
        LLMHandler stops consuming/emitting tokens from a stale
        revision as soon as it notices that RevisionTracker has
        observed a newer revision.

    Transport-level cancellation can be added later where the
    concrete backend supports it.
    """

    def __init__(
        self,
        valid_turn_queue,
        llm_output_queue,
        stop_event,
        conversation_manager,
        backend,
        revision_tracker=None,
        max_tokens=128,
        temperature=0.5,
        name="LLMHandler",
    ):
        threading.Thread.__init__(self, name=name)

        self.valid_turn_queue = valid_turn_queue
        self.llm_output_queue = llm_output_queue
        self.stop_event = stop_event

        self.conversation_manager = conversation_manager
        self.backend = backend
        self.revision_tracker = revision_tracker

        self.max_tokens = max_tokens
        self.temperature = temperature

        self.error = None
        self.completed_count = 0
        self.failed_count = 0
        self.cancelled_count = 0

    def _emit(self, event):
        self.llm_output_queue.put(event)

    def _is_stale(
        self,
        turn_id,
        revision,
    ):
        if self.revision_tracker is None:
            return False

        return self.revision_tracker.is_stale(
            turn_id=turn_id,
            revision=revision,
        )

    def _abort_turn_safely(
        self,
        turn_id,
        revision,
        reason,
    ):
        try:
            self.conversation_manager.abort_turn(
                turn_id=turn_id,
                revision=revision,
                reason=reason,
            )
        except Exception:
            pass

    def _cancel_stale_turn(
        self,
        turn,
        worker_start,
    ):
        turn_id = turn["turn_id"]
        revision = turn.get("revision", 0)

        self._abort_turn_safely(
            turn_id=turn_id,
            revision=revision,
            reason="stale revision",
        )

        turn["llm_processing_s"] = (
            time.perf_counter()
            - worker_start
        )

        self.cancelled_count += 1

        latest_revision = None

        if self.revision_tracker is not None:
            latest_revision = (
                self.revision_tracker.latest_revision(
                    turn_id
                )
            )

        self._emit({
            "type": "turn_cancelled",
            "turn_id": turn_id,
            "revision": revision,
            "latest_revision": latest_revision,
            "runtime_index": turn["runtime_index"],
            "text": turn.get("text", ""),
            "reason": "stale_revision",
            "turn": dict(turn),
        })

    def _process_turn(self, turn):
        turn["valid_turn_queue_leave"] = time.perf_counter()

        worker_start = time.perf_counter()

        turn_id = turn["turn_id"]
        revision = turn.get("revision", 0)
        text = turn.get("text", "").strip()

        if self.revision_tracker is not None:
            self.revision_tracker.observe(
                turn_id=turn_id,
                revision=revision,
            )

        # A queued revision may already have become stale
        # before the LLM worker starts it.
        if self._is_stale(
            turn_id=turn_id,
            revision=revision,
        ):
            self._cancel_stale_turn(
                turn=turn,
                worker_start=worker_start,
            )
            return

        self._emit({
            "type": "turn_start",
            "turn_id": turn_id,
            "revision": revision,
            "runtime_index": turn["runtime_index"],
            "text": text,
        })

        try:
            messages = (
                self.conversation_manager.start_turn(
                    turn_id=turn_id,
                    revision=revision,
                    text=text,
                )
            )

            turn["t3"] = time.perf_counter()

            answer_parts = []
            t4 = None
            t5 = None

            for token in self.backend.stream_generate(
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            ):
                # This check is intentionally inside the streaming
                # loop. A newer revision can appear while this
                # generation is already running.
                if self._is_stale(
                    turn_id=turn_id,
                    revision=revision,
                ):
                    self._cancel_stale_turn(
                        turn=turn,
                        worker_start=worker_start,
                    )
                    return

                if not token:
                    continue

                token_time = time.perf_counter()

                if t4 is None:
                    t4 = token_time

                t5 = token_time
                answer_parts.append(token)

                self._emit({
                    "type": "token",
                    "turn_id": turn_id,
                    "revision": revision,
                    "text": token,
                })

        except Exception as exc:
            self._abort_turn_safely(
                turn_id=turn_id,
                revision=revision,
                reason=str(exc),
            )

            turn["llm_processing_s"] = (
                time.perf_counter()
                - worker_start
            )

            self.failed_count += 1

            self._emit({
                "type": "llm_error",
                "turn_id": turn_id,
                "revision": revision,
                "runtime_index":
                    turn["runtime_index"],
                "text": text,
                "error": str(exc),
                "turn": dict(turn),
            })

            return

        # One final stale check before history commit.
        if self._is_stale(
            turn_id=turn_id,
            revision=revision,
        ):
            self._cancel_stale_turn(
                turn=turn,
                worker_start=worker_start,
            )
            return

        answer = "".join(answer_parts).strip()

        turn["t4"] = t4
        turn["t5"] = t5

        turn["llm_processing_s"] = (
            time.perf_counter()
            - worker_start
        )

        if answer:
            try:
                self.conversation_manager.commit_turn(
                    turn_id=turn_id,
                    revision=revision,
                    assistant_text=answer,
                )

            except Exception as exc:
                self._abort_turn_safely(
                    turn_id=turn_id,
                    revision=revision,
                    reason=str(exc),
                )

                self.failed_count += 1

                self._emit({
                    "type": "llm_error",
                    "turn_id": turn_id,
                    "revision": revision,
                    "runtime_index":
                        turn["runtime_index"],
                    "text": text,
                    "error": str(exc),
                    "turn": dict(turn),
                })

                return

        else:
            self._abort_turn_safely(
                turn_id=turn_id,
                revision=revision,
                reason="empty assistant response",
            )

        self.completed_count += 1

        self._emit({
            "type": "turn_done",
            "turn_id": turn_id,
            "revision": revision,
            "runtime_index": turn["runtime_index"],
            "text": text,
            "answer": answer,
            "turn": dict(turn),
        })

    def run(self):
        try:
            while (
                not self.stop_event.is_set()
                or not self.valid_turn_queue.empty()
            ):
                try:
                    turn = self.valid_turn_queue.get(
                        timeout=0.1
                    )
                except queue.Empty:
                    continue

                try:
                    self._process_turn(turn)

                finally:
                    self.valid_turn_queue.task_done()

        except Exception as exc:
            self.error = exc
            self.stop_event.set()
