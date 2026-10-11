"""AI-assisted creation of rename format profiles.

The model only *writes a profile* (rules, patterns, a short name); it never renames anything.
The result is validated like any hand-made profile, then verified by running it on the
examples.

There are two ways to ask:

* From ``before -> after`` **examples** the user types. Only those examples are sent.
* From the **folder** the user picked ("suggest from folder names"): a capped sample of the
  real names in that folder (see :func:`build_sample`) is sent too, so the model can see what
  the names look like and infer the pattern. That sends folder names, and the names of a few
  video files inside some folders, to the model provider; file contents are never read. The
  sample is at most :data:`SAMPLE_MAX_NAMES` names, each cut to :data:`SAMPLE_NAME_LEN`
  characters, picked so that every distinct name shape is represented.

After a folder suggestion the tool also picks a few representative names and shows what the
profile does to them (:func:`propose_examples`). The user confirms or corrects those; they
come back as ordinary examples on the next call, and the profile is regenerated against them.
"""

from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .ai import InvalidJsonError, Provider, get_provider
from .ai import usage as ai_usage
from .dates import VIDEO_EXTENSIONS as DATE_VIDEO_EXTENSIONS
from .dates import DateTuple, earliest_date_in_folder
from .rename import SUBTITLE_EXTENSIONS, VIDEO_EXTENSIONS, preview_media_name
from .rename_generic import Item, item_date_source, item_new_stem, preview_generic_name, scan_items
from .rename_profiles import (
    BRACKET_KINDS,
    CASE_MODES,
    PATTERN_TOKENS,
    Profile,
    ProfileError,
    pattern_uses_token,
    profile_from_dict,
)

MODES = ("media", "generic")
MAX_EXAMPLES = 12
MAX_EXAMPLE_LEN = 300
MAX_ATTEMPTS = 2

# What is sent to the model about a folder: never more than this.
SAMPLE_MAX_NAMES = 60
SAMPLE_NAME_LEN = 120
SAMPLE_FOLDERS_WITH_FILES = 12  # folders that also show a few file names inside
SAMPLE_FILES_PER_FOLDER = 3

# Names considered when picking examples to show the user, and how many are shown.
PROPOSAL_POOL = 80
PROPOSAL_POOL_WITH_DATES = 40  # a {date} has to be looked up in each folder, which is slower
PROPOSAL_COUNT = 5

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _system_prompt(mode: str, sampled: bool = False) -> str:
    if mode == "media":
        context = (
            "The tool renames TV episodes and movies. It already finds the show/movie title, "
            "season, episode and year by itself and always turns dots/underscores into spaces "
            "and removes [bracket] tags. Your profile only decides how the *title text* is "
            "cleaned and what the final file name looks like.\n"
            "Patterns: \"tv\" (episodes, tokens "
            + ", ".join("{" + t + "}" for t in PATTERN_TOKENS["tv"])
            + ") and \"movie\" (tokens "
            + ", ".join("{" + t + "}" for t in PATTERN_TOKENS["movie"])
            + "). {code} is like S01E02 (S01E02&E03 for double episodes). Defaults: tv "
            "\"{show} - {code} - {title}\", movie \"{title} ({year})\". Only set a pattern when the "
            "example needs a different one. {season:02} zero-pads to 2 digits; :upper, :lower "
            "and :title change case. A token with no value is dropped together with the "
            "separators around it.\n"
            "\"strip_release_junk\": true removes tags like 1080p/WEB-DL/x265 (default); false keeps them.\n"
            "Leave folder layout alone; you only shape file names."
        )
    else:
        context = (
            "The tool renames folders and/or files by cleaning each name (without extension). "
            "Pattern key: \"generic\" with tokens "
            + ", ".join("{" + t + "}" for t in PATTERN_TOKENS["generic"])
            + ". {name} is the cleaned original name, {parent} the cleaned name of the containing "
            "folder, {n} a 1-based counter among siblings ({n:02} zero-pads). Default pattern "
            "\"{name}\": only set one when the example adds or reorders parts. Set "
            "\"strip_release_junk\" to false.\n"
            "{date} is the earliest date found in the video file names inside a folder; it cannot be "
            "worked out from the example, so only use it when the new names contain a date. Give it a "
            "format after a colon, e.g. \"{date:YYYY MMMM D} - {name}\" (YYYY year, MMMM month name, "
            "MMM short month name, MM month number, DD day with 2 digits, D day). Set \"date_locale\" "
            "to \"nl\" for Dutch month names (juli) or \"en\" for English (July). Folders without a "
            "date are left alone. When a date moves into the pattern, add the \"prune_date\" rule so "
            "an old date in the name is not repeated."
        )
        if sampled:
            context += (
                "\n\nYou also get \"folder_sample\": a SAMPLE of the real names in the user's folder. "
                "The user has not said what the final names should look like unless they give examples. "
                "Infer the patterns you see (dates, release or junk tags, separators, casing, repeated "
                "words, numbering) and propose ONE profile that tidies these names consistently while "
                "keeping what identifies each item. \"similar\" is how many names in the folder share the "
                "shape of that name, so it shows what is common and what is an outlier. "
                "\"date_in_videos\" (folders only) is the earliest date found in the names of the videos "
                "inside that folder and \"files_inside\" shows a few of those file names: use {date} only "
                "when the names clearly carry a date that belongs in the result. \"selected_folder\" marks "
                "the folder the user picked, which is renamed too. Examples the user confirmed or "
                "corrected are ground truth: reproduce them exactly, and let them steer how you "
                "treat the rest of the sample."
            )
    return (
        "You design rename profiles for a file-renaming tool. Reply with ONE JSON object only:\n"
        '{"name": "<short profile name, max 30 chars>", "rules": [...], '
        '"patterns": {...}, "strip_release_junk": true|false, "date_locale": "en"|"nl"}\n\n'
        f"{context}\n\n"
        "Rules run in order over each name. Allowed rule objects:\n"
        '- {"type": "replace", "find": "<text>", "with": "<text>"}  (literal, every occurrence)\n'
        '- {"type": "remove_words", "words": ["a", "b"]}  (whole words, case-insensitive)\n'
        f'- {{"type": "remove_brackets", "brackets": [{", ".join(chr(34) + b + chr(34) for b in BRACKET_KINDS)}]}}'
        "  (removes the bracket AND its content; pick only the kinds needed)\n"
        f'- {{"type": "case", "mode": one of {", ".join(CASE_MODES)}}}\n'
        '- {"type": "regex_replace", "pattern": "<python regex>", "with": "<text>"}  '
        "(last resort, only when nothing simpler works)\n"
        '- {"type": "prune_date"}  (Other mode: removes dates like 2006, 13 juli 2006 or 2006-07-13 from the name)\n\n'
        "Prefer the simplest rules that reproduce ALL examples. Whitespace is collapsed and "
        "leading/trailing spaces, dashes, dots and underscores are trimmed automatically. "
        "Do not invent tokens. Patterns must not contain / or \\. Give a short descriptive "
        "name (e.g. \"Sample pack tidy\")."
    )


def _strip_known_ext(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in VIDEO_EXTENSIONS or suffix in SUBTITLE_EXTENSIONS:
        return name[: -len(suffix)]
    return name


def _strip_shared_suffix(before: str, after: str) -> tuple[str, str]:
    """Drop a file extension present on both sides (Other mode examples)."""
    sb, sa = Path(before).suffix, Path(after).suffix
    if sb and sb.lower() == sa.lower() and len(sb) <= 6 and " " not in sb:
        return before[: -len(sb)], after[: -len(sa)]
    return before, after


def _iso(date: Optional[DateTuple]) -> Optional[str]:
    return None if date is None else f"{date[0]:04d}-{date[1]:02d}-{date[2]:02d}"


def _parse_iso(value: Any) -> Optional[DateTuple]:
    match = _ISO_DATE.match(str(value or ""))
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def _apply(profile: Profile, mode: str, before: str, example: Optional[Dict[str, Any]] = None) -> Optional[str]:
    if mode == "media":
        out = preview_media_name(profile, before)
        return None if out is None else _strip_known_ext(out)
    example = example or {}
    return preview_generic_name(
        profile,
        before,
        parent=example.get("parent") or "Parent",
        n=int(example.get("n") or 1),
        date=_parse_iso(example.get("date")),
    )


def verify_profile(profile: Profile, mode: str, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run *profile* over each example and report whether it gives the expected name.

    An example may say where the name sat (``parent``, ``n``) and which date the videos in the
    folder gave (``date``, ``YYYY-MM-DD``), so a real folder's result can be checked exactly.
    """
    results: List[Dict[str, Any]] = []
    for ex in examples:
        before, after = ex["before"], ex["after"]
        if mode == "media":
            before_c, after_c = _strip_known_ext(before), _strip_known_ext(after)
        else:
            before_c, after_c = _strip_shared_suffix(before, after)
        actual = _apply(profile, mode, before_c, ex)
        results.append(
            {
                "before": before,
                "expected": after,
                "actual": actual,
                "ok": actual == after_c,
            }
        )
    return results


def _clean_examples(examples: Any, *, allow_empty: bool = False) -> List[Dict[str, Any]]:
    if not isinstance(examples, list) or (not examples and not allow_empty):
        raise ProfileError("Give at least one example (before and after).")
    if len(examples) > MAX_EXAMPLES:
        raise ProfileError(f"Use at most {MAX_EXAMPLES} examples.")
    cleaned: List[Dict[str, Any]] = []
    for ex in examples:
        ex = ex or {}
        before = str(ex.get("before", "")).strip()
        after = str(ex.get("after", "")).strip()
        if not before or not after:
            raise ProfileError("Each example needs both a 'before' and an 'after' name.")
        if len(before) > MAX_EXAMPLE_LEN or len(after) > MAX_EXAMPLE_LEN:
            raise ProfileError("Example names are too long.")
        item: Dict[str, Any] = {"before": before, "after": after}
        parent = str(ex.get("parent") or "").strip()
        if parent:
            item["parent"] = parent[:MAX_EXAMPLE_LEN]
        if ex.get("n") is not None:
            try:
                item["n"] = max(1, min(int(ex["n"]), 100000))
            except (TypeError, ValueError):
                raise ProfileError("Example position must be a number.") from None
        if ex.get("date"):
            if _parse_iso(ex["date"]) is None:
                raise ProfileError("Example dates must look like 2006-07-13.")
            item["date"] = str(ex["date"])
        cleaned.append(item)
    return cleaned


# ---------------------------------------------------------------------------
# What the model sees of a folder
# ---------------------------------------------------------------------------


def name_shape(name: str) -> str:
    """A name with its content blanked out, so names built the same way share a shape.

    ``2006-07-13 Holiday [720p]`` -> ``9-9-9 Aa [9a]``: digit runs become ``9`` and letter runs
    ``a`` (lowercase), ``A`` (uppercase) or ``Aa`` (mixed). Punctuation is kept.
    """

    def letters(match: "re.Match[str]") -> str:
        word = match.group(0)
        return "A" if word.isupper() else "a" if word.islower() else "Aa"

    return re.sub(r"\d+", "9", re.sub(r"[^\W\d_]+", letters, name))


def _spread_order(count: int) -> List[int]:
    """Indices 0..count-1 ordered so that any prefix is spread evenly over the range."""
    order: List[int] = []
    queue = deque([(0, count)])
    while queue:
        lo, hi = queue.popleft()
        if lo >= hi:
            continue
        mid = (lo + hi) // 2
        order.append(mid)
        queue.append((lo, mid))
        queue.append((mid + 1, hi))
    return order


def balanced_pick(items: Iterable[Item], limit: int) -> List[Tuple[Item, int]]:
    """Pick up to *limit* items so that every name shape is represented before any repeats.

    Returns ``(item, similar)`` pairs where ``similar`` is the size of the item's shape group.
    The choice is deterministic: groups are visited largest first, and inside a group the items
    are taken evenly spread over the sorted names rather than from the front.
    """
    groups: Dict[Tuple[str, str], List[Item]] = {}
    for item in items:
        groups.setdefault((item.kind, name_shape(item.path.name)), []).append(item)
    ordered = sorted(groups.values(), key=lambda g: (-len(g), g[0].path.name.lower()))
    pools = [[g[i] for i in _spread_order(len(g))] for g in ordered]

    picked: List[Tuple[Item, int]] = []
    depth = 0
    while len(picked) < limit:
        added = False
        for pool in pools:
            if depth < len(pool):
                picked.append((pool[depth], len(pool)))
                added = True
                if len(picked) >= limit:
                    break
        if not added:
            break
        depth += 1
    return picked


@dataclass
class FolderContext:
    """The folder a suggestion is about: what a rename of it would look at."""

    root: Path
    targets: str
    max_depth: int
    include_root: bool
    items: List[Item]
    truncated: bool

    @classmethod
    def scan(cls, root: Path, targets: str, max_depth: int, include_root: bool = False) -> "FolderContext":
        items, truncated = scan_items(root, targets, max_depth, include_root=include_root)
        return cls(root, targets, max_depth, include_root, items, truncated)


def _cut(text: str, length: int = SAMPLE_NAME_LEN) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def _peek_folder(folder: Path) -> Tuple[List[str], Optional[DateTuple]]:
    """A few video file names directly inside *folder*, and the earliest date found in its videos."""
    names: List[str] = []
    try:
        for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_file() and entry.suffix.lower() in DATE_VIDEO_EXTENSIONS:
                names.append(_cut(entry.name))
                if len(names) >= SAMPLE_FILES_PER_FOLDER:
                    break
    except OSError:
        pass
    return names, earliest_date_in_folder(folder)


def build_sample(context: FolderContext) -> Dict[str, Any]:
    """The capped sample of names that is sent to the model, plus a summary for the user.

    ``{"entries": [...], "info": {"sent", "total", "truncated", "shapes"}}``. ``info`` is what the
    interface shows ("40 of 312 names"); ``entries`` is exactly what goes to the model.
    """
    picked = balanced_pick(context.items, SAMPLE_MAX_NAMES)
    shapes = len({(i.kind, name_shape(i.path.name)) for i in context.items})
    entries: List[Dict[str, Any]] = []
    with_files = 0
    for item, similar in picked:
        entry: Dict[str, Any] = {"name": _cut(item.path.name), "kind": item.kind}
        if similar > 1:
            entry["similar"] = similar
        if item.is_root:
            entry["selected_folder"] = True
        if item.kind == "folder" and with_files < SAMPLE_FOLDERS_WITH_FILES:
            inside, date = _peek_folder(item.path)
            if inside:
                entry["files_inside"] = inside
            if date is not None:
                entry["date_in_videos"] = _iso(date)
            if inside or date is not None:
                with_files += 1
        entries.append(entry)
    return {
        "entries": entries,
        "info": {
            "sent": len(entries),
            "total": len(context.items),
            "truncated": context.truncated,
            "shapes": shapes,
            "folders_with_files": with_files,
        },
    }


# ---------------------------------------------------------------------------
# Examples shown back to the user
# ---------------------------------------------------------------------------


def propose_examples(
    profile: Profile,
    context: FolderContext,
    *,
    exclude: Optional[Set[str]] = None,
    count: int = PROPOSAL_COUNT,
) -> List[Dict[str, Any]]:
    """Pick a few representative names from the folder and show what *profile* makes of them.

    The names come from different name shapes (the most common shapes first), and from each shape
    the one the profile changes the most, so the user sees the effect where it matters. The
    result is what a real run would give: real ``{parent}``, ``{n}`` and the real ``{date}`` read
    from the folder's videos. Items a ``{date}`` pattern would skip (no date found) are left out.

    Each entry: ``before``, ``after`` (with the extension for files), ``kind``, ``parent``, ``n``,
    ``date`` (or None) and ``changed``. The entries are ready to be sent back as examples.
    """
    exclude = exclude or set()
    uses_date = pattern_uses_token(profile.pattern("generic"), "date")
    pool_size = PROPOSAL_POOL_WITH_DATES if uses_date else PROPOSAL_POOL
    candidates = [item for item in context.items if item.path.name not in exclude]
    pool = [item for item, _ in balanced_pick(candidates, pool_size)]

    # Group what the profile gives by the shape of the original name.
    groups: Dict[Tuple[str, str], List[Tuple[float, Item, str, str]]] = {}
    for item in pool:
        try:
            new_stem = item_new_stem(profile, item)
        except OSError:
            continue
        if new_stem is None:
            continue
        before = item.path.name
        after = new_stem + (item.path.suffix if item.kind == "file" else "")
        similarity = SequenceMatcher(None, before, after).ratio() if before != after else 1.0
        groups.setdefault((item.kind, name_shape(before)), []).append((similarity, item, before, after))

    # Inside a shape: the most changed name first. Between shapes: those the profile changes come
    # before those it leaves alone (they only fill spare places), then the more common shapes.
    ranked: List[List[Tuple[float, Item, str, str]]] = []
    for members in groups.values():
        ranked.append(sorted(members, key=lambda m: (m[0], m[2].lower())))
    ranked.sort(key=lambda g: (0 if g[0][0] < 1.0 else 1, -len(g), g[0][2].lower()))

    chosen: List[Tuple[float, Item, str, str]] = [g[0] for g in ranked[:count]]
    if len(chosen) < count:  # fewer shapes than wanted: add the next most changed names
        left = [m for g in ranked for m in g[1:]]
        left.sort(key=lambda m: (m[0], m[2].lower()))
        chosen.extend(left[: count - len(chosen)])

    proposals: List[Dict[str, Any]] = []
    for similarity, item, before, after in chosen:
        date = None
        if uses_date:
            source = item_date_source(item)
            date = source() if callable(source) else source
        proposals.append(
            {
                "before": before,
                "after": after,
                "kind": item.kind,
                "parent": item.directory.name,
                "n": item.n,
                "date": _iso(date),
                "changed": before != after,
            }
        )
    return proposals


# ---------------------------------------------------------------------------
# Asking the model
# ---------------------------------------------------------------------------


def _example_for_model(ex: Dict[str, Any]) -> Dict[str, Any]:
    """An example as the model reads it: the names, plus where the item sat if that is known."""
    out: Dict[str, Any] = {"before": ex["before"], "after": ex["after"]}
    if ex.get("parent"):
        out["inside_folder"] = ex["parent"]
    if ex.get("n"):
        out["position_in_folder"] = ex["n"]
    if ex.get("date"):
        out["date_in_videos"] = ex["date"]
    return out


def _user_message(examples: List[Dict[str, Any]], sample: Optional[Dict[str, Any]]) -> str:
    parts: List[str] = []
    if sample is not None:
        info = sample["info"]
        parts.append(
            f"folder_sample ({info['sent']} of {info['total']}{'+' if info['truncated'] else ''} names, "
            "picked so every name shape is represented):\n"
            + json.dumps(sample["entries"], ensure_ascii=False, indent=1)
        )
    if examples:
        heading = "Examples the user confirmed or wrote (before -> after)" if sample is not None else "Examples (before -> after)"
        parts.append(heading + ":\n" + json.dumps([_example_for_model(e) for e in examples], ensure_ascii=False, indent=1))
    elif sample is not None:
        parts.append("The user has not given examples yet. Propose the profile that best tidies this folder's names.")
    return "\n\n".join(parts)


def generate_profile(
    examples: Any,
    mode: str,
    *,
    folder: Optional[FolderContext] = None,
    model: Optional[str] = None,
    provider: Optional[Provider] = None,
) -> Dict[str, Any]:
    """Ask the model for a profile that turns each *before* into its *after*.

    With *folder* (Other mode only) the model also gets a capped sample of the real names in it,
    so *examples* may then be empty, and the result carries ``proposed_examples`` for the user
    to review. Returns ``{"profile", "verification", "all_ok", "attempts", "model", "sample",
    "proposed_examples"}``. The profile is a validated draft (not saved). If the first draft
    misses an example, the mismatch is fed back once for a correction.
    """
    if mode not in MODES:
        raise ProfileError("mode must be 'media' or 'generic'.")
    if folder is not None and mode != "generic":
        raise ProfileError("Suggesting from a folder only works in the Other mode.")
    examples = _clean_examples(examples, allow_empty=folder is not None)
    sample = build_sample(folder) if folder is not None else None
    provider = provider or get_provider(model)

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": _system_prompt(mode, sampled=sample is not None)},
        {"role": "user", "content": _user_message(examples, sample)},
    ]

    best: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with ai_usage.feature("Rename assist"):
                reply = provider.complete_json(messages, temperature=0)
        except InvalidJsonError as exc:
            # Unusable JSON: let the model see what it sent and try again.
            last_error = str(exc)
            messages.append({"role": "assistant", "content": exc.raw})
            messages.append(
                {"role": "user", "content": "That was not valid JSON. Reply with the corrected JSON object only."}
            )
            continue
        messages.append({"role": "assistant", "content": reply.text})

        try:
            data = reply.data
            if isinstance(data, dict):
                data.pop("id", None)  # never trust an id from the model
            profile = profile_from_dict(data)
        except ProfileError as exc:
            last_error = str(exc)
            messages.append(
                {"role": "user", "content": f"That profile was invalid: {exc}. Reply with corrected JSON only."}
            )
            continue

        verification = verify_profile(profile, mode, examples)
        all_ok = all(v["ok"] for v in verification)
        best = {
            "profile": profile.to_dict(),
            "verification": verification,
            "all_ok": all_ok,
            "attempts": attempt,
            "model": provider.model,
            "sample": sample["info"] if sample is not None else None,
            "proposed_examples": [],
            "_profile": profile,
        }
        if all_ok:
            break

        misses = "; ".join(
            f"{v['before']!r} gave {v['actual']!r} but should give {v['expected']!r}"
            for v in verification
            if not v["ok"]
        )
        messages.append(
            {"role": "user", "content": f"Your profile does not reproduce every example: {misses}. Fix it and reply with corrected JSON only."}
        )

    if best is None:
        raise ProfileError(f"The AI did not return a usable profile ({last_error}). Try rewording the example.")

    built: Profile = best.pop("_profile")
    if folder is not None:
        best["proposed_examples"] = propose_examples(built, folder, exclude={ex["before"] for ex in examples})
    return best
