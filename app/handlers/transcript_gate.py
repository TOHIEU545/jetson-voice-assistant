#!/usr/bin/env python3

import queue
import threading
import time


WHISPER_ANNOTATION_MARKERS = "()[]{}"


def validate_transcript(turn):
    """
    Conservative Transcript Gate v1.

    Returns:
        (True, None)
        or
        (False, reason)
    """

    text = turn.get("text", "").strip()

    if not text:
        return False, "empty"

    if any(ch in text for ch in WHISPER_ANNOTATION_MARKERS):
        return False, "whisper_annotation"

    return True, None


class TranscriptGateHandler(threading.Thread):
    """
    transcript_queue
          |
          v
    TranscriptGateHandler
          |
          +---- DROP event ----> output_event_queue
          |
          v
    valid_turn_queue
    """

    def __init__(
        self,
        transcript_queue,
        valid_turn_queue,
        stop_event,
        output_event_queue=None,
        name="TranscriptGateHandler",
    ):
        threading.Thread.__init__(self, name=name)

        self.transcript_queue = transcript_queue
        self.valid_turn_queue = valid_turn_queue
        self.stop_event = stop_event
        self.output_event_queue = output_event_queue

        self.error = None

        self.accepted_count = 0
        self.dropped_count = 0

    def _emit_drop(self, turn, reason):
        if self.output_event_queue is None:
            return

        self.output_event_queue.put({
            "type": "gate_drop",
            "turn_id": turn["turn_id"],
            "runtime_index": turn["runtime_index"],
            "text": turn.get("text", ""),
            "reason": reason,
            "turn": dict(turn),
        })

    def run(self):
        try:
            while (
                not self.stop_event.is_set()
                or not self.transcript_queue.empty()
            ):
                try:
                    turn = self.transcript_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                try:
                    turn["transcript_queue_leave"] = (
                        time.perf_counter()
                    )

                    gate_start = time.perf_counter()

                    accepted, reason = validate_transcript(turn)

                    gate_end = time.perf_counter()

                    turn["gate_processing_s"] = (
                        gate_end - gate_start
                    )

                    if not accepted:
                        turn["gate_drop_reason"] = reason
                        self.dropped_count += 1

                        self._emit_drop(
                            turn=turn,
                            reason=reason,
                        )

                        continue

                    self.accepted_count += 1

                    turn["valid_turn_queue_enter"] = (
                        time.perf_counter()
                    )

                    turn["valid_turn_queue_depth_at_enqueue"] = (
                        self.valid_turn_queue.qsize() + 1
                    )

                    self.valid_turn_queue.put(turn)

                finally:
                    self.transcript_queue.task_done()

        except Exception as exc:
            self.error = exc
            self.stop_event.set()
