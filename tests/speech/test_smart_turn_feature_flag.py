#!/usr/bin/env python3

import os
import subprocess
import sys


PROJECT_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
    )
)

APP_DIR = os.path.join(PROJECT_ROOT, "app")


def run_config(extra_env=None):
    env = os.environ.copy()
    env.pop("VOICE_ASSISTANT_GTCRN", None)
    env.pop("VOICE_ASSISTANT_SMART_TURN", None)

    if extra_env:
        env.update(extra_env)

    env["PYTHONPATH"] = APP_DIR

    code = r'''
import config

print("GTCRN=" + str(config.ENABLE_GTCRN))
print("SMART_TURN=" + str(config.ENABLE_SMART_TURN))

for arg in config.build_speech_command():
    if (
        "speech-denoiser-gtcrn-model" in arg
        or "smart-turn-" in arg
    ):
        print(arg)
'''

    return subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
    )


def main():
    # Default: both OFF.
    output = run_config()

    assert "GTCRN=False" in output
    assert "SMART_TURN=False" in output
    assert "--smart-turn-model=" not in output
    assert "--smart-turn-threshold=" not in output
    assert "--smart-turn-num-threads=" not in output

    # Smart Turn only.
    output = run_config({
        "VOICE_ASSISTANT_SMART_TURN": "1",
    })

    assert "GTCRN=False" in output
    assert "SMART_TURN=True" in output

    assert "--smart-turn-model=" in output
    assert (
        "smart-turn-v3.2-cpu-opset16-ir8-clean.onnx"
        in output
    )
    assert "--smart-turn-threshold=0.5" in output
    assert "--smart-turn-num-threads=4" in output

    # Both optional features enabled.
    output = run_config({
        "VOICE_ASSISTANT_GTCRN": "1",
        "VOICE_ASSISTANT_SMART_TURN": "1",
    })

    assert "GTCRN=True" in output
    assert "SMART_TURN=True" in output
    assert "--speech-denoiser-gtcrn-model=" in output
    assert "--smart-turn-model=" in output

    print("PASS: Phase 7C Smart Turn feature flag")
    print("default OFF: PASS")
    print("Smart Turn ON: PASS")
    print("GTCRN + Smart Turn coexistence: PASS")


if __name__ == "__main__":
    main()
