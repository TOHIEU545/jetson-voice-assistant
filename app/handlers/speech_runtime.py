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


class SpeechRuntimeParser(object):
    """
    Stateful parser for the current sherpa stdout/stderr contract.

    Expected sequence:

        0: What is a microcontroller?
        [LATENCY] VAD   : 0.500 s
        [LATENCY] STT   : 1.650 s
        [LATENCY] TOTAL : 2.150 s

    T2 is captured immediately when the transcript line is received.

    A complete turn is emitted after TOTAL arrives so downstream
    consumers receive transcript + C++ latency metadata together.
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
            runtime_index = int(transcript_match.group(1))
            text = transcript_match.group(2).strip()

            if not text:
                return None

            # T2: final transcript reaches the Python application.
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
            self.pending_turn["vad_stt_total_s"] = value

        if not is_complete_transcript_turn(self.pending_turn):
            return None

        completed_turn = self.pending_turn
        self.pending_turn = None

        return completed_turn


class SpeechRuntimeHandler(threading.Thread):
    """
    Owns the sherpa subprocess and continuously drains its output.

    Responsibilities:
        subprocess lifecycle
        stdout ingestion
        transcript/latency parsing
        transcript_queue.put()

    It must never call the LLM.
    """

    def __init__(
        self,
        command,
        transcript_queue,
        stop_event,
        name="SpeechRuntimeHandler",
    ):
        threading.Thread.__init__(self, name=name)

        self.command = command
        self.transcript_queue = transcript_queue
        self.stop_event = stop_event

        self.process = None
        self.parser = SpeechRuntimeParser()
        self.error = None

    def run(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )

            for raw_line in iter(self.process.stdout.readline, ""):
                if self.stop_event.is_set():
                    break

                turn = self.parser.feed_line(raw_line)

                if turn is None:
                    continue

                turn["transcript_queue_enter"] = time.perf_counter()

                # qsize() is approximate under concurrency, but is
                # sufficient for Phase-4 backlog instrumentation.
                turn["transcript_queue_depth_at_enqueue"] = (
                    self.transcript_queue.qsize() + 1
                )

                # Phase 4 currently uses an unbounded queue.
                # Text/metadata payload is small and this put must not
                # become the new speech-ingestion bottleneck.
                self.transcript_queue.put(turn)

        except Exception as exc:
            self.error = exc
            self.stop_event.set()

        finally:
            self.stop()

    def stop(self):
        """
        Gracefully stop the C++ speech runtime.

        SIGINT preserves the Phase-3 shutdown contract:
        producer stops, queued speech is drained by the STT worker,
        and the process exits after worker join.

        SIGTERM is only a fallback if graceful shutdown stalls.
        """

        process = self.process

        if process is None:
            return

        if process.poll() is None:
            try:
                process.send_signal(signal.SIGINT)
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
