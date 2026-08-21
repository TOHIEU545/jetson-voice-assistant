#!/usr/bin/env python3

import queue
import re
import signal
import subprocess
import threading
import time

from core.messages import (
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

    def feed_line(self, raw_line):
        line = raw_line.strip()

        if not line:
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

            self.pending_turn = create_transcript_turn(
                turn_id=self.next_turn_id,
                runtime_index=runtime_index,
                text=text,
                t2=t2,
            )

            self.next_turn_id += 1

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
