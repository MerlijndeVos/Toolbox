"""Persistent user settings stored in the app data directory."""

from __future__ import annotations

import json
from typing import Any

from .runtime import app_data_dir

_DEFAULTS: dict[str, Any] = {
    "file_logging": True,
    # AI provider choice and per-provider keys live under "ai" (see core/ai/config.py).
    # Ids of user-installed mods the user has turned on (built-in features are always on).
    "enabled_mods": [],
    # Appearance: the id of the active theme mod (see core/mods/theme.py) and light/dark/system.
    "theme": "theme-default",
    "color_mode": "system",
    # Syntax highlighting of code and log previews, and its colour scheme ("theme" follows the theme).
    "syntax_code": True,
    "syntax_logs": True,
    "syntax_scheme": "theme",
    # Offer the rolling experimental build of the production branch as an update.
    "experimental_updates": False,
}


def _settings_path():
    return app_data_dir() / "settings.json"


def load_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.is_file():
        return dict(_DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(_DEFAULTS)
        return {**_DEFAULTS, **data}
    except Exception:
        return dict(_DEFAULTS)


def save_settings(**updates: Any) -> dict[str, Any]:
    current = load_settings()
    current.update(updates)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current
