"""Translate: translate SRT subtitles with the configured AI provider (wraps ``core.subtitles``)."""

import argparse
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from core.paths import clean_path_string
from core.subtitles import run_subtitle_translate


class Params(BaseModel):
    input: str
    source_lang: str = "auto"
    target_lang: str = "en"
    overwrite: bool = False
    glossary: str = ""
    notes: str = ""
    remove_junk: bool = True
    model: str = ""
    concurrency: int = Field(default=1, ge=1, le=4)
    review: bool = False
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
            glossary=p.get("glossary", ""),
            notes=p.get("notes", ""),
            remove_junk=p.get("remove_junk", True),
            dry_run=p["dry_run"],
            model=(p.get("model") or "").strip() or None,
            concurrency=p.get("concurrency", 1),
            review=p.get("review", False),
        ),
        should_cancel=ctx.cancelled,
    )
    if p["dry_run"] and report.est_requests:
        ctx.result(
            "counters",
            title="Estimated cost of this translation",
            items={
                "Requests": report.est_requests,
                "Input tokens (about)": report.est_input_tokens,
                "Output tokens (about)": report.est_output_tokens,
            },
        )
    if not p["dry_run"] and (report.untranslated or report.flagged or report.revised):
        ctx.result(
            "counters",
            title="Translation finished with warnings",
            items={
                "Cues translated": report.total - report.untranslated,
                "Kept original text": report.untranslated,
                "May need a check": report.flagged,
                "Improved by review": report.revised,
            },
        )
