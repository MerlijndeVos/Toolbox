"""Rename mode: TV show / movie / subtitle organizer (plus dedup).

Renames messy media into a clean Plex/Jellyfin/Kodi friendly layout, moves
matching subtitles alongside their video, supports an undo journal, and
includes the ``dedup`` helper that strips duplicate ``(N)`` filename suffixes.
"""

import argparse
import json
import os
import re
import sys
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .log_storage import operation_log_path, rename_undo_journal_path
from .logging_setup import setup_simple_logging
from .paths import copy_path, ext_path, make_dirs, move_path, path_exists
from .rename_profiles import (
    DEFAULT_PATTERNS,
    Profile,
    apply_rules,
    load_profile_spec,
    render_pattern,
    standard_profile,
)
from .text_utils import SMALL_WORDS, title_case  # noqa: F401  (re-exported for callers/tests)

VIDEO_EXTENSIONS: Set[str] = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".ts", ".m2ts", ".mts", ".mpg", ".mpeg", ".vob", ".divx", ".ogm",
}

SUBTITLE_EXTENSIONS: Set[str] = {
    ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".smi", ".sup",
}

# Lowercase tokens that indicate a subtitle language code (ISO 639-1 / common 639-2).
SUB_LANG_TOKENS: Set[str] = {
    "en", "eng", "english", "nl", "dut", "nld", "dutch", "fr", "fra", "fre", "french",
    "de", "ger", "deu", "german", "es", "spa", "spanish", "it", "ita", "italian",
    "pt", "por", "portuguese", "pob", "sv", "swe", "swedish", "no", "nor", "norwegian",
    "da", "dan", "danish", "fi", "fin", "finnish", "pl", "pol", "polish", "ru", "rus",
    "russian", "ja", "jpn", "japanese", "zh", "chi", "zho", "chinese", "ko", "kor",
    "korean", "ar", "ara", "arabic", "tr", "tur", "turkish", "cs", "cze", "ces", "hu",
    "hun", "el", "gre", "ell", "he", "heb", "th", "tha", "vi", "vie", "ro", "ron", "rum",
    "uk", "ukr", "hr", "hrv", "sr", "srp", "sk", "slk", "slo", "sl", "slv", "bg", "bul",
    "et", "est", "lv", "lav", "lt", "lit", "id", "ind", "ms", "msa", "hi", "hin",
}

# Lowercase tokens that flag special subtitle variants (kept on the renamed sub).
SUB_FLAG_TOKENS: Set[str] = {"forced", "sdh", "cc", "hi", "default", "foreign"}

# Junk / release-info tokens stripped from titles. Matched case-insensitively as
# whole words on a space-normalized string.
JUNK_PATTERNS: List[str] = [
    r"\b\d{3,4}p\b", r"\b4k\b", r"\b2160p\b",
    r"\bweb[-\s]?dl\b", r"\bweb[-\s]?rip\b", r"\bwebrip\b", r"\bweb\b",
    r"\bblu[-\s]?ray\b", r"\bbluray\b", r"\bbrrip\b", r"\bbdrip\b", r"\bbdremux\b",
    r"\bhdtv\b", r"\bpdtv\b", r"\bdvdrip\b", r"\bdvdscr\b", r"\bdvd\b", r"\bhdrip\b",
    r"\bhddvd\b", r"\bcam\b", r"\bts\b", r"\btc\b", r"\bremux\b",
    r"\bx264\b", r"\bx265\b", r"\bh[-\s]?264\b", r"\bh[-\s]?265\b", r"\bhevc\b",
    r"\bavc\b", r"\bxvid\b", r"\bdivx\b", r"\bvp9\b", r"\bav1\b",
    r"\baac\d?\b", r"\bac3\b", r"\beac3\b", r"\bdts[-\s]?hd\b", r"\bdts\b",
    r"\btruehd\b", r"\batmos\b", r"\bdd[p]?\s?\d[\s.]?\d\b", r"\bflac\b", r"\bmp3\b",
    r"\bopus\b", r"\b\d[\s.]1\b",
    r"\b10\s?bit\b", r"\b8\s?bit\b", r"\bhdr10\+?\b", r"\bhdr\b", r"\bsdr\b",
    r"\bdolby\s?vision\b", r"\bdovi\b",
    r"\bproper\b", r"\brepack\b", r"\binternal\b", r"\breal\b", r"\buncut\b",
    r"\bamzn\b", r"\bnf\b", r"\bdsnp\b", r"\bhmax\b", r"\batvp\b", r"\bhulu\b", r"\bmax\b",
    r"\bremastered\b", r"\bextended\b", r"\bunrated\b", r"\btheatrical\b", r"\bimax\b",
    r"\bedition\b",
    r"\b\d\s?ch\b", r"\bre[-\s.]?enc(?:ode|oded)?\b", r"\bdual\b", r"\bmulti\b",
]
JUNK_RE = re.compile("|".join(JUNK_PATTERNS), re.IGNORECASE)

# The optional multi-episode group deliberately forbids whitespace before the
# second number (uses [._&+-] not [\s._&+-]) so a spaced title number like
# 'S02E09 - 4 Days Out' is NOT misread as the range 'S02E09-E04'. Real ranges
# (S01E01-E02, S01E01-02, S01E01E02, S01E01&E02, S01E01+E02) are written tightly
# without spaces. '&' and '+' join double episodes (e.g. 'S03E14&E15').
RE_SXXEXX = re.compile(
    r"\bS(\d{1,2})[\s._-]?E(\d{1,3})(?:[._&+-]*E?(\d{1,3}))?\b", re.IGNORECASE
)
RE_XFORMAT = re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{1,3})(?:[._&+-]*x?(\d{1,3}))?\b", re.IGNORECASE)
RE_SEASON_WORD = re.compile(r"\bseason[\s._-]*(\d{1,2}).*?episode[\s._-]*(\d{1,3})\b", re.IGNORECASE)
RE_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
RE_BRACKETS = re.compile(r"[\[\{][^\]\}]*[\]\}]")
# A standalone 1-3 digit number at the very end (not part of a longer number/year).
# Used by --bare-episode-numbers to treat 'Show 36' as Season 1, Episode 36.
RE_TRAILING_NUM = re.compile(r"(?<!\d)(\d{1,3})\s*$")
# A standalone 1-3 digit number that splits a show name from an optional episode
# title. Used by --bare-episode-numbers to treat 'Niels Holgersson 1 De kabouter'
# as Season 1, Episode 1, title 'De kabouter' (the title group is optional so a
# trailing 'Show 36' still works). The non-greedy show keeps the first such number.
RE_BARE_EP = re.compile(r"^(?P<show>.+?)\s+(?P<ep>\d{1,3})(?!\d)(?:\s+(?P<title>.+))?$")


@dataclass
class MediaInfo:
    kind: str  # "tv" or "movie"
    title: str
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_end: Optional[int] = None
    episode_title: Optional[str] = None


@dataclass
class RenameOp:
    src: Path
    dst: Path
    kind: str  # "video" or "subtitle"


def _collapse_acronyms(text: str) -> str:
    """Collapse dotted acronyms so they survive separator normalization.

    'I.F.T.' -> 'IFT', 'S.W.A.T.' -> 'SWAT'. Only sequences of 2+ single
    letters each followed by a dot are affected, so 'Mr.' is left untouched.
    """
    return re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda m: m.group(0).replace(".", ""), text)


def _strip_release_parens(text: str) -> str:
    """Remove (...) groups that contain release/quality junk.

    e.g. '(1080p BluRay x265 Silence)' is dropped entirely (including the
    trailing scene-group word), while a wrapped year like '(2008)' is preserved.
    A group containing a year is kept (so '(2006 1080p)' keeps the year, with
    its quality token cleaned up later).
    """
    return re.sub(
        r"\(([^()]*)\)",
        lambda m: ""
        if (JUNK_RE.search(m.group(1)) and not RE_YEAR.search(m.group(1)))
        else m.group(0),
        text,
    )


def normalize_separators(text: str) -> str:
    # Drop bracketed release tags like [RARBG] or {edition}; collapse dotted
    # acronyms; drop parenthetical release info (e.g. '(1080p x265 Silence)');
    # then turn ._() into spaces (a wrapped year survives as a bare number).
    text = RE_BRACKETS.sub(" ", text)
    text = _collapse_acronyms(text)
    text = _strip_release_parens(text)
    text = re.sub(r"[._()]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -._")


def strip_trailing_group(text: str) -> str:
    """Remove a trailing scene release group like ' -GROUP' or ' - RARBG'.

    Requires whitespace before the dash so legitimate hyphenated words
    (e.g. 'Spider-Man') and titles are preserved.
    """
    return re.sub(r"\s+-\s*[A-Za-z0-9]+\s*$", "", text).strip(" -._")


def remove_junk(text: str) -> str:
    text = JUNK_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -._")


def _junk(text: str, strip_junk: bool) -> str:
    """remove_junk, or just whitespace tidying when the profile keeps release tags."""
    if strip_junk:
        return remove_junk(text)
    return re.sub(r"\s+", " ", text).strip(" -._")


def strip_release_group(text: str) -> str:
    """Remove a trailing scene release group like '-LUMI' or '-RARBG'.

    Unlike strip_trailing_group, this also handles groups attached directly to a
    preceding token without whitespace (e.g. 'ReEnc-LUMI'). To avoid harming real
    hyphenated titles (e.g. 'Spider-Man', 'Catch-22'), it only acts when the text
    clearly looks like a release -- i.e. it contains at least one known junk tag
    (resolution, codec, source, etc.).
    """
    if JUNK_RE.search(text):
        text = re.sub(r"-[A-Za-z0-9]{2,}\s*$", "", text)
    return text


def strip_trailing_words(text: str, words: Set[str]) -> str:
    """Remove trailing whole words (case-insensitive) that appear in *words*.

    Handy for dropping a release-group word that survived junk removal, e.g.
    'Pilot Silence' -> 'Pilot' when words={'silence'}. Returns '' if every
    word was stripped.
    """
    if not words or not text:
        return text
    parts = text.split(" ")
    while parts and parts[-1].lower() in words:
        parts.pop()
    return " ".join(parts).strip(" -._")


def longest_common_movie_prefix(titles: List[str]) -> Optional[str]:
    """Return a shared franchise prefix when several movie titles start the same way.

    Requires at least two titles, a prefix of two or more words, and a suffix of
    at least two words on every title so we don't split unrelated pairs like
    'The Dark Knight' / 'The Dark Tower'.
    """
    if len(titles) < 2:
        return None
    word_lists = [t.split() for t in titles if t]
    if len(word_lists) < 2:
        return None

    prefix_len = 0
    for i in range(len(word_lists[0])):
        word = word_lists[0][i]
        if all(i < len(words) and words[i].lower() == word.lower() for words in word_lists[1:]):
            prefix_len = i + 1
        else:
            break

    if prefix_len < 2:
        return None
    if any(len(words) <= prefix_len + 1 for words in word_lists):
        return None

    return " ".join(word_lists[0][:prefix_len])


def apply_franchise_separator(
    title: str,
    common_prefix: str,
    titlecase_enabled: bool,
) -> str:
    """Format a shared franchise prefix as 'Franchise - Subtitle'."""
    title_words = title.split()
    prefix_words = common_prefix.split()
    if len(title_words) <= len(prefix_words):
        return title
    if [w.lower() for w in title_words[: len(prefix_words)]] != [
        w.lower() for w in prefix_words
    ]:
        return title
    prefix = " ".join(title_words[: len(prefix_words)])
    suffix = title_case(" ".join(title_words[len(prefix_words) :]), titlecase_enabled)
    if not suffix:
        return title
    return f"{prefix} - {suffix}"


def parse_media_info(
    stem: str,
    forced_type: str,
    titlecase_enabled: bool,
    strip_words: Optional[Set[str]] = None,
    bare_numbers: bool = False,
    strip_junk: bool = True,
) -> Optional[MediaInfo]:
    """Parse a video file stem into TV or movie info. Returns None if unclassifiable."""
    strip_words = strip_words or set()
    if forced_type in ("auto", "tv"):
        # Auto and TV modes accept bare episode numbers (e.g. 'Show Name 47 Title')
        # after standard SxxExx / 1x01 patterns. The CLI --bare-episode-numbers flag
        # is kept for explicit opt-in when calling _parse_tv in isolation.
        use_bare = bare_numbers or forced_type in ("auto", "tv")
        info = _parse_tv(
            stem, titlecase_enabled, strip_words, bare_numbers=use_bare, strip_junk=strip_junk
        )
        if info is not None:
            return info
        if forced_type == "tv":
            return None

    if forced_type in ("auto", "movie"):
        # In auto mode require a year so we don't reorganize unrelated files;
        # when the user forces --type movie we accept titles without a year.
        return _parse_movie(
            stem,
            titlecase_enabled,
            strip_words,
            require_year=(forced_type == "auto"),
            strip_junk=strip_junk,
        )

    return None


def _parse_tv(
    stem: str,
    titlecase_enabled: bool,
    strip_words: Optional[Set[str]] = None,
    bare_numbers: bool = False,
    strip_junk: bool = True,
) -> Optional[MediaInfo]:
    strip_words = strip_words or set()
    season = episode = episode_end = None
    split_at = end_at = None

    for rx in (RE_SXXEXX, RE_XFORMAT, RE_SEASON_WORD):
        m = rx.search(stem)
        if m:
            season, episode = int(m.group(1)), int(m.group(2))
            if rx is not RE_SEASON_WORD and m.lastindex and m.lastindex >= 3 and m.group(3):
                episode_end = int(m.group(3))
            split_at, end_at = m.start(), m.end()
            break

    # A multi-episode range must strictly increase; otherwise it is spurious
    # (e.g. a stray title number wrongly captured as the range end).
    if episode_end is not None and episode is not None and episode_end <= episode:
        episode_end = None

    if season is None:
        # Optional fallback: a bare number means Season 1, that episode. Handles
        # both a trailing number ('Full Metal Alchemist Brotherhood 36' -> S01E36)
        # and a number followed by an episode title
        # ('Niels Holgersson 1 De kabouter' -> S01E01 - De kabouter).
        if not bare_numbers:
            return None
        cleaned = _junk(normalize_separators(stem), strip_junk)
        bm = RE_BARE_EP.search(cleaned)
        if not bm:
            return None
        show = title_case(strip_trailing_group(bm.group("show")), titlecase_enabled)
        if not show:
            return None
        # Re-wrap a trailing year as 'Name (2008)' to match the SxxExx path.
        show = re.sub(r"\s+((?:19|20)\d{2})$", r" (\1)", show)
        episode_title = None
        title_part = bm.group("title")
        if title_part:
            tail = strip_trailing_group(_junk(normalize_separators(title_part), strip_junk))
            tail = strip_trailing_words(tail, strip_words)
            episode_title = title_case(tail, titlecase_enabled) if tail else None
        return MediaInfo(
            kind="tv",
            title=show,
            season=1,
            episode=int(bm.group("ep")),
            episode_title=episode_title,
        )

    show = title_case(_junk(normalize_separators(stem[:split_at]), strip_junk), titlecase_enabled)
    if not show:
        return None

    # Re-wrap a trailing year as 'Name (2008)' (Plex/Jellyfin style) instead of
    # the flattened 'Name 2008' left after separator normalization.
    show = re.sub(r"\s+((?:19|20)\d{2})$", r" (\1)", show)

    # Drop a scene group attached to the tail (e.g. 'ReEnc-LUMI') before cleaning,
    # then strip the usual junk/release tags so we don't keep a fake episode title.
    tail_raw = strip_release_group(stem[end_at:]) if strip_junk else stem[end_at:]
    tail = strip_trailing_group(_junk(normalize_separators(tail_raw), strip_junk))
    tail = strip_trailing_words(tail, strip_words)
    episode_title = title_case(tail, titlecase_enabled) if tail else None

    return MediaInfo(
        kind="tv",
        title=show,
        season=season,
        episode=episode,
        episode_end=episode_end,
        episode_title=episode_title,
    )


def _parse_movie(
    stem: str,
    titlecase_enabled: bool,
    strip_words: Optional[Set[str]] = None,
    require_year: bool = False,
    strip_junk: bool = True,
) -> Optional[MediaInfo]:
    strip_words = strip_words or set()
    cleaned = normalize_separators(stem)
    year = None
    title_part = cleaned

    # Prefer the last year that is not at the very start (a leading year is likely the title).
    chosen = None
    for mt in RE_YEAR.finditer(cleaned):
        if mt.start() == 0:
            continue
        chosen = mt
    if chosen is not None:
        year = int(chosen.group(1))
        title_part = cleaned[: chosen.start()]
        # In auto mode a real movie has its year at the end (only release junk
        # may trail it). If meaningful words follow the year, this is probably a
        # featurette/extra like 'Gallery 1988 Art Show', not a movie -> reject.
        if require_year:
            trailing = remove_junk(cleaned[chosen.end():])
            if trailing:
                return None

    if require_year and year is None:
        return None

    title = strip_trailing_group(
        title_case(_junk(normalize_separators(title_part), strip_junk), titlecase_enabled)
    )
    if not title:
        title = strip_trailing_group(title_case(_junk(cleaned, strip_junk), titlecase_enabled))
    title = strip_trailing_words(title, strip_words)
    if not title:
        return None

    return MediaInfo(kind="movie", title=title, year=year)


def _is_subtitle_tag(token: str) -> bool:
    """True when a trailing dotted token is a language or flag tag rather than a title word.

    Tags are written ``en``, ``EN`` or ``English``. A short Capitalised token such as ``It``,
    ``No`` or ``Hi`` is a word in the title ("Where.Is.It"), not Italian, Norwegian or Hindi.
    """
    lowered = token.lower()
    if lowered not in SUB_LANG_TOKENS and lowered not in SUB_FLAG_TOKENS:
        return False
    if len(token) <= 3 and token[:1].isupper() and token[1:].islower():
        return False
    return True


def split_subtitle_suffix(stem: str) -> Tuple[str, str]:
    """Split a subtitle stem into (base_stem, suffix) where suffix holds trailing
    language/flag tags. Suffix is returned without a leading dot.

    e.g. 'Show.S01E01.en.forced' -> ('Show.S01E01', 'en.forced')
    """
    parts = stem.split(".")
    suffix_parts: List[str] = []
    while len(parts) > 1:
        last = parts[-1].lower()
        if _is_subtitle_tag(parts[-1]):
            suffix_parts.insert(0, parts[-1])
            parts = parts[:-1]
        else:
            break
    return ".".join(parts), ".".join(suffix_parts)


def suffix_has_language(suffix: str) -> bool:
    """True if a subtitle suffix already carries a language token (vs. only
    flag tokens like 'forced'/'sdh', or being empty)."""
    return any(tok.lower() in SUB_LANG_TOKENS for tok in suffix.split(".") if tok)


def apply_default_sub_language(suffix: str, default_lang: Optional[str]) -> str:
    """Ensure a subtitle suffix carries a language code, defaulting untagged
    subtitles to *default_lang* (e.g. 'Show.srt' -> 'Show.en.srt').

    The default language is prepended ahead of any flag tokens so a forced
    track without a language becomes e.g. 'en.forced'. Subtitles that already
    name a language are left untouched. Passing a falsy *default_lang* disables
    the behavior.
    """
    if not default_lang or suffix_has_language(suffix):
        return suffix
    return f"{default_lang}.{suffix}" if suffix else default_lang


def reserve_name(
    dest_dir: Path,
    base_stem: str,
    extension: str,
    used: Set[str],
    ignore_path: Optional[Path] = None,
) -> str:
    """Return a unique filename within dest_dir, honoring already-used/planned names.

    *ignore_path* is the source file being renamed; an existing file at that exact
    path must not count as a collision, otherwise an already-correctly-named file
    would be needlessly bumped to a ' (2)' suffix.
    """
    ignore_norm = (
        os.path.normcase(os.path.abspath(ext_path(ignore_path)))
        if ignore_path is not None
        else None
    )

    def occupied(path: Path) -> bool:
        if not path_exists(path):
            return False
        if ignore_norm is not None and (
            os.path.normcase(os.path.abspath(ext_path(path))) == ignore_norm
        ):
            return False
        return True

    candidate = f"{base_stem}{extension}"
    key = candidate.lower()
    idx = 2
    while key in used or occupied(dest_dir / candidate):
        candidate = f"{base_stem} ({idx}){extension}"
        key = candidate.lower()
        idx += 1
    used.add(key)
    return candidate


def sanitize_component(name: str) -> str:
    """Sanitize a single path component (folder or file stem) for Windows."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned or "Unknown"


def _show_key(text: str) -> str:
    """Comparison key for a show/movie title that ignores any embedded year and
    punctuation, e.g. 'Breaking Bad (2008)' and 'Breaking Bad' share the key
    'breaking bad'."""
    return _norm_key(RE_YEAR.sub(" ", text))


def _folder_is_title(folder_name: str, title: str) -> bool:
    """True if *folder_name* already represents *title* (ignoring a year and
    punctuation), e.g. 'Game of Thrones (2011)' matches show 'Game of Thrones'.

    Used to avoid creating a redundant nested show/movie folder when the rename
    runs in place with the destination root already being that title's folder.
    """
    fk = _show_key(folder_name)
    return bool(fk) and fk == _show_key(title)


def existing_show_folder_name(
    video: Path, input_root: Path, title: str
) -> Optional[str]:
    """Return the name of an existing ancestor folder of *video* (at or under
    *input_root*) that represents *title* ignoring year/punctuation.

    The on-disk folder name is treated as authoritative for the show's spelling
    and year, so e.g. a file 'Breaking Bad 2008 - S01E01' living under a folder
    named 'Breaking Bad' keeps the show name 'Breaking Bad' (no year added),
    instead of being moved into a new 'Breaking Bad (2008)' folder.
    """
    key = _show_key(title)
    if not key:
        return None
    parent = video.parent
    while True:
        if _show_key(parent.name) == key:
            return parent.name
        if parent == input_root:
            break
        nxt = parent.parent
        if nxt == parent:
            break
        parent = nxt
    return None


def _episode_code(info: MediaInfo) -> str:
    if info.episode_end:
        return f"S{info.season:02d}E{info.episode:02d}&E{info.episode_end:02d}"
    return f"S{info.season:02d}E{info.episode:02d}"


def render_media_stem(info: MediaInfo, profile: Optional[Profile] = None) -> str:
    """Build the file name stem for *info* from the profile's tv/movie pattern."""
    if info.kind == "tv":
        year_match = re.search(r"\(((?:19|20)\d{2})\)\s*$", info.title)
        values = {
            "show": info.title,
            "season": info.season,
            "episode": info.episode,
            "episode_end": info.episode_end,
            "code": _episode_code(info),
            "title": info.episode_title or "",
            "year": year_match.group(1) if year_match else "",
        }
        pattern = profile.pattern("tv") if profile else DEFAULT_PATTERNS["tv"]
    else:
        values = {"title": info.title, "year": info.year or ""}
        pattern = profile.pattern("movie") if profile else DEFAULT_PATTERNS["movie"]
    return sanitize_component(render_pattern(pattern, values))


def build_target_dir_and_stem(
    info: MediaInfo, dest_root: Path, profile: Optional[Profile] = None
) -> Tuple[Path, str]:
    stem = render_media_stem(info, profile)
    if info.kind == "tv":
        show = sanitize_component(info.title)
        season_folder = f"Season {info.season:02d}"
        # If dest_root is already this show's folder, don't nest another one.
        if _folder_is_title(dest_root.name, info.title):
            target_dir = dest_root / season_folder
        else:
            target_dir = dest_root / show / season_folder
        return target_dir, stem

    # movie: the folder is always "Title (Year)"; only the file name follows the pattern.
    folder = f"{info.title} ({info.year})" if info.year else info.title
    folder = sanitize_component(folder)
    # If dest_root is already this movie's folder, place the file directly in it.
    if _folder_is_title(dest_root.name, info.title):
        target_dir = dest_root
    else:
        target_dir = dest_root / folder
    return target_dir, stem


def scan_directory_group(
    files: List[Path],
) -> Tuple[List[Path], List[Path]]:
    """Split a directory's files into (videos, subtitles)."""
    videos = [f for f in files if f.suffix.lower() in VIDEO_EXTENSIONS]
    subs = [f for f in files if f.suffix.lower() in SUBTITLE_EXTENSIONS]
    return videos, subs


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def match_subtitle_to_video(sub: Path, videos: List[Path]) -> Optional[Path]:
    """Find the video a subtitle belongs to within the same directory."""
    if not videos:
        return None

    base, _suffix = split_subtitle_suffix(sub.stem)
    base_key = _norm_key(base)

    # 1) Exact normalized stem match.
    for v in videos:
        if _norm_key(v.stem) == base_key:
            return v

    # 2) Single video in the folder -> assume it owns the subtitle.
    if len(videos) == 1:
        return videos[0]

    # 3) Signature match via the same parser (TV: season+episode, movie: year).
    sub_info = parse_media_info(base, "auto", True)
    if sub_info is not None:
        for v in videos:
            v_info = parse_media_info(v.stem, "auto", True)
            if v_info is None or v_info.kind != sub_info.kind:
                continue
            if sub_info.kind == "tv" and (v_info.season, v_info.episode) == (sub_info.season, sub_info.episode):
                return v
            if sub_info.kind == "movie" and v_info.year == sub_info.year and _norm_key(v_info.title) == _norm_key(sub_info.title):
                return v

    # 4) Longest normalized-prefix match in either direction.
    best: Optional[Path] = None
    best_len = 0
    for v in videos:
        vk = _norm_key(v.stem)
        if (base_key.startswith(vk) or vk.startswith(base_key)) and len(vk) > best_len:
            best, best_len = v, len(vk)
    return best


def _apply_profile_to_info(info: MediaInfo, profile: Profile) -> None:
    """Run the profile's cleanup rules over the parsed title fields."""
    title = apply_rules(info.title, profile.rules, keep_year_parens=True)
    info.title = title or info.title
    if info.episode_title:
        info.episode_title = apply_rules(info.episode_title, profile.rules, keep_year_parens=True) or None


def preview_media_name(
    profile: Profile,
    filename: str,
    forced_type: str = "auto",
) -> Optional[str]:
    """Return the new file name for a single sample (no folder layout), or None if
    the name cannot be classified as an episode/movie. Used by the profile tester
    and to verify AI-generated profiles."""
    suffix = Path(filename).suffix
    known = suffix.lower() in VIDEO_EXTENSIONS or suffix.lower() in SUBTITLE_EXTENSIONS
    stem = filename[: -len(suffix)] if known else filename
    ext = suffix.lower() if known else ""
    info = parse_media_info(
        stem, forced_type, False, None, False, strip_junk=profile.strip_release_junk
    )
    if info is None:
        return None
    _apply_profile_to_info(info, profile)
    return render_media_stem(info, profile) + ext


def plan_rename(
    input_root: Path,
    dest_root: Path,
    forced_type: str,
    titlecase_enabled: bool,
    logger: logging.Logger,
    strip_words: Optional[Set[str]] = None,
    bare_numbers: bool = False,
    default_sub_lang: Optional[str] = "en",
    profile: Optional[Profile] = None,
    layout: bool = True,
) -> Tuple[List[RenameOp], List[Tuple[Path, str]]]:
    """Build the list of rename operations and a list of (path, reason) skips.

    *profile* supplies cleanup rules and name patterns (default: the historic
    Title Case + release-tag cleanup). With ``layout=False`` files keep their
    folder (mirrored under *dest_root*) instead of moving into ``Show/Season NN``.
    """
    ops: List[RenameOp] = []
    skipped: List[Tuple[Path, str]] = []
    strip_words = strip_words or set()
    if profile is None:
        profile = standard_profile(title_case_enabled=titlecase_enabled)
    titlecase_enabled = profile.title_case

    # Track reserved names per destination directory to avoid collisions.
    used_by_dir: Dict[str, Set[str]] = {}

    # Group source files by their containing directory.
    files_by_dir: Dict[Path, List[Path]] = {}
    for p in input_root.rglob("*"):
        if p.is_file():
            files_by_dir.setdefault(p.parent, []).append(p)

    for directory in sorted(files_by_dir, key=lambda d: str(d).lower()):
        videos, subs = scan_directory_group(files_by_dir[directory])

        # Map each video to its planned target so subtitles can follow.
        video_targets: Dict[Path, Tuple[Path, str]] = {}
        parsed_videos: List[Tuple[Path, MediaInfo]] = []

        for video in sorted(videos, key=lambda v: v.name.lower()):
            # Casing is done by the profile's rules below, not by the parser.
            info = parse_media_info(
                video.stem,
                forced_type,
                False,
                strip_words,
                bare_numbers,
                strip_junk=profile.strip_release_junk,
            )
            if info is None:
                skipped.append((video, "could not classify (no SxxExx / year)"))
                continue
            _apply_profile_to_info(info, profile)

            # Respect an existing show folder: if the file already lives under a
            # folder that represents this show (ignoring year/punctuation), keep
            # that folder's exact name as the show title so we neither add nor
            # drop a year against the on-disk layout.
            if info.kind == "tv":
                existing = existing_show_folder_name(video, input_root, info.title)
                if existing:
                    info.title = existing

            parsed_videos.append((video, info))

        movie_titles = [info.title for _, info in parsed_videos if info.kind == "movie"]
        franchise_prefix = longest_common_movie_prefix(movie_titles)

        for video, info in parsed_videos:
            if info.kind == "movie" and franchise_prefix:
                info.title = apply_franchise_separator(
                    info.title, franchise_prefix, titlecase_enabled
                )

            target_dir, base_stem = build_target_dir_and_stem(info, dest_root, profile)
            if not layout:
                target_dir = dest_root / video.parent.relative_to(input_root)
            used = used_by_dir.setdefault(str(target_dir).lower(), set())
            ext = video.suffix.lower()
            new_name = reserve_name(target_dir, base_stem, ext, used, ignore_path=video)
            dst = target_dir / new_name

            video_targets[video] = (target_dir, Path(new_name).stem)

            if dst == video:
                skipped.append((video, "already correctly named"))
                continue
            ops.append(RenameOp(src=video, dst=dst, kind="video"))

        # Attach subtitles to their videos.
        for sub in sorted(subs, key=lambda s: s.name.lower()):
            owner = match_subtitle_to_video(sub, videos)
            if owner is None or owner not in video_targets:
                skipped.append((sub, "no matching video in folder"))
                continue
            target_dir, video_stem = video_targets[owner]
            _base, suffix = split_subtitle_suffix(sub.stem)
            suffix = apply_default_sub_language(suffix, default_sub_lang)
            used = used_by_dir.setdefault(str(target_dir).lower(), set())
            ext = sub.suffix.lower()
            sub_stem = f"{video_stem}.{suffix}" if suffix else video_stem
            # reserve_name appends " (2)" before extension if needed; build full stem first.
            new_name = reserve_name(target_dir, sub_stem, ext, used, ignore_path=sub)
            dst = target_dir / new_name
            if dst == sub:
                skipped.append((sub, "already correctly named"))
                continue
            ops.append(RenameOp(src=sub, dst=dst, kind="subtitle"))

    return ops, skipped


def execute_rename(
    ops: List[RenameOp],
    use_copy: bool,
    logger: logging.Logger,
) -> Tuple[int, int, List[RenameOp]]:
    """Perform the planned operations.

    Returns (succeeded, failed, done) where *done* is the list of operations
    that completed, so the caller can record them in an undo journal.
    """
    succeeded = 0
    failed = 0
    done: List[RenameOp] = []
    verb = "Copying" if use_copy else "Moving"
    for op in ops:
        try:
            make_dirs(op.dst.parent)
            logger.info("%s [%s] '%s' -> '%s'", verb, op.kind, op.src, op.dst)
            if use_copy:
                copy_path(op.src, op.dst)
            else:
                move_path(op.src, op.dst)
            succeeded += 1
            done.append(op)
        except Exception as exc:
            logger.error("FAILED to process '%s' -> '%s': %s", op.src, op.dst, exc)
            failed += 1
    return succeeded, failed, done


# Legacy name when journals lived next to the destination (removed on write/migrate).
LEGACY_UNDO_JOURNAL_NAME = "rename_undo.json"
UNDO_JOURNAL_NAME = LEGACY_UNDO_JOURNAL_NAME  # backwards compat for imports/tests


def undo_journal_path(dest_root: Path) -> Path:
    return rename_undo_journal_path(dest_root)


def legacy_undo_journal_path(dest_root: Path) -> Path:
    return dest_root / LEGACY_UNDO_JOURNAL_NAME


def build_undo_journal(
    done: List[RenameOp],
    use_copy: bool,
    *,
    dest_root: Optional[Path] = None,
    input_root: Optional[Path] = None,
    mode: str = "media",
    renamed_root: Optional[dict] = None,
) -> dict:
    """Build a structured undo manifest from completed rename operations.

    *renamed_root* (``{"from": old path, "to": new path}``) is set when the selected folder itself
    was renamed, so callers can point at the new path.
    """
    manifest = {
        "version": 1,
        "mode": mode,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": "copy" if use_copy else "move",
        "dest_root": str(dest_root) if dest_root is not None else None,
        "input_root": str(input_root) if input_root is not None else None,
        "operations": [
            {"src": str(op.src), "dst": str(op.dst), "kind": op.kind} for op in done
        ],
    }
    if renamed_root:
        manifest["renamed_root"] = renamed_root
    return manifest


def _write_undo_journal_file(path: Path, data: dict, logger: logging.Logger) -> None:
    try:
        make_dirs(path.parent)
        with open(ext_path(path), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        logger.info("Wrote undo journal (%d op(s)): %s", len(data.get("operations", [])), path)
    except Exception as exc:  # journal is best-effort, never fail the run over it
        logger.warning("Could not write undo journal '%s': %s", path, exc)


def _remove_legacy_undo_journal(dest_root: Path, logger: logging.Logger) -> None:
    legacy = legacy_undo_journal_path(dest_root)
    if not path_exists(legacy):
        return
    try:
        os.remove(ext_path(legacy))
        logger.info("Removed legacy undo journal from media folder: %s", legacy)
    except Exception as exc:
        logger.warning("Could not remove legacy undo journal '%s': %s", legacy, exc)


def load_undo_journal(dest_root: Path, logger: logging.Logger) -> Optional[dict]:
    """Load the undo journal for *dest_root*, migrating legacy media-folder copies."""
    path = undo_journal_path(dest_root)
    legacy = legacy_undo_journal_path(dest_root)

    if not path_exists(path) and path_exists(legacy):
        logger.info("Migrating undo journal from media folder to app data.")
        try:
            with open(ext_path(legacy), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.error("Could not read legacy undo journal '%s': %s", legacy, exc)
            return None
        _write_undo_journal_file(path, data, logger)
        _remove_legacy_undo_journal(dest_root, logger)
        return data

    if not path_exists(path):
        return None
    try:
        with open(ext_path(path), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.error("Could not read undo journal '%s': %s", path, exc)
        return None


def write_undo_journal(
    dest_root: Path,
    done: List[RenameOp],
    use_copy: bool,
    logger: logging.Logger,
    *,
    input_root: Optional[Path] = None,
    mode: str = "media",
    renamed_root: Optional[dict] = None,
) -> None:
    """Record completed operations so they can be reversed later.

    Stored under the per-user app data directory, not in the media library.
    Overwrites any previous journal for the same destination root.
    """
    if not done:
        return
    path = undo_journal_path(dest_root)
    data = build_undo_journal(
        done, use_copy, dest_root=dest_root, input_root=input_root, mode=mode,
        renamed_root=renamed_root,
    )
    _write_undo_journal_file(path, data, logger)
    _remove_legacy_undo_journal(dest_root, logger)


def prune_empty_dirs_after_undo(journal: dict, logger: logging.Logger) -> None:
    """Remove empty folders left behind after undoing a rename/copy layout."""
    dirs: Set[Path] = set()
    for entry in journal.get("operations", []):
        dst = Path(entry["dst"])
        for parent in dst.parents:
            dirs.add(parent)

    for current in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            if not path_exists(current):
                continue
            if not os.path.isdir(ext_path(current)):
                continue
            if os.listdir(ext_path(current)):
                continue
            os.rmdir(ext_path(current))
            logger.info("Removed empty folder: %s", current)
        except OSError as exc:
            logger.warning("Could not remove '%s': %s", current, exc)


def run_undo_from_journal(
    journal: dict,
    apply: bool,
    logger: logging.Logger,
) -> Tuple[int, int, int]:
    """Reverse rename operations from a structured undo manifest."""
    ops = journal.get("operations", [])
    action = journal.get("action", "move")
    logger.info("Undo rename (%s).", "APPLY" if apply else "DRY-RUN")
    logger.info(
        "Reversing %d %s operation(s) from job manifest (created %s).",
        len(ops),
        action,
        journal.get("created", "?"),
    )
    restored, failed, skipped = execute_undo(journal, apply, logger)
    logger.info("Undo result: restored=%d, failed=%d, skipped=%d.", restored, failed, skipped)
    # Other mode renames in place, so there are no layout folders to clean up.
    if apply and restored > 0 and journal.get("mode", "media") != "generic":
        prune_empty_dirs_after_undo(journal, logger)
    return restored, failed, skipped


def execute_undo(
    journal: dict,
    apply: bool,
    logger: logging.Logger,
) -> Tuple[int, int, int]:
    """Reverse the operations recorded in *journal*.

    A move is undone by moving the file back to its original path; a copy is
    undone by deleting the created copy (the original is left untouched).
    Returns (restored, failed, skipped).
    """
    use_copy = journal.get("action") == "copy"
    ops = journal.get("operations", [])
    restored = failed = skipped = 0
    # Reverse the original order so nested folders unwind cleanly.
    for entry in reversed(ops):
        src = Path(entry["src"])  # original location the file came from
        dst = Path(entry["dst"])  # where the file lives now

        if use_copy:
            # Undo a copy = remove the copy we created; never touch the original.
            if not path_exists(dst):
                logger.warning("Undo skip: copy not found at '%s'.", dst)
                skipped += 1
                continue
            if apply:
                try:
                    os.remove(ext_path(dst))
                    logger.info("Removed copy '%s'", dst)
                    restored += 1
                except Exception as exc:
                    logger.error("FAILED to remove copy '%s': %s", dst, exc)
                    failed += 1
            else:
                logger.info("[DRY-RUN] would remove copy '%s'", dst)
                restored += 1
            continue

        # Undo a move = put the file back where it came from.
        if not path_exists(dst):
            logger.warning("Undo skip: file not found at '%s' (moved/renamed since?).", dst)
            skipped += 1
            continue
        # A case-only rename (Kick -> kick) leaves src "existing" on case-insensitive
        # filesystems because it is the very same entry as dst; that is not a clash.
        same_entry = os.path.normcase(os.path.abspath(ext_path(src))) == os.path.normcase(
            os.path.abspath(ext_path(dst))
        )
        if path_exists(src) and not same_entry:
            logger.warning("Undo skip: original path already exists '%s'.", src)
            skipped += 1
            continue
        if apply:
            try:
                make_dirs(src.parent)
                move_path(dst, src)
                logger.info("Restored '%s' -> '%s'", dst, src)
                restored += 1
            except Exception as exc:
                logger.error("FAILED to restore '%s' -> '%s': %s", dst, src, exc)
                failed += 1
        else:
            logger.info("[DRY-RUN] would restore '%s' -> '%s'", dst, src)
            restored += 1
    return restored, failed, skipped


def run_rename_undo(args: argparse.Namespace, logger: logging.Logger) -> None:
    """Reverse the most recent --apply rename run using its undo journal."""
    dest_root: Path = args.output if args.output is not None else args.input
    apply = bool(args.apply)

    logger.info("Undo rename (%s).", "APPLY" if apply else "DRY-RUN")
    journal = load_undo_journal(dest_root, logger)
    if journal is None:
        legacy = legacy_undo_journal_path(dest_root)
        logger.error(
            "No undo journal found for destination '%s'. Nothing to undo "
            "(only --apply runs create one, and a successful undo removes it). "
            "Journals are stored under app data, not in the media folder.",
            dest_root,
        )
        if path_exists(legacy):
            logger.error("Found a legacy journal at '%s' but could not load it.", legacy)
        return

    path = undo_journal_path(dest_root)
    ops = journal.get("operations", [])
    action = journal.get("action", "move")
    logger.info("Journal: %s (created %s)", path, journal.get("created", "?"))
    logger.info("Reversing %d %s operation(s) from the last rename.", len(ops), action)

    restored, failed, skipped = run_undo_from_journal(journal, apply, logger)

    if not apply:
        logger.info("Dry-run complete. Re-run with --undo --apply to perform the undo.")
        return

    # Drop the journal once the undo fully succeeded, so it cannot run twice.
    if failed == 0 and skipped == 0:
        try:
            os.remove(ext_path(path))
            logger.info("Removed undo journal '%s'.", path)
        except Exception as exc:
            logger.warning("Could not remove undo journal '%s': %s", path, exc)
    else:
        logger.info("Undo journal kept at '%s' (some operations did not reverse).", path)


def prune_empty_dirs(root: Path, dry_run: bool, logger: logging.Logger) -> None:
    """Remove directories left empty under root (bottom-up). Never removes root itself."""
    for current, dirs, files in os.walk(ext_path(root), topdown=False):
        # Skip the root directory itself.
        if os.path.normcase(current) == os.path.normcase(ext_path(root)):
            continue
        try:
            if not os.listdir(current):
                if dry_run:
                    logger.info("[DRY-RUN] Would remove empty folder: %s", current)
                else:
                    os.rmdir(current)
                    logger.info("Removed empty folder: %s", current)
        except OSError as exc:
            logger.warning("Could not remove '%s': %s", current, exc)


def run_rename(args: argparse.Namespace) -> Optional[dict]:
    input_root: Path = args.input
    dest_root: Path = args.output if args.output is not None else args.input
    apply = bool(args.apply)
    use_copy = bool(args.copy)
    forced_type: str = args.type
    titlecase_enabled = not args.no_titlecase
    # Accept comma- and/or space-separated words; compare case-insensitively.
    raw_strip = getattr(args, "strip_words", None) or []
    strip_words: Set[str] = {
        w.strip().lower()
        for chunk in raw_strip
        for w in chunk.split(",")
        if w.strip()
    }
    bare_numbers = bool(getattr(args, "bare_episode_numbers", False))
    raw_sub_lang = getattr(args, "default_sub_lang", "en")
    # An empty string disables defaulting; otherwise normalize to a lowercase code.
    default_sub_lang: Optional[str] = raw_sub_lang.strip().lower() or None

    profile = load_profile_spec(getattr(args, "profile", None))

    if not input_root.is_dir():
        print(
            f"Input root '{input_root}' does not exist or is not a directory. "
            f"(If this is a network drive, make sure it is connected/mapped.)",
            file=sys.stderr,
        )
        sys.exit(1)

    log_path = operation_log_path("rename") if apply else None
    logger = setup_simple_logging("video_rename", log_path)

    if getattr(args, "undo", False):
        run_rename_undo(args, logger)
        return None

    if getattr(args, "include_root", False) and getattr(args, "mode", "media") != "generic":
        logger.error("--include-root only works with --mode generic.")
        sys.exit(2)

    if getattr(args, "mode", "media") == "generic":
        from .rename_generic import run_generic_rename

        try:
            return run_generic_rename(args, logger, profile or standard_profile())
        except ValueError as exc:  # unusable options, e.g. renaming a drive root
            logger.error("%s", exc)
            sys.exit(2)

    mode = "APPLY" if apply else "DRY-RUN"
    action = "copy" if use_copy else "move"
    logger.info("Rename mode (%s).", mode)
    logger.info("Input root : %s", input_root)
    logger.info("Destination: %s%s", dest_root, " (in place)" if dest_root == input_root else "")
    logger.info("Type=%s, action=%s, title_case=%s, prune_empty_dirs=%s",
                forced_type, action, titlecase_enabled, args.prune_empty_dirs)
    logger.info("Strip words=%s, bare_episode_numbers=%s",
                sorted(strip_words) if strip_words else "(none)", bare_numbers)
    logger.info("Default subtitle language (untagged subs)=%s",
                default_sub_lang or "(disabled)")
    layout = bool(getattr(args, "layout", True))
    if profile is not None:
        logger.info("Profile: %s | TV pattern: %s | movie pattern: %s | layout=%s",
                    profile.name, profile.pattern("tv"), profile.pattern("movie"),
                    "Show/Season folders" if layout else "keep folders")

    if use_copy and dest_root == input_root:
        logger.warning(
            "--copy with no --output will duplicate files into a new layout under the same root."
        )

    ops, skipped = plan_rename(
        input_root, dest_root, forced_type, titlecase_enabled, logger,
        strip_words=strip_words, bare_numbers=bare_numbers,
        default_sub_lang=default_sub_lang,
        profile=profile, layout=layout,
    )

    videos = sum(1 for o in ops if o.kind == "video")
    subtitles = sum(1 for o in ops if o.kind == "subtitle")
    logger.info("Planned operations: %d (videos=%d, subtitles=%d).", len(ops), videos, subtitles)

    undo_manifest: Optional[dict] = None
    if not apply:
        for op in ops:
            logger.info("[DRY-RUN] %s '%s' -> '%s'", op.kind, op.src, op.dst)
    else:
        succeeded, failed, done = execute_rename(ops, use_copy, logger)
        logger.info("Executed: succeeded=%d, failed=%d.", succeeded, failed)
        if done:
            undo_manifest = build_undo_journal(
                done, use_copy, dest_root=dest_root, input_root=input_root
            )
            write_undo_journal(
                dest_root, done, use_copy, logger, input_root=input_root
            )

    if skipped:
        logger.info("Skipped %d file(s):", len(skipped))
        for path, reason in skipped:
            logger.info("  SKIP (%s): %s", reason, path)

    # Prune empty folders only when we actually moved files (copying leaves originals).
    if args.prune_empty_dirs and not use_copy:
        prune_empty_dirs(input_root, dry_run=not apply, logger=logger)
    elif args.prune_empty_dirs and use_copy:
        logger.info("--prune-empty-dirs ignored because --copy keeps originals in place.")

    if not apply:
        logger.info("Dry-run complete. Re-run with --apply to perform these changes.")
    logger.info("Done.")
    return undo_manifest


# =====================================================================
# Dedup mode: strip duplicate "(N)" suffixes from filenames
# =====================================================================

# Matches a stem ending in a duplicate counter like "name (2)".
# Limited to 1-3 digits so it never strips a 4-digit year, e.g. "Movie (2020)".
RE_DUP_SUFFIX = re.compile(r"^(?P<base>.+?) \((?P<n>\d{1,3})\)$")


def dedup_target_for(path: Path) -> Optional[Path]:
    """Return the de-duplicated target path for *path*, or None if it has no
    ``(N)`` counter.

    Handles the counter whether it sits at the very end of the name
    (``name (2).srt``) or in front of subtitle language/flag tags
    (``name (2).en.srt`` -> ``name.en.srt``).
    """
    ext = path.suffix
    stem = path.stem

    # Counter right before the final extension, e.g. "name (2).srt" / "name.en (2).srt".
    m = RE_DUP_SUFFIX.match(stem)
    if m:
        return path.with_name(m.group("base") + ext)

    # For subtitles the counter may precede the language/flag tags, e.g.
    # "name (2).en.srt". Peel those tags off and look again.
    if ext.lower() in SUBTITLE_EXTENSIONS:
        base, suffix = split_subtitle_suffix(stem)
        m = RE_DUP_SUFFIX.match(base)
        if m:
            new_stem = f"{m.group('base')}.{suffix}" if suffix else m.group("base")
            return path.with_name(new_stem + ext)

    return None


def run_dedup(args: argparse.Namespace) -> None:
    input_root: Path = args.input
    apply = bool(args.apply)

    if not input_root.is_dir():
        print(
            f"Input '{input_root}' does not exist or is not a directory. "
            f"(If this is a network drive, make sure it is connected/mapped.)",
            file=sys.stderr,
        )
        sys.exit(1)

    log_path = operation_log_path("dedup") if apply else None
    logger = setup_simple_logging("video_dedup", log_path)

    logger.info("Dedup mode (%s).", "APPLY" if apply else "DRY-RUN")
    logger.info("Input root: %s", input_root)

    # Collect every file, sorted, so behavior is deterministic and so a lower
    # counter is handled before a higher one mapping to the same base name.
    files: List[Path] = []
    for current, _dirs, names in os.walk(ext_path(input_root)):
        for name in names:
            files.append(Path(current) / name)
    files.sort(key=lambda p: str(p).lower())

    renamed = removed = skipped = 0
    # Base targets we've already claimed in this run (normalized for case-insensitive FS).
    planned: Set[str] = set()

    def norm(p: Path) -> str:
        return os.path.normcase(str(p))

    def size_of(p: Path) -> Optional[int]:
        try:
            return os.path.getsize(ext_path(p))
        except OSError:
            return None

    for f in files:
        target = dedup_target_for(f)
        if target is None:
            continue
        tnorm = norm(target)
        on_disk = path_exists(target)

        if not on_disk and tnorm not in planned:
            # Un-suffixed name is free: just strip the counter.
            if apply:
                try:
                    move_path(f, target)
                except Exception as exc:
                    logger.error("FAILED to rename '%s' -> '%s': %s", f, target, exc)
                    skipped += 1
                    continue
                logger.info("Renamed '%s' -> '%s'", f, target)
            else:
                logger.info("[DRY-RUN] would rename '%s' -> '%s'", f, target)
            planned.add(tnorm)
            renamed += 1
            continue

        # The un-suffixed name already exists (on disk or claimed this run).
        # Only delete the suffixed copy when it is clearly the same file (size match).
        dup_size = size_of(f)
        orig_size = size_of(target) if on_disk else None
        if on_disk and dup_size is not None and dup_size == orig_size:
            if apply:
                try:
                    os.remove(ext_path(f))
                except OSError as exc:
                    logger.error("FAILED to remove duplicate '%s': %s", f, exc)
                    skipped += 1
                    continue
                logger.info("Removed duplicate '%s' (identical to '%s')", f, target)
            else:
                logger.info("[DRY-RUN] would remove duplicate '%s' (identical to '%s')", f, target)
            removed += 1
        elif not on_disk and tnorm in planned:
            # An earlier copy this run already claimed the base name.
            if apply:
                try:
                    os.remove(ext_path(f))
                except OSError as exc:
                    logger.error("FAILED to remove extra duplicate '%s': %s", f, exc)
                    skipped += 1
                    continue
                logger.info("Removed extra duplicate '%s' (another copy maps to '%s')", f, target)
            else:
                logger.info("[DRY-RUN] would remove extra duplicate '%s' (another copy maps to '%s')", f, target)
            removed += 1
        else:
            logger.warning(
                "SKIP '%s': '%s' already exists with different content; leaving both in place.",
                f, target,
            )
            skipped += 1

    logger.info("Dedup summary: renamed=%d, removed_duplicates=%d, skipped=%d.",
                renamed, removed, skipped)
    if not apply and (renamed or removed):
        logger.info("Dry-run complete. Re-run with --apply to perform these changes.")
    logger.info("Done.")
