# Changelog

All notable changes are listed here, following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Per-release write-ups live in `release-notes/`.

## [Unreleased]

### Added
- Subtitle translation re-asks only for cues the model skipped, answered badly, or returned with changed tags or odd line breaks, then falls back to one cue at a time.
- Translated batches are checkpointed, so a retry after a failure or cancel resumes instead of paying again.
- After a run with problems, the Translate tool shows how many cues kept their original text or may need a check.

### Changed
- A file that fails to translate no longer stops the rest of the folder; the job ends as failed and names the files.
- Translated subtitles are written atomically, so an interrupted run cannot leave a truncated file behind.
- Subtitle files in a legacy encoding (Windows-1252, UTF-16) are decoded properly, with a warning, instead of being filled with replacement characters.

### Fixed
- Cancelling a translation now stops it, instead of continuing to call the AI provider and writing the file afterwards.
- OpenAI models that reject a custom temperature are retried without it.
