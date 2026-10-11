"""Subtitle translation: repair loop, validation, cancellation, resume and file handling."""

import argparse
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core import subtitles
from core.ai import AiError, InvalidJsonError, JsonResult, Provider
from core.mods.context import ModCancelled
from core.subtitles import (
    SubtitleCue,
    TranslationReport,
    TranslationStyle,
    char_budget,
    mask_tags,
    plan_translation_files,
    remove_auto_junk,
    unmask_tags,
    parse_srt,
    process_srt_file,
    read_subtitle_text,
    translate_cues_batch,
)

LOG = logging.getLogger("test_subtitles")


class Scripted(Provider):
    label = "Fake"

    def __init__(self, replies):
        super().__init__(model="fake-model")
        self.replies = list(replies)
        self.calls = []

    def complete_json(self, messages, *, temperature=0.0):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        if isinstance(reply, Exception):
            raise reply
        return JsonResult(text="", data=reply)


def cue(i, text):
    return SubtitleCue(index=i, start="00:00:01,000", end="00:00:02,000", lines=text.split("\n"))


def answer(*texts):
    return {"translations": [{"id": i, "text": t} for i, t in enumerate(texts, start=1)]}


class RepairLoopTests(unittest.TestCase):
    def run_batch(self, cues, replies, **kw):
        provider = Scripted(replies)
        report = TranslationReport()
        out = translate_cues_batch(
            cues, source_lang="en", target_lang="nl", model=None, logger=LOG,
            provider=provider, report=report, **kw,
        )
        return out, provider, report

    def test_invalid_json_is_retried(self):
        out, provider, report = self.run_batch(
            [cue(1, "Hello")],
            [InvalidJsonError("nope", "nope"), answer("Hallo")],
        )
        self.assertEqual(out[0].lines, ["Hallo"])
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(report.clean)

    def test_only_failed_cues_are_asked_again(self):
        cues = [cue(1, "One"), cue(2, "Two"), cue(3, "Three")]
        out, provider, report = self.run_batch(
            cues,
            [{"translations": [{"id": 1, "text": "Een"}, {"id": 3, "text": "Drie"}]}, answer("Twee")],
        )
        self.assertEqual([c.text for c in out], ["Een", "Twee", "Drie"])
        retry = provider.calls[1][1]["content"]
        self.assertIn("Two", retry.split("Translate ONLY")[1])
        self.assertNotIn("Three", retry.split("Translate ONLY")[1])
        self.assertEqual(report.untranslated, 0)

    def test_changed_tags_are_retried_then_flagged(self):
        out, _provider, report = self.run_batch([cue(1, "<i>Hello</i>")], [answer("Hallo")] * 3)
        self.assertEqual(out[0].lines, ["Hallo"])
        self.assertEqual(report.flagged, 1)
        self.assertEqual(report.untranslated, 0)

    def test_tags_fixed_on_retry(self):
        out, _p, report = self.run_batch(
            [cue(1, "<i>Hello</i>")], [answer("Hallo"), answer("<i>Hallo</i>")]
        )
        self.assertEqual(out[0].lines, ["<i>Hallo</i>"])
        self.assertEqual(report.flagged, 0)

    def test_markers_are_sent_and_restored(self):
        out, provider, report = self.run_batch(
            [cue(1, "{\\an8}<i>Hello</i>")], [answer("⟦1⟧⟦2⟧Hallo⟦3⟧")]
        )
        self.assertEqual(out[0].lines, ["{\\an8}<i>Hallo</i>"])
        sent = provider.calls[0][1]["content"]
        self.assertIn("⟦1⟧", sent)
        self.assertNotIn("<i>", sent.split("Translate ONLY")[1])
        self.assertEqual(report.flagged, 0)

    def test_style_and_lookahead_reach_the_prompt(self):
        glossary = "Hawkins = Hawkins\n# comment\nupside down = de Andere Kant"
        style = TranslationStyle.parse(glossary, "Teen drama")
        size = subtitles.TRANSLATE_BATCH_SIZE
        cues = [cue(1, f"Line {i}") for i in range(size + 1)]
        replies = [answer(*[f"T{i}" for i in range(size)]), answer("Z")]
        _out, provider, _r = self.run_batch(cues, replies, style=style)
        first = provider.calls[0][1]["content"]
        self.assertIn("upside down -> de Andere Kant", first)
        self.assertIn("Teen drama", first)
        self.assertIn(f"Line {size}", first.split("Upcoming lines")[1].split("Translate ONLY")[0])

    def test_unknown_source_asks_the_model_to_detect_it(self):
        _o, provider, _r = self.run_batch([cue(1, "Hello")], [answer("Hallo")])
        self.assertIn("en", provider.calls[0][0]["content"])
        provider = Scripted([answer("Hallo")])
        translate_cues_batch(
            [cue(1, "Hello")], source_lang="auto", target_lang="nl", model=None, logger=LOG, provider=provider
        )
        self.assertIn("detect it yourself", provider.calls[0][0]["content"])

    def test_blank_line_inside_a_cue_is_a_problem(self):
        _out, _p, report = self.run_batch([cue(1, "Hello")], [answer("Ha\n\nllo")] * 3)
        self.assertEqual(report.flagged, 1)

    def test_provider_errors_are_not_retried(self):
        with self.assertRaises(AiError):
            self.run_batch([cue(1, "Hello")], [AiError("Bad key")])

    def test_multi_batch_carries_context(self):
        size = subtitles.TRANSLATE_BATCH_SIZE
        cues = [cue(1, f"Line {i}") for i in range(size + 2)]
        replies = [answer(*[f"T{i}" for i in range(size)]), answer("X", "Y")]
        out, provider, _r = self.run_batch(cues, replies)
        self.assertEqual(len(out), len(cues))
        second = provider.calls[1][1]["content"]
        self.assertIn("Previously translated", second)
        self.assertIn(f"T{size - 1}", second)


class HelperTests(unittest.TestCase):
    def test_mask_round_trip(self):
        masked, tags = mask_tags("<i>Hi</i> {\\an8}there")
        self.assertEqual(unmask_tags(masked, tags), "<i>Hi</i> {\\an8}there")
        self.assertNotIn("<", masked)

    def test_title_words_are_not_language_tags(self):
        from core.rename import split_subtitle_suffix

        self.assertEqual(split_subtitle_suffix("Where.Is.It"), ("Where.Is.It", ""))
        self.assertEqual(split_subtitle_suffix("Say.Hi"), ("Say.Hi", ""))
        self.assertEqual(split_subtitle_suffix("Where.Is.It.en"), ("Where.Is.It", "en"))
        self.assertEqual(split_subtitle_suffix("Show.S01E01.en.forced"), ("Show.S01E01", "en.forced"))
        self.assertEqual(split_subtitle_suffix("Show.it"), ("Show", "it"))
        self.assertEqual(split_subtitle_suffix("Show.EN"), ("Show", "EN"))
        self.assertEqual(split_subtitle_suffix("Show.Dutch"), ("Show", "Dutch"))

    def test_char_budget_uses_duration(self):
        self.assertEqual(char_budget(cue(1, "x")), 17)

    def test_auto_junk_leaves_sound_captions(self):
        cues = [cue(1, "Hello\nwww.example.com"), cue(2, "[door slams]"), cue(3, "Synced by someone")]
        cleaned, removed = remove_auto_junk(cues)
        self.assertEqual(removed, 2)
        self.assertEqual([c.text for c in cleaned], ["Hello", "[door slams]"])

    def test_folder_plan_skips_target_language_and_duplicates(self):
        files = [Path("a/Show.de.srt"), Path("a/Show.en.srt"), Path("a/Show.fr.srt")]
        planned = plan_translation_files(files, "de", LOG)
        self.assertEqual(planned, [Path("a/Show.en.srt")])


class CancelAndResumeTests(unittest.TestCase):
    def test_cancel_stops_before_any_request(self):
        provider = Scripted([answer("Hallo")])
        with self.assertRaises(ModCancelled):
            translate_cues_batch(
                [cue(1, "Hello")], source_lang="en", target_lang="nl", model=None,
                logger=LOG, provider=provider, should_cancel=lambda: True,
            )
        self.assertEqual(provider.calls, [])

    def test_checkpointed_batches_are_not_requested_again(self):
        provider = Scripted([])
        report = TranslationReport()
        out = translate_cues_batch(
            [cue(1, "Hello")], source_lang="en", target_lang="nl", model=None, logger=LOG,
            provider=provider, report=report, checkpoint={1: ["Hallo"]},
        )
        self.assertEqual(out[0].lines, ["Hallo"])
        self.assertEqual(report.resumed_batches, 1)
        self.assertEqual(provider.calls, [])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        patcher = mock.patch.object(subtitles, "app_data_dir", return_value=self.dir / "data")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text, encoding="utf-8"):
        path = self.dir / name
        path.write_bytes(text.encode(encoding))
        return path

    def test_legacy_encoding_is_decoded_not_replaced(self):
        path = self.write("a.srt", "1\n00:00:01,000 --> 00:00:02,000\nCafé\n", "cp1252")
        self.assertIn("Café", read_subtitle_text(path))

    def test_output_is_written_atomically_and_cancel_writes_nothing(self):
        src = self.write("Show.en.srt", "1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        provider = Scripted([answer("Hallo")])
        kwargs = dict(
            target_lang="nl", source_lang="en", model="fake", clean_junk=False,
            confirmed_removals=set(), dry_run=False, overwrite=True, logger=LOG,
        )
        with mock.patch.object(subtitles, "get_provider", return_value=provider):
            with self.assertRaises(ModCancelled):
                process_srt_file(src, should_cancel=lambda: True, **kwargs)
            self.assertFalse((self.dir / "Show.nl.srt").exists())
            dst = process_srt_file(src, **kwargs)
        self.assertEqual(parse_srt(dst.read_text(encoding="utf-8"))[0].lines, ["Hallo"])
        self.assertFalse((self.dir / "Show.nl.srt.tmp").exists())

    def test_vtt_file_is_translated_in_its_own_format(self):
        src = self.write("Clip.en.vtt", "WEBVTT\n\n00:01.000 --> 00:02.000\nHello\n")
        provider = Scripted([answer("Hallo")])
        kwargs = dict(
            target_lang="nl", source_lang="en", model="fake", clean_junk=False,
            confirmed_removals=set(), dry_run=False, overwrite=True, logger=LOG,
        )
        with mock.patch.object(subtitles, "get_provider", return_value=provider):
            dst = process_srt_file(src, **kwargs)
        self.assertEqual(dst.name, "Clip.nl.vtt")
        self.assertEqual(dst.read_text(encoding="utf-8"), "WEBVTT\n\n00:01.000 --> 00:02.000\nHallo\n")

    def test_dry_run_reports_an_estimate(self):
        src = self.write("Show.en.srt", "1\n00:00:01,000 --> 00:00:02,000\nHello there\n")
        report = TranslationReport()
        process_srt_file(
            src, target_lang="nl", source_lang="en", model="fake", clean_junk=False,
            confirmed_removals=set(), dry_run=True, overwrite=True, logger=LOG, report=report,
        )
        self.assertEqual(report.est_requests, 1)
        self.assertGreater(report.est_input_tokens, 0)

    def test_one_failing_file_does_not_stop_the_folder(self):
        self.write("a.en.srt", "1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        self.write("b.en.srt", "1\n00:00:01,000 --> 00:00:02,000\nWorld\n")
        calls = {"n": 0}

        def process(path, **kw):
            calls["n"] += 1
            if path.name == "a.en.srt":
                raise ValueError("boom")
            return path

        args = argparse.Namespace(
            input=self.dir, target_lang="nl", source_lang="en", overwrite=True, dry_run=False, model="m"
        )
        with mock.patch.object(subtitles, "process_srt_file", side_effect=process), mock.patch.object(
            subtitles, "setup_simple_logging", return_value=LOG
        ):
            with self.assertRaisesRegex(RuntimeError, "1 of 2 file"):
                subtitles.run_subtitle_translate(args)
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
