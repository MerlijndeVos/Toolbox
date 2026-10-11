"""Translate: translate SRT subtitles with the configured AI provider (wraps ``core.subtitles``)."""

import argparse
from pathlib import Path

from pydantic import BaseModel, field_validator

from core.paths import clean_path_string
from core.subtitles import run_subtitle_translate


class Params(BaseModel):
    input: str
    source_lang: str = "auto"
    target_lang: str = "en"
    overwrite: bool = False
    dry_run: bool = True

    @field_validator("input")
    @classmethod
    def normalize_input(cls, value: str) -> str:
        return clean_path_string(value)


def run(params, ctx):
    p = params
    report = run_subtitle_translate(
        argparse.Namespace(
            input=Path(p["input"]),
            source_lang=p["source_lang"],
            target_lang=p["target_lang"],
            overwrite=p["overwrite"],
            dry_run=p["dry_run"],
            model=None,
        ),
        should_cancel=ctx.cancelled,
    )
    if not p["dry_run"] and (report.untranslated or report.flagged):
        ctx.result(
            "counters",
            title="Translation finished with warnings",
            items={
                "Cues translated": report.total - report.untranslated,
                "Kept original text": report.untranslated,
                "May need a check": report.flagged,
            },
        )
