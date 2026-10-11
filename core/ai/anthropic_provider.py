"""Anthropic (Claude) over the native Messages API."""

from __future__ import annotations

import json

from .base import AiError, HttpProvider, JsonResult, Message, parse_json, split_system
from .usage import usage_from_anthropic

DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
# Required by the API. Generous: a translation batch is a couple of thousand tokens.
MAX_OUTPUT_TOKENS = 8192

_TOOL_NAME = "reply"


class AnthropicProvider(HttpProvider):
    label = "Anthropic"

    def complete_json(self, messages: list[Message], *, temperature: float = 0.0) -> JsonResult:
        system, turns = split_system(messages)
        payload = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "temperature": temperature,
            "messages": turns,
            # There is no JSON mode. Forcing a tool call makes the model hand back a
            # JSON object as the tool's input, which needs no text parsing.
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": "Send your reply. The input is the JSON object that was asked for.",
                    "input_schema": {"type": "object"},
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }
        if system:
            payload["system"] = system

        body = self._post(
            f"{self.base_url or DEFAULT_BASE_URL}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            payload=payload,
        )

        blocks = body.get("content") or []
        for block in blocks:
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                result = JsonResult(text=json.dumps(block["input"], ensure_ascii=False), data=block["input"])
                return self._finish(result, usage_from_anthropic(body.get("usage")))

        if body.get("stop_reason") == "max_tokens":
            raise AiError("The reply was cut off (token limit). Try a model with a larger output limit.")
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return self._finish(parse_json(text), usage_from_anthropic(body.get("usage")))
