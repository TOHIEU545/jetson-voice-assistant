#!/usr/bin/env python3

import threading


class RevisionTracker(object):
    """
    Track the newest known revision for each logical turn.

    Phase 8 purpose:
        - identify stale speculative work
        - allow an old LLM generation to stop when a newer
          revision of the same turn appears

    This component does not perform model inference and does
    not know anything about Smart Turn audio.
    """

    def __init__(self):
        self._latest = {}
        self._lock = threading.RLock()

    def observe(self, turn_id, revision):
        """
        Record a revision.

        Returns True when this call advances the latest revision.
        """
        if revision < 0:
            raise ValueError(
                "revision must be >= 0"
            )

        with self._lock:
            previous = self._latest.get(turn_id)

            if (
                previous is None
                or revision > previous
            ):
                self._latest[turn_id] = revision
                return True

            return False

    def latest_revision(self, turn_id):
        with self._lock:
            return self._latest.get(turn_id)

    def is_latest(self, turn_id, revision):
        with self._lock:
            latest = self._latest.get(turn_id)

            if latest is None:
                return True

            return revision >= latest

    def is_stale(self, turn_id, revision):
        return not self.is_latest(
            turn_id=turn_id,
            revision=revision,
        )

    def snapshot(self):
        with self._lock:
            return dict(self._latest)
