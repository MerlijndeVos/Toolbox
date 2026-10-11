"""AI providers behind one interface.

Features call :func:`get_provider` and then ``provider.complete_json(messages, ...)``.
They never touch an SDK or an HTTP API themselves, so adding a provider means adding
one adapter here.
"""

from __future__ import annotations

from typing import Any, Optional

from . import usage
from .anthropic_provider import AnthropicProvider
from .claude_code_provider import ClaudeCodeProvider
from .base import (
    AiConfigError,
    AiError,
    InvalidJsonError,
    JsonResult,
    Message,
    Provider,
    parse_json,
)
from .config import (
    DEFAULT_PROVIDER,
    PROVIDERS,
    ProviderSpec,
    ResolvedProvider,
    normalize_base_url,
    resolve_provider,
    save_ai_settings,
    stored_ai_settings,
    validate,
)
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAiProvider

__all__ = [
    "AiConfigError",
    "AiError",
    "DEFAULT_PROVIDER",
    "InvalidJsonError",
    "JsonResult",
    "Message",
    "PROVIDERS",
    "Provider",
    "ProviderSpec",
    "ResolvedProvider",
    "build_provider",
    "get_provider",
    "parse_json",
    "usage",
    "resolve_model",
    "resolve_provider",
    "save_ai_settings",
    "stored_ai_settings",
    "check_connection",
]


def build_provider(resolved: ResolvedProvider, *, http_client: Any = None) -> Provider:
    """Create the adapter for already-resolved settings. Raises :class:`AiConfigError`."""
    validate(resolved)
    kwargs = dict(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        http_client=http_client,
    )
    if resolved.id == "anthropic":
        provider: Provider = AnthropicProvider(**kwargs)
    elif resolved.id == "gemini":
        provider = GeminiProvider(**kwargs)
    elif resolved.id == "claude_subscription":
        provider = ClaudeCodeProvider(**kwargs)
    else:
        provider = OpenAiProvider(label=resolved.spec.label, **kwargs)
    provider.provider_id = resolved.id
    return provider


def get_provider(model: Optional[str] = None, *, http_client: Any = None) -> Provider:
    """The provider selected in settings. ``model`` overrides the saved model id."""
    return build_provider(resolve_provider(overrides={"model": model or ""}), http_client=http_client)


def resolve_model(explicit: Optional[str] = None) -> str:
    """The model id that would be used, without needing a key (for dry runs and logs)."""
    return explicit or resolve_provider().model


def check_connection(
    provider_id: Optional[str] = None,
    *,
    overrides: Optional[dict[str, str]] = None,
    http_client: Any = None,
) -> str:
    """Make a tiny JSON request and return a success message. Raises :class:`AiError`."""
    resolved = resolve_provider(provider_id, overrides=overrides)
    provider = build_provider(resolved, http_client=http_client)
    messages = [
        {"role": "system", "content": 'Reply with the JSON object {"ok": true}.'},
        {"role": "user", "content": "ping"},
    ]
    try:
        with usage.feature("Connection test"):
            provider.complete_json(messages)
    except InvalidJsonError as exc:
        raise AiError(
            f"Connected to {resolved.spec.label}, but {resolved.model} did not answer with valid JSON, "
            "which Toolbox needs. Try a more capable model."
        ) from exc
    return f"Connected: {resolved.spec.label} answered using {resolved.model}."
