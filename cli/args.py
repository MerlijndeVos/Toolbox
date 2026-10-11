"""Command-line argument definitions for Toolbox."""

import argparse
import sys
from pathlib import Path

from core.config import DEFAULT_CRF, DEFAULT_X264_PRESET, DEFAULT_VTS_MIN_MB
from core.mods import set_safe_mode

from . import mods_cli


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    # Mod subcommands are built from the mods on disk, so safe mode has to be known before
    # the parser is assembled (the flag itself is declared below for --help and validation).
    if "--no-mods" in (sys.argv[1:] if argv is None else argv):
        set_safe_mode(True)

    parser = argparse.ArgumentParser(
        prog="toolbox",
        description="Toolbox: convert DV files to MP4, or rename/organize TV & movie libraries.",
    )
    parser.add_argument(
        "--no-file-log",
        action="store_true",
        help="Do not write per-operation log files (console output only).",
    )
    parser.add_argument(
        "--no-mods",
        action="store_true",
        help="Safe mode: do not load user-installed mods (built-in features are unaffected).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ------------------------------------------------------------------
    # convert subcommand (DV -> MP4)
    # ------------------------------------------------------------------
    convert = subparsers.add_parser(
        "convert",
        help="Batch-convert video files (e.g. DV->MP4, AVI->MKV) with folder mirroring.",
        description=(
            "Batch-convert video files between formats with folder mirroring. "
            "Input and output formats are selectable (default DV -> MP4)."
        ),
    )
    convert.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input root folder containing source files (and subfolders).",
    )
    convert.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output root folder where converted files and logs will be written.",
    )
    convert.add_argument(
        "--input-format",
        default="dv",
        help=(
            "Input file extension to scan for, with or without a leading dot "
            "(e.g. dv, avi, mov, mp4, ts), or 'auto' to convert every supported "
            "video in the folder that is not already the output format. Default: dv."
        ),
    )
    convert.add_argument(
        "--output-format",
        default="mp4",
        choices=["mp4", "mkv", "mov"],
        help="Output container format. Default: mp4.",
    )
    convert.add_argument(
        "--deinterlace",
        choices=["auto", "on", "off"],
        default="auto",
        help=(
            "Deinterlace the video with bwdif. 'auto' (default) enables it only "
            "for interlaced sources like DV, and disables it otherwise."
        ),
    )
    convert.add_argument(
        "--use-gpu",
        choices=["auto", "on", "off"],
        default="auto",
        help="GPU usage mode: auto (default), on (require NVENC), off (CPU only).",
    )
    convert.add_argument(
        "--crf",
        type=int,
        default=DEFAULT_CRF,
        help=f"CRF for libx264 when GPU is off/unavailable (default: {DEFAULT_CRF}).",
    )
    convert.add_argument(
        "--preset",
        default=DEFAULT_X264_PRESET,
        help=f"libx264 preset when GPU is off/unavailable (default: {DEFAULT_X264_PRESET}).",
    )
    convert.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without calling ffmpeg or modifying the filesystem.",
    )
    convert.add_argument(
        "--prune-output",
        action="store_true",
        help="After successful conversion of each folder, delete files not matching the output format from that output folder.",
    )
    convert.add_argument(
        "--copy-useful-only",
        action="store_true",
        help=(
            "After conversion, create a separate '<output>_useful' tree containing ONLY the converted files. "
            "Does nothing in --dry-run mode."
        ),
    )

    # ------------------------------------------------------------------
    # vts subcommand (DVD VIDEO_TS / VTS_xx_x.VOB -> MKV)
    # ------------------------------------------------------------------
    vts = subparsers.add_parser(
        "vts",
        help="Join DVD title-set VOBs (VTS_xx_x.VOB) into one file per title (default: lossless MKV remux).",
        description=(
            "Scan for DVD VIDEO_TS rips, join each title set's split VOB segments "
            "(VTS_01_1.VOB, VTS_01_2.VOB, ...) in order, and write one file per title. "
            "By default this is a fast, lossless remux (stream copy) into MKV; pass "
            "--reencode to transcode the video to H.264 instead."
        ),
    )
    vts.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Folder containing VIDEO_TS rip(s) or VTS_xx_x.VOB files (scanned recursively).",
    )
    vts.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output root folder where joined files and logs will be written.",
    )
    vts.add_argument(
        "--output-format",
        default="mkv",
        choices=["mkv", "mp4", "mov"],
        help="Output container format. Default: mkv (best for DVD streams + subtitles).",
    )
    vts.add_argument(
        "--reencode",
        action="store_true",
        help="Re-encode the video to H.264 instead of a lossless stream copy (slower, smaller files).",
    )
    vts.add_argument(
        "--deinterlace",
        choices=["auto", "on", "off"],
        default="auto",
        help=(
            "Deinterlace with bwdif when re-encoding. 'auto' (default) enables it "
            "(DVD video is typically interlaced). Ignored for lossless remux."
        ),
    )
    vts.add_argument(
        "--use-gpu",
        choices=["auto", "on", "off"],
        default="auto",
        help="GPU mode when --reencode is set: auto (default), on (require NVENC), off (CPU only).",
    )
    vts.add_argument(
        "--crf",
        type=int,
        default=DEFAULT_CRF,
        help=f"CRF for libx264 when re-encoding on CPU (default: {DEFAULT_CRF}).",
    )
    vts.add_argument(
        "--preset",
        default=DEFAULT_X264_PRESET,
        help=f"libx264 preset when re-encoding on CPU (default: {DEFAULT_X264_PRESET}).",
    )
    vts.add_argument(
        "--include-menus",
        action="store_true",
        help="Also convert the title-set menu segment (VTS_xx_0.VOB), normally skipped.",
    )
    vts.add_argument(
        "--min-mb",
        type=int,
        default=DEFAULT_VTS_MIN_MB,
        help=(
            f"Skip title sets whose joined size is below this many MB (default: {DEFAULT_VTS_MIN_MB}). "
            "Filters out tiny junk titles (menus, warnings). Pass 0 to convert everything."
        ),
    )
    vts.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the title sets and planned outputs without calling ffmpeg or writing files.",
    )

    # ------------------------------------------------------------------
    # rename subcommand (TV / movie / subtitle organizer)
    # ------------------------------------------------------------------
    rename = subparsers.add_parser(
        "rename",
        help="Rename/organize TV show & movie folders, files and subtitles (Plex/Jellyfin style).",
        description=(
            "Rename and reorganize messy TV show / movie files, folders and subtitles into a "
            "clean Plex/Jellyfin/Kodi friendly layout. Dry-run by default; pass --apply to make changes. "
            "Works on local disks, mapped network drives (Z:\\...) and UNC paths (\\\\server\\share\\...)."
        ),
    )
    rename.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Root folder to scan for media (recursively).",
    )
    rename.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional destination root for the organized library. "
            "If omitted, files are reorganized in place under --input."
        ),
    )
    rename.add_argument(
        "--type",
        choices=["auto", "tv", "movie"],
        default="auto",
        help="Force media type, or 'auto' (default) to detect per file.",
    )
    rename.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the renames/moves. Without this flag it is a dry-run.",
    )
    rename.add_argument(
        "--copy",
        action="store_true",
        help="Copy files into the new layout instead of moving them (originals are kept).",
    )
    rename.add_argument(
        "--undo",
        action="store_true",
        help=(
            "Reverse the most recent --apply run using the undo journal stored "
            "under app data. Dry-run by default; add --apply to perform it. "
            "Use the same --input/--output as the original run."
        ),
    )
    rename.add_argument(
        "--prune-empty-dirs",
        action="store_true",
        help="After moving files, delete folders left empty under --input.",
    )
    rename.add_argument(
        "--no-titlecase",
        action="store_true",
        help="Do not apply Title Case to show/movie/episode names; keep cleaned text as-is.",
    )
    rename.add_argument(
        "--strip-words",
        nargs="*",
        default=[],
        metavar="WORD",
        help=(
            "Trailing word(s) to remove from episode/movie titles (e.g. a leftover "
            "release-group name like 'Silence'). Space- or comma-separated, "
            "case-insensitive. Example: --strip-words Silence RARBG"
        ),
    )
    rename.add_argument(
        "--bare-episode-numbers",
        action="store_true",
        help=(
            "Treat a file whose name ends in a plain number (no SxxExx) as Season 1, "
            "that episode. E.g. 'Show Name 36.mkv' -> 'Show Name - S01E36.mkv'."
        ),
    )
    rename.add_argument(
        "--default-sub-lang",
        default="en",
        metavar="LANG",
        help=(
            "Language tag to apply to subtitles that have no language code, so "
            "e.g. 'Show.srt' becomes 'Show - S01E01.en.srt' instead of '...S01E01.srt'. "
            "Defaults to 'en'. Pass an empty string ('') to disable and keep untagged subs as-is."
        ),
    )
    rename.add_argument(
        "--profile",
        default=None,
        metavar="NAME_OR_FILE",
        help=(
            "Format profile (cleanup rules + name patterns): the name or id of a saved profile, "
            "or a path to a profile .json file. Default: Standard."
        ),
    )
    rename.add_argument(
        "--mode",
        choices=["media", "generic"],
        default="media",
        help=(
            "'media' (default) organizes TV shows/movies. 'generic' renames folders and/or "
            "files in place using the profile (see --targets, --max-depth)."
        ),
    )
    rename.add_argument(
        "--targets",
        choices=["folders", "files", "both"],
        default="folders",
        help="With --mode generic: what to rename (default: folders).",
    )
    rename.add_argument(
        "--max-depth",
        type=int,
        default=1,
        metavar="N",
        help="With --mode generic: how many levels below --input to rename (1 = direct children; default: 1).",
    )
    rename.add_argument(
        "--include-root",
        action="store_true",
        help=(
            "With --mode generic: also rename the --input folder itself (after everything inside it). "
            "Needs --targets folders or both. To undo, point --input at the folder's new path."
        ),
    )
    rename.add_argument(
        "--no-layout",
        dest="layout",
        action="store_false",
        help="With --mode media: only rename files, keeping them in their folders instead of Show/Season NN.",
    )

    # ------------------------------------------------------------------
    # audio subcommand (set default audio language in MKV files)
    # ------------------------------------------------------------------
    audio = subparsers.add_parser(
        "audio",
        help="Set the default audio language (track) in MKV files using ffmpeg.",
        description=(
            "Mark the audio track of a chosen language as the default track in .mkv files. "
            "Remuxes with stream copy (no re-encode). Dry-run by default; "
            "pass --apply to make changes. Requires ffmpeg/ffprobe."
        ),
    )
    audio.add_argument(
        "--input",
        required=True,
        type=Path,
        help="An .mkv file, or a folder to scan for .mkv files (recursively by default).",
    )
    audio.add_argument(
        "--lang",
        required=True,
        help="Desired default audio language: 2-letter (en), 3-letter (eng/dut/nld) or name (english).",
    )
    audio.add_argument(
        "--apply",
        action="store_true",
        help="Actually edit the files. Without this flag it is a dry-run.",
    )
    audio.add_argument(
        "--set-language",
        action="store_true",
        help="Also (re)write the chosen track's language tag to --lang (fixes 'und'/mislabeled tracks).",
    )
    audio.add_argument(
        "--no-recursive",
        action="store_true",
        help="When --input is a folder, do not descend into subfolders.",
    )

    # ------------------------------------------------------------------
    # dedup subcommand (strip duplicate "(N)" suffixes from filenames)
    # ------------------------------------------------------------------
    dedup = subparsers.add_parser(
        "dedup",
        help="Rename 'name (2).ext' back to 'name.ext' (clean up duplicate-counter suffixes).",
        description=(
            "Scan a folder recursively for files whose name ends in a duplicate "
            "counter like ' (2)', ' (3)', and rename them back to the un-suffixed "
            "name. If the un-suffixed name already exists, the suffixed copy is "
            "removed only when it is identical (same size); otherwise it is left "
            "untouched and reported. Dry-run by default; pass --apply to make changes."
        ),
    )
    dedup.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Folder to scan recursively for '(N)' suffixed files.",
    )
    dedup.add_argument(
        "--apply",
        action="store_true",
        help="Actually rename/remove files. Without this flag it is a dry-run.",
    )

    # ------------------------------------------------------------------
    # download subcommand (YouTube URL -> MP4 / MP3)
    # ------------------------------------------------------------------
    download = subparsers.add_parser(
        "download",
        help="Download a YouTube (or other yt-dlp supported) URL as MP4 video or MP3 audio.",
        description=(
            "Download a single video URL into a folder, either as a merged MP4 video "
            "or as an extracted MP3 audio file. Requires yt-dlp (pip install yt-dlp) "
            "and ffmpeg on PATH."
        ),
    )
    download.add_argument(
        "--url",
        required=True,
        help="The video URL to download (YouTube or any other yt-dlp supported site).",
    )
    download.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output folder where the downloaded file will be written.",
    )
    download.add_argument(
        "--format",
        default="mp4",
        choices=["mp4", "mp3"],
        help="Output type: mp4 (video) or mp3 (audio only). Default: mp4.",
    )
    download.add_argument(
        "--video-quality",
        default="best",
        choices=["best", "2160", "1440", "1080", "720", "480", "360"],
        help=(
            "Maximum video height for MP4 downloads (e.g. 1080). 'best' (default) "
            "picks the highest available. Ignored for --format mp3."
        ),
    )
    download.add_argument(
        "--audio-bitrate",
        type=int,
        default=192,
        help="MP3 audio bitrate in kbps (e.g. 128, 192, 320). Default: 192. Used only for --format mp3.",
    )
    download.add_argument(
        "--playlist",
        action="store_true",
        help=(
            "Download the whole playlist when the URL is (or points into) a playlist. "
            "Each item is saved under a per-playlist subfolder, prefixed with its index. "
            "Without this flag, only the single video is downloaded."
        ),
    )
    download.add_argument(
        "--no-playlist-index",
        action="store_true",
        help=(
            "When downloading a playlist, do not prefix each filename with its "
            "playlist index number (files are named by title only). Has no effect "
            "without --playlist."
        ),
    )

    # ------------------------------------------------------------------
    # trim subcommand (cut seconds off the start and/or end of a video)
    # ------------------------------------------------------------------
    trim = subparsers.add_parser(
        "trim",
        help="Trim a number of seconds off the start and/or end of one video or a whole folder.",
        description=(
            "Cut time off the start and/or end of a video. Works on a single file "
            "or, when --input is a folder, on every matching file in it. By default "
            "the streams are copied without re-encoding (fast, lossless), so the cut "
            "snaps to the nearest keyframe; pass --reencode for a frame-accurate cut. "
            "Originals are never modified: trimmed copies are written next to the "
            "source as 'name - trimmed.ext', or into --output if given."
        ),
    )
    trim.add_argument(
        "--input",
        required=True,
        type=Path,
        help="A single video file, or a folder to scan for files matching --input-format.",
    )
    trim.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional output folder. If omitted, each trimmed file is written next "
            "to its source as 'name - trimmed.ext'."
        ),
    )
    trim.add_argument(
        "--trim-start",
        default="0",
        help=(
            "How much to cut off the START. Accepts seconds (e.g. 10, 0.5), "
            "milliseconds (e.g. 500ms), or a timestamp (e.g. 0:10, 1:02:03). "
            "Default: 0 (cut nothing off the start)."
        ),
    )
    trim.add_argument(
        "--trim-end",
        default="0",
        help=(
            "How much to cut off the END. Accepts seconds (e.g. 5, 0.25), "
            "milliseconds (e.g. 250ms), or a timestamp (e.g. 0:05). "
            "Default: 0 (cut nothing off the end)."
        ),
    )
    trim.add_argument(
        "--input-format",
        default="mp4",
        help=(
            "When --input is a folder, the file extension to look for, or 'auto' "
            "to trim every supported video in the folder. Default: mp4."
        ),
    )
    trim.add_argument(
        "--no-recursive",
        action="store_true",
        help="When --input is a folder, do not descend into subfolders.",
    )
    trim.add_argument(
        "--reencode",
        action="store_true",
        help=(
            "Re-encode for a frame-accurate cut (H.264 + AAC) instead of copying "
            "streams. Slower, but the cut lands exactly on the requested times."
        ),
    )
    trim.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Overwrite each source file with its trimmed version instead of "
            "keeping the original. The trim is written to a temporary file first "
            "and only swapped in once it succeeds. Ignores --output."
        ),
    )
    trim.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be trimmed without writing anything.",
    )

    # ------------------------------------------------------------------
    # stitch subcommand (join several videos into one)
    # ------------------------------------------------------------------
    stitch = subparsers.add_parser(
        "stitch",
        help="Join two or more videos into a single file, in the given order.",
        description=(
            "Concatenate videos end-to-end into one file. Give the parts in order "
            "with repeated --input flags, or pass a single folder as --input to "
            "stitch every matching file in it (sorted by name). By default the "
            "streams are copied without re-encoding (fast, lossless), which needs "
            "the parts to share the same codec/resolution; pass --reencode to "
            "join clips that differ. Inputs are never modified."
        ),
    )
    stitch.add_argument(
        "--input",
        required=True,
        action="append",
        type=Path,
        metavar="PATH",
        help=(
            "A video file to add to the sequence. Repeat this flag for each part, "
            "in the order you want them joined. Alternatively pass it once with a "
            "folder to stitch every matching file inside it."
        ),
    )
    stitch.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output file to write the stitched video to (e.g. D:\\out\\joined.mp4).",
    )
    stitch.add_argument(
        "--output-format",
        default=None,
        choices=["mp4", "mkv", "mov"],
        help=(
            "Output container format. When set, the output path extension is adjusted "
            "to match. If omitted, the extension on --output is used (default: mp4)."
        ),
    )
    stitch.add_argument(
        "--input-format",
        default="mp4",
        help="When --input is a single folder, the file extension to look for. Default: mp4.",
    )
    stitch.add_argument(
        "--no-recursive",
        action="store_true",
        help="When --input is a folder, do not descend into subfolders.",
    )
    stitch.add_argument(
        "--reencode",
        action="store_true",
        help=(
            "Re-encode the parts to a common format (H.264 + AAC) before joining. "
            "Slower, but required when the clips have different codecs, resolutions "
            "or frame rates."
        ),
    )
    stitch.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the parts that would be joined without writing anything.",
    )

    # ------------------------------------------------------------------
    # rename_folders subcommand (date-stamp subfolders)
    # ------------------------------------------------------------------
    rename_folders = subparsers.add_parser(
        "rename_folders",
        help="(Deprecated) Date-stamp subfolders, e.g. 2006 juli 13 - Holiday.",
        description=(
            "Deprecated: use 'rename --mode generic --profile \"Date + name (Dutch)\"' instead, which "
            "does the same and supports undo. Renames direct subfolders of --root to Dutch date-stamped "
            "names (e.g. 2006 juli 13 - Holiday); dates come from video filenames inside each folder."
        ),
    )
    rename_folders.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Root folder whose direct subfolders will be renamed.",
    )
    rename_folders.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned renames without changing anything.",
    )

    # ------------------------------------------------------------------
    # subtitle_translate subcommand
    # ------------------------------------------------------------------
    subtitle_translate = subparsers.add_parser(
        "subtitle_translate",
        help="Translate SRT subtitles with an AI provider.",
        description=(
            "Translate .srt subtitle files using the AI provider chosen in settings. Output files use the target "
            "language suffix (e.g. Show.en.srt -> Show.de.srt)."
        ),
    )
    subtitle_translate.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Subtitle file (.srt, .vtt, .ass, .ssa) or folder containing them.",
    )
    subtitle_translate.add_argument(
        "--source-lang",
        default="auto",
        help="Source language code or 'auto' to detect from filename (default: auto).",
    )
    subtitle_translate.add_argument(
        "--target-lang",
        required=True,
        help="Target language code (ISO 639-1, e.g. de, nl, en).",
    )
    subtitle_translate.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing translated output files.",
    )
    subtitle_translate.add_argument(
        "--glossary-file",
        type=Path,
        help="Text file with one 'term = translation' per line (a bare term is kept untranslated).",
    )
    subtitle_translate.add_argument(
        "--notes",
        default="",
        help="Free-form notes for the translator, e.g. 'teen drama, informal register'.",
    )
    subtitle_translate.add_argument(
        "--model",
        default=None,
        help="Model id for this run (default: the model saved in AI settings).",
    )
    subtitle_translate.add_argument(
        "--concurrency",
        type=int,
        default=1,
        choices=range(1, 5),
        help="Batches translated at the same time (1-4). Above 1, a batch sees the earlier source lines "
        "instead of their translations.",
    )
    subtitle_translate.add_argument(
        "--review",
        action="store_true",
        help="Add an editing pass that fixes mistranslations and unnatural lines (about twice the tokens).",
    )
    subtitle_translate.add_argument(
        "--keep-junk",
        dest="remove_junk",
        action="store_false",
        help="Translate ad, credit and URL lines instead of dropping them.",
    )
    subtitle_translate.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned actions without calling the AI provider or writing files.",
    )

    # ------------------------------------------------------------------
    # subtitle_cleanup subcommand
    # ------------------------------------------------------------------
    subtitle_cleanup = subparsers.add_parser(
        "subtitle_cleanup",
        help="Remove junk lines from SRT subtitles.",
        description=(
            "Remove URLs, credits, watermarks, and similar non-dialogue lines "
            "from .srt files in place."
        ),
    )
    subtitle_cleanup.add_argument(
        "--input",
        required=True,
        type=Path,
        help="SRT file or folder containing .srt files.",
    )
    subtitle_cleanup.set_defaults(confirmed_removals=[], junk_reviewed=True)
    subtitle_cleanup.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned removals without writing files.",
    )

    mods_cli.register(subparsers)

    return parser.parse_args(argv)

