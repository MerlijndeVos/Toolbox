<div align="center">
<img src="packaging/icons/toolbox.svg" width="128" alt="Toolbox app icon"/>

# Toolbox
### Media processing for your desktop

**Convert, trim, stitch, organize libraries, download from YouTube, and more**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Website](https://img.shields.io/badge/Website-toolbox.murly.nl-0ea5e9)](https://toolbox.murly.nl)
[![GitHub Releases](https://img.shields.io/badge/Releases-GitHub-blue)](https://github.com/MerlijndeVos/Toolbox/releases)

</div>

---

## Features

| Tool | What it does |
|------|----------------|
| **Convert** | Batch-convert video (e.g. DV → H.264 MP4) with folder mirroring and optional NVENC |
| **Trim** | Cut seconds off the start/end of one file or a whole folder |
| **Stitch** | Join multiple clips end-to-end |
| **Download** | Save URLs as MP4 or MP3 via yt-dlp |
| **DVD (VTS)** | Join DVD `VIDEO_TS` VOB segments into MKV per title |
| **Rename** | Organize TV/movie files for Plex/Jellyfin, or clean up any folder/file names, with reusable format profiles (optionally AI-generated: from examples you type, or by letting the AI look at a capped sample of the names in your folder, which you then check and correct). In the *Other* mode the selected folder itself can be renamed too. Includes a built-in *Date + name* profile that date-stamps folders (`2006 juli 13 - Holiday`) from the dates in their video file names |
| **Audio** | Set default audio track in MKV files |
| **Dedup** | Strip `(2)` duplicate suffixes from filenames |

The UI includes drag-and-drop paths, live logs, per-job progress, light and dark mode with switchable themes and syntax highlighting for code and logs (**Settings → Appearance**), and native folder pickers in the desktop app.

**Mods:** every tool above is a *mod*, and you can add your own without touching the app's code. A mod is a folder with a `mod.toml` and a `main.py`; it gets a generated form, live logs and a `toolbox <id>` command. Install one from a git address, folder, zip or file (with a review prompt first), or browse the [mod market](market/README.md); mods you add start turned off. A mod picks which menu section it appears in, and its form can have sections, conditional fields, sliders and a table or file list of results, all from `mod.toml`. **Themes** are mods too: one data file that changes colours, corners and font (no code), installable the same way. See **[MODDING.md](MODDING.md)** (it includes prompts you can give an AI assistant to write a mod or design a theme for you) and the examples in [`examples/mods`](examples/mods).

**AI (optional):** subtitle translation and AI-generated rename profiles need an AI provider. Pick one on the **AI** page in settings: **OpenAI** (the default), any **OpenAI-compatible** server (Ollama, LM Studio, OpenRouter, Groq, ... using a base URL, so a local model keeps everything on your machine), **Anthropic (Claude)**, **Google Gemini**, or your **Claude subscription** (Pro/Max, through the Claude Code program, no API key needed). Each provider keeps its own key, and **Test connection** checks the settings before you use them. The AI page also shows a **Usage** window with tokens per day, task and model, and your Claude plan's 5-hour and weekly limits. Keys can also come from `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY`.

## Install (end users)

Download the installer for your OS from **[GitHub Releases](https://github.com/MerlijndeVos/Toolbox/releases)** (tag `v0.1.0` or newer).

| Platform | File |
|----------|------|
| Windows | `Toolbox-Setup-*-win64.exe` |
| macOS | `Toolbox-*-macos.dmg` |
| Linux | `Toolbox-*-linux-*.AppImage` |

Installers are **unsigned**. Windows SmartScreen and macOS Gatekeeper may ask you to confirm once (“Run anyway” / “Open”).

**ffmpeg** is **not** included in the installer (keeps downloads small). On first launch the app downloads a one-time essentials build (~100 MB) into your user data folder. The app verifies the binaries run correctly and shows progress in the UI; use **Retry** if your OS or antivirus blocks them. Installers are unsigned — you may need to allow the app once, and on macOS check **System Settings → Privacy & Security** if ffmpeg is blocked after download.

## Run from source

Requires **Python 3.11+** and **Node.js 20+** (for building the UI).

```powershell
git clone https://github.com/MerlijndeVos/Toolbox.git
cd Toolbox
pip install -e ".[desktop]"
cd web/frontend && npm install && npm run build
cd ../..
python app.py
```

Equivalent entry points after install:

```powershell
toolbox-app          # desktop window
toolbox-web          # API + browser UI at http://127.0.0.1:8765/app/
toolbox convert --help   # CLI
```

### Dependency groups

| Group | Install | Use |
|-------|---------|-----|
| (default) | `pip install -e .` | CLI + yt-dlp |
| `web` | `pip install -e ".[web]"` | FastAPI server |
| `desktop` | `pip install -e ".[desktop]"` | pywebview app |
| `pack` | `pip install -e ".[pack]"` | PyInstaller (add to desktop for builds) |

All dependencies are declared in `pyproject.toml`.

### Web UI development

```powershell
# Terminal 1
pip install -e ".[web]"
python -m web

# Terminal 2
cd web/frontend && npm install && npm run dev
```

Open http://127.0.0.1:5173/app/ (Vite proxies `/api` to port 8765).

### Build installers locally

```powershell
pip install -e ".[desktop,pack]"
.\packaging\build.ps1
# → dist\Toolbox\Toolbox.exe
# Optional: iscc packaging\windows\setup.iss
```

Push a version tag to trigger CI builds for all three platforms:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Builds appear at https://github.com/MerlijndeVos/Toolbox/releases.

## Command line

Every feature is available as a subcommand. Examples:

```powershell
toolbox convert --input "C:\DV_in" --output "D:\DV_out"
toolbox vts --input "D:\DVD_rips" --output "E:\MKV_out" --dry-run
toolbox rename --input "Z:\Media"                # previews; add --apply to rename
toolbox rename --input "D:\Samples" --mode generic --targets both --max-depth 3 --profile "Tidy names"
toolbox rename --input "D:\Samples\Pack_[FREE]" --mode generic --include-root --apply   # also renames the Pack_[FREE] folder itself, last
toolbox dedup --input "Z:\Media" --apply
toolbox download --url "https://youtu.be/…" --output "D:\Downloads"
toolbox trim --input "clip.mp4" --trim-start 10
toolbox stitch --input part1.mp4 --input part2.mp4 --output joined.mp4
toolbox rename --input "D:\DV_out" --mode generic --profile "Date + name (Dutch)" --apply
```

`toolbox mods list` shows every mod, `mods install <git-url|folder|zip|file>` adds one (after showing you what it is), `mods search` browses the market, `mods update [id]` checks for newer commits, `mods enable|disable|remove <id>` manage them, and `--no-mods` starts without any user mods.

Use `--help` on any subcommand for full options. GPU encoding (`--use-gpu auto|on|off`), CRF, presets, dry-run, and resume-safe output handling apply where relevant.

### External tools

| Tool | Required for | Notes |
|------|----------------|-------|
| ffmpeg / ffprobe | Convert, trim, stitch, VTS, download, audio default | Auto-downloaded on first app launch (or use a system install on PATH) |
| Node.js or Deno | YouTube downloads | Needed by yt-dlp for modern YouTube extraction |

## Architecture

Three layers share one `core/` library:

```
core/          ← all media logic (ffmpeg, yt-dlp, rename rules, …) and the mod loader
builtin_mods/  ← the built-in features, each a mod (mod.toml + main.py)
cli/           ← argparse → core
web/           ← FastAPI + React UI + pywebview desktop shell
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for detail. Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Built with

- [Python](https://python.org) 3.11 — [FastAPI](https://fastapi.tiangolo.com) — [uvicorn](https://www.uvicorn.org)
- [React](https://react.dev) — [Vite](https://vitejs.dev) — [Tailwind CSS](https://tailwindcss.com)
- [pywebview](https://pywebview.flowrl.com) — [yt-dlp](https://github.com/yt-dlp/yt-dlp) — [ffmpeg](https://ffmpeg.org)
- [PyInstaller](https://pyinstaller.org) — GitHub Actions

## Legal

Only download or convert content you own or are licensed to use. YouTube downloads may violate YouTube’s Terms of Service if used on third-party content.
