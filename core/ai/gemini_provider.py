"""Google Gemini over the native generateContent API."""

from __future__ import annotations

from urllib.parse import quote

from .base import AiError, HttpProvider, JsonResult, Message, parse_json, split_system
from .usage import usage_from_gemini

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


class GeminiProvider(HttpProvider):
    label = "Gemini"

    def complete_json(self, messages: list[Message], *, temperature: float = 0.0) -> JsonResult:
        system, turns = split_system(messages)
        payload = {
            # Gemini calls the assistant role "model".
            "contents": [
                {"role": "model" if t["role"] == "assistant" else "user", "parts": [{"text": t["content"]}]}
                for t in turns
            ],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        model = self.model.removeprefix("models/")
        body = self._post(
            f"{self.base_url or DEFAULT_BASE_URL}/v1beta/models/{quote(model, safe='')}:generateContent",
            headers={"x-goog-api-key": self.api_key, "content-type": "application/json"},
            payload=payload,
        )

        blocked = (body.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise AiError(f"Gemini blocked the request ({blocked}).")
        candidates = body.get("candidates") or []
        if not candidates:
            raise AiError("Gemini returned no answer.")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        finish = candidate.get("finishReason")
        if finish == "MAX_TOKENS":
            raise AiError("The reply was cut off (token limit). Try a model with a larger output limit.")
        if not text and finish not in (None, "STOP"):
            raise AiError(f"Gemini stopped without an answer ({finish}).")
        return self._finish(parse_json(text), usage_from_gemini(body.get("usageMetadata")))
