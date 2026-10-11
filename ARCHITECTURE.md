# Architecture

Toolbox separates **business logic** from **front-ends**. Every feature is implemented once in `core/` and exposed through the CLI, HTTP API, and desktop app.

```
┌─────────────────────────────────────────────────────────────┐
│  Desktop app (app.py / toolbox-app)                      │
│  pywebview window → http://127.0.0.1:<port>/app/            │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│  Browser UI (optional)   │   React + Vite (web/frontend)    │
│  http://127.0.0.1:8765/app/  or dev server :5173            │
└──────────────────────────┼──────────────────────────────────┘
                           │ REST + SSE
┌──────────────────────────▼──────────────────────────────────┐
│  web/server.py — FastAPI                                    │
│  web/jobs.py   — background threads, job IDs, log streaming │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  core/                                                      │
│  convert — vts — rename — audio — download — dates          │
│  tools — ffmpeg_bootstrap — progress — probe — paths        │
└──────────────────────────┬──────────────────────────────────┘
                           │ subprocess / filesystem
┌──────────────────────────▼──────────────────────────────────┐
│  ffmpeg — ffprobe — yt-dlp (ffmpeg first-run download)      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  CLI (toolbox / python -m cli)                           │
│  cli/args.py → cli/dispatch.py → core.run_*                 │
└─────────────────────────────────────────────────────────────┘
```

## `core/`

| Module | Responsibility |
|--------|----------------|
| `convert.py` | Batch convert, trim, stitch |
| `vts.py` | DVD VIDEO_TS join |
| `rename.py` | Media library rename (shows/movies), dedup, undo journal |
| `rename_profiles.py` | Format profiles: cleanup rules, name patterns, saved-profile store |
| `rename_generic.py` | Other mode: rename folders/files in place with a profile (incl. `{date}`, idempotent re-runs). Optionally renames the selected folder itself, last, so the planned child paths stay valid; the undo journal is then filed under the new path |
| `rename_ai.py` | AI-generated profiles (verified, never renames). From typed before/after examples (only those are sent), or from a capped, shape-balanced sample of the real names in the chosen folder (at most 60 names, a few video file names inside some folders; never file contents). After a folder suggestion it picks representative names, shows what the profile makes of them, and takes the user's confirmations and corrections back as examples |
| `ai/` | AI providers behind one interface (see below) |
| `dates.py` | Dates in names: read them from DV/MP4 file names, format (`{date:YYYY MMMM D}`), prune them |
| `rename_folders.py` | Deprecated `rename_folders` CLI command, now a shim over the *Date + name (Dutch)* profile |
| `audio.py` | MKV default audio track |
| `download.py` | yt-dlp wrapper (CLI + cancellable API downloads) |
| `tools.py` | ffmpeg discovery, background first-run bootstrap + verify |
| `ffmpeg_bootstrap.py` | Download static ffmpeg builds per OS |
| `runtime.py` | Frozen-app paths, user data directory |
| `progress.py` | `on_log` / `on_progress` callbacks for any front-end |
| `mods/` | The mod system: manifest parser, registry (built-in + user mods), the `ctx` a mod receives, `install.py` (stage → trust prompt → commit, pinned git installs, update checks, remove), `market.py` (the public index), `prompts.py` (the AI prompts), `groups.py` (categories: name matching, fixed section order, near-miss detection), `theme.py` (theme tokens, strict validation, contrast rules), `results.py` (the `ctx.result` views) |

### AI providers (`core/ai/`)

Subtitle translation (`subtitles.py`) and rename-profile generation (`rename_ai.py`) never talk to an SDK or an HTTP API. They call `get_provider()` and then `provider.complete_json(messages, temperature=...)`, which returns the model's JSON (`JsonResult.text` is what it said, `.data` the parsed value) or raises `AiError` with a message that is safe to show as-is. Tests pass their own `provider=` to both features.

| Module | Responsibility |
|--------|----------------|
| `base.py` | `Provider` interface, `AiError` / `AiConfigError` / `InvalidJsonError`, tolerant JSON parsing (code fences, `<think>` blocks, prose around the object), HTTP error text, and the retrying HTTPS transport the native adapters share |
| `openai_provider.py` | OpenAI **and** any OpenAI-compatible server (custom `base_url`), via the `openai` SDK. Uses `response_format=json_object`; if the server rejects it, retries with a prompt-only JSON instruction and remembers that per (URL, model) for the session |
| `anthropic_provider.py` | Native Messages API over `httpx`. JSON comes from a forced tool call (there is no JSON mode) |
| `gemini_provider.py` | Native `generateContent` API over `httpx` with `responseMimeType: application/json` |
| `claude_code_provider.py` | Runs the local `claude -p` CLI (tool-less, empty working folder, `stream-json`) so a Claude subscription can be used without an API key; reads usage and the plan windows from its stream |
| `usage.py` | Local ledger of tokens per call (`ai_usage.json` in the app data folder), per-feature labels, and the stored plan windows behind `/api/ai/usage` |
| `config.py` | Which provider is selected, per-provider key/model/base URL, env-var fallback, validation |

Settings live in `settings.json` under `ai` (`provider`, and `providers.<id>.{api_key, model, base_url}` for `openai`, `openai_compatible`, `anthropic`, `gemini`, `claude_subscription`), so switching provider never loses another provider's key. A key saved in settings wins over `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`. Settings from before providers existed (flat `openai_api_key` / `openai_model`) are still read, and moved under `ai` the first time AI settings are saved. The API never returns keys, only whether one is set.

To add a provider: write an adapter with `complete_json`, add a `ProviderSpec` in `config.py`, return it from `build_provider` in `__init__.py`, and add its entry to `web/frontend/src/lib/aiProviders.ts`.

`core` does not import FastAPI, React, pywebview, or argparse.

## `web/`

- **`server.py`** — REST endpoints, serves production React build at `/app/`
- **`jobs.py`** — Runs any mod as a background job (concurrency limit, cancel, undo); SSE streams logs and progress
- **`mod_params.py`** — Builds each mod's request-validation model from its manifest (or its own `Params`)
- **`schemas.py`** — Pydantic models (local paths, no upload)
- **`desktop.py`** — Starts uvicorn in a thread, opens pywebview
- **`desktop_api.py`** — Native file/folder dialogs for the React UI
- **`run.py`** — Shared port selection and uvicorn startup

Long-running work uses background threads with cancel support. The UI polls job status and subscribes to `/api/jobs/{id}/events`.

## `cli/`

- **`args.py`** — Subcommand definitions for the built-in features
- **`dispatch.py`** — `command → core.run_*` table
- **`mods_cli.py`** — `toolbox mods ...` and one generated subcommand per enabled user mod
- **`console.py`** — Installs console log/progress handlers via `core.progress`

## Mods

Every feature is a **mod**: a folder with a `mod.toml` manifest (name, group, parameters, ...)
and a `main.py` with `run(params, ctx)`. A **theme** is a mod with `type = "theme"` and no code. Toolbox's own features live in `builtin_mods/`;
users can add more under `<app data>/mods/` (off until enabled). See [MODDING.md](MODDING.md).

```
builtin_mods/<id>/   mod.toml + main.py        (ship with the app, always on)
<app data>/mods/<id>/  mod.toml + main.py      (user mods, opt-in, skipped in safe mode)
        │
core/mods/registry.py   discovers manifests (never runs mod code), imports main.py on first use
        │
web/mod_params.py       manifest [[params]] → pydantic model   ─┐
web/jobs.py             validate → mod.run(params, ctx)          ├─ /api/jobs, /api/mods, /api/commands
web/frontend            /api/mods → nav, home tiles, generated ModForm (or a built-in custom panel)
web/frontend/src/lib/theme.ts   theme tokens → CSS variables (re-validated), Appearance picker
cli/mods_cli.py         manifest [[params]] → argparse flags (user mods; built-ins keep cli/args.py)
```

**Categories.** A tool's `group` is normalised in `core/mods/groups.py`: names match ignoring case and
spacing, the five built-in sections (Files, Media, Subtitles, Experimental, Other) have a fixed order,
and new ones follow A to Z. `order` only positions a mod inside its section. The registry merges
different spellings of a new category and records a notice for a name that merely looks like another.

**Themes and the declarative UI are data, not code.** The colours the interface uses are CSS variables
(`web/frontend/src/index.css`, mapped in `tailwind.config.js`); `core/mods/theme.py` holds the same
token list and defaults (a test compares them), validates a theme down to colours, one length and a font
choice, and refuses a theme that would make warnings or the destructive buttons unreadable. The page
turns the resolved tokens into a `<style>` element (`lib/theme.ts`, values re-checked). A tool's form
(`ModForm.tsx`) is drawn from `[[params]]`, `[[sections]]` (with `show_if`) and `[[actions]]`; results
that a run reports with `ctx.result(...)` arrive as `result` SSE events and are drawn by `ModResults.tsx`.
No mod code runs in the page, and nothing a mod sends is rendered as HTML.

The built-in mods are thin wrappers around the `core` functions. Features whose form is too
rich for a manifest (Stitch, Download, Rename, the subtitle tools) set `[ui] kind = "builtin"`
to use a React panel that ships with the app and export their own `Params` model; only
built-in mods may do that. Mods run in the app's own process on a job thread.

## Packaging

PyInstaller `--onedir` bundles Python, dependencies, `web/frontend/dist` and `builtin_mods/`. Per-OS installers are built in CI (Inno Setup, `.dmg`, AppImage). See `packaging/` and `.github/workflows/release.yml`.

## Design choices

- **Local paths only** — Large videos are never uploaded; the UI sends filesystem paths.
- **ffmpeg first-run download** — Keeps installers small; downloads essentials builds, verifies they run, clears macOS quarantine / Windows MOTW, with UI progress and retry.
- **Unsigned installers** — Acceptable for friends/family; code signing can be added later.
- **Single repo** — Python backend and React frontend live together for simpler releases.
