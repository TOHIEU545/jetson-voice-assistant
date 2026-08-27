#!/usr/bin/env python3

import os
import subprocess
import sys


ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
    )
)


def command_for(backend, smart_turn="0"):
    env = os.environ.copy()

    env["VOICE_ASSISTANT_STT"] = backend
    env["VOICE_ASSISTANT_GTCRN"] = "0"
    env["VOICE_ASSISTANT_SMART_TURN"] = smart_turn
    env["VOICE_ASSISTANT_SPECULATIVE"] = "0"

    code = (
        "import sys;"
        "sys.path.insert(0,'app');"
        "import config;"
        "print('\\n'.join(config.build_speech_command()))"
    )

    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )


def main():
    # Whisper must stay on the existing offline runtime.
    r = command_for("whisper")
    assert r.returncode == 0, r.stderr
    assert "sherpa-onnx-vad-alsa-offline-asr" in r.stdout
    assert "--whisper-encoder=" in r.stdout
    assert "--encoder=" not in r.stdout

    # 20M must use the new streaming runtime.
    r = command_for("zipformer_20m")
    assert r.returncode == 0, r.stderr
    assert "sherpa-onnx-vad-alsa-streaming-asr" in r.stdout
    assert "streaming-zipformer-en-20M-2023-02-17" in r.stdout
    assert "--encoder=" in r.stdout
    assert "--whisper-encoder=" not in r.stdout

    # Larger Zipformer must use the same streaming runtime.
    r = command_for("zipformer_2023_06_21")
    assert r.returncode == 0, r.stderr
    assert "sherpa-onnx-vad-alsa-streaming-asr" in r.stdout
    assert "streaming-zipformer-en-2023-06-21" in r.stdout

    # Smart Turn must not accidentally enter streaming runtime yet.
    r = command_for("zipformer_20m", smart_turn="1")
    assert r.returncode != 0
    assert "Smart Turn" in r.stderr

    print("PASS: STT backend selection")
    print("Whisper -> offline runtime")
    print("Zipformer 20M -> streaming runtime")
    print("Zipformer 2023-06-21 -> streaming runtime")
    print("Streaming + Smart Turn guard -> PASS")


if __name__ == "__main__":
    main()
