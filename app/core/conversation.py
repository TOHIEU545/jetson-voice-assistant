#!/usr/bin/env python3

import threading
import time


class ConversationManager(object):
    """
    Own conversation state independently from the LLM transport.

    Responsibilities:
        - preserve initial/system messages
        - keep bounded completed user/assistant turns
        - track current turn
        - track assistant state
        - expose timestamps/state for later realtime phases

    A turn is added to history only after a successful assistant
    response. Failed/aborted turns never pollute conversation history.
    """

    def __init__(
        self,
        initial_history,
        max_turns=6,
    ):
        if max_turns < 0:
            raise ValueError(
                "max_turns must be >= 0"
            )

        self.max_turns = max_turns

        # Initial messages are persistent.
        # In production this currently contains the system prompt.
        self._initial_history = [
            dict(message)
            for message in initial_history
        ]

        # Completed conversational turns only.
        #
        # Each entry owns one complete:
        #     user -> assistant
        # pair so trimming never leaves an orphan message.
        self._turns = []

        self.current_turn = None
        self.assistant_state = "idle"

        now = time.time()

        self.timestamps = {
            "created_at": now,
            "last_turn_started_at": None,
            "last_turn_committed_at": None,
            "last_turn_aborted_at": None,
        }

        # Phase 5 currently has one LLM worker, but keeping state
        # protected makes the manager safe for later cancellation
        # and realtime coordination phases.
        self._lock = threading.RLock()

    def _history_locked(self):
        messages = [
            dict(message)
            for message in self._initial_history
        ]

        for turn in self._turns:
            messages.append(
                dict(turn["user"])
            )
            messages.append(
                dict(turn["assistant"])
            )

        return messages

    @property
    def history(self):
        """
        Return a copy of committed conversation history.

        The caller cannot mutate internal state through this list.
        """
        with self._lock:
            return self._history_locked()

    @property
    def turn_count(self):
        with self._lock:
            return len(self._turns)

    def start_turn(self, turn_id, text):
        """
        Start one LLM turn and return request messages.

        The current user message is included in the returned request,
        but is NOT committed to history yet.
        """
        text = text.strip()

        if not text:
            raise ValueError(
                "conversation turn text must not be empty"
            )

        with self._lock:
            if self.current_turn is not None:
                raise RuntimeError(
                    "a conversation turn is already active"
                )

            now = time.time()

            self.current_turn = {
                "turn_id": turn_id,
                "text": text,
                "started_at": now,
            }

            self.assistant_state = "generating"

            self.timestamps[
                "last_turn_started_at"
            ] = now

            messages = self._history_locked()

            messages.append({
                "role": "user",
                "content": text,
            })

            return messages

    def commit_turn(
        self,
        turn_id,
        assistant_text,
    ):
        """
        Commit the complete user/assistant pair.

        Old turns are removed as complete pairs when max_turns
        is exceeded.
        """
        assistant_text = assistant_text.strip()

        if not assistant_text:
            raise ValueError(
                "assistant_text must not be empty"
            )

        with self._lock:
            self._require_active_turn(turn_id)

            now = time.time()

            user_text = self.current_turn["text"]

            self._turns.append({
                "turn_id": turn_id,
                "user": {
                    "role": "user",
                    "content": user_text,
                },
                "assistant": {
                    "role": "assistant",
                    "content": assistant_text,
                },
                "committed_at": now,
            })

            if len(self._turns) > self.max_turns:
                self._turns = self._turns[
                    -self.max_turns:
                ]

            # Special case: bounded history disabled.
            if self.max_turns == 0:
                self._turns = []

            self.current_turn = None
            self.assistant_state = "idle"

            self.timestamps[
                "last_turn_committed_at"
            ] = now

    def abort_turn(
        self,
        turn_id,
        reason=None,
    ):
        """
        End an active turn without modifying committed history.
        """
        with self._lock:
            self._require_active_turn(turn_id)

            now = time.time()

            self.current_turn = None
            self.assistant_state = "idle"

            self.timestamps[
                "last_turn_aborted_at"
            ] = now

    def _require_active_turn(self, turn_id):
        if self.current_turn is None:
            raise RuntimeError(
                "no active conversation turn"
            )

        if self.current_turn["turn_id"] != turn_id:
            raise RuntimeError(
                "active turn_id does not match"
            )

    def snapshot(self):
        """
        Return a read-only-style copy useful for tests/debugging.
        """
        with self._lock:
            current_turn = None

            if self.current_turn is not None:
                current_turn = dict(
                    self.current_turn
                )

            return {
                "history": self._history_locked(),
                "turn_count": len(self._turns),
                "max_turns": self.max_turns,
                "current_turn": current_turn,
                "assistant_state":
                    self.assistant_state,
                "timestamps":
                    dict(self.timestamps),
            }
