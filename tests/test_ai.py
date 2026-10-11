"""Tests for the AI provider layer (no network: HTTP is faked with httpx.MockTransport).

Run with::

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import ai, settings_store  # noqa: E402
from core.ai import openai_provider  # noqa: E402
from core.ai.base import (  # noqa: E402
    AiConfigError,
    AiError,
    InvalidJsonError,
    JsonResult,
    describe_status,
    parse_json,
    split_system,
    with_json_instruction,
)
from core.ai.config import normalize_base_url  # noqa: E402

SECRET = "sk-secret-value"
MESSAGES = [
    {"role": "system", "content": "You translate."},
    {"role": "user", "content": "Hello"},
]


def client_for(handler) -> tuple[httpx.Client, list[httpx.Request]]:
    """An httpx client whose server is *handler*; also returns the requests it saw."""
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), seen


def body_of(request: httpx.Request) -> dict:
    return json.loads(request.content)


class ParseJsonTests(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(parse_json('{"a": 1}').data, {"a": 1})

    def test_code_fence(self):
        self.assertEqual(parse_json('Sure!\n```json\n{"a": 1}\n```').data, {"a": 1})

    def test_prose_around_object(self):
        self.assertEqual(parse_json('Here you go: {"a": {"b": 2}} Hope that helps.').data, {"a": {"b": 2}})

    def test_reasoning_block_is_ignored(self):
        self.assertEqual(parse_json('<think>maybe {"x": 0}</think>{"a": 1}').data, {"a": 1})

    def test_list(self):
        self.assertEqual(parse_json('[{"id": 1}]').data, [{"id": 1}])

    def test_keeps_original_text(self):
        raw = 'ok {"a": 1}'
        self.assertEqual(parse_json(raw).text, raw)

    def test_garbage_raises_with_preview(self):
        with self.assertRaises(InvalidJsonError) as ctx:
            parse_json("I cannot do that.")
        self.assertIn("I cannot do that.", str(ctx.exception))
        self.assertEqual(ctx.exception.raw, "I cannot do that.")

    def test_empty_raises(self):
        with self.assertRaises(InvalidJsonError):
            parse_json("")


class MessageHelperTests(unittest.TestCase):
    def test_split_system_merges_same_role_turns(self):
        system, turns = split_system(
            [
                {"role": "system", "content": "A"},
                {"role": "user", "content": "one"},
                {"role": "user", "content": "two"},
                {"role": "assistant", "content": "x"},
            ]
        )
        self.assertEqual(system, "A")
        self.assertEqual(turns, [{"role": "user", "content": "one\n\ntwo"}, {"role": "assistant", "content": "x"}])

    def test_json_instruction_extends_system_prompt_without_mutating(self):
        out = with_json_instruction(MESSAGES)
        self.assertIn("JSON", out[0]["content"])
        self.assertTrue(out[0]["content"].startswith("You translate."))
        self.assertEqual(MESSAGES[0]["content"], "You translate.")

    def test_json_instruction_added_when_no_system_prompt(self):
        out = with_json_instruction([{"role": "user", "content": "hi"}])
        self.assertEqual([m["role"] for m in out], ["system", "user"])

    def test_status_messages(self):
        self.assertIn("rejected the API key", describe_status("X", 401))
        self.assertIn("rate limit", describe_status("X", 429))
        self.assertIn("having problems", describe_status("X", 503))
        self.assertIn("model id and base URL", describe_status("X", 404, has_base_url=True))
        self.assertIn("API key not valid", describe_status("X", 400, "API key not valid."))
        # Gemini reports a bad key as 400.
        self.assertIn("rejected the API key", describe_status("X", 400, "API key not valid."))


class AnthropicTests(unittest.TestCase):
    def provider(self, handler):
        http, seen = client_for(handler)
        sleeps: list[float] = []
        provider = ai.AnthropicProvider(
            model="claude-test", api_key=SECRET, http_client=http, sleep=sleeps.append
        )
        return provider, seen, sleeps

    def test_request_shape_and_tool_result(self):
        def handler(request):
            return httpx.Response(
                200, json={"content": [{"type": "tool_use", "name": "reply", "input": {"translations": []}}]}
            )

        provider, seen, _ = self.provider(handler)
        result = provider.complete_json(MESSAGES, temperature=0.15)

        self.assertEqual(result.data, {"translations": []})
        self.assertEqual(json.loads(result.text), {"translations": []})
        request = seen[0]
        self.assertEqual(str(request.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.headers["x-api-key"], SECRET)
        self.assertIn("anthropic-version", request.headers)
        body = body_of(request)
        self.assertEqual(body["system"], "You translate.")
        self.assertEqual(body["messages"], [{"role": "user", "content": "Hello"}])
        self.assertGreater(body["max_tokens"], 0)
        self.assertEqual(body["temperature"], 0.15)
        self.assertEqual(body["tool_choice"], {"type": "tool", "name": "reply"})

    def test_falls_back_to_text_reply(self):
        provider, _, _ = self.provider(
            lambda r: httpx.Response(200, json={"content": [{"type": "text", "text": 'Sure: {"a": 1}'}]})
        )
        self.assertEqual(provider.complete_json(MESSAGES).data, {"a": 1})

    def test_truncated_reply(self):
        provider, _, _ = self.provider(
            lambda r: httpx.Response(200, json={"content": [], "stop_reason": "max_tokens"})
        )
        with self.assertRaisesRegex(AiError, "cut off"):
            provider.complete_json(MESSAGES)

    def test_auth_error_is_readable_and_does_not_leak_key(self):
        provider, _, _ = self.provider(
            lambda r: httpx.Response(401, json={"error": {"type": "authentication_error", "message": "invalid x-api-key"}})
        )
        with self.assertRaises(AiError) as ctx:
            provider.complete_json(MESSAGES)
        self.assertIn("rejected the API key", str(ctx.exception))
        self.assertIn("invalid x-api-key", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_retries_rate_limit_using_retry_after(self):
        replies = [
            httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}}),
            httpx.Response(200, json={"content": [{"type": "tool_use", "input": {"ok": True}}]}),
        ]
        provider, seen, sleeps = self.provider(lambda r: replies.pop(0))
        self.assertEqual(provider.complete_json(MESSAGES).data, {"ok": True})
        self.assertEqual(len(seen), 2)
        self.assertEqual(sleeps, [7.0])

    def test_gives_up_after_retries(self):
        provider, seen, sleeps = self.provider(lambda r: httpx.Response(529, json={"error": {"message": "overloaded"}}))
        with self.assertRaisesRegex(AiError, "having problems"):
            provider.complete_json(MESSAGES)
        self.assertEqual(len(seen), 3)
        self.assertEqual(len(sleeps), 2)

    def test_does_not_retry_client_errors(self):
        provider, seen, _ = self.provider(lambda r: httpx.Response(400, json={"error": {"message": "bad"}}))
        with self.assertRaises(AiError):
            provider.complete_json(MESSAGES)
        self.assertEqual(len(seen), 1)

    def test_unreachable_host(self):
        def handler(request):
            raise httpx.ConnectError("refused")

        provider, _, _ = self.provider(handler)
        with self.assertRaisesRegex(AiError, "Could not reach"):
            provider.complete_json(MESSAGES)


class GeminiTests(unittest.TestCase):
    def provider(self, handler, model="gemini-test"):
        http, seen = client_for(handler)
        return ai.GeminiProvider(model=model, api_key=SECRET, http_client=http, sleep=lambda s: None), seen

    def ok(self, text):
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
        )

    def test_request_shape(self):
        provider, seen = self.provider(lambda r: self.ok('{"a": 1}'))
        result = provider.complete_json(
            MESSAGES + [{"role": "assistant", "content": "x"}, {"role": "user", "content": "again"}],
            temperature=0.15,
        )

        self.assertEqual(result.data, {"a": 1})
        request = seen[0]
        self.assertEqual(
            str(request.url),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent",
        )
        self.assertEqual(request.headers["x-goog-api-key"], SECRET)
        self.assertNotIn(SECRET, str(request.url))
        body = body_of(request)
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "You translate."}]})
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["temperature"], 0.15)

    def test_model_prefix_is_accepted(self):
        provider, seen = self.provider(lambda r: self.ok("{}"), model="models/gemini-test")
        provider.complete_json(MESSAGES)
        self.assertTrue(str(seen[0].url).endswith("/models/gemini-test:generateContent"))

    def test_bad_key_reads_as_auth_error(self):
        provider, _ = self.provider(
            lambda r: httpx.Response(400, json={"error": {"code": 400, "message": "API key not valid. Please pass a valid API key."}})
        )
        with self.assertRaisesRegex(AiError, "rejected the API key"):
            provider.complete_json(MESSAGES)

    def test_blocked_prompt(self):
        provider, _ = self.provider(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
        with self.assertRaisesRegex(AiError, "blocked"):
            provider.complete_json(MESSAGES)

    def test_truncated_reply(self):
        provider, _ = self.provider(
            lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"a'}]}, "finishReason": "MAX_TOKENS"}]})
        )
        with self.assertRaisesRegex(AiError, "cut off"):
            provider.complete_json(MESSAGES)

    def test_non_json_reply(self):
        provider, _ = self.provider(lambda r: self.ok("no json here"))
        with self.assertRaises(InvalidJsonError):
            provider.complete_json(MESSAGES)


class OpenAiTests(unittest.TestCase):
    def setUp(self):
        openai_provider._NO_JSON_MODE.clear()
        self.addCleanup(openai_provider._NO_JSON_MODE.clear)

    def provider(self, handler, base_url=""):
        http, seen = client_for(handler)
        return ai.OpenAiProvider(model="m", api_key=SECRET, base_url=base_url, http_client=http), seen

    @staticmethod
    def completion(text, finish="stop"):
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "m",
                "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": text}}],
            },
        )

    def test_uses_json_mode_and_custom_base_url(self):
        provider, seen = self.provider(lambda r: self.completion('{"a": 1}'), base_url="http://localhost:11434/v1")
        result = provider.complete_json(MESSAGES, temperature=0.15)

        self.assertEqual(result.data, {"a": 1})
        request = seen[0]
        self.assertEqual(str(request.url), "http://localhost:11434/v1/chat/completions")
        body = body_of(request)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["temperature"], 0.15)
        self.assertEqual(body["messages"], MESSAGES)

    def test_falls_back_to_prompt_only_json_and_remembers(self):
        def handler(request):
            if "response_format" in body_of(request):
                return httpx.Response(400, json={"error": {"message": "response_format is not supported"}})
            return self.completion('Here: {"a": 1}')

        provider, seen = self.provider(handler, base_url="http://localhost:1234/v1")
        self.assertEqual(provider.complete_json(MESSAGES).data, {"a": 1})
        self.assertEqual(len(seen), 2)
        retry = body_of(seen[1])
        self.assertNotIn("response_format", retry)
        self.assertIn("JSON", retry["messages"][0]["content"])

        # Second call goes straight to the prompt-only path.
        provider.complete_json(MESSAGES)
        self.assertEqual(len(seen), 3)
        self.assertNotIn("response_format", body_of(seen[2]))

    def test_real_error_after_fallback_is_reported(self):
        provider, _ = self.provider(lambda r: httpx.Response(400, json={"error": {"message": "unknown model 'm'"}}))
        with self.assertRaisesRegex(AiError, "unknown model"):
            provider.complete_json(MESSAGES)
        self.assertFalse(openai_provider._NO_JSON_MODE)

    def test_auth_error(self):
        provider, _ = self.provider(lambda r: httpx.Response(401, json={"error": {"message": "Incorrect API key"}}))
        with self.assertRaises(AiError) as ctx:
            provider.complete_json(MESSAGES)
        self.assertIn("rejected the API key", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_missing_model_reports_base_url_hint(self):
        provider, _ = self.provider(
            lambda r: httpx.Response(404, json={"error": {"message": "model not found"}}), base_url="http://x/v1"
        )
        with self.assertRaisesRegex(AiError, "model id and base URL"):
            provider.complete_json(MESSAGES)

    def test_truncated_reply(self):
        provider, _ = self.provider(lambda r: self.completion('{"a', finish="length"))
        with self.assertRaisesRegex(AiError, "cut off"):
            provider.complete_json(MESSAGES)

    def test_unusable_output(self):
        provider, _ = self.provider(lambda r: self.completion("Sorry, no."))
        with self.assertRaises(InvalidJsonError):
            provider.complete_json(MESSAGES)


class SettingsTestCase(unittest.TestCase):
    """Runs against a throwaway settings.json and a clean environment."""

    ENV_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "settings.json"
        patcher = mock.patch.object(settings_store, "_settings_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for var in self.ENV_VARS:
            os.environ.pop(var, None)

    def write_raw(self, data: dict) -> None:
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def read_raw(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))


class ConfigTests(SettingsTestCase):
    def test_defaults_to_openai(self):
        resolved = ai.resolve_provider()
        self.assertEqual((resolved.id, resolved.model, resolved.api_key), ("openai", "gpt-4o-mini", ""))

    def test_legacy_openai_settings_still_work(self):
        self.write_raw({"openai_api_key": " sk-old ", "openai_model": "gpt-4o"})
        resolved = ai.resolve_provider()
        self.assertEqual((resolved.id, resolved.api_key, resolved.model), ("openai", "sk-old", "gpt-4o"))
        self.assertIsInstance(ai.get_provider(), ai.OpenAiProvider)

    def test_first_save_moves_legacy_settings(self):
        self.write_raw({"openai_api_key": "sk-old", "openai_model": "gpt-4o", "file_logging": False})
        ai.save_ai_settings(provider="anthropic")

        raw = self.read_raw()
        self.assertEqual(raw["openai_api_key"], "")
        self.assertFalse(raw["file_logging"])
        self.assertEqual(raw["ai"]["provider"], "anthropic")
        self.assertEqual(raw["ai"]["providers"]["openai"], {"api_key": "sk-old", "model": "gpt-4o", "base_url": ""})

    def test_key_can_be_cleared_after_migration(self):
        self.write_raw({"openai_api_key": "sk-old"})
        ai.save_ai_settings(providers={"openai": {"api_key": ""}})
        self.assertEqual(ai.resolve_provider("openai").api_key, "")

    def test_switching_provider_keeps_other_keys(self):
        ai.save_ai_settings(provider="openai", providers={"openai": {"api_key": "sk-o"}})
        ai.save_ai_settings(provider="anthropic", providers={"anthropic": {"api_key": "sk-a", "model": "claude-x"}})
        ai.save_ai_settings(provider="openai")

        self.assertEqual(ai.resolve_provider().api_key, "sk-o")
        anthropic = ai.resolve_provider("anthropic")
        self.assertEqual((anthropic.api_key, anthropic.model), ("sk-a", "claude-x"))

    def test_none_and_missing_fields_are_kept(self):
        ai.save_ai_settings(providers={"gemini": {"api_key": "g", "model": "gm"}})
        ai.save_ai_settings(providers={"gemini": {"api_key": None}})
        self.assertEqual(ai.resolve_provider("gemini").api_key, "g")

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(AiConfigError):
            ai.save_ai_settings(provider="nope")
        with self.assertRaises(AiConfigError):
            ai.resolve_provider("nope")

    def test_environment_is_used_when_no_key_saved(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-env"
        resolved = ai.resolve_provider("anthropic")
        self.assertEqual(resolved.api_key, "sk-env")
        self.assertTrue(resolved.key_from_env)

    def test_saved_key_beats_environment(self):
        os.environ["GEMINI_API_KEY"] = "env"
        ai.save_ai_settings(providers={"gemini": {"api_key": "saved"}})
        resolved = ai.resolve_provider("gemini")
        self.assertEqual((resolved.api_key, resolved.key_from_env), ("saved", False))

    def test_overrides_win_when_not_blank(self):
        ai.save_ai_settings(providers={"openai": {"api_key": "saved", "model": "saved-model"}})
        resolved = ai.resolve_provider("openai", overrides={"api_key": "typed", "model": "  "})
        self.assertEqual((resolved.api_key, resolved.model), ("typed", "saved-model"))

    def test_get_provider_model_override(self):
        ai.save_ai_settings(providers={"openai": {"api_key": "k"}})
        self.assertEqual(ai.get_provider("gpt-4.1").model, "gpt-4.1")

    def test_builds_each_adapter(self):
        ai.save_ai_settings(
            providers={
                "openai": {"api_key": "a"},
                "openai_compatible": {"base_url": "localhost:11434", "model": "llama3.1"},
                "anthropic": {"api_key": "b"},
                "gemini": {"api_key": "c"},
            }
        )
        kinds = {}
        with mock.patch("core.ai.claude_code_provider.find_claude", return_value="claude"):
            for pid in ai.PROVIDERS:
                kinds[pid] = type(ai.build_provider(ai.resolve_provider(pid))).__name__
        self.assertEqual(
            kinds,
            {
                "openai": "OpenAiProvider",
                "openai_compatible": "OpenAiProvider",
                "anthropic": "AnthropicProvider",
                "gemini": "GeminiProvider",
                "claude_subscription": "ClaudeCodeProvider",
            },
        )

    def test_validation_messages(self):
        with self.assertRaisesRegex(AiConfigError, "no API key"):
            ai.get_provider()
        with self.assertRaisesRegex(AiConfigError, "base URL"):
            ai.build_provider(ai.resolve_provider("openai_compatible"))
        ai.save_ai_settings(providers={"openai_compatible": {"base_url": "http://x/v1"}})
        with self.assertRaisesRegex(AiConfigError, "model id"):
            ai.build_provider(ai.resolve_provider("openai_compatible"))

    def test_compatible_provider_needs_no_key(self):
        ai.save_ai_settings(providers={"openai_compatible": {"base_url": "http://x/v1", "model": "m"}})
        provider = ai.build_provider(ai.resolve_provider("openai_compatible"))
        self.assertEqual(provider.api_key, "")

    def test_config_errors_stay_value_errors(self):
        # The web layer answers ValueError with 422 and everything else with 502.
        with self.assertRaises(ValueError):
            ai.get_provider()

    def test_normalize_base_url(self):
        cases = {
            "": "",
            "http://localhost:11434": "http://localhost:11434/v1",
            "localhost:11434/": "http://localhost:11434/v1",
            "http://localhost:1234/v1/": "http://localhost:1234/v1",
            "https://x.openai.azure.com/openai/v1": "https://x.openai.azure.com/openai/v1",
            " https://openrouter.ai/api/v1 ": "https://openrouter.ai/api/v1",
        }
        for given, expected in cases.items():
            self.assertEqual(normalize_base_url(given), expected, given)


class ConnectionTests(SettingsTestCase):
    def test_success_message(self):
        http, _ = client_for(
            lambda r: httpx.Response(200, json={"content": [{"type": "tool_use", "input": {"ok": True}}]})
        )
        message = ai.check_connection("anthropic", overrides={"api_key": "k", "model": "claude-x"}, http_client=http)
        self.assertIn("Anthropic", message)
        self.assertIn("claude-x", message)

    def test_reports_provider_error(self):
        http, _ = client_for(lambda r: httpx.Response(403, json={"error": {"message": "nope"}}))
        with self.assertRaisesRegex(AiError, "403"):
            ai.check_connection("gemini", overrides={"api_key": "k"}, http_client=http)

    def test_reports_missing_configuration(self):
        with self.assertRaisesRegex(AiConfigError, "no API key"):
            ai.check_connection("anthropic")

    def test_reports_unusable_json(self):
        http, _ = client_for(
            lambda r: httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "hello!"}]}, "finishReason": "STOP"}]}
            )
        )
        with self.assertRaisesRegex(AiError, "valid JSON"):
            ai.check_connection("gemini", overrides={"api_key": "k"}, http_client=http)


class FakeProvider(ai.Provider):
    """Replays scripted replies (JsonResult, or an exception to raise) and records calls."""

    label = "Fake"

    def __init__(self, replies):
        super().__init__(model="fake-model")
        self.replies = list(replies)
        self.calls: list[tuple[list, float]] = []

    def complete_json(self, messages, *, temperature=0.0):
        self.calls.append(([dict(m) for m in messages], temperature))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FeatureTests(unittest.TestCase):
    def test_subtitle_translation_goes_through_the_provider(self):
        from core.subtitles import SubtitleCue, translate_cues_batch

        cues = [
            SubtitleCue(index=1, start="00:00:01,000", end="00:00:02,000", lines=["Hello"]),
            SubtitleCue(index=2, start="00:00:02,000", end="00:00:03,000", lines=["World"]),
        ]
        reply = {"translations": [{"id": 1, "text": "Hallo"}, {"id": 2, "text": "Wereld"}]}
        provider = FakeProvider([JsonResult(text=json.dumps(reply), data=reply)])

        out = translate_cues_batch(
            cues, source_lang="en", target_lang="nl", model=None,
            logger=logging.getLogger("test"), provider=provider,
        )

        self.assertEqual([c.lines for c in out], [["Hallo"], ["Wereld"]])
        messages, temperature = provider.calls[0]
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertEqual(temperature, 0.15)

    def test_untranslated_cues_keep_their_text_and_warn(self):
        from core.subtitles import SubtitleCue, translate_cues_batch

        cues = [
            SubtitleCue(index=1, start="00:00:01,000", end="00:00:02,000", lines=["Hello"]),
            SubtitleCue(index=2, start="00:00:02,000", end="00:00:03,000", lines=["World"]),
        ]
        first = {"translations": [{"id": 1, "text": "Hallo"}]}
        never = {"translations": []}
        # Whole batch, then the missing cue, then the missing cue on its own.
        provider = FakeProvider([JsonResult(text="", data=d) for d in (first, never, never)])

        with self.assertLogs("test", level="WARNING") as logs:
            out = translate_cues_batch(
                cues, source_lang="en", target_lang="nl", model=None,
                logger=logging.getLogger("test"), provider=provider,
            )
        self.assertEqual([c.lines for c in out], [["Hallo"], ["World"]])
        self.assertEqual(len(provider.calls), 3)
        self.assertTrue(any("could not be translated" in line for line in logs.output))

    def test_rename_profile_recovers_from_unusable_json(self):
        from core.rename_ai import generate_profile

        profile = {"name": "Keep", "rules": [], "patterns": {"generic": "{name}"}, "strip_release_junk": False}
        provider = FakeProvider(
            [
                InvalidJsonError("The model did not return valid JSON: sorry", "sorry"),
                JsonResult(text=json.dumps(profile), data=profile),
            ]
        )

        result = generate_profile([{"before": "Some Name", "after": "Some Name"}], "generic", provider=provider)

        self.assertTrue(result["all_ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["model"], "fake-model")
        # The model is shown its own bad reply and asked to fix it.
        retry_messages, _ = provider.calls[1]
        self.assertEqual([m["role"] for m in retry_messages[-2:]], ["assistant", "user"])
        self.assertEqual(retry_messages[-2]["content"], "sorry")

    def test_rename_profile_gives_up_with_readable_error(self):
        from core.rename_ai import generate_profile
        from core.rename_profiles import ProfileError

        provider = FakeProvider([InvalidJsonError("bad", "x")] * 3)
        with self.assertRaises(ProfileError):
            generate_profile([{"before": "a", "after": "b"}], "generic", provider=provider)


try:
    from fastapi.testclient import TestClient

    from web import server
except ImportError:  # web extras not installed
    server = None


@unittest.skipIf(server is None, "web extras (fastapi) not installed")
class SettingsApiTests(SettingsTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(server.app)
        patcher = mock.patch.object(server, "logs_stats", lambda: {"path": "", "total_bytes": 0, "file_count": 0, "files": []})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults(self):
        data = self.client.get("/api/settings").json()
        self.assertEqual(data["ai"]["provider"], "openai")
        self.assertEqual(set(data["ai"]["providers"]), set(ai.PROVIDERS))
        self.assertEqual(data["ai"]["providers"]["openai"]["model"], "gpt-4o-mini")
        self.assertFalse(data["ai"]["providers"]["openai"]["api_key_set"])

    def test_keys_are_never_returned(self):
        response = self.client.patch(
            "/api/settings",
            json={"ai": {"provider": "anthropic", "providers": {"anthropic": {"api_key": SECRET, "model": "claude-x"}}}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET, response.text)
        data = response.json()["ai"]
        self.assertEqual(data["provider"], "anthropic")
        self.assertTrue(data["providers"]["anthropic"]["api_key_set"])
        self.assertEqual(data["providers"]["anthropic"]["model"], "claude-x")
        self.assertFalse(data["providers"]["openai"]["api_key_set"])

    def test_legacy_key_shows_as_set(self):
        self.write_raw({"openai_api_key": "sk-old", "openai_model": "gpt-4o"})
        openai = self.client.get("/api/settings").json()["ai"]["providers"]["openai"]
        self.assertTrue(openai["api_key_set"])
        self.assertEqual(openai["model"], "gpt-4o")

    def test_empty_string_clears_key_and_other_settings_survive(self):
        self.client.patch("/api/settings", json={"file_logging": False})
        self.client.patch("/api/settings", json={"ai": {"providers": {"gemini": {"api_key": "g"}}}})
        data = self.client.patch("/api/settings", json={"ai": {"providers": {"gemini": {"api_key": ""}}}}).json()
        self.assertFalse(data["ai"]["providers"]["gemini"]["api_key_set"])
        self.assertFalse(data["file_logging"])

    def test_env_key_is_flagged(self):
        os.environ["GEMINI_API_KEY"] = "env"
        gemini = self.client.get("/api/settings").json()["ai"]["providers"]["gemini"]
        self.assertTrue(gemini["api_key_set"])
        self.assertTrue(gemini["api_key_from_env"])

    def test_compatible_base_url_is_normalised(self):
        self.client.patch(
            "/api/settings",
            json={"ai": {"providers": {"openai_compatible": {"base_url": "localhost:11434", "model": "llama3.1"}}}},
        )
        data = self.client.get("/api/settings").json()["ai"]["providers"]["openai_compatible"]
        self.assertEqual(data["base_url"], "http://localhost:11434/v1")

    def test_unknown_provider_is_422(self):
        response = self.client.patch("/api/settings", json={"ai": {"provider": "nope"}})
        self.assertEqual(response.status_code, 422)

    def test_test_endpoint_passes_form_values_and_reports_success(self):
        with mock.patch.object(server, "check_connection", return_value="Connected: fine.") as check:
            data = self.client.post(
                "/api/ai/test", json={"provider": "anthropic", "api_key": "typed", "model": "claude-x"}
            ).json()
        self.assertEqual(data, {"ok": True, "message": "Connected: fine."})
        check.assert_called_once_with(
            "anthropic", overrides={"api_key": "typed", "model": "claude-x", "base_url": ""}
        )

    def test_test_endpoint_reports_failure_as_200(self):
        with mock.patch.object(server, "check_connection", side_effect=AiError("Anthropic rejected the API key (401).")):
            response = self.client.post("/api/ai/test", json={"provider": "anthropic"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": False, "message": "Anthropic rejected the API key (401)."})

    def test_test_endpoint_reports_missing_config(self):
        data = self.client.post("/api/ai/test", json={"provider": "anthropic"}).json()
        self.assertFalse(data["ok"])
        self.assertIn("no API key", data["message"])


if __name__ == "__main__":
    unittest.main()
