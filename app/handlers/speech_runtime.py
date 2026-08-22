#!/usr/bin/env python3

import queue
import re
import signal
import subprocess
import threading
import time

from core.messages import (
    TURN_COMPLETION_SMART_TURN,
    TURN_COMPLETION_SMART_TURN_FALLBACK,
    TURN_ID_SOURCE_SPEECH_RUNTIME,
    create_transcript_turn,
    is_complete_transcript_turn,
)


TRANSCRIPT_RE = re.compile(
    r"^(\d+):\s*(.+)$"
)

LATENCY_RE = re.compile(
    r"^\[LATENCY\]\s+(VAD|STT|TOTAL)\s*:\s*"
    r"([0-9.]+)\s*s$"
)

SMART_TURN_DECISION_RE = re.compile(
    r"^\[SMART_TURN\]\s+"
    r"turn_id=(\d+)\s+"
    r"candidate_id=(\d+)\s+"
    r"segment_count=(\d+)\s+"
    r"audio_prep_ms=([0-9eE+.-]+)\s+"
    r"feature_ms=([0-9eE+.-]+)\s+"
    r"infer_ms=([0-9eE+.-]+)\s+"
    r"total_ms=([0-9eE+.-]+)\s+"
    r"score=([0-9eE+.-]+)\s+"
    r"decision=(COMPLETE|INCOMPLETE)$"
)

SMART_TURN_FALLBACK_RE = re.compile(
    r"^\[SMART_TURN\]\s+"
    r"turn_id=(\d+)\s+"
    r"candidate_id=(\d+)\s+"
    r"segment_count=(\d+)\s+"
    r"decision=ERROR\s+fallback=WHISPER$"
)

# Phase 9 runtime contract.
#
# Future C++ runtime may emit:
#
#     [SPEECH_STARTED]
#
# or:
#
#     [SPEECH_STARTED] ...
#
# Additional metadata after the marker is intentionally ignored
# by Phase 9A.
SPEECH_STARTED_RE = re.compile(
    r"^\[SPEECH_STARTED\](?:\s+.*)?$"
)


class SpeechRuntimeParser(object):
    """
    Stateful parser for sherpa transcript/latency output.

    Current sequence:

        0: What is a microcontroller?
        [LATENCY] VAD   : 0.500 s
        [LATENCY] STT   : 1.650 s
        [LATENCY] TOTAL : 2.150 s

    T2 is captured immediately when the transcript line arrives.
    """

    def __init__(self):
        self.pending_turn = None
        self.next_turn_id = 0

        # Smart Turn decisions arrive before the final transcript.
        # Keep all candidate evaluations for the active logical turn.
        self.smart_turn_evaluations = []
        self.pending_smart_turn = None

    def feed_line(self, raw_line):
        line = raw_line.strip()

        if not line:
            return None

        smart_turn_match = SMART_TURN_DECISION_RE.match(
            line
        )

        if smart_turn_match:
            evaluation = {
                "turn_id": int(smart_turn_match.group(1)),
                "candidate_id": int(
                    smart_turn_match.group(2)
                ),
                "segment_count": int(
                    smart_turn_match.group(3)
                ),
                "audio_prep_ms": float(
                    smart_turn_match.group(4)
                ),
                "feature_ms": float(
                    smart_turn_match.group(5)
                ),
                "infer_ms": float(
                    smart_turn_match.group(6)
                ),
                "total_ms": float(
                    smart_turn_match.group(7)
                ),
                "score": float(
                    smart_turn_match.group(8)
                ),
                "decision": smart_turn_match.group(9),
            }

            if (
                self.smart_turn_evaluations
                and self.smart_turn_evaluations[0][
                    "turn_id"
                ] != evaluation["turn_id"]
            ):
                self.smart_turn_evaluations = []

            self.smart_turn_evaluations.append(
                evaluation
            )

            if evaluation["decision"] == "COMPLETE":
                self.pending_smart_turn = {
                    "turn_id": evaluation["turn_id"],
                    "segment_count":
                        evaluation["segment_count"],
                    "decision": "COMPLETE",
                    "score": evaluation["score"],
                    "audio_prep_ms":
                        evaluation["audio_prep_ms"],
                    "feature_ms":
                        evaluation["feature_ms"],
                    "infer_ms":
                        evaluation["infer_ms"],
                    "total_ms":
                        evaluation["total_ms"],
                    "evaluations": list(
                        self.smart_turn_evaluations
                    ),
                }

                self.smart_turn_evaluations = []

            return None

        smart_turn_fallback = (
            SMART_TURN_FALLBACK_RE.match(line)
        )

        if smart_turn_fallback:
            turn_id = int(
                smart_turn_fallback.group(1)
            )

            segment_count = int(
                smart_turn_fallback.group(3)
            )

            self.smart_turn_evaluations.append({
                "turn_id": turn_id,
                "candidate_id": int(
                    smart_turn_fallback.group(2)
                ),
                "segment_count": segment_count,
                "decision": "ERROR",
            })

            self.pending_smart_turn = {
                "turn_id": turn_id,
                "segment_count": segment_count,
                "decision": "ERROR",
                "score": None,
                "audio_prep_ms": None,
                "feature_ms": None,
                "infer_ms": None,
                "total_ms": None,
                "evaluations": list(
                    self.smart_turn_evaluations
                ),
            }

            self.smart_turn_evaluations = []

            return None

        transcript_match = TRANSCRIPT_RE.match(line)

        if transcript_match:
            runtime_index = int(
                transcript_match.group(1)
            )

            text = (
                transcript_match.group(2)
                .strip()
            )

            if not text:
                return None

            t2 = time.perf_counter()

            smart_meta = self.pending_smart_turn

            if smart_meta is None:
                turn_id = self.next_turn_id

                self.pending_turn = create_transcript_turn(
                    turn_id=turn_id,
                    runtime_index=runtime_index,
                    text=text,
                    t2=t2,
                )

                self.next_turn_id += 1

            else:
                turn_id = smart_meta["turn_id"]
                segment_count = smart_meta[
                    "segment_count"
                ]

                completion_source = (
                    TURN_COMPLETION_SMART_TURN
                    if smart_meta["decision"]
                    == "COMPLETE"
                    else
                    TURN_COMPLETION_SMART_TURN_FALLBACK
                )

                self.pending_turn = create_transcript_turn(
                    turn_id=turn_id,
                    revision=max(
                        segment_count - 1,
                        0,
                    ),
                    runtime_index=runtime_index,
                    text=text,
                    t2=t2,
                    turn_id_source=(
                        TURN_ID_SOURCE_SPEECH_RUNTIME
                    ),
                    completion_source=completion_source,
                    segment_count=segment_count,
                )

                self.pending_turn[
                    "smart_turn_complete"
                ] = (
                    True
                    if smart_meta["decision"]
                    == "COMPLETE"
                    else None
                )

                self.pending_turn[
                    "smart_turn_score"
                ] = smart_meta["score"]

                infer_ms = smart_meta["infer_ms"]
                prep_ms = smart_meta["audio_prep_ms"]
                feature_ms = smart_meta["feature_ms"]
                total_ms = smart_meta["total_ms"]

                if infer_ms is not None:
                    self.pending_turn[
                        "smart_turn_inference_s"
                    ] = infer_ms / 1000.0

                if prep_ms is not None:
                    self.pending_turn[
                        "smart_turn_audio_prep_s"
                    ] = prep_ms / 1000.0

                if feature_ms is not None:
                    self.pending_turn[
                        "smart_turn_feature_s"
                    ] = feature_ms / 1000.0

                if total_ms is not None:
                    self.pending_turn[
                        "smart_turn_total_s"
                    ] = total_ms / 1000.0

                self.pending_turn[
                    "smart_turn_decision"
                ] = smart_meta["decision"]

                self.pending_turn[
                    "smart_turn_evaluations"
                ] = smart_meta["evaluations"]

                self.pending_smart_turn = None

                self.next_turn_id = max(
                    self.next_turn_id,
                    turn_id + 1,
                )

            return None

        latency_match = LATENCY_RE.match(line)

        if not latency_match:
            return None

        if self.pending_turn is None:
            return None

        stage = latency_match.group(1)
        value = float(latency_match.group(2))

        if stage == "VAD":
            self.pending_turn["vad_s"] = value

        elif stage == "STT":
            self.pending_turn["stt_s"] = value

        elif stage == "TOTAL":
            self.pending_turn[
                "vad_stt_total_s"
            ] = value

        if not is_complete_transcript_turn(
            self.pending_turn
        ):
            return None

        completed_turn = self.pending_turn
        self.pending_turn = None

        return completed_turn


class SpeechRuntimeHandler(threading.Thread):
    """
    Own the C++ speech subprocess and continuously drain output.

    Phase 9A additionally consumes the runtime event:

        [SPEECH_STARTED]

    and forwards it to GenerationCancellationController.

    SpeechRuntimeHandler still never calls the LLM directly.
    """

    def __init__(
        self,
        command,
        transcript_queue,
        stop_event,
        cancellation_controller=None,
        name="SpeechRuntimeHandler",
    ):
        threading.Thread.__init__(self, name=name)

        self.command = command
        self.transcript_queue = transcript_queue
        self.stop_event = stop_event

        self.cancellation_controller = (
            cancellation_controller
        )

        self.process = None
        self.parser = SpeechRuntimeParser()
        self.error = None

        self.speech_started_count = 0
        self.last_interruption = None

    def _handle_runtime_event_line(
        self,
        raw_line,
    ):
        """
        Handle realtime events that are not transcript records.

        Returns True when the line was consumed as a runtime event.
        """
        line = raw_line.strip()

        if not SPEECH_STARTED_RE.match(line):
            return False

        self.speech_started_count += 1

        if self.cancellation_controller is not None:
            self.last_interruption = (
                self.cancellation_controller.cancel_active(
                    reason="barge_in"
                )
            )

        return True

    def run(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )

            for raw_line in iter(
                self.process.stdout.readline,
                "",
            ):
                if self.stop_event.is_set():
                    break

                # Phase 9 realtime events must be handled before
                # transcript parsing.
                if self._handle_runtime_event_line(
                    raw_line
                ):
                    continue

                turn = self.parser.feed_line(
                    raw_line
                )

                if turn is None:
                    continue

                turn[
                    "transcript_queue_enter"
                ] = time.perf_counter()

                turn[
                    "transcript_queue_depth_at_enqueue"
                ] = (
                    self.transcript_queue.qsize()
                    + 1
                )

                self.transcript_queue.put(turn)

        except Exception as exc:
            self.error = exc
            self.stop_event.set()

        finally:
            self.stop()

    def stop(self):
        """
        Gracefully stop the C++ speech runtime.

        SIGINT preserves the Phase-3 worker-drain contract.
        SIGTERM is only a fallback.
        """

        process = self.process

        if process is None:
            return

        if process.poll() is None:
            try:
                process.send_signal(
                    signal.SIGINT
                )

            except Exception:
                try:
                    process.terminate()
                except Exception:
                    pass

        try:
            process.wait(timeout=30.0)

        except subprocess.TimeoutExpired:
            try:
                process.terminate()
            except Exception:
                pass

            try:
                process.wait(timeout=5.0)
            except Exception:
                pass

        except Exception:
            pass
