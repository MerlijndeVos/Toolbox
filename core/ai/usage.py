"""Token usage: what each AI call cost, kept in a small local ledger for the usage window.

Providers attach a :class:`Usage` to the :class:`~core.ai.base.JsonResult` they return and
call :func:`record`. Features wrap their work in ``with usage.feature("Subtitle translation")``
so the window can say what the tokens were spent on.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Iterator, Optional

MAX_EVENTS = 5000
DAY = 86400

_feature: contextvars.ContextVar[str] = contextvars.ContextVar("ai_feature", default="Other")
_lock = threading.Lock()


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Only set when the backend reports a price (the Claude subscription CLI does).
    cost_usd: Optional[float] = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def usage_from_openai(raw: Any) -> Optional[Usage]:
    if raw is None:
        return None
    return Usage(
        input_tokens=_int(getattr(raw, "prompt_tokens", 0)),
        output_tokens=_int(getattr(raw, "completion_tokens", 0)),
    )


def usage_from_anthropic(raw: Any) -> Optional[Usage]:
    if not isinstance(raw, dict):
        return None
    cost = raw.get("cost_usd")
    return Usage(
        input_tokens=_int(raw.get("input_tokens")),
        output_tokens=_int(raw.get("output_tokens")),
        cache_read_tokens=_int(raw.get("cache_read_input_tokens")),
        cache_write_tokens=_int(raw.get("cache_creation_input_tokens")),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
    )


def usage_from_gemini(raw: Any) -> Optional[Usage]:
    if not isinstance(raw, dict):
        return None
    return Usage(
        input_tokens=_int(raw.get("promptTokenCount")),
        output_tokens=_int(raw.get("candidatesTokenCount")) + _int(raw.get("thoughtsTokenCount")),
        cache_read_tokens=_int(raw.get("cachedContentTokenCount")),
    )


@contextlib.contextmanager
def feature(name: str) -> Iterator[None]:
    """Label the AI calls made inside the block."""
    token = _feature.set(name)
    try:
        yield
    finally:
        _feature.reset(token)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def _path():
    from ..runtime import app_data_dir

    return app_data_dir() / "ai_usage.json"


def _load() -> list[dict]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def record(provider_id: str, model: str, usage: Optional[Usage], *, label: str = "") -> None:
    """Append one call. Never raises: usage tracking must not break a translation."""
    if usage is None:
        return
    event = {
        "ts": time.time(),
        "provider": provider_id,
        "label": label or provider_id,
        "model": model,
        "feature": _feature.get(),
        **asdict(usage),
    }
    try:
        with _lock:
            events = _load()
            events.append(event)
            path = _path()
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(events[-MAX_EVENTS:]), encoding="utf-8")
            tmp.replace(path)
    except OSError:
        pass


def _limits_path():
    from ..runtime import app_data_dir

    return app_data_dir() / "claude_limits.json"


def record_limits(info: Any) -> None:
    """Keep the plan windows the Claude CLI reports (``rate_limit_event``). Never raises."""
    if not isinstance(info, dict):
        return
    windows: dict[str, dict[str, Any]] = {}
    raw = info.get("unifiedWindows")
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict) and isinstance(value.get("utilization"), (int, float)):
                windows[str(name)] = {
                    "utilization": float(value["utilization"]),
                    "resets_at": value.get("resetsAt"),
                }
    if not windows and isinstance(info.get("utilization"), (int, float)):
        windows[str(info.get("rateLimitType") or "five_hour")] = {
            "utilization": float(info["utilization"]),
            "resets_at": info.get("resetsAt"),
        }
    payload = {
        "updated": time.time(),
        "status": str(info.get("status") or ""),
        "limit_type": str(info.get("rateLimitType") or ""),
        "windows": windows,
    }
    try:
        with _lock:
            path = _limits_path()
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
    except OSError:
        pass


def limits() -> Optional[dict[str, Any]]:
    try:
        data = json.loads(_limits_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear() -> None:
    try:
        with _lock:
            _path().write_text("[]", encoding="utf-8")
    except OSError:
        pass


def _totals(events: list[dict]) -> dict[str, Any]:
    cost = [e["cost_usd"] for e in events if isinstance(e.get("cost_usd"), (int, float))]
    return {
        "calls": len(events),
        "input_tokens": sum(_int(e.get("input_tokens")) for e in events),
        "output_tokens": sum(_int(e.get("output_tokens")) for e in events),
        "cache_tokens": sum(_int(e.get("cache_read_tokens")) + _int(e.get("cache_write_tokens")) for e in events),
        "cost_usd": round(sum(cost), 4) if cost else None,
    }


def _group(events: list[dict], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict]] = {}
    for event in events:
        groups.setdefault(str(event.get(key) or "Other"), []).append(event)
    rows = [{"name": name, **_totals(items)} for name, items in groups.items()]
    rows.sort(key=lambda r: r["input_tokens"] + r["output_tokens"], reverse=True)
    return rows


def summary(now: Optional[float] = None) -> dict[str, Any]:
    """Everything the usage window shows."""
    now = now if now is not None else time.time()
    events = _load()
    today = [e for e in events if now - float(e.get("ts", 0)) < DAY]
    week = [e for e in events if now - float(e.get("ts", 0)) < 7 * DAY]
    days: list[dict[str, Any]] = []
    for back in range(6, -1, -1):
        lo, hi = now - (back + 1) * DAY, now - back * DAY
        bucket = [e for e in events if lo <= float(e.get("ts", 0)) < hi]
        days.append({"start": lo, **_totals(bucket)})
    return {
        "today": _totals(today),
        "week": _totals(week),
        "all": _totals(events),
        "days": days,
        "limits": limits(),
        "by_model": _group(week, "model"),
        "by_feature": _group(week, "feature"),
        "recent": [
            {k: e.get(k) for k in ("ts", "label", "model", "feature", "input_tokens", "output_tokens", "cost_usd")}
            for e in reversed(events[-30:])
        ],
    }
