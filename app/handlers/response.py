#!/usr/bin/env python3

import json
import queue
import sys
import threading
from datetime import datetime


class ResponseProcessor(threading.Thread):
    """
    Final output stage.

        llm_output_queue
                |
                v
        ResponseProcessor
                |
                +--> terminal
                +--> conversation log
                +--> Python/LLM benchmark
                +--> full-pipeline benchmark

    This is the only Phase-4 component responsible for user-visible
    terminal output and persistent conversation/latency records.
    """

    def __init__(
        self,
        output_queue,
        stop_event,
        conversation_log_path,
        benchmark_log_path,
        full_pipeline_log_path,
        session_start=None,
        output_stream=None,
        name="ResponseProcessor",
    ):
        threading.Thread.__init__(self, name=name)

        self.output_queue = output_queue
        self.stop_event = stop_event

        self.conversation_log_path = conversation_log_path
        self.benchmark_log_path = benchmark_log_path
        self.full_pipeline_log_path = (
            full_pipeline_log_path
        )

        if session_start is None:
            session_start = datetime.now()

        self.session_start = session_start

        if output_stream is None:
            output_stream = sys.stdout

        self.output_stream = output_stream

        self.error = None

        # Keeps the old user-facing benchmark numbering:
        # accepted LLM turn 1, 2, 3, ...
        self.response_turn_index = 0
        self.turn_numbers = {}

    def _console(self, text, flush=False):
        self.output_stream.write(text)

        if flush:
            self.output_stream.flush()

    @staticmethod
    def _duration_ms(start, end):
        if start is None or end is None:
            return None

        return (end - start) * 1000.0

    @staticmethod
    def _seconds_to_ms(value):
        if value is None:
            return None

        return value * 1000.0

    def _build_latency_record(self, turn, text):
        t2 = turn.get("t2")
        t3 = turn.get("t3")
        t4 = turn.get("t4")
        t5 = turn.get("t5")

        if (
            t2 is None
            or t3 is None
            or t4 is None
            or t5 is None
        ):
            return None

        turn_id = turn["turn_id"]

        python_overhead = t3 - t2
        llm_ttft = t4 - t3
        llm_generation = t5 - t4

        transcript_to_first = t4 - t2
        transcript_to_last = t5 - t2

        return {
            # Preserve the old accepted-turn sequence.
            "turn": self.turn_numbers.get(turn_id),

            # New Phase-4 identity.
            "turn_id": turn_id,
            "runtime_index": turn.get("runtime_index"),

            "revision": turn.get("revision"),
            "segment_count": turn.get("segment_count"),
            "completion_source": turn.get(
                "completion_source"
            ),

            "smart_turn_complete": turn.get(
                "smart_turn_complete"
            ),
            "smart_turn_score": turn.get(
                "smart_turn_score"
            ),
            "smart_turn_inference_s": turn.get(
                "smart_turn_inference_s"
            ),
            "smart_turn_audio_prep_s": turn.get(
                "smart_turn_audio_prep_s"
            ),
            "smart_turn_feature_s": turn.get(
                "smart_turn_feature_s"
            ),
            "smart_turn_total_s": turn.get(
                "smart_turn_total_s"
            ),
            "smart_turn_decision": turn.get(
                "smart_turn_decision"
            ),
            "smart_turn_evaluations": turn.get(
                "smart_turn_evaluations"
            ),

            "timestamp": datetime.now().isoformat(),
            "transcript": text,

            "python_overhead_s": python_overhead,
            "llm_ttft_s": llm_ttft,
            "llm_generation_s": llm_generation,

            "transcript_to_first_token_s":
                transcript_to_first,

            "transcript_to_last_token_s":
                transcript_to_last,

            # New Phase-4 queue/worker metrics.
            "transcript_queue_wait_ms":
                self._duration_ms(
                    turn.get("transcript_queue_enter"),
                    turn.get("transcript_queue_leave"),
                ),

            "valid_turn_queue_wait_ms":
                self._duration_ms(
                    turn.get("valid_turn_queue_enter"),
                    turn.get("valid_turn_queue_leave"),
                ),

            "gate_processing_ms":
                self._seconds_to_ms(
                    turn.get("gate_processing_s")
                ),

            "llm_worker_processing_ms":
                self._seconds_to_ms(
                    turn.get("llm_processing_s")
                ),

            "transcript_queue_depth_at_enqueue":
                turn.get(
                    "transcript_queue_depth_at_enqueue"
                ),

            "valid_turn_queue_depth_at_enqueue":
                turn.get(
                    "valid_turn_queue_depth_at_enqueue"
                ),
        }

    def _write_latency_summary(
        self,
        turn,
        latency_record,
        full_record,
    ):
        self._console("\n")

        self._console(
            "[LATENCY] VAD          T0->T1 : "
            "{:.3f} s\n".format(
                full_record["vad_s"]
            )
        )

        self._console(
            "[LATENCY] STT          T1->T2 : "
            "{:.3f} s\n".format(
                full_record["stt_s"]
            )
        )

        self._console(
            "[LATENCY] VAD + STT    T0->T2 : "
            "{:.3f} s\n".format(
                full_record["vad_stt_total_s"]
            )
        )

        smart_decision = turn.get(
            "smart_turn_decision"
        )

        if smart_decision is not None:
            smart_score = turn.get(
                "smart_turn_score"
            )
            smart_total = turn.get(
                "smart_turn_total_s"
            )
            segment_count = turn.get(
                "segment_count"
            )

            score_text = (
                "{:.6f}".format(smart_score)
                if smart_score is not None
                else "n/a"
            )

            total_text = (
                "{:.3f} s".format(smart_total)
                if smart_total is not None
                else "n/a"
            )

            self._console(
                "[SMART_TURN] decision={} "
                "score={} total={} "
                "segments={}\n".format(
                    smart_decision,
                    score_text,
                    total_text,
                    segment_count,
                )
            )

        self._console(
            "[LATENCY] Python       T2->T3 : "
            "{:.3f} s\n".format(
                latency_record["python_overhead_s"]
            )
        )

        self._console(
            "[LATENCY] LLM TTFT     T3->T4 : "
            "{:.3f} s\n".format(
                latency_record["llm_ttft_s"]
            )
        )

        self._console(
            "[LATENCY] LLM Gen      T4->T5 : "
            "{:.3f} s\n".format(
                latency_record["llm_generation_s"]
            )
        )

        self._console(
            "-------------------------------------------\n"
        )

        self._console(
            "[FULL] Speech -> First T0->T4 : "
            "{:.3f} s\n".format(
                full_record[
                    "speech_end_to_first_token_s"
                ]
            )
        )

        self._console(
            "[FULL] Speech -> Last  T0->T5 : "
            "{:.3f} s\n".format(
                full_record[
                    "speech_end_to_last_token_s"
                ]
            )
        )

        transcript_wait = latency_record.get(
            "transcript_queue_wait_ms"
        )

        valid_wait = latency_record.get(
            "valid_turn_queue_wait_ms"
        )

        gate_ms = latency_record.get(
            "gate_processing_ms"
        )

        llm_worker_ms = latency_record.get(
            "llm_worker_processing_ms"
        )

        self._console(
            "-------------------------------------------\n"
        )

        if transcript_wait is not None:
            self._console(
                "[QUEUE] Transcript wait       : "
                "{:.3f} ms\n".format(
                    transcript_wait
                )
            )

        if valid_wait is not None:
            self._console(
                "[QUEUE] Valid turn wait       : "
                "{:.3f} ms\n".format(
                    valid_wait
                )
            )

        if gate_ms is not None:
            self._console(
                "[WORKER] Gate processing      : "
                "{:.3f} ms\n".format(
                    gate_ms
                )
            )

        if llm_worker_ms is not None:
            self._console(
                "[WORKER] LLM processing       : "
                "{:.3f} ms\n".format(
                    llm_worker_ms
                )
            )

        transcript_depth = latency_record.get(
            "transcript_queue_depth_at_enqueue"
        )

        valid_depth = latency_record.get(
            "valid_turn_queue_depth_at_enqueue"
        )

        if transcript_depth is not None:
            self._console(
                "[QUEUE] Transcript depth      : {}\n".format(
                    transcript_depth
                )
            )

        if valid_depth is not None:
            self._console(
                "[QUEUE] Valid turn depth      : {}\n".format(
                    valid_depth
                )
            )

    def _process_event(
        self,
        event,
        conversation_file,
        benchmark_file,
        full_pipeline_file,
    ):
        event_type = event.get("type")

        if event_type == "status":
            self._console(
                event.get("text", ""),
                flush=True,
            )
            return

        if event_type == "gate_drop":
            text = event.get("text", "")
            reason = event.get(
                "reason",
                "unknown",
            )

            self._console(
                '\n[GATE] DROP [{}]: "{}"\n'.format(
                    reason,
                    text,
                )
            )

            conversation_file.write(
                '[GATE DROP] {}: "{}"\n'.format(
                    reason,
                    text,
                )
            )

            self._console("\nSpeak...\n")

            return

        if event_type == "turn_start":
            turn_id = event["turn_id"]
            text = event.get("text", "")

            self.response_turn_index += 1

            self.turn_numbers[turn_id] = (
                self.response_turn_index
            )

            self._console(
                "\nYou: {}\n".format(text)
            )

            self._console(
                "Assistant: ",
                flush=True,
            )

            conversation_file.write(
                "You: " + text + "\n"
            )

            return

        if event_type == "token":
            self._console(
                event.get("text", ""),
                flush=True,
            )

            return

        if event_type == "llm_error":
            error = event.get(
                "error",
                "unknown error",
            )

            self._console(
                "\nLLM error: {}\n".format(error)
            )

            conversation_file.write(
                "LLM error: " + error + "\n\n"
            )

            self._console("\nSpeak...\n")

            return

        if event_type != "turn_done":
            return

        self._console("\n")

        text = event.get("text", "")
        answer = event.get("answer", "")
        turn = event.get("turn", {})

        if answer:
            conversation_file.write(
                "Assistant: " + answer + "\n\n"
            )

        latency_record = self._build_latency_record(
            turn=turn,
            text=text,
        )

        if latency_record is None:
            self._console("\nSpeak...\n")
            return

        benchmark_file.write(
            json.dumps(latency_record) + "\n"
        )

        vad = turn.get("vad_s")
        stt = turn.get("stt_s")
        vad_stt_total = turn.get(
            "vad_stt_total_s"
        )

        if (
            vad is None
            or stt is None
            or vad_stt_total is None
        ):
            self._console("\nSpeak...\n")
            return

        full_record = dict(latency_record)

        full_record.update({
            "vad_s": vad,
            "stt_s": stt,
            "vad_stt_total_s": vad_stt_total,

            "speech_end_to_first_token_s":
                vad_stt_total
                + latency_record[
                    "transcript_to_first_token_s"
                ],

            "speech_end_to_last_token_s":
                vad_stt_total
                + latency_record[
                    "transcript_to_last_token_s"
                ],
        })

        full_pipeline_file.write(
            json.dumps(full_record) + "\n"
        )

        self._write_latency_summary(
            turn=turn,
            latency_record=latency_record,
            full_record=full_record,
        )

        self._console("\nSpeak...\n")

    def run(self):
        conversation_file = None
        benchmark_file = None
        full_pipeline_file = None

        try:
            conversation_file = open(
                self.conversation_log_path,
                "w",
                buffering=1,
            )

            benchmark_file = open(
                self.benchmark_log_path,
                "w",
                buffering=1,
            )

            full_pipeline_file = open(
                self.full_pipeline_log_path,
                "w",
                buffering=1,
            )

            conversation_file.write(
                "=" * 60 + "\n"
            )

            conversation_file.write(
                "Session started: "
                + self.session_start.strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                + "\n"
            )

            conversation_file.write(
                "=" * 60 + "\n\n"
            )

            while (
                not self.stop_event.is_set()
                or not self.output_queue.empty()
            ):
                try:
                    event = self.output_queue.get(
                        timeout=0.1
                    )
                except queue.Empty:
                    continue

                try:
                    self._process_event(
                        event=event,
                        conversation_file=conversation_file,
                        benchmark_file=benchmark_file,
                        full_pipeline_file=full_pipeline_file,
                    )

                finally:
                    self.output_queue.task_done()

        except Exception as exc:
            self.error = exc
            self.stop_event.set()

        finally:
            if conversation_file is not None:
                session_end = datetime.now()

                conversation_file.write(
                    "=" * 60 + "\n"
                )

                conversation_file.write(
                    "Session ended: "
                    + session_end.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    + "\n"
                )

                conversation_file.write(
                    "=" * 60 + "\n"
                )

            if full_pipeline_file is not None:
                full_pipeline_file.close()

            if benchmark_file is not None:
                benchmark_file.close()

            if conversation_file is not None:
                conversation_file.close()
