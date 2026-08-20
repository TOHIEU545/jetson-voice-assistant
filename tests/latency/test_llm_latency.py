#!/usr/bin/env python3

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path.home() / "jetson-voice-assistant"
LOG_DIR = PROJECT_ROOT / "logs" / "benchmarks" / "llm_latency"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LLM_URL = "http://127.0.0.1:8080/v1/chat/completions"

TEST_PROMPTS = [
    "What is a microcontroller?",
    "What is UART?",
    "What is SPI?",
    "What is CAN bus?",
    "What is an RTOS?",
]

SYSTEM_PROMPT = (
    "You are EmbedAI, a voice assistant specialized in embedded systems. "
    "Answer naturally, technically, and directly. "
    "Prefer 1 to 3 concise sentences."
)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_file = LOG_DIR / f"llm_latency_{timestamp}.txt"

results = []

print("==========================================")
print(" LLM Latency Benchmark")
print("==========================================")
print("URL:", LLM_URL)
print()

for i, prompt in enumerate(TEST_PROMPTS, 1):

    body = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 128,
        "temperature": 0.5,
        "stream": True,
    }

    request = urllib.request.Request(
        LLM_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    print(f"[{i}/{len(TEST_PROMPTS)}] {prompt}")

    request_start = time.perf_counter()
    first_token_time = None
    last_token_time = None
    answer_parts = []
    chunk_count = 0

    try:
        with urllib.request.urlopen(request) as response:

            for raw_line in response:

                line = raw_line.decode("utf-8").strip()

                if not line.startswith("data:"):
                    continue

                data = line[5:].strip()

                if not data or data == "[DONE]":
                    if data == "[DONE]":
                        break
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
                    token = delta.get("content") or ""

                if not token:
                    token = choice.get("text") or ""

                if not token:
                    continue

                now = time.perf_counter()

                if first_token_time is None:
                    first_token_time = now

                last_token_time = now
                answer_parts.append(token)
                chunk_count += 1

        request_end = time.perf_counter()

        if first_token_time is None:
            print("  ERROR: no streamed token received")
            continue

        ttft = first_token_time - request_start
        generation_time = (
            last_token_time - first_token_time
            if last_token_time is not None
            else 0.0
        )
        total_time = request_end - request_start

        answer = "".join(answer_parts).strip()

        # Streaming chunks are not guaranteed to map 1:1 to model tokens.
        # This is only a rough output throughput estimate.
        approx_tokens = len(answer.split())
        approx_tok_s = (
            approx_tokens / generation_time
            if generation_time > 0
            else 0.0
        )

        result = {
            "prompt": prompt,
            "ttft": ttft,
            "generation_time": generation_time,
            "total_time": total_time,
            "approx_tokens": approx_tokens,
            "approx_tok_s": approx_tok_s,
            "chunks": chunk_count,
            "answer": answer,
        }

        results.append(result)

        print(f"  TTFT              : {ttft:.3f} s")
        print(f"  Generation        : {generation_time:.3f} s")
        print(f"  Total             : {total_time:.3f} s")
        print(f"  Approx throughput : {approx_tok_s:.2f} word/s")
        print()

    except Exception as e:
        print("  ERROR:", e)
        print()


if results:

    avg_ttft = sum(r["ttft"] for r in results) / len(results)
    avg_generation = sum(r["generation_time"] for r in results) / len(results)
    avg_total = sum(r["total_time"] for r in results) / len(results)

    print("==========================================")
    print(" Average")
    print("==========================================")
    print(f"TTFT       : {avg_ttft:.3f} s")
    print(f"Generation : {avg_generation:.3f} s")
    print(f"Total      : {avg_total:.3f} s")

    with open(log_file, "w") as f:
        f.write("LLM Latency Benchmark\n")
        f.write("=" * 60 + "\n\n")

        for r in results:
            f.write(f"Prompt: {r['prompt']}\n")
            f.write(f"TTFT: {r['ttft']:.3f} s\n")
            f.write(f"Generation: {r['generation_time']:.3f} s\n")
            f.write(f"Total: {r['total_time']:.3f} s\n")
            f.write(f"Approx output words: {r['approx_tokens']}\n")
            f.write(f"Approx throughput: {r['approx_tok_s']:.2f} word/s\n")
            f.write(f"Answer: {r['answer']}\n")
            f.write("-" * 60 + "\n")

        f.write("\nAVERAGE\n")
        f.write(f"TTFT: {avg_ttft:.3f} s\n")
        f.write(f"Generation: {avg_generation:.3f} s\n")
        f.write(f"Total: {avg_total:.3f} s\n")

    print()
    print("Log:", log_file)
