#!/usr/bin/env python3

import queue
import threading
import time


class LLMHandler(threading.Thread):
    """
    Coordinate streaming LLM generation.

    Cancellation sources:

        Phase 8:
            newer revision
            -> stale_revision

        Phase 9:
            speech_started
            -> barge_in
    """

    def __init__(
        self,
        valid_turn_queue,
        llm_output_queue,
        stop_event,
        conversation_manager,
        backend,
        revision_tracker=None,
        cancellation_controller=None,
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
        self.cancellation_controller = (
            cancellation_controller
        )

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

    def _cancel_turn(
        self,
        turn,
        worker_start,
        reason,
        cancellation_state=None,
    ):
        turn_id = turn["turn_id"]
        revision = turn.get("revision", 0)

        self._abort_turn_safely(
            turn_id=turn_id,
            revision=revision,
            reason=reason,
        )

        observed_at = time.perf_counter()

        turn["llm_processing_s"] = (
            observed_at - worker_start
        )

        latest_revision = None

        if self.revision_tracker is not None:
            latest_revision = (
                self.revision_tracker.latest_revision(
                    turn_id
                )
            )

        cancel_requested_at = None
        cancel_detection_ms = None

        if cancellation_state is not None:
            cancel_requested_at = (
                cancellation_state.get(
                    "cancel_requested_at"
                )
            )

            if cancel_requested_at is not None:
                cancel_detection_ms = (
                    observed_at
                    - cancel_requested_at
                ) * 1000.0

        turn["cancel_reason"] = reason
        turn["cancel_requested_at"] = (
            cancel_requested_at
        )
        turn["cancel_observed_at"] = (
            observed_at
        )
        turn["cancel_detection_ms"] = (
            cancel_detection_ms
        )

        self.cancelled_count += 1

        self._emit({
            "type": "turn_cancelled",
            "turn_id": turn_id,
            "revision": revision,
            "latest_revision": latest_revision,
            "runtime_index":
                turn["runtime_index"],
            "text": turn.get("text", ""),
            "reason": reason,
            "cancel_detection_ms":
                cancel_detection_ms,
            "turn": dict(turn),
        })

    def _process_turn(self, turn):
        turn[
            "valid_turn_queue_leave"
        ] = time.perf_counter()

        worker_start = time.perf_counter()

        turn_id = turn["turn_id"]
        revision = turn.get("revision", 0)
        text = turn.get("text", "").strip()

        if self.revision_tracker is not None:
            self.revision_tracker.observe(
                turn_id=turn_id,
                revision=revision,
            )

        # Revision may already be obsolete while waiting in queue.
        if self._is_stale(
            turn_id=turn_id,
            revision=revision,
        ):
            self._cancel_turn(
                turn=turn,
                worker_start=worker_start,
                reason="stale_revision",
            )
            return

        scope_id = None

        if self.cancellation_controller is not None:
            scope_id = (
                self.cancellation_controller
                .begin_generation(
                    turn_id=turn_id,
                    revision=revision,
                )
            )

        try:
            self._emit({
                "type": "turn_start",
                "turn_id": turn_id,
                "revision": revision,
                "runtime_index":
                    turn["runtime_index"],
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

                for token in (
                    self.backend.stream_generate(
                        messages=messages,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                    )
                ):
                    # Phase 8 cancellation.
                    if self._is_stale(
                        turn_id=turn_id,
                        revision=revision,
                    ):
                        self._cancel_turn(
                            turn=turn,
                            worker_start=worker_start,
                            reason="stale_revision",
                        )
                        return

                    # Phase 9 cancellation.
                    if (
                        scope_id is not None
                        and self.cancellation_controller
                        .is_cancelled(scope_id)
                    ):
                        cancel_state = (
                            self.cancellation_controller
                            .scope_snapshot(scope_id)
                        )

                        reason = "barge_in"

                        if cancel_state is not None:
                            reason = (
                                cancel_state.get(
                                    "reason"
                                )
                                or reason
                            )

                        self._cancel_turn(
                            turn=turn,
                            worker_start=worker_start,
                            reason=reason,
                            cancellation_state=
                                cancel_state,
                        )
                        return

                    if not token:
                        continue

                    token_time = time.perf_counter()

                    if t4 is None:
                        t4 = token_time
                        turn["t4"] = t4

                    t5 = token_time
                    turn["t5"] = t5

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

            # Final revision check before history commit.
            if self._is_stale(
                turn_id=turn_id,
                revision=revision,
            ):
                self._cancel_turn(
                    turn=turn,
                    worker_start=worker_start,
                    reason="stale_revision",
                )
                return

            # Final barge-in check before history commit.
            if (
                scope_id is not None
                and self.cancellation_controller
                .is_cancelled(scope_id)
            ):
                cancel_state = (
                    self.cancellation_controller
                    .scope_snapshot(scope_id)
                )

                reason = "barge_in"

                if cancel_state is not None:
                    reason = (
                        cancel_state.get("reason")
                        or reason
                    )

                self._cancel_turn(
                    turn=turn,
                    worker_start=worker_start,
                    reason=reason,
                    cancellation_state=cancel_state,
                )
                return

            answer = "".join(
                answer_parts
            ).strip()

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
                "runtime_index":
                    turn["runtime_index"],
                "text": text,
                "answer": answer,
                "turn": dict(turn),
            })

        finally:
            if (
                scope_id is not None
                and self.cancellation_controller
                is not None
            ):
                self.cancellation_controller.finish_generation(
                    scope_id
                )

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
