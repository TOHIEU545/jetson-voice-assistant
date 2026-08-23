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

APP = os.path.join(ROOT, "app")


def inspect(extra_env):
    env = os.environ.copy()

    env.pop(
        "VOICE_ASSISTANT_SMART_TURN",
        None,
    )
    env.pop(
        "VOICE_ASSISTANT_SPECULATIVE",
        None,
    )

    env.update(extra_env)
    env["PYTHONPATH"] = APP

    code = (
        "import config;"
        "print(config.ENABLE_SMART_TURN);"
        "print(config.ENABLE_SPECULATIVE_TURN);"
        "print(' '.join(config.build_speech_command()))"
    )

    return subprocess.check_output(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        universal_newlines=True,
    )


def main():
    default = inspect({})

    lines = default.splitlines()

    assert lines[0] == "False"
    assert lines[1] == "False"
    assert "--smart-turn-speculative=1" not in default

    # Speculative alone cannot activate without Smart Turn.
    spec_only = inspect({
        "VOICE_ASSISTANT_SPECULATIVE": "1",
    })

    lines = spec_only.splitlines()

    assert lines[0] == "False"
    assert lines[1] == "False"
    assert "--smart-turn-speculative=1" not in spec_only

    enabled = inspect({
        "VOICE_ASSISTANT_SMART_TURN": "1",
        "VOICE_ASSISTANT_SPECULATIVE": "1",
    })

    lines = enabled.splitlines()

    assert lines[0] == "True"
    assert lines[1] == "True"
    assert "--smart-turn-speculative=1" in enabled

    print("PASS: Phase 8B speculative feature flag")
    print("default OFF: PASS")
    print("Smart Turn OFF isolation: PASS")
    print("explicit opt-in: PASS")


if __name__ == "__main__":
    main()
