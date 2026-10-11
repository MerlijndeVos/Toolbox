"""AI usage ledger and the Claude subscription provider (Claude Code CLI)."""

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from core.ai import AiConfigError, AiError, InvalidJsonError, usage
from core.ai.claude_code_provider import ClaudeCodeProvider


def stream(*events):
    return "\n".join(json.dumps(e) for e in events).encode("utf-8")


RATE = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "rateLimitType": "five_hour",
        "unifiedWindows": {
            "five_hour": {"utilization": 0.15, "resetsAt": 1791750000},
            "seven_day": {"utilization": 0.69, "resetsAt": 1791878400},
        },
    },
}


def result(text, **extra):
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "total_cost_usd": 0.002,
        "usage": {"input_tokens": 3, "output_tokens": 9, "cache_creation_input_tokens": 700, "cache_read_input_tokens": 0},
        **extra,
    }


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch("core.runtime.app_data_dir", return_value=Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_record_and_summarise_by_feature_and_model(self):
        with usage.feature("Subtitle translation"):
            usage.record("openai", "gpt-4o-mini", usage.Usage(100, 50), label="OpenAI")
            usage.record("openai", "gpt-4o-mini", usage.Usage(10, 5), label="OpenAI")
        usage.record("anthropic", "claude", usage.Usage(1, 1, cost_usd=0.5), label="Anthropic")
        summary = usage.summary()
        self.assertEqual(summary["today"]["calls"], 3)
        self.assertEqual(summary["all"]["input_tokens"], 111)
        self.assertEqual(summary["by_feature"][0]["name"], "Subtitle translation")
        self.assertEqual(summary["by_feature"][0]["calls"], 2)
        self.assertEqual(summary["all"]["cost_usd"], 0.5)
        self.assertEqual(len(summary["days"]), 7)

    def test_old_events_leave_today_but_stay_in_week(self):
        usage.record("openai", "m", usage.Usage(1, 1))
        later = time.time() + 2 * usage.DAY
        summary = usage.summary(now=later)
        self.assertEqual(summary["today"]["calls"], 0)
        self.assertEqual(summary["week"]["calls"], 1)

    def test_limits_are_kept(self):
        usage.record_limits(RATE["rate_limit_info"])
        info = usage.limits()
        self.assertEqual(info["windows"]["seven_day"]["utilization"], 0.69)
        self.assertEqual(usage.summary()["limits"]["status"], "allowed")

    def test_clear_empties_the_ledger(self):
        usage.record("openai", "m", usage.Usage(1, 1))
        usage.clear()
        self.assertEqual(usage.summary()["all"]["calls"], 0)


class ClaudeCodeProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in (
            ("core.runtime.app_data_dir", Path(self.tmp.name)),
            ("core.ai.claude_code_provider.find_claude", "claude"),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_provider(self, stdout, returncode=0, **kw):
        provider = ClaudeCodeProvider(model="sonnet", **kw)
        completed = subprocess.CompletedProcess([], returncode, stdout, b"")
        with mock.patch("core.ai.claude_code_provider.subprocess.run", return_value=completed) as run:
            out = provider.complete_json(
                [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]
            )
        return out, run

    def test_reads_result_usage_and_limits(self):
        out, run = self.run_provider(stream(RATE, result('{"ok": true}')))
        self.assertEqual(out.data, {"ok": True})
        self.assertEqual(out.usage.output_tokens, 9)
        self.assertEqual(out.usage.cache_write_tokens, 700)
        self.assertEqual(out.usage.cost_usd, 0.002)
        self.assertEqual(usage.limits()["windows"]["five_hour"]["utilization"], 0.15)
        args = run.call_args.args[0]
        self.assertIn("--tools", args)
        self.assertEqual(args[args.index("--model") + 1], "sonnet")
        self.assertEqual(usage.summary()["all"]["calls"], 1)

    def test_api_key_in_environment_is_not_passed_on(self):
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-secret"}):
            _out, run = self.run_provider(stream(result("{}")), api_key="oauth-token")
        env = run.call_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "oauth-token")

    def test_not_signed_in_gives_a_login_hint(self):
        bad = result("Invalid API key. Please run /login", is_error=True)
        with self.assertRaisesRegex(AiError, "not signed in"):
            self.run_provider(stream(bad))

    def test_plan_limit_message(self):
        bad = result("Claude usage limit reached|1790000000", is_error=True)
        with self.assertRaisesRegex(AiError, "plan is at its limit"):
            self.run_provider(stream(bad))

    def test_unusable_text_is_invalid_json(self):
        with self.assertRaises(InvalidJsonError):
            self.run_provider(stream(result("sorry, no")))

    def test_missing_cli(self):
        with mock.patch("core.ai.claude_code_provider.find_claude", return_value=None):
            with self.assertRaises(AiConfigError):
                ClaudeCodeProvider(model="sonnet").complete_json([{"role": "user", "content": "x"}])


if __name__ == "__main__":
    unittest.main()
