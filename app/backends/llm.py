#!/usr/bin/env python3

import json
import urllib.request


class LLMBackend(object):
    """
    Base interface for streaming LLM backends.

    Backends own:
        - endpoint configuration
        - HTTP request construction
        - authentication headers
        - OpenAI-compatible stream parsing

    LLMHandler owns:
        - queue consumption
        - conversation coordination
        - latency timestamps
        - output events
    """

    def stream_generate(
        self,
        messages,
        max_tokens,
        temperature,
    ):
        raise NotImplementedError


class OpenAICompatibleBackend(LLMBackend):
    """
    Shared implementation for OpenAI-compatible
    /v1/chat/completions servers.
    """

    def __init__(
        self,
        base_url,
        model=None,
        api_key=None,
        urlopen_func=None,
    ):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key

        if urlopen_func is None:
            self.urlopen_func = urllib.request.urlopen
        else:
            self.urlopen_func = urlopen_func

    def _build_body(
        self,
        messages,
        max_tokens,
        temperature,
    ):
        body = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }

        if self.model:
            body["model"] = self.model

        return body

    def _build_headers(self):
        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = (
                "Bearer " + self.api_key
            )

        return headers

    def stream_generate(
        self,
        messages,
        max_tokens,
        temperature,
    ):
        body = self._build_body(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(body).encode("utf-8"),
            headers=self._build_headers(),
        )

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

                # Compatibility with text-completion-like
                # OpenAI-compatible streaming servers.
                if not token:
                    token = (
                        choice.get("text")
                        or ""
                    )

                if token:
                    yield token


class LocalLlamaCppBackend(OpenAICompatibleBackend):
    """
    Local llama.cpp server running on the Jetson.
    """

    def __init__(
        self,
        base_url,
        model=None,
        urlopen_func=None,
    ):
        OpenAICompatibleBackend.__init__(
            self,
            base_url=base_url,
            model=model,
            api_key=None,
            urlopen_func=urlopen_func,
        )


class RemoteOpenAICompatibleBackend(
    OpenAICompatibleBackend
):
    """
    Remote OpenAI-compatible backend.

    Intended for a LAN GPU server such as an RTX workstation
    running llama.cpp, vLLM, or another compatible server.
    """

    def __init__(
        self,
        base_url,
        model=None,
        api_key=None,
        urlopen_func=None,
    ):
        OpenAICompatibleBackend.__init__(
            self,
            base_url=base_url,
            model=model,
            api_key=api_key,
            urlopen_func=urlopen_func,
        )


def create_llm_backend(
    mode,
    base_url,
    model=None,
    api_key=None,
    urlopen_func=None,
):
    """
    Create the configured LLM backend.

    mode:
        local  -> llama.cpp server on Jetson
        remote -> OpenAI-compatible external server
    """
    normalized_mode = mode.strip().lower()

    if normalized_mode == "local":
        return LocalLlamaCppBackend(
            base_url=base_url,
            model=model,
            urlopen_func=urlopen_func,
        )

    if normalized_mode == "remote":
        return RemoteOpenAICompatibleBackend(
            base_url=base_url,
            model=model,
            api_key=api_key,
            urlopen_func=urlopen_func,
        )

    raise ValueError(
        "Unsupported LLM_MODE: %s" % mode
    )
