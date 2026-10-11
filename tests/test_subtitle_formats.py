"""ASS/SSA and WebVTT round trips, parallel batches, the review pass and the dry-run estimate."""

import json
import logging
import threading
import unittest
from pathlib import Path

from core import subtitles
from core.ai import AiError, JsonResult, Provider
from core.subtitle_formats import load_subtitle
from core.subtitles import (
    SubtitleCue,
    TranslationReport,
    estimate_translation,
    translate_cues_batch,
)

LOG = logging.getLogger("test_formats")

ASS = (
    "[Script Info]\nTitle: Demo\n\n[V4+ Styles]\nFormat: Name, Fontname\nStyle: Default,Arial\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\\an8}Hello, there\\Nfriend\n"
    "Comment: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,not spoken\n"
    "Dialogue: 0,0:00:06.00,0:00:07.00,Default,,0,0,0,,{\\p1}m 0 0 l 10 10{\\p0}\n"
    "Dialogue: 0,0:00:08.00,0:00:09.00,Default,,0,0,0,,Bye\n"
)

VTT = (
    "WEBVTT\n\nNOTE a comment\n\nintro\n00:01.000 --> 00:03.000 align:start\n<i>Hello</i>\nthere\n\n"
    "00:04.000 --> 00:05.000\nBye\n"
)


class Echo(Provider):
    """Answers every cue as ``NL:<source>`` and records the prompts it was sent."""

    label = "Echo"

    def __init__(self, review_edits=None):
        super().__init__(model="echo")
        self.lock = threading.Lock()
        self.prompts = []
        self.review_edits = review_edits

    def complete_json(self, messages, *, temperature=0.0):
        user = messages[1]["content"]
        with self.lock:
            self.prompts.append(user)
        if "senior subtitle editor" in messages[0]["content"]:
            return JsonResult(text="", data={"edits": self.review_edits or []})
        marker = "Translate ONLY the following cues (they appear in order):\n"
        payload = json.loads(user.split(marker)[1].split("\n")[0])
        data = {"translations": [{"id": c["id"], "text": "NL:" + c["text"]} for c in payload]}
        return JsonResult(text="", data=data)


class Boom(Provider):
    label = "Boom"

    def __init__(self):
        super().__init__(model="boom")

    def complete_json(self, messages, *, temperature=0.0):
        raise AiError("quota")


def cue(i, text):
    return SubtitleCue(index=i, start="00:00:01,000", end="00:00:02,000", lines=text.split("\n"))


class FormatTests(unittest.TestCase):
    def test_ass_translates_text_and_keeps_everything_else(self):
        loaded = load_subtitle(Path("a.ass"), ASS)
        self.assertEqual([c.lines for c in loaded.cues], [["{\\an8}Hello, there", "friend"], ["Bye"]])
        translated = [SubtitleCue(c.index, c.start, c.end, ["X" + ln for ln in c.lines]) for c in loaded.cues]
        out = loaded.render(translated)
        self.assertIn("Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,X{\\an8}Hello, there\\NXfriend", out)
        self.assertIn("Comment: 0,0:00:04.00,0:00:05.00,Default,,0,0,0,,not spoken", out)
        self.assertIn("{\\p1}m 0 0 l 10 10{\\p0}", out)
        self.assertIn("[V4+ Styles]", out)

    def test_ass_dropped_cue_is_removed(self):
        loaded = load_subtitle(Path("a.ass"), ASS)
        out = loaded.render(loaded.cues[:1])
        self.assertNotIn("Bye", out)
        self.assertIn("Hello, there", out)

    def test_vtt_round_trip(self):
        loaded = load_subtitle(Path("a.vtt"), VTT)
        self.assertEqual(len(loaded.cues), 2)
        self.assertEqual(loaded.cues[0].lines, ["<i>Hello</i>", "there"])
        self.assertEqual(subtitles._seconds(loaded.cues[0].start), 1.0)
        translated = [SubtitleCue(c.index, c.start, c.end, ["T"]) for c in loaded.cues]
        out = loaded.render(translated)
        self.assertTrue(out.startswith("WEBVTT"))
        self.assertIn("NOTE a comment", out)
        self.assertIn("intro\n00:01.000 --> 00:03.000 align:start\nT", out)

    def test_srt_still_works(self):
        loaded = load_subtitle(Path("a.srt"), "1\n00:00:01,000 --> 00:00:02,000\nHi\n")
        self.assertEqual(loaded.cues[0].lines, ["Hi"])
        self.assertIn("Hi", loaded.render(loaded.cues))


class ParallelAndReviewTests(unittest.TestCase):
    def cues(self, n):
        return [cue(i, f"Line {i}") for i in range(n)]

    def test_parallel_keeps_order_and_uses_source_only_context(self):
        provider = Echo()
        size = subtitles.TRANSLATE_BATCH_SIZE
        out = translate_cues_batch(
            self.cues(size * 3), source_lang="en", target_lang="nl", model=None, logger=LOG,
            provider=provider, concurrency=3,
        )
        self.assertEqual([c.text for c in out], [f"NL:Line {i}" for i in range(size * 3)])
        later = [p for p in provider.prompts if f"Line {size + 1}" in p.split("Translate ONLY")[1]][0]
        self.assertIn("Earlier lines", later)
        self.assertNotIn("Previously translated", later)

    def test_parallel_failure_propagates(self):
        with self.assertRaises(AiError):
            translate_cues_batch(
                self.cues(subtitles.TRANSLATE_BATCH_SIZE * 2), source_lang="en", target_lang="nl",
                model=None, logger=LOG, provider=Boom(), concurrency=2,
            )

    def test_review_applies_valid_edits_only(self):
        edits = [{"id": 1, "text": "Better"}, {"id": 2, "text": "<b>Tag added</b>"}]
        report = TranslationReport()
        out = translate_cues_batch(
            [cue(1, "Hello"), cue(2, "World")], source_lang="en", target_lang="nl", model=None,
            logger=LOG, provider=Echo(review_edits=edits), review=True, report=report,
        )
        self.assertEqual([c.text for c in out], ["Better", "NL:World"])
        self.assertEqual(report.revised, 1)


class EstimateTests(unittest.TestCase):
    def test_review_costs_more(self):
        cues = [cue(i, "Some reasonably long subtitle line here") for i in range(60)]
        plain = estimate_translation(cues, None, review=False)
        reviewed = estimate_translation(cues, None, review=True)
        self.assertEqual(plain[2], 3)
        self.assertGreater(reviewed[0], plain[0])
        self.assertEqual(reviewed[2], 6)


if __name__ == "__main__":
    unittest.main()
