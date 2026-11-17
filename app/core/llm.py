"""One small interface to a chat language model, so providers swap by configuration.

Only the coach uses this; the matcher never calls a language model.

OpenAICompatibleLLM speaks the widely implemented "chat completions" HTTP
format, which hosted providers and local servers both offer. It uses only the
standard library, so no extra dependency is needed.
"""

import json
import time
import urllib.error
import urllib.request
from typing import Protocol


class LLMUnavailable(Exception):
    """The model could not be reached or returned an unusable response."""


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 8.0,
        max_retries: int = 2,
        temperature: float = 0.2,
        max_tokens: int = 400,
    ):
        if not base_url or not model:
            raise ValueError("The LLM base URL and model must be set.")
        self.name = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._temperature = temperature
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        problem = "no attempt made"
        for attempt in range(self._max_retries + 1):
            if attempt:
                time.sleep(0.5 * attempt)
            request = urllib.request.Request(self._url, data=payload, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty content")
                return content.strip()
            except urllib.error.HTTPError as exc:
                problem = f"HTTP {exc.code}"
                # 4xx other than rate limiting is a configuration problem: do not retry
                if exc.code < 500 and exc.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                problem = "connection failed or timed out"
            except (ValueError, KeyError, IndexError, TypeError):
                problem = "unexpected response format"
        raise LLMUnavailable(problem)


def build_llm(
    provider: str, base_url: str, model: str, api_key: str = "", timeout: float = 8.0
) -> LLM | None:
    """Return the configured model, or None for retrieval-only mode."""
    if provider == "none":
        return None
    if provider == "openai-compatible":
        return OpenAICompatibleLLM(base_url, model, api_key, timeout=timeout)
    raise ValueError(f"Unknown LLM provider: {provider!r}")
