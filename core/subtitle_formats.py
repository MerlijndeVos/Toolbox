"""Reading and writing subtitle files: SRT, WebVTT and ASS/SSA.

Every format is read into the same :class:`SubtitleCue` list, and :meth:`SubtitleFile.render`
writes cues back in the original format. For ASS and WebVTT the rest of the file (styles, headers,
notes, positions, effects) is kept exactly as it was; only the cue text is replaced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

SUPPORTED_EXTENSIONS = (".srt", ".vtt", ".ass", ".ssa")


@dataclass
class SubtitleCue:
    index: int
    start: str
    end: str
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class SubtitleFile:
    kind: str
    cues: list[SubtitleCue]
    _render: Callable[[Sequence[SubtitleCue]], str]

    def render(self, cues: Sequence[SubtitleCue]) -> str:
        return self._render(cues)


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------

def parse_srt(content: str) -> list[SubtitleCue]:
    text = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    blocks = re.split(r"\n\s*\n", text)
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() or ln == ""]
        if len(lines) < 2:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        timing = lines[1]
        if "-->" not in timing:
            continue
        start, end = [part.strip() for part in timing.split("-->", 1)]
        body = lines[2:]
        while body and not body[-1].strip():
            body.pop()
        cues.append(SubtitleCue(index=index, start=start, end=end, lines=body))
    return cues


def format_srt(cues: Sequence[SubtitleCue]) -> str:
    parts: list[str] = []
    for i, cue in enumerate(cues, start=1):
        parts.append(str(i))
        parts.append(f"{cue.start} --> {cue.end}")
        parts.extend(cue.lines)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# WebVTT
# ---------------------------------------------------------------------------

def _load_vtt(content: str) -> SubtitleFile:
    text = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    blocks = re.split(r"\n[ \t]*\n", text)
    # Each block is either kept as it is, or a cue whose text can be replaced.
    layout: list[tuple[str, object]] = []
    cues: list[SubtitleCue] = []
    for number, block in enumerate(blocks):
        lines = block.split("\n")
        timing_at = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        is_meta = number == 0 and lines[0].startswith("WEBVTT")
        if is_meta or lines[0].startswith(("NOTE", "STYLE", "REGION")) or timing_at is None:
            layout.append(("keep", block))
            continue
        start, end = [part.strip() for part in lines[timing_at].split("-->", 1)]
        cue = SubtitleCue(index=len(cues) + 1, start=start, end=end, lines=lines[timing_at + 1 :])
        cues.append(cue)
        layout.append(("cue", (cue.index, lines[: timing_at + 1])))

    def render(translated: Sequence[SubtitleCue]) -> str:
        by_index = {c.index: c for c in translated}
        out: list[str] = []
        for kind, payload in layout:
            if kind == "keep":
                out.append(str(payload))
                continue
            index, head = payload  # type: ignore[misc]
            cue = by_index.get(index)
            if cue is not None:
                out.append("\n".join([*head, *cue.lines]))
        return "\n\n".join(out).rstrip("\n") + "\n"

    return SubtitleFile("vtt", cues, render)


# ---------------------------------------------------------------------------
# ASS / SSA
# ---------------------------------------------------------------------------

_DRAWING_RE = re.compile(r"\\p[1-9]")


def _load_ass(content: str) -> SubtitleFile:
    text = content.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = text.split("\n")

    in_events = False
    columns: list[str] = []
    cues: list[SubtitleCue] = []
    # line number -> (prefix before the text, cue index) for dialogue lines that can be translated
    editable: dict[int, tuple[str, int]] = {}
    for number, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped.startswith("["):
            in_events = stripped.lower() == "[events]"
            continue
        if not in_events:
            continue
        lowered = stripped.lower()
        if lowered.startswith("format:"):
            columns = [c.strip().lower() for c in stripped.split(":", 1)[1].split(",")]
            continue
        if not lowered.startswith("dialogue:") or not columns or "text" not in columns:
            continue
        value = stripped.split(":", 1)[1].lstrip()
        fields = value.split(",", len(columns) - 1)
        if len(fields) != len(columns):
            continue
        body = fields[columns.index("text")]
        if not body.strip() or _DRAWING_RE.search(body):
            continue
        prefix = line[: line.index(":") + 1] + " " + ",".join(fields[:-1]) + ","
        cue = SubtitleCue(
            index=number,
            start=fields[columns.index("start")].strip() if "start" in columns else "",
            end=fields[columns.index("end")].strip() if "end" in columns else "",
            lines=body.split("\\N"),
        )
        cues.append(cue)
        editable[number] = (prefix, cue.index)

    def render(translated: Sequence[SubtitleCue]) -> str:
        by_index = {c.index: c for c in translated}
        out: list[str] = []
        for number, line in enumerate(raw_lines):
            if number not in editable:
                out.append(line)
                continue
            prefix, index = editable[number]
            cue = by_index.get(index)
            if cue is not None:
                out.append(prefix + "\\N".join(cue.lines))
        return "\n".join(out)

    return SubtitleFile("ass", cues, render)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def load_subtitle(path: Path, content: str) -> SubtitleFile:
    """Parse *content* as the format *path*'s extension names."""
    suffix = path.suffix.lower()
    if suffix == ".vtt":
        return _load_vtt(content)
    if suffix in (".ass", ".ssa"):
        return _load_ass(content)
    return SubtitleFile("srt", parse_srt(content), format_srt)
