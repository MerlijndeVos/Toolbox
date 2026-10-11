"""Provider-independent pieces: the adapter interface, errors and JSON handling."""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

from . import usage as usage_ledger
from .usage import Usage

Message = dict  # {"role": "system" | "user" | "assistant", "content": str}

JSON_ONLY_INSTRUCTION = (
    "Respond with a single valid JSON object and nothing else: no prose, no code fences."
)

# Local models can be slow; connecting should still fail fast.
REQUEST_TIMEOUT = httpx.Timeout(180.0, connect=15.0)
MAX_RETRIES = 2
MAX_RETRY_DELAY = 30.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 529})


class AiError(RuntimeError):
    """A failed AI call, with a message that is fine to show the user as-is."""


class AiConfigError(AiError, ValueError):
    """The AI settings are incomplete (no key, no model, no base URL...)."""


class InvalidJsonError(AiError):
    """The model answered, but not with usable JSON."""

    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


@dataclass(frozen=True)
class JsonResult:
    """``text`` is what the model said (handy for chat history); ``data`` is it parsed."""

    text: str
    data: Any
    usage: Optional[Usage] = None


class Provider(ABC):
    """One AI backend. Both features talk to this and nothing else."""

    label = "AI provider"
    provider_id = ""

    def __init__(
        self,
        *,
        model: str,
        api_key: str = "",
        base_url: str = "",
        http_client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http_client = http_client
        self._sleep = sleep

    @abstractmethod
    def complete_json(self, messages: list[Message], *, temperature: float = 0.0) -> JsonResult:
        """Send a chat and return the model's JSON reply.

        ``messages`` is a list of ``{"role", "content"}`` dicts, system first. Raises
        :class:`AiError` (readable message) on any failure.
        """


    def _finish(self, result: JsonResult, usage: Optional[Usage]) -> JsonResult:
        """Attach the call's usage to the result and add it to the ledger."""
        usage_ledger.record(self.provider_id or self.label.lower(), self.model, usage, label=self.label)
        return JsonResult(text=result.text, data=result.data, usage=usage)


# ---------------------------------------------------------------------------
# JSON handling
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_json(text: str) -> JsonResult:
    """Parse a model reply that should be JSON but may be wrapped in chatter.

    Handles code fences, reasoning-model ``<think>`` blocks and prose around the
    object. Raises :class:`InvalidJsonError` if nothing parses.
    """
    raw = text or ""
    cleaned = _THINK_RE.sub("", raw).strip()
    candidates = [cleaned]
    fenced = _FENCE_RE.search(cleaned)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())

    for candidate in candidates:
        try:
            return JsonResult(text=raw, data=json.loads(candidate))
        except (json.JSONDecodeError, ValueError):
            pass
        found = _first_json_value(candidate)
        if found is not None:
            return JsonResult(text=raw, data=found)

    preview = cleaned[:200] or "(empty reply)"
    raise InvalidJsonError(f"The model did not return valid JSON: {preview}", raw)


def _first_json_value(text: str) -> Any:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[{\[]", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return value
    return None


def with_json_instruction(messages: list[Message]) -> list[Message]:
    """Copy of *messages* with the JSON-only instruction added to the system prompt."""
    out = [dict(m) for m in messages]
    if out and out[0].get("role") == "system":
        out[0]["content"] = f"{out[0]['content']}\n\n{JSON_ONLY_INSTRUCTION}"
    else:
        out.insert(0, {"role": "system", "content": JSON_ONLY_INSTRUCTION})
    return out


def split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    """Separate system text from the chat turns, merging adjacent same-role turns.

    Anthropic and Gemini take the system prompt outside the message list and insist
    that turns alternate.
    """
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    turns: list[Message] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n\n" + m["content"]
        else:
            turns.append({"role": role, "content": m["content"]})
    return "\n\n".join(system_parts), turns


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def describe_status(label: str, status: int, detail: str = "", *, has_base_url: bool = False) -> str:
    """Readable text for an HTTP failure. ``detail`` is the API's own message, if any."""
    detail = (detail or "").strip()
    # Gemini reports a bad key as 400 rather than 401.
    if status == 400 and "api key" in detail.lower():
        status = 401
    if status == 401:
        text = f"{label} rejected the API key (401). Check the key in AI settings."
    elif status == 403:
        text = f"{label} refused the request (403). The key may not have access to this model."
    elif status == 404:
        where = "model id and base URL" if has_base_url else "model id"
        text = f"{label} could not find that model or endpoint (404). Check the {where}."
    elif status == 429:
        text = f"{label} rate limit or quota reached (429). Wait a moment, or check your plan and billing."
    elif status >= 500:
        text = f"{label} is having problems (HTTP {status}). Try again later."
    else:
        text = f"{label} returned an error (HTTP {status})."
    if detail:
        text += f" {detail[:300]}"
    return text


def unreachable_message(label: str, base_url: str) -> str:
    target = base_url or label
    return f"Could not reach {target}. Check your internet connection, and that the server is running and the address is right."


def timeout_message(label: str) -> str:
    return f"{label} took too long to answer. A slow or overloaded model may need another try."


def error_detail(response: httpx.Response) -> str:
    """The ``error.message`` all three APIs put in their error bodies."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or "")
    if isinstance(error, str):
        return error
    return ""


# ---------------------------------------------------------------------------
# Plain-HTTPS transport for the native adapters
# ---------------------------------------------------------------------------

class HttpProvider(Provider):
    """Base for adapters that speak HTTPS directly instead of using an SDK."""

    def _post(self, url: str, *, headers: dict[str, str], payload: dict) -> dict:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._send(url, headers, payload)
            except httpx.TimeoutException as exc:
                raise AiError(timeout_message(self.label)) from exc
            except httpx.TransportError as exc:
                raise AiError(unreachable_message(self.label, self.base_url)) from exc

            if response.status_code < 400:
                try:
                    body = response.json()
                except ValueError as exc:
                    raise AiError(f"{self.label} sent a reply that is not JSON.") from exc
                if not isinstance(body, dict):
                    raise AiError(f"{self.label} sent an unexpected reply.")
                return body

            if response.status_code in _RETRY_STATUSES and attempt < MAX_RETRIES:
                self._sleep(_retry_delay(response, attempt))
                continue
            raise AiError(describe_status(self.label, response.status_code, error_detail(response)))
        raise AssertionError("unreachable")  # pragma: no cover

    def _send(self, url: str, headers: dict[str, str], payload: dict) -> httpx.Response:
        if self._http_client is not None:
            return self._http_client.post(url, headers=headers, json=payload)
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            return client.post(url, headers=headers, json=payload)


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    try:
        wanted = float(response.headers.get("retry-after", ""))
    except ValueError:
        wanted = 2.0 * (attempt + 1)
    return max(0.0, min(wanted, MAX_RETRY_DELAY))
