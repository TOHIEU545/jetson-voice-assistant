#!/usr/bin/env python3

import threading
import time


class GenerationCancellationController(object):
    """
    Own cancellation state for the currently active LLM generation.

    Phase 9 use case:

        LLM generating
             |
        speech_started
             |
        cancel_active("barge_in")
             |
        LLMHandler stops stale output

    This controller is independent from RevisionTracker.

    RevisionTracker:
        same logical turn, newer revision

    GenerationCancellationController:
        external interruption of the active generation
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._next_scope_id = 1
        self._active = None

    def begin_generation(
        self,
        turn_id,
        revision,
    ):
        with self._lock:
            if self._active is not None:
                raise RuntimeError(
                    "an LLM generation is already active"
                )

            scope_id = self._next_scope_id
            self._next_scope_id += 1

            self._active = {
                "scope_id": scope_id,
                "turn_id": turn_id,
                "revision": revision,
                "cancelled": False,
                "reason": None,
                "started_at": time.perf_counter(),
                "cancel_requested_at": None,
            }

            return scope_id

    def cancel_active(self, reason="cancelled"):
        """
        Cancel only the generation that is active NOW.

        If there is no active generation, this does nothing.
        Therefore an old speech_started event cannot poison a
        future LLM request.
        """
        with self._lock:
            if self._active is None:
                return None

            if self._active["cancelled"]:
                return dict(self._active)

            self._active["cancelled"] = True
            self._active["reason"] = reason
            self._active[
                "cancel_requested_at"
            ] = time.perf_counter()

            return dict(self._active)

    def scope_snapshot(self, scope_id):
        with self._lock:
            if self._active is None:
                return None

            if self._active["scope_id"] != scope_id:
                return None

            return dict(self._active)

    def is_cancelled(self, scope_id):
        snapshot = self.scope_snapshot(scope_id)

        return (
            snapshot is not None
            and snapshot["cancelled"]
        )

    def finish_generation(self, scope_id):
        with self._lock:
            if self._active is None:
                return None

            if self._active["scope_id"] != scope_id:
                return None

            snapshot = dict(self._active)
            self._active = None

            return snapshot

    def active_snapshot(self):
        with self._lock:
            if self._active is None:
                return None

            return dict(self._active)
