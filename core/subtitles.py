"""SRT subtitle translation and junk-line cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, Set

from . import config
from .mods.context import ModCancelled
from .runtime import app_data_dir
from .log_storage import operation_log_path
from .logging_setup import setup_simple_logging
from .paths import clean_path_string, path_exists, path_is_dir, path_is_file
from .progress import get_active_hooks
from .rename import SUB_FLAG_TOKENS, split_subtitle_suffix
from .ai import AiError, InvalidJsonError, Provider, get_provider, resolve_model
from .subtitle_languages import (
    LANGUAGE_LABELS,
    normalize_lang_code,
)

SRT_EXTENSION = ".srt"
TRANSLATE_BATCH_SIZE = 25
CONTEXT_CUES = 8
LOOKAHEAD_CUES = 3
# Reading speed the per-cue character budget is derived from (characters per second).
TARGET_CPS = 17
PLACEHOLDER_RE = re.compile(r"\u27e6\d+\u27e7")
TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
# Junk reasons removed automatically before translating. Bracket lines are left alone: they are
# often legitimate sound captions such as [door slams].
AUTO_JUNK_REASONS = {"url", "email", "credit_line", "release_tag"}
# Requests per batch: the whole batch, then only the cues that failed, then one cue at a time.
MAX_REPAIR_ATTEMPTS = 3
TRANSLATE_TEMPERATURE = 0.15
TAG_RE = re.compile(r"<[^>]+>|\{[^}]*\}")

URL_RE = re.compile(
    r"(https?://|www\.)[^\s]+",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
BRACKET_LINE_RE = re.compile(r"^\s*[\[\{].*[\]\}]\s*$")
CREDIT_RE = re.compile(
    r"(?i)\b("
    r"sync(?:ed|hronized)?\s+by|subtitles?\s+by|translated?\s+by|"
    r"translation\s+by|ripped?\s+by|encoded?\s+by|brought?\s+to\s+you\s+by|"
    r"download(?:ed)?\s+from|visit\s+us\s+at|"
    r"opensubtitles|subscene|addic7ed|yify|yts|rarbg|ettv|eztv"
    r")\b",
)
RELEASE_TAG_RE = re.compile(
    r"(?i)^[\[\{\(<].*(?:yify|yts|rarbg|ettv|eztv|sync|subtitles?)[\]\}\)>]?$",
)
NOISE_LINE_RE = re.compile(r"^[\W_]+$")

JUNK_REASON_LABELS = {
    "url": "URL or web address",
    "email": "Email address",
    "bracket_watermark": "Bracket watermark",
    "credit_line": "Credits or site promotion",
    "release_tag": "Release group tag",
    "noise": "Non-dialogue noise line",
}


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
class JunkCandidate:
    id: str
    file: str
    cue_index: int
    line_index: int
    text: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file": self.file,
            "cue_index": self.cue_index,
            "line_index": self.line_index,
            "text": self.text,
            "reason": self.reason,
            "reason_label": JUNK_REASON_LABELS.get(self.reason, self.reason),
        }


def detect_lang_from_path(path: Path) -> Optional[str]:
    """Detect source language from subtitle filename suffix tokens."""
    _base, suffix = split_subtitle_suffix(path.stem)
    for tok in suffix.split("."):
        if tok and tok.lower() in SUB_FLAG_TOKENS:
            continue
        code = normalize_lang_code(tok)
        if code:
            return code
    return None


def resolve_source_lang(path: Path, source_lang: str) -> str:
    """Resolve 'auto' to a filename token. With none, stay 'auto' and let the model detect it."""
    if source_lang and source_lang.lower() != "auto":
        code = normalize_lang_code(source_lang)
        if code:
            return code
        return source_lang.lower()
    detected = detect_lang_from_path(path)
    return detected or "auto"


def build_output_path(src: Path, target_lang: str) -> Path:
    """Build translated output path with target language suffix."""
    base, suffix = split_subtitle_suffix(src.stem)
    flag_parts = [p for p in suffix.split(".") if p and p.lower() in SUB_FLAG_TOKENS]
    new_suffix = ".".join([target_lang, *flag_parts]) if flag_parts else target_lang
    return src.with_name(f"{base}.{new_suffix}{src.suffix}")


def collect_srt_files(input_path: Path) -> list[Path]:
    input_path = Path(clean_path_string(str(input_path)))
    if path_is_file(input_path):
        if input_path.suffix.lower() != SRT_EXTENSION:
            raise ValueError(f"Not an SRT file: {input_path}")
        return [input_path]
    if not path_is_dir(input_path):
        raise ValueError(f"Input path not found: {input_path}")
    files = sorted(
        p for p in input_path.rglob("*") if path_is_file(p) and p.suffix.lower() == SRT_EXTENSION
    )
    if not files:
        raise ValueError(f"No .srt files found under {input_path}")
    return files


def parse_srt(content: str) -> list[SubtitleCue]:
    text = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
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


def _junk_reason(line: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped:
        return None
    if URL_RE.search(stripped):
        return "url"
    if EMAIL_RE.search(stripped):
        return "email"
    if BRACKET_LINE_RE.match(stripped) and len(stripped) <= 120:
        return "bracket_watermark"
    if RELEASE_TAG_RE.match(stripped):
        return "release_tag"
    if CREDIT_RE.search(stripped):
        return "credit_line"
    if NOISE_LINE_RE.match(stripped) and len(stripped) >= 3:
        return "noise"
    return None


def junk_line_id(file_path: Path, cue_index: int, line_index: int) -> str:
    return f"{os.path.normcase(os.path.abspath(str(file_path)))}:{cue_index}:{line_index}"


def scan_junk_in_file(path: Path) -> list[JunkCandidate]:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    cues = parse_srt(content)
    results: list[JunkCandidate] = []
    file_str = str(path)
    for cue_index, cue in enumerate(cues):
        for line_index, line in enumerate(cue.lines):
            reason = _junk_reason(line)
            if reason:
                results.append(
                    JunkCandidate(
                        id=junk_line_id(path, cue_index, line_index),
                        file=file_str,
                        cue_index=cue_index,
                        line_index=line_index,
                        text=line,
                        reason=reason,
                    )
                )
    return results


def scan_junk(input_path: Path) -> list[JunkCandidate]:
    return [item for path in collect_srt_files(input_path) for item in scan_junk_in_file(path)]


def apply_junk_removals(
    cues: list[SubtitleCue],
    file_path: Path,
    confirmed_ids: Set[str],
) -> tuple[list[SubtitleCue], int]:
    """Return cues with confirmed junk lines removed."""
    removed = 0
    cleaned: list[SubtitleCue] = []
    for cue_index, cue in enumerate(cues):
        kept_lines: list[str] = []
        for line_index, line in enumerate(cue.lines):
            line_id = junk_line_id(file_path, cue_index, line_index)
            if line_id in confirmed_ids and _junk_reason(line):
                removed += 1
                continue
            kept_lines.append(line)
        if kept_lines:
            cleaned.append(
                SubtitleCue(index=cue.index, start=cue.start, end=cue.end, lines=kept_lines)
            )
    return cleaned, removed


def remove_auto_junk(cues: list[SubtitleCue]) -> tuple[list[SubtitleCue], int]:
    """Drop obvious ads and credit lines (URLs, emails, release tags) without asking."""
    removed = 0
    cleaned: list[SubtitleCue] = []
    for cue in cues:
        kept = [ln for ln in cue.lines if _junk_reason(ln) not in AUTO_JUNK_REASONS]
        removed += len(cue.lines) - len(kept)
        if kept:
            cleaned.append(SubtitleCue(index=cue.index, start=cue.start, end=cue.end, lines=kept))
    return cleaned, removed


def _language_name(code: str) -> str:
    return LANGUAGE_LABELS.get(code, code)


def _truncate_sample(text: str, max_len: int = 140) -> str:
    compact = " ".join(text.replace("\n", " ").split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1] + "…"


def _translation_samples(batch: Sequence[SubtitleCue], by_id: dict[int, str]) -> list[dict[str, str]]:
    if not batch:
        return []
    indices = [0]
    if len(batch) > 2:
        indices.append(len(batch) // 2)
    samples: list[dict[str, str]] = []
    for idx in indices:
        cue = batch[idx]
        target = by_id.get(idx + 1, cue.text)
        samples.append(
            {
                "source": _truncate_sample(cue.text),
                "target": _truncate_sample(target),
            }
        )
    return samples


def _build_translation_prompts(
    batch: Sequence[SubtitleCue],
    *,
    source_lang: str,
    target_lang: str,
    context_pairs: Sequence[tuple[str, str]],
    lookahead: Sequence[str] = (),
    style: Optional["TranslationStyle"] = None,
) -> tuple[str, str]:
    auto = source_lang == "auto"
    source_label = "source" if auto else source_lang
    target_name = _language_name(target_lang)
    if auto:
        route = (
            f"Translate from the source language (detect it yourself) into natural, fluent "
            f"{target_name} ({target_lang}) dialogue."
        )
    else:
        route = (
            f"Translate from {_language_name(source_lang)} ({source_lang}) into natural, fluent "
            f"{target_name} ({target_lang}) dialogue."
        )
    has_markers = any(PLACEHOLDER_RE.search(cue.text) for cue in batch)
    system_prompt = (
        "You are an expert subtitle translator for film and television.\n\n"
        f"{route}\n\n"
        "Quality rules:\n"
        "- Write how native speakers would actually say it: idiomatic, grammatical, "
        "and natural, never stiff, awkward, or word-for-word literal.\n"
        "- Consecutive cues are continuous dialogue; keep tone, register, and story "
        "context consistent across lines.\n"
        "- Each subtitle must read as a correct sentence or natural spoken phrase.\n"
        "- Fix clumsy source phrasing when needed so the target line still sounds right.\n"
        "- Preserve meaning, emotion, humor, and subtext.\n"
        "- Keep the same line breaks as the source (use \\n only where the source does).\n"
        "- Keep lines concise and easy to read on screen. When a cue has max_chars, stay at or "
        "under it by condensing, without losing the meaning.\n"
        "- Do not add notes, speaker labels, or numbering.\n"
        "- Keep names of people and places consistent across the whole file.\n"
    )
    if has_markers:
        system_prompt += (
            "- Markers like \u27e61\u27e7 stand for formatting. Keep every marker exactly once, "
            "in the matching place, and never translate or renumber them.\n"
        )
    system_prompt += "- Return JSON only."

    parts: list[str] = []
    if style is not None and style.notes:
        parts.extend(["Notes about this material:", f"  {style.notes}", ""])
    if style is not None and style.glossary:
        parts.append("Glossary (always use these):")
        for term, target in style.glossary:
            parts.append(f"  {term} -> {target}" if target else f"  {term} (keep as is, do not translate)")
        parts.append("")
    if context_pairs:
        parts.append(
            "Previously translated lines (for dialogue continuity, do NOT re-translate these):"
        )
        for src, tgt in context_pairs:
            parts.append(f"  [{source_label}] {src}")
            parts.append(f"  [{target_lang}] {tgt}")
        parts.append("")
    if lookahead:
        parts.append("Upcoming lines (context only, do NOT translate these):")
        parts.extend(f"  [{source_label}] {text}" for text in lookahead)
        parts.append("")

    payload = []
    for i, cue in enumerate(batch):
        item: dict[str, object] = {"id": i + 1, "text": cue.text}
        budget = char_budget(cue)
        if budget is not None:
            item["max_chars"] = budget
        payload.append(item)
    parts.extend(
        [
            "Translate ONLY the following cues (they appear in order):",
            json.dumps(payload, ensure_ascii=False),
            "",
            'Return JSON: {"translations": [{"id": <matching id>, "text": "<translated subtitle>"}, ...]}',
        ]
    )
    return system_prompt, "\n".join(parts)


@dataclass
class TranslationStyle:
    """Optional guidance from the user: a glossary and free-form notes about the show."""

    glossary: list[tuple[str, Optional[str]]] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def parse(cls, glossary_text: str = "", notes: str = "") -> "TranslationStyle":
        """Glossary lines are ``term = translation``; a bare ``term`` means keep it untranslated."""
        entries: list[tuple[str, Optional[str]]] = []
        for raw in (glossary_text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            term, sep, target = line.partition("=")
            term = term.strip()
            if not term:
                continue
            entries.append((term, target.strip() or None if sep else None))
        return cls(glossary=entries[:200], notes=(notes or "").strip()[:1000])

    def key(self) -> str:
        return json.dumps([self.glossary, self.notes], ensure_ascii=False)


def mask_tags(text: str) -> tuple[str, list[str]]:
    """Swap formatting tags for numbered markers the model can keep intact."""
    tags: list[str] = []

    def take(match: "re.Match[str]") -> str:
        tags.append(match.group(0))
        return f"\u27e6{len(tags)}\u27e7"

    return TAG_RE.sub(take, text), tags


def unmask_tags(text: str, tags: Sequence[str]) -> str:
    def put(match: "re.Match[str]") -> str:
        number = int(match.group(0)[1:-1])
        return tags[number - 1] if 1 <= number <= len(tags) else ""

    return PLACEHOLDER_RE.sub(put, text)


def _seconds(stamp: str) -> Optional[float]:
    match = TIME_RE.search(stamp)
    if not match:
        return None
    h, m, sec, frac = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(frac) / (10 ** len(frac))


def char_budget(cue: SubtitleCue) -> Optional[int]:
    """How many characters comfortably fit in this cue at the target reading speed."""
    start, end = _seconds(cue.start), _seconds(cue.end)
    if start is None or end is None or end <= start:
        return None
    return max(10, int((end - start) * TARGET_CPS))


@dataclass
class TranslationReport:
    """What a translation run could not do cleanly, so callers can tell success from partial."""

    total: int = 0
    untranslated: int = 0
    flagged: int = 0
    resumed_batches: int = 0

    @property
    def clean(self) -> bool:
        return self.untranslated == 0


def _check_cancel(should_cancel: Optional[Callable[[], bool]]) -> None:
    if should_cancel is not None and should_cancel():
        raise ModCancelled()


def read_subtitle_text(path: Path, logger: Optional[logging.Logger] = None) -> str:
    """Read a subtitle file, falling back from UTF-8 to UTF-16 (BOM) and then Windows-1252.

    Never substitutes U+FFFD silently: a legacy encoding is logged so the user can check it.
    """
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    for encoding in ("cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if logger is not None:
            logger.warning("%s is not valid UTF-8; read it as %s.", path.name, encoding)
        return text
    return raw.decode("utf-8", errors="replace")


def _translation_problem(source: SubtitleCue, text: str, tags: Sequence[str] = ()) -> Optional[str]:
    """Why a translated cue is not usable as-is, or None. Soft problems still keep the text.

    ``source`` holds the masked text (markers instead of tags); ``tags`` are the tags behind them.
    """
    if not text.strip():
        return "empty"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if any(not ln.strip() for ln in lines):
        return "blank line"
    if len(lines) > max(len(source.lines), 2):
        return "too many lines"
    expected = sorted(PLACEHOLDER_RE.findall(source.text))
    # Accept the markers kept, or the model writing the original tags back itself.
    if sorted(PLACEHOLDER_RE.findall(text)) != expected and sorted(TAG_RE.findall(text)) != sorted(tags):
        return "tags changed"
    budget = char_budget(source)
    if budget is not None and len(text.replace("\n", " ")) > max(budget * 2, 30):
        return "too long to read"
    return None


def _renumber(masked_line: str, offset: int) -> str:
    """Shift the markers of one line so they stay unique across a cue's lines."""
    if not offset:
        return masked_line
    return PLACEHOLDER_RE.sub(lambda m: f"\u27e6{int(m.group(0)[1:-1]) + offset}\u27e7", masked_line)


def _extract_translations(parsed: object) -> dict[int, str]:
    items = parsed.get("translations") if isinstance(parsed, dict) else parsed
    if isinstance(parsed, dict) and items is None:
        # Accept a list under any key.
        for value in parsed.values():
            if isinstance(value, list):
                items = value
                break
    if not isinstance(items, list):
        raise RuntimeError(f"Unexpected response shape: {str(parsed)[:200]}")
    by_id: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            cue_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        text = item.get("text")
        if isinstance(text, str):
            by_id[cue_id] = text
    return by_id


def _request_translations(
    provider: Provider,
    cues: Sequence[SubtitleCue],
    *,
    source_lang: str,
    target_lang: str,
    context_pairs: Sequence[tuple[str, str]],
    lookahead: Sequence[str],
    style: Optional[TranslationStyle],
    logger: logging.Logger,
) -> dict[int, str]:
    """One request. Unusable replies come back as {} so the caller can retry those cues."""
    system_prompt, user_prompt = _build_translation_prompts(
        cues,
        source_lang=source_lang,
        target_lang=target_lang,
        context_pairs=context_pairs,
        lookahead=lookahead,
        style=style,
    )
    try:
        parsed = provider.complete_json(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=TRANSLATE_TEMPERATURE,
        ).data
        return _extract_translations(parsed)
    except AiError as exc:
        if isinstance(exc, InvalidJsonError):
            logger.warning("%s sent a reply that was not valid JSON.", provider.label)
            return {}
        raise
    except RuntimeError as exc:
        logger.warning("%s sent a reply that could not be used: %s", provider.label, exc)
        return {}


def _translate_batch(
    provider: Provider,
    batch: Sequence[SubtitleCue],
    *,
    source_lang: str,
    target_lang: str,
    context_pairs: Sequence[tuple[str, str]],
    lookahead: Sequence[str] = (),
    style: Optional[TranslationStyle] = None,
    logger: logging.Logger,
    should_cancel: Optional[Callable[[], bool]],
    report: TranslationReport,
) -> list[str]:
    """Translate one batch, re-asking only for cues that failed validation.

    Attempt 1 sends the whole batch, attempt 2 only the failures, and the last attempt sends
    them one by one. A cue that never validates keeps the model's text when it has some
    (flagged for review), otherwise the source text (counted as untranslated).
    """
    results: dict[int, str] = {}
    fallback: dict[int, str] = {}  # soft failures: usable text with a problem
    pending = list(range(len(batch)))

    # The model sees numbered markers instead of tags; they are put back afterwards.
    tag_lists: list[list[str]] = []
    masked_batch: list[SubtitleCue] = []
    for cue in batch:
        masked_lines, tags = [], []
        for line in cue.lines:
            masked, found = mask_tags(line)
            masked_lines.append(_renumber(masked, len(tags)))
            tags.extend(found)
        tag_lists.append(tags)
        masked_batch.append(SubtitleCue(index=cue.index, start=cue.start, end=cue.end, lines=masked_lines))

    for attempt in range(MAX_REPAIR_ATTEMPTS):
        if not pending:
            break
        last = attempt == MAX_REPAIR_ATTEMPTS - 1
        groups = [[i] for i in pending] if last and len(pending) > 1 else [pending]
        still: list[int] = []
        for group in groups:
            _check_cancel(should_cancel)
            got = _request_translations(
                provider,
                [masked_batch[i] for i in group],
                source_lang=source_lang,
                target_lang=target_lang,
                context_pairs=context_pairs,
                lookahead=lookahead,
                style=style,
                logger=logger,
            )
            for local, i in enumerate(group, start=1):
                text = got.get(local)
                if text is None:
                    still.append(i)
                    continue
                problem = _translation_problem(masked_batch[i], text, tag_lists[i])
                if problem is None:
                    results[i] = text
                else:
                    if text.strip():
                        fallback[i] = text
                    still.append(i)
        if still and not last:
            logger.warning(
                "%s: %d of %d cue(s) in this batch need another try.", provider.label, len(still), len(batch)
            )
        pending = still

    texts: list[str] = []
    for i, cue in enumerate(batch):
        if i in results:
            texts.append(unmask_tags(results[i], tag_lists[i]))
        elif i in fallback:
            report.flagged += 1
            logger.warning(
                "Cue %d may need a check (%s).",
                cue.index,
                _translation_problem(masked_batch[i], fallback[i], tag_lists[i]),
            )
            texts.append(unmask_tags(fallback[i], tag_lists[i]))
        else:
            report.untranslated += 1
            logger.warning("Cue %d could not be translated; keeping its original text.", cue.index)
            texts.append(cue.text)
    return texts


def translate_cues_batch(
    cues: list[SubtitleCue],
    *,
    source_lang: str,
    target_lang: str,
    model: Optional[str],
    logger: logging.Logger,
    on_progress: Optional[Callable[[dict], None]] = None,
    provider: Optional[Provider] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    report: Optional[TranslationReport] = None,
    checkpoint: Optional[dict[int, list[str]]] = None,
    on_batch_done: Optional[Callable[[int, list[str]], None]] = None,
    style: Optional[TranslationStyle] = None,
) -> list[SubtitleCue]:
    """Translate cues batch by batch.

    ``checkpoint`` maps batch number to already translated texts (resume); ``on_batch_done``
    is called with each freshly translated batch so the caller can persist it.
    """
    if not cues:
        return []

    report = report if report is not None else TranslationReport()
    report.total += len(cues)
    provider = provider or get_provider(model)

    translated: list[SubtitleCue] = []
    total_batches = max(1, (len(cues) + TRANSLATE_BATCH_SIZE - 1) // TRANSLATE_BATCH_SIZE)
    for batch_num, batch_start in enumerate(range(0, len(cues), TRANSLATE_BATCH_SIZE), start=1):
        _check_cancel(should_cancel)
        batch = cues[batch_start : batch_start + TRANSLATE_BATCH_SIZE]
        saved = (checkpoint or {}).get(batch_num)
        if saved is not None and len(saved) == len(batch):
            texts = saved
            report.resumed_batches += 1
        else:
            context_pairs = [
                (cues[i].text, translated[i].text)
                for i in range(max(0, batch_start - CONTEXT_CUES), batch_start)
                if i < len(translated)
            ]
            texts = _translate_batch(
                provider,
                batch,
                source_lang=source_lang,
                target_lang=target_lang,
                context_pairs=context_pairs,
                lookahead=[
                    c.text for c in cues[batch_start + len(batch) : batch_start + len(batch) + LOOKAHEAD_CUES]
                ],
                style=style,
                logger=logger,
                should_cancel=should_cancel,
                report=report,
            )
            if on_batch_done is not None:
                on_batch_done(batch_num, texts)

        by_id = {i + 1: text for i, text in enumerate(texts)}
        for cue, text in zip(batch, texts):
            lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            translated.append(SubtitleCue(index=cue.index, start=cue.start, end=cue.end, lines=lines))
        logger.info(
            "Translated cues %d–%d of %d.",
            batch_start + 1,
            batch_start + len(batch),
            len(cues),
        )
        if on_progress is not None:
            cues_done = batch_start + len(batch)
            on_progress(
                {
                    "file_pct": cues_done / len(cues) * 100,
                    "batch": batch_num,
                    "total_batches": total_batches,
                    "status": f"Batch {batch_num}/{total_batches}",
                    "samples": _translation_samples(batch, by_id),
                }
            )

    return translated


def _checkpoint_path(content_hash: str, target_lang: str, model: str) -> Path:
    key = hashlib.sha256(
        f"{content_hash}|{target_lang}|{model}|{TRANSLATE_BATCH_SIZE}".encode("utf-8")
    ).hexdigest()[:24]
    folder = app_data_dir() / "translate_checkpoints"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.json"


def _load_checkpoint(path: Path) -> dict[int, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {int(k): [str(t) for t in v] for k, v in data.items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _write_atomic(dst: Path, text: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, dst)


def process_srt_file(
    src: Path,
    *,
    target_lang: str,
    source_lang: str,
    model: str,
    clean_junk: bool,
    confirmed_removals: Set[str],
    dry_run: bool,
    overwrite: bool,
    logger: logging.Logger,
    file_index: int = 1,
    total_files: int = 1,
    on_progress: Optional[Callable[[dict], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    report: Optional[TranslationReport] = None,
    style: Optional[TranslationStyle] = None,
    remove_junk: bool = False,
) -> Optional[Path]:
    def emit_progress(payload: dict) -> None:
        if on_progress is None:
            return
        file_pct = float(payload.get("file_pct", 0))
        overall = ((file_index - 1) / total_files * 100) + (file_pct / total_files)
        on_progress(
            {
                "pct": overall,
                "title": src.name,
                "status": payload.get("status", "Translating"),
                "samples": payload.get("samples"),
            }
        )
    dst = build_output_path(src, target_lang)
    resolved_source = resolve_source_lang(src, source_lang)

    if dst.resolve() == src.resolve():
        logger.warning("Skip %s: output path equals input.", src.name)
        return None
    if path_exists(dst) and not overwrite:
        logger.warning("Skip %s: output already exists (%s).", src.name, dst.name)
        return None

    content = read_subtitle_text(src, logger)
    cues = parse_srt(content)
    if not cues:
        logger.warning("Skip %s: no cues parsed.", src.name)
        return None

    removed = 0
    if clean_junk and confirmed_removals:
        cues, removed = apply_junk_removals(cues, src, confirmed_removals)
        if removed:
            logger.info("%s: removing %d junk line(s).", src.name, removed)

    if remove_junk:
        cues, auto_removed = remove_auto_junk(cues)
        if auto_removed:
            logger.info("%s: dropping %d ad/credit line(s) before translating.", src.name, auto_removed)
        if not cues:
            logger.warning("Skip %s: nothing left after removing junk lines.", src.name)
            return None

    if dry_run:
        logger.info(
            "Would translate %s -> %s (%d cues, %s -> %s).",
            src.name,
            dst.name,
            len(cues),
            resolved_source,
            target_lang,
        )
        emit_progress({"file_pct": 100, "status": "Preview"})
        return dst

    emit_progress({"file_pct": 0, "status": "Starting"})
    checkpoint_file = _checkpoint_path(
        hashlib.sha256(format_srt(cues).encode("utf-8")).hexdigest(),
        target_lang,
        f"{model or ''}|{resolved_source}|{style.key() if style else ''}",
    )
    saved = _load_checkpoint(checkpoint_file)
    if saved:
        logger.info("Resuming %s: %d batch(es) already translated.", src.name, len(saved))

    def remember(batch_num: int, texts: list[str]) -> None:
        saved[batch_num] = texts
        try:
            _write_atomic(checkpoint_file, json.dumps(saved, ensure_ascii=False))
        except OSError:
            pass

    report = report if report is not None else TranslationReport()
    untranslated_before = report.untranslated
    translated = translate_cues_batch(
        cues,
        source_lang=resolved_source,
        target_lang=target_lang,
        model=model,
        logger=logger,
        on_progress=emit_progress,
        should_cancel=should_cancel,
        report=report,
        checkpoint=saved,
        on_batch_done=remember,
        style=style,
    )
    _write_atomic(dst, format_srt(translated))
    try:
        checkpoint_file.unlink()
    except OSError:
        pass
    logger.info("Wrote %s (%d cues).", dst.name, len(translated))
    missed = report.untranslated - untranslated_before
    if missed:
        logger.warning("%s: %d cue(s) kept their original text.", dst.name, missed)
    return dst


def process_srt_cleanup_file(
    src: Path,
    *,
    confirmed_removals: Set[str],
    dry_run: bool,
    logger: logging.Logger,
) -> int:
    """Remove confirmed junk lines from *src*. Returns lines removed."""
    content = read_subtitle_text(src, logger)
    cues = parse_srt(content)
    if not cues:
        logger.warning("Skip %s: no cues parsed.", src.name)
        return 0

    cues, removed = apply_junk_removals(cues, src, confirmed_removals)
    if removed == 0:
        logger.info("No junk lines to remove in %s.", src.name)
        return 0

    if dry_run:
        logger.info("Would remove %d junk line(s) from %s.", removed, src.name)
        return removed

    src.write_text(format_srt(cues), encoding="utf-8")
    logger.info("Wrote %s (%d junk line(s) removed).", src.name, removed)
    return removed


def plan_translation_files(files: list[Path], target_lang: str, logger: logging.Logger) -> list[Path]:
    """Folder mode: leave out files that are already in the target language, and keep one
    source per output file, so a translation is never translated again."""
    planned: list[Path] = []
    seen: dict[Path, Path] = {}
    for path in files:
        if detect_lang_from_path(path) == target_lang:
            logger.info("Skip %s: already in the target language.", path.name)
            continue
        dst = build_output_path(path, target_lang)
        if dst in seen:
            logger.info("Skip %s: %s is already being translated to %s.", path.name, seen[dst].name, dst.name)
            continue
        seen[dst] = path
        planned.append(path)
    return planned


def run_subtitle_translate(
    args: argparse.Namespace,
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> TranslationReport:
    """Translate one file or a folder. A failing file is reported and the rest carry on.

    Raises ``RuntimeError`` at the end when any file failed, so the job does not end as a
    plain success. Returns the combined report.
    """
    input_path: Path = args.input
    target_lang = normalize_lang_code(args.target_lang) or args.target_lang.lower()
    if not target_lang or target_lang == "auto":
        raise SystemExit("A concrete target language is required.")

    logger = setup_simple_logging(
        "subtitle_translate",
        operation_log_path("subtitle_translate") if not args.dry_run else None,
    )
    logger.info("Subtitle translate: input=%s target=%s dry_run=%s", input_path, target_lang, args.dry_run)

    model = resolve_model(getattr(args, "model", None))
    files = collect_srt_files(input_path)
    if len(files) > 1 or path_is_dir(Path(clean_path_string(str(input_path)))):
        files = plan_translation_files(files, target_lang, logger)
        if not files:
            logger.warning("Nothing to translate.")
            return TranslationReport()
    total = len(files)
    glossary_text = getattr(args, "glossary", "") or ""
    glossary_file = getattr(args, "glossary_file", None)
    if glossary_file:
        glossary_text = read_subtitle_text(Path(glossary_file), logger)
    style = TranslationStyle.parse(glossary_text, getattr(args, "notes", "") or "")
    remove_junk = bool(getattr(args, "remove_junk", True))

    hooks = get_active_hooks()
    progress_cb = hooks.on_progress
    report = TranslationReport()
    failed: list[str] = []
    for i, path in enumerate(files, start=1):
        _check_cancel(should_cancel)
        try:
            process_srt_file(
                path,
                target_lang=target_lang,
                source_lang=args.source_lang,
                model=model,
                clean_junk=False,
                confirmed_removals=set(),
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                logger=logger,
                file_index=i,
                total_files=total,
                on_progress=progress_cb,
                should_cancel=should_cancel,
                report=report,
                style=style,
                remove_junk=remove_junk,
            )
        except AiError as exc:
            # Provider-level problems (bad key, quota, unreachable) hit every file alike.
            logger.error("Stopped at %s: %s", path.name, exc)
            raise
        except ModCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad file must not lose the others
            logger.error("Failed %s: %s", path.name, exc)
            failed.append(path.name)
        if progress_cb is not None:
            progress_cb(
                {
                    "pct": i / total * 100,
                    "title": path.name,
                    "status": "File complete",
                }
            )

    if args.dry_run:
        logger.info("Dry run complete (%d file(s)).", total)
        return report

    logger.info("Translation complete (%d file(s)).", total)
    if report.flagged:
        logger.warning("%d cue(s) may need a check (tags or line breaks changed).", report.flagged)
    if report.untranslated:
        logger.warning("%d cue(s) kept their original text.", report.untranslated)
    if failed:
        raise RuntimeError(f"{len(failed)} of {total} file(s) failed: {', '.join(failed)}")
    return report


def run_subtitle_cleanup(args: argparse.Namespace) -> None:
    input_path: Path = args.input
    logger = setup_simple_logging(
        "subtitle_cleanup",
        operation_log_path("subtitle_cleanup") if not args.dry_run else None,
    )
    logger.info("Subtitle cleanup: input=%s dry_run=%s", input_path, args.dry_run)

    confirmed: set[str] = set(getattr(args, "confirmed_removals", []) or [])
    files = collect_srt_files(input_path)
    total = len(files)

    if not confirmed and not getattr(args, "junk_reviewed", False):
        for path in files:
            for item in scan_junk_in_file(path):
                confirmed.add(item.id)
        if confirmed:
            logger.info("Removing %d junk line(s) (all detected).", len(confirmed))

    if not confirmed:
        logger.info("No junk lines selected for removal.")
        return

    removed_total = 0
    hooks = get_active_hooks()
    for i, path in enumerate(files, start=1):
        if hooks.on_progress is not None:
            hooks.on_progress(
                {"pct": (i - 1) / total * 100, "title": path.name},
            )
        removed_total += process_srt_cleanup_file(
            path,
            confirmed_removals=confirmed,
            dry_run=args.dry_run,
            logger=logger,
        )
        if hooks.on_progress is not None:
            hooks.on_progress({"pct": i / total * 100, "title": path.name})

    if args.dry_run:
        logger.info("Dry run complete (%d junk line(s) across %d file(s)).", removed_total, total)
    else:
        logger.info("Cleanup complete (%d junk line(s) across %d file(s)).", removed_total, total)
