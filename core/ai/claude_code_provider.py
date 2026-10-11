"""Claude through a Claude subscription (Pro/Max), by running the local Claude Code CLI.

No API key and no per-token bill: the ``claude`` program does the call with the login it
already has (``claude`` then ``/login``), or with a token from ``claude setup-token`` that
is passed on as ``CLAUDE_CODE_OAUTH_TOKEN``. Toolbox only runs the official CLI; it never
reads its credentials.

Each call is a one-shot, tool-less ``claude -p`` in an empty working folder. The CLI's
stream also carries the plan's 5-hour and weekly windows, which are kept for the usage view.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from ..subprocess_utils import no_window_kwargs
from . import usage as usage_ledger
from .base import (
    AiConfigError,
    AiError,
    JsonResult,
    Message,
    Provider,
    parse_json,
    split_system,
    with_json_instruction,
)
from .usage import usage_from_anthropic

CALL_TIMEOUT = 240.0
# A command line is limited on Windows (about 32k); longer system prompts go to stdin.
MAX_SYSTEM_ARG = 6000
_FALLBACK_SYSTEM = "You are a precise assistant. Follow the instructions in the user message exactly."

LOGIN_HINT = (
    "Claude Code is not signed in. Run `claude` once in a terminal and use /login, "
    "or run `claude setup-token` and paste the token in AI settings."
)


def find_claude() -> Optional[str]:
    return shutil.which("claude")


def _workdir() -> str:
    """An empty folder to run in, so no project CLAUDE.md or settings are picked up.

    The system temp folder is used rather than the app data folder: a sandboxed or packaged
    Python can see a different AppData than the ``claude`` program does.
    """
    path = Path(tempfile.gettempdir()) / "toolbox-claude"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _looks_unauthenticated(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in ("not logged in", "please run /login", "invalid api key", "authentication", "oauth token", "/login")
    )


class ClaudeCodeProvider(Provider):
    label = "Claude subscription"
    provider_id = "claude_subscription"

    def complete_json(self, messages: list[Message], *, temperature: float = 0.0) -> JsonResult:
        exe = find_claude()
        if not exe:
            raise AiConfigError(
                "Claude subscription: the `claude` command was not found. Install Claude Code "
                "(https://claude.com/claude-code) and sign in, then try again."
            )

        system, turns = split_system(with_json_instruction(messages))
        user = "\n\n".join(t["content"] for t in turns)
        args = [
            exe,
            "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--model", self.model,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            "--disable-slash-commands",
        ]
        if system and len(system) <= MAX_SYSTEM_ARG:
            args += ["--system-prompt", system]
            stdin = user
        else:
            args += ["--system-prompt", _FALLBACK_SYSTEM]
            stdin = f"{system}\n\n{user}" if system else user

        env = dict(os.environ)
        # An API key in the environment would make the CLI bill the API instead of the plan.
        for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
            env.pop(name, None)
        if self.api_key:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.api_key

        try:
            proc = subprocess.run(
                args,
                input=stdin.encode("utf-8"),
                capture_output=True,
                cwd=_workdir(),
                env=env,
                timeout=CALL_TIMEOUT,
                **no_window_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise AiError("Claude took too long to answer. A busy plan may need another try.") from exc
        except OSError as exc:
            raise AiError(f"Could not start Claude Code: {exc}") from exc

        stdout = proc.stdout.decode("utf-8", errors="replace")
        result: Optional[dict[str, Any]] = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "rate_limit_event":
                usage_ledger.record_limits(event.get("rate_limit_info"))
            elif event.get("type") == "result":
                result = event

        if result is None:
            detail = (proc.stderr.decode("utf-8", errors="replace") or stdout).strip()
            if _looks_unauthenticated(detail):
                raise AiError(LOGIN_HINT)
            raise AiError(f"Claude Code gave no answer (exit {proc.returncode}). {detail[:300]}".strip())

        text = str(result.get("result") or "")
        if result.get("is_error") or result.get("subtype") not in (None, "success"):
            if _looks_unauthenticated(text):
                raise AiError(LOGIN_HINT)
            if "limit" in text.lower():
                raise AiError(f"Your Claude plan is at its limit: {text[:300]}")
            raise AiError(f"Claude Code reported an error: {text[:300] or result.get('subtype')}")

        raw_usage = dict(result.get("usage") or {})
        cost = result.get("total_cost_usd")
        if isinstance(cost, (int, float)):
            raw_usage["cost_usd"] = float(cost)
        return self._finish(parse_json(text), usage_from_anthropic(raw_usage))
