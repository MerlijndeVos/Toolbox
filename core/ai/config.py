"""AI provider settings: what is stored, what the environment adds, and the legacy layout.

Stored in ``settings.json`` as::

    "ai": {"provider": "openai",
           "providers": {"openai": {"api_key": "", "model": ""},
                         "openai_compatible": {"base_url": "", "api_key": "", "model": ""},
                         "anthropic": {...}, "gemini": {...}}}

Settings written before providers existed used flat ``openai_api_key`` / ``openai_model``
keys. Those are read while no ``ai`` block exists, and moved into it on the first save.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from ..settings_store import load_settings, save_settings
from .base import AiConfigError


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    default_model: str
    env_vars: tuple[str, ...] = ()
    needs_base_url: bool = False
    needs_key: bool = True


PROVIDERS: dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (
        ProviderSpec("openai", "OpenAI", "gpt-4o-mini", ("OPENAI_API_KEY",)),
        ProviderSpec("openai_compatible", "OpenAI-compatible", "", needs_base_url=True, needs_key=False),
        ProviderSpec("anthropic", "Anthropic (Claude)", "claude-haiku-4-5-20251001", ("ANTHROPIC_API_KEY",)),
        ProviderSpec("gemini", "Google Gemini", "gemini-flash-latest", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
        # Runs the local Claude Code CLI. The "key" is an optional `claude setup-token` token.
        ProviderSpec(
            "claude_subscription",
            "Claude subscription",
            "sonnet",
            ("CLAUDE_CODE_OAUTH_TOKEN",),
            needs_key=False,
        ),
    )
}
DEFAULT_PROVIDER = "openai"

_FIELDS = ("api_key", "model", "base_url")


@dataclass(frozen=True)
class ResolvedProvider:
    """One provider's effective settings (stored values, plus env var and defaults)."""

    id: str
    api_key: str
    model: str
    base_url: str
    key_from_env: bool

    @property
    def spec(self) -> ProviderSpec:
        return PROVIDERS[self.id]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def stored_ai_settings() -> dict[str, Any]:
    """The saved settings as ``{"provider", "providers": {id: {api_key, model, base_url}}}``."""
    settings = load_settings()
    raw = settings.get("ai")
    has_block = isinstance(raw, dict)
    raw = raw if has_block else {}
    raw_providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}

    providers: dict[str, dict[str, str]] = {}
    for pid in PROVIDERS:
        entry = raw_providers.get(pid)
        entry = entry if isinstance(entry, dict) else {}
        providers[pid] = {f: _clean(entry.get(f)) for f in _FIELDS}

    if not has_block:
        providers["openai"]["api_key"] = _clean(settings.get("openai_api_key"))
        providers["openai"]["model"] = _clean(settings.get("openai_model"))

    provider = _clean(raw.get("provider"))
    return {"provider": provider if provider in PROVIDERS else DEFAULT_PROVIDER, "providers": providers}


def save_ai_settings(
    *,
    provider: Optional[str] = None,
    providers: Optional[dict[str, dict[str, Optional[str]]]] = None,
) -> None:
    """Merge an update into the saved settings. Fields left out (or ``None``) are kept."""
    current = stored_ai_settings()
    if provider is not None:
        if provider not in PROVIDERS:
            raise AiConfigError(f"Unknown AI provider: {provider!r}.")
        current["provider"] = provider
    for pid, fields in (providers or {}).items():
        if pid not in PROVIDERS:
            raise AiConfigError(f"Unknown AI provider: {pid!r}.")
        for name, value in fields.items():
            if name in _FIELDS and value is not None:
                current["providers"][pid][name] = _clean(value)

    updates: dict[str, Any] = {"ai": current}
    if "ai" not in load_settings():
        # First save in the new layout: the key now lives under "ai" only.
        updates.update(openai_api_key="", openai_model="")
    save_settings(**updates)


def normalize_base_url(url: str) -> str:
    """Trim the address and add ``/v1`` when only a host was given (``http://localhost:11434``)."""
    url = _clean(url)
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/v1"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def resolve_provider(provider_id: Optional[str] = None, *, overrides: Optional[dict[str, str]] = None) -> ResolvedProvider:
    """Effective settings for a provider (default: the selected one).

    ``overrides`` (api_key/model/base_url) win over saved values when non-blank; used by
    "Test connection" to try unsaved form values.
    """
    stored = stored_ai_settings()
    pid = provider_id or stored["provider"]
    if pid not in PROVIDERS:
        raise AiConfigError(f"Unknown AI provider: {pid!r}.")
    spec = PROVIDERS[pid]
    values = dict(stored["providers"][pid])
    for name, value in (overrides or {}).items():
        if name in _FIELDS and _clean(value):
            values[name] = _clean(value)

    api_key = values["api_key"]
    from_env = False
    if not api_key:
        for var in spec.env_vars:
            api_key = _clean(os.environ.get(var))
            if api_key:
                from_env = True
                break

    return ResolvedProvider(
        id=pid,
        api_key=api_key,
        model=values["model"] or spec.default_model,
        base_url=normalize_base_url(values["base_url"]) if spec.needs_base_url else "",
        key_from_env=from_env,
    )


def validate(resolved: ResolvedProvider) -> None:
    """Raise :class:`AiConfigError` unless *resolved* has everything a call needs."""
    spec = resolved.spec
    if spec.needs_base_url and not resolved.base_url:
        raise AiConfigError(f"{spec.label}: set the base URL in AI settings (for example http://localhost:11434/v1).")
    if resolved.id == "claude_subscription":
        from .claude_code_provider import find_claude

        if not find_claude():
            raise AiConfigError(
                "Claude subscription: the `claude` command was not found. Install Claude Code "
                "and sign in with /login, then try again."
            )
    if spec.needs_key and not resolved.api_key:
        env = f" or set {spec.env_vars[0]}" if spec.env_vars else ""
        raise AiConfigError(f"{spec.label}: no API key configured. Add it in AI settings{env}.")
    if not resolved.model:
        raise AiConfigError(f"{spec.label}: set a model id in AI settings.")
