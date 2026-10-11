"""OpenAI and OpenAI-compatible endpoints (Ollama, LM Studio, OpenRouter, Groq, ...).

Uses the ``openai`` SDK, which also handles retries and ``Retry-After``.
"""

from __future__ import annotations

from typing import Any

from .base import (
    REQUEST_TIMEOUT,
    AiError,
    JsonResult,
    Message,
    Provider,
    describe_status,
    parse_json,
    timeout_message,
    unreachable_message,
    with_json_instruction,
)

# (base_url, model) pairs whose server rejected ``response_format``. Remembered for the
# session so a local model does not pay for a failed request on every batch.
_NO_JSON_MODE: set[tuple[str, str]] = set()
# Same for models that only accept their default temperature (reasoning models).
_NO_TEMPERATURE: set[tuple[str, str]] = set()


class OpenAiProvider(Provider):
    label = "OpenAI"

    def __init__(self, *, label: str = "OpenAI", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.label = label

    def complete_json(self, messages: list[Message], *, temperature: float = 0.0) -> JsonResult:
        import openai

        client = self._client(openai)
        key = (self.base_url, self.model)
        try:
            try:
                if key in _NO_JSON_MODE:
                    raise _NoJsonMode
                response = self._call(client, messages, temperature, json_mode=True)
            except (_NoJsonMode, openai.BadRequestError, openai.UnprocessableEntityError) as exc:
                # Not every server supports response_format. Retry with a prompt-only
                # instruction; remember that only if the retry works.
                response = self._call(client, with_json_instruction(messages), temperature, json_mode=False)
                if not isinstance(exc, _NoJsonMode):
                    _NO_JSON_MODE.add(key)
        except openai.APITimeoutError as exc:
            raise AiError(timeout_message(self.label)) from exc
        except openai.APIConnectionError as exc:
            raise AiError(unreachable_message(self.label, self.base_url)) from exc
        except openai.APIStatusError as exc:
            raise AiError(
                describe_status(self.label, exc.status_code, str(exc.message), has_base_url=bool(self.base_url))
            ) from exc

        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise AiError("The reply was cut off (token limit). Try a model with a larger output limit.")
        return parse_json(choice.message.content or "")

    def _client(self, openai: Any) -> Any:
        return openai.OpenAI(
            # The SDK insists on a key; local servers ignore it.
            api_key=self.api_key or "not-needed",
            base_url=self.base_url or None,
            http_client=self._http_client,
            timeout=REQUEST_TIMEOUT,
        )

    def _call(self, client: Any, messages: list[Message], temperature: float, *, json_mode: bool) -> Any:
        """``_create``, dropping ``temperature`` for models that reject a custom value."""
        import openai

        key = (self.base_url, self.model)
        use = None if key in _NO_TEMPERATURE else temperature
        try:
            return self._create(client, messages, use, json_mode=json_mode)
        except (openai.BadRequestError, openai.UnprocessableEntityError) as exc:
            if use is None or "temperature" not in str(exc).lower():
                raise
            response = self._create(client, messages, None, json_mode=json_mode)
            _NO_TEMPERATURE.add(key)
            return response

    def _create(self, client: Any, messages: list[Message], temperature: float | None, *, json_mode: bool) -> Any:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kwargs)


class _NoJsonMode(Exception):
    """Internal: skip straight to the prompt-only path."""
