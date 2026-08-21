#!/usr/bin/env python3

import os
import sys


PROJECT_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
    )
)

APP_DIR = os.path.join(PROJECT_ROOT, "app")

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from handlers.speech_runtime import SpeechRuntimeParser


def feed_turn(parser, runtime_index, text, vad, stt, total):
    lines = [
        "{}: {}\n".format(runtime_index, text),
        "[LATENCY] VAD   : {:.3f} s\n".format(vad),
        "[LATENCY] STT   : {:.3f} s\n".format(stt),
        "[LATENCY] TOTAL : {:.3f} s\n".format(total),
    ]

    completed = None

    for line in lines:
        turn = parser.feed_line(line)

        if turn is not None:
            completed = turn

    return completed


def main():
    parser = SpeechRuntimeParser()

    first = feed_turn(
        parser,
        runtime_index=17,
        text="What is a microcontroller?",
        vad=0.500,
        stt=1.654,
        total=2.154,
    )

    second = feed_turn(
        parser,
        runtime_index=18,
        text="What is embedded programming?",
        vad=0.500,
        stt=1.600,
        total=2.100,
    )

    assert first is not None
    assert second is not None

    # Python pipeline identity.
    assert first["turn_id"] == 0
    assert second["turn_id"] == 1

    # Sherpa stdout identity.
    assert first["runtime_index"] == 17
    assert second["runtime_index"] == 18

    assert first["text"] == "What is a microcontroller?"
    assert first["vad_s"] == 0.500
    assert first["stt_s"] == 1.654
    assert first["vad_stt_total_s"] == 2.154
    assert first["t2"] is not None

    print("PASS: SpeechRuntimeParser")
    print(
        "turn_id={} runtime_index={}".format(
            first["turn_id"],
            first["runtime_index"],
        )
    )
    print(
        "turn_id={} runtime_index={}".format(
            second["turn_id"],
            second["runtime_index"],
        )
    )


if __name__ == "__main__":
    main()
