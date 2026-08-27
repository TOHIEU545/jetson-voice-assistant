#!/usr/bin/env python3

import json
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


from backends.llm import (
    LocalLlamaCppBackend,
    RemoteOpenAICompatibleBackend,
)


class FakeResponse(object):

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        return False

    def __iter__(self):
        return iter(self.lines)


def main():
    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url

        captured["body"] = json.loads(
            request.data.decode("utf-8")
        )

        captured["headers"] = dict(
            request.header_items()
        )

        return FakeResponse([
            (
                b'data: {"choices":[{"delta":'
                b'{"content":"Hello "}}]}\n'
            ),
            (
                b'data: {"choices":[{"delta":'
                b'{"content":"world"}}]}\n'
            ),
            b'data: [DONE]\n',
        ])

    messages = [
        {
            "role": "system",
            "content": "You are EmbedAI.",
        },
        {
            "role": "user",
            "content": "Hello",
        },
    ]

    # --------------------------------------------------------
    # Local llama.cpp
    # --------------------------------------------------------

    local = LocalLlamaCppBackend(
        base_url=(
            "http://127.0.0.1:8080/"
            "v1/chat/completions"
        ),
        urlopen_func=fake_urlopen,
    )

    tokens = list(
        local.stream_generate(
            messages=messages,
            max_tokens=128,
            temperature=0.5,
        )
    )

    assert tokens == [
        "Hello ",
        "world",
    ]

    assert captured["body"]["stream"] is True
    assert captured["body"]["messages"] == messages
    assert captured["body"]["max_tokens"] == 128
    assert captured["body"]["temperature"] == 0.5

    # Local backend should not require an API key.
    assert "Authorization" not in captured["headers"]

    # --------------------------------------------------------
    # Remote backend
    # --------------------------------------------------------

    remote = RemoteOpenAICompatibleBackend(
        base_url=(
            "http://192.168.1.100:8000/"
            "v1/chat/completions"
        ),
        model="test-model",
        api_key="test-key",
        urlopen_func=fake_urlopen,
    )

    tokens = list(
        remote.stream_generate(
            messages=messages,
            max_tokens=64,
            temperature=0.2,
        )
    )

    assert tokens == [
        "Hello ",
        "world",
    ]

    assert captured["body"]["model"] == "test-model"

    assert (
        captured["headers"]["Authorization"]
        == "Bearer test-key"
    )

    print("PASS: LLMBackend abstraction")
    print("local llama.cpp backend: PASS")
    print("remote OpenAI-compatible backend: PASS")
    print("stream parser: PASS")
    print("API key support: PASS")


if __name__ == "__main__":
    main()
