# Changelog

All notable changes are listed here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Per-release write-ups live in `release-notes/`.

## [Unreleased]

### Added
- Subtitle translation re-asks only for cues the model skipped, answered badly, or returned with changed tags or odd line breaks, then falls back to one cue at a time.
- Translated batches are checkpointed, so a retry after a failure or cancel resumes instead of paying again.
- After a run with problems, the Translate tool shows how many cues kept their original text or may need a check.
- Translate keeps `<i>`, `{\an8}` and other formatting tags safe by swapping them for markers the model cannot rewrite.
- Translate takes a glossary (`term = translation`, or a bare term to keep as is) and free-form notes about the show, in the form and on the CLI (`--glossary-file`, `--notes`).
- Each cue carries a reading-speed character budget, so translations stay readable on screen.
- Ad and credit lines (web addresses, emails, release tags, "subtitles by") are dropped before translating; `--keep-junk` turns that off.

- AI provider **Claude subscription**: translation and rename assist can run through the Claude Code program with your Pro/Max plan, no API key. An optional `claude setup-token` token is supported.
- A **Usage** window on the AI page: tokens per day, per task and per model, recent calls, and the Claude plan's 5-hour and weekly limits with reset times.
- Translate reads and writes WebVTT (`.vtt`) and ASS/SSA (`.ass`, `.ssa`) as well as SRT, keeping styles, positions, notes and non-dialogue lines as they were.
- Translate can run up to 4 batches at once, add a review pass that fixes mistranslations, and take a model for the run (`--concurrency`, `--review`, `--model`).
- Preview shows an estimate of the requests and tokens a translation will use.

### Changed
- The model now sees 8 previous translated cues and the next 3 source cues, and keeps names consistent across batches.
- When no language tag is in the filename, the model detects the source language instead of assuming English.
- Folder runs skip files already in the target language and never translate two sources into the same output file.
- A file that fails to translate no longer stops the rest of the folder; the job ends as failed and names the files.
- Translated subtitles are written atomically, so an interrupted run cannot leave a truncated file behind.
- Subtitle files in a legacy encoding (Windows-1252, UTF-16) are decoded properly, with a warning, instead of being filled with replacement characters.

### Fixed
- A title word at the end of a subtitle name ("Where.Is.It.srt") is no longer read as a language tag, so Rename and Translate keep the full title. Tags are `en`, `EN` or `English`; short Capitalised words are left alone.
- Cancelling a translation now stops it, instead of continuing to call the AI provider and writing the file afterwards.
- OpenAI models that reject a custom temperature are retried without it.
