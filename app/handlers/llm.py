#!/usr/bin/env python3

import json
import queue
import threading
import time
import urllib.request


class LLMHandler(threading.Thread):
    """
    Consume valid transcript turns and run the streaming LLM request.

        valid_turn_queue
                |
                v
            LLMHandler
                |
                v
         llm_output_queue

    Phase 5 responsibilities:
        - obtain conversation context from ConversationManager
        - perform HTTP request
        - parse streaming tokens
        - timestamp T3/T4/T5
        - emit response events

    Conversation history ownership belongs to ConversationManager.

    LLMBackend abstraction belongs to Phase 6.
    """

    def __init__(
        self,
        valid_turn_queue,
        llm_output_queue,
        stop_event,
        llm_url,
        conversation_manager,
        max_tokens=128,
        temperature=0.5,
        urlopen_func=None,
        name="LLMHandler",
    ):
        threading.Thread.__init__(self, name=name)

        self.valid_turn_queue = valid_turn_queue
        self.llm_output_queue = llm_output_queue
        self.stop_event = stop_event

        self.llm_url = llm_url
        self.max_tokens = max_tokens
        self.temperature = temperature

        self.conversation_manager = conversation_manager

        if urlopen_func is None:
            self.urlopen_func = urllib.request.urlopen
        else:
            self.urlopen_func = urlopen_func

        self.error = None
        self.completed_count = 0
        self.failed_count = 0

    def _emit(self, event):
        self.llm_output_queue.put(event)

    def _abort_turn_safely(
        self,
        turn_id,
        reason,
    ):
        try:
            self.conversation_manager.abort_turn(
                turn_id=turn_id,
                reason=reason,
            )
        except Exception:
            pass

    def _process_turn(self, turn):
        turn["valid_turn_queue_leave"] = time.perf_counter()

        worker_start = time.perf_counter()

        turn_id = turn["turn_id"]
        text = turn.get("text", "").strip()

        self._emit({
            "type": "turn_start",
            "turn_id": turn_id,
            "runtime_index": turn["runtime_index"],
            "text": text,
        })

        try:
            messages = (
                self.conversation_manager.start_turn(
                    turn_id=turn_id,
                    text=text,
                )
            )

            body = {
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "stream": True,
            }

            request = urllib.request.Request(
                self.llm_url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                },
            )

            # T3: client starts the LLM request.
            turn["t3"] = time.perf_counter()

            answer_parts = []
            t4 = None
            t5 = None

            with self.urlopen_func(request) as response:

                for raw_line in response:
                    line = raw_line.decode(
                        "utf-8"
                    ).strip()

                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()

                    if data == "[DONE]":
                        break

                    if not data:
                        continue

                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue

                    choices = chunk.get("choices", [])

                    if not choices:
                        continue

                    choice = choices[0]
                    token = ""

                    delta = choice.get("delta", {})

                    if isinstance(delta, dict):
                        token = (
                            delta.get("content")
                            or ""
                        )

                    if not token:
                        token = (
                            choice.get("text")
                            or ""
                        )

                    if not token:
                        continue

                    token_time = time.perf_counter()

                    if t4 is None:
                        t4 = token_time

                    t5 = token_time

                    answer_parts.append(token)

                    self._emit({
                        "type": "token",
                        "turn_id": turn_id,
                        "text": token,
                    })

        except Exception as exc:
            self._abort_turn_safely(
                turn_id=turn_id,
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
                "runtime_index": turn["runtime_index"],
                "text": text,
                "error": str(exc),
                "turn": dict(turn),
            })

            return

        answer = "".join(answer_parts).strip()

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
                    assistant_text=answer,
                )

            except Exception as exc:
                self._abort_turn_safely(
                    turn_id=turn_id,
                    reason=str(exc),
                )

                self.failed_count += 1

                self._emit({
                    "type": "llm_error",
                    "turn_id": turn_id,
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
                reason="empty assistant response",
            )

        self.completed_count += 1

        self._emit({
            "type": "turn_done",
            "turn_id": turn_id,
            "runtime_index": turn["runtime_index"],
            "text": text,
            "answer": answer,
            "turn": dict(turn),
        })

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