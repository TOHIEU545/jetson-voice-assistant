#!/usr/bin/env python3

import threading
import time


class ConversationManager(object):
    """
    Own committed conversation history and current turn state.

    Phase 7 adds revision-aware active-turn validation.

    Conversation history is committed only after a successful
    assistant response.
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

        self._initial_history = [
            dict(message)
            for message in initial_history
        ]

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
        with self._lock:
            return self._history_locked()

    @property
    def turn_count(self):
        with self._lock:
            return len(self._turns)

    def start_turn(
        self,
        turn_id,
        text,
        revision=0,
    ):
        text = text.strip()

        if not text:
            raise ValueError(
                "conversation turn text must not be empty"
            )

        if revision < 0:
            raise ValueError(
                "revision must be >= 0"
            )

        with self._lock:
            if self.current_turn is not None:
                raise RuntimeError(
                    "a conversation turn is already active"
                )

            now = time.time()

            self.current_turn = {
                "turn_id": turn_id,
                "revision": revision,
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
        revision=None,
    ):
        assistant_text = assistant_text.strip()

        if not assistant_text:
            raise ValueError(
                "assistant_text must not be empty"
            )

        with self._lock:
            self._require_active_turn(
                turn_id=turn_id,
                revision=revision,
            )

            now = time.time()

            user_text = self.current_turn["text"]
            active_revision = (
                self.current_turn["revision"]
            )

            committed_turn = {
                "turn_id": turn_id,
                "revision": active_revision,
                "user": {
                    "role": "user",
                    "content": user_text,
                },
                "assistant": {
                    "role": "assistant",
                    "content": assistant_text,
                },
                "committed_at": now,
            }

            replace_index = None

            for index, existing in enumerate(
                self._turns
            ):
                if existing["turn_id"] != turn_id:
                    continue

                existing_revision = existing.get(
                    "revision",
                    0,
                )

                if active_revision < existing_revision:
                    raise RuntimeError(
                        "cannot commit stale revision"
                    )

                replace_index = index
                break

            if replace_index is None:
                self._turns.append(
                    committed_turn
                )
            else:
                self._turns[
                    replace_index
                ] = committed_turn

            if self.max_turns == 0:
                self._turns = []

            elif len(self._turns) > self.max_turns:
                self._turns = self._turns[
                    -self.max_turns:
                ]

            self.current_turn = None
            self.assistant_state = "idle"

            self.timestamps[
                "last_turn_committed_at"
            ] = now

    def abort_turn(
        self,
        turn_id,
        reason=None,
        revision=None,
    ):
        with self._lock:
            self._require_active_turn(
                turn_id=turn_id,
                revision=revision,
            )

            now = time.time()

            self.current_turn = None
            self.assistant_state = "idle"

            self.timestamps[
                "last_turn_aborted_at"
            ] = now

    def _require_active_turn(
        self,
        turn_id,
        revision=None,
    ):
        if self.current_turn is None:
            raise RuntimeError(
                "no active conversation turn"
            )

        if self.current_turn["turn_id"] != turn_id:
            raise RuntimeError(
                "active turn_id does not match"
            )

        if (
            revision is not None
            and self.current_turn["revision"]
            != revision
        ):
            raise RuntimeError(
                "active revision does not match"
            )

    def snapshot(self):
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
