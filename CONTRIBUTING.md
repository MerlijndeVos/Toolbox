# Contributing

Thanks for your interest in Toolbox. New features should land in `core/` first, then get wired into the CLI and web API.

## Development setup

```powershell
git clone https://github.com/MerlijndeVos/Toolbox.git
cd Toolbox
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[desktop,pack]"

cd web/frontend && npm install && npm run build
cd ../..
python app.py
```

## Project layout

| Path | Purpose |
|------|---------|
| `core/` | All media processing logic |
| `core/mods/` | Mod system: manifest parser, registry, the `ctx` mods receive |
| `builtin_mods/` | The built-in features, each a mod (`mod.toml` + `main.py`) |
| `cli/` | Command-line interface |
| `web/server.py` | FastAPI app |
| `web/frontend/` | React UI |
| `web/jobs.py` | API job runner (runs any mod) |
| `tests/` | Unit tests (`python -m unittest discover -s tests`) |
| `examples/mods/` | Example mods: a small tool, a tool with the full declarative form, and a theme |
| `app.py` | Desktop entry point |
| `packaging/` | PyInstaller spec and installer scripts |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full picture.

## Adding a feature

Every feature is a mod, see [MODDING.md](MODDING.md).

1. Implement logic in `core/` with logging via the standard `logging` module (respects `core.progress` hooks).
2. Add `builtin_mods/<id>/mod.toml` and `main.py` (`run(params, ctx)` calls into `core`). Describe the
   parameters in `[[params]]`: the form, the API validation and the CLI flags are generated from them.
   Use [`builtin_mods/trim`](builtin_mods/trim) as a model.
3. Only if the form is too rich for a manifest: set `[ui] kind = "builtin"`, add a React panel and
   register it in `BuiltinPanel` in `web/frontend/src/components/ToolPanel.tsx`, and export a
   `Params` pydantic model from `main.py`.
4. Optional: a hand-written subcommand in `cli/args.py` + `cli/dispatch.py` if you want richer flags
   than the generated ones.
5. Test with `python -m unittest discover -s tests`, the CLI and the desktop app.

## Frontend

```powershell
python -m web
cd web/frontend && npm run dev
```

Build before committing UI changes:

```powershell
cd web/frontend && npm run build
```

## Releases

**Version lives in one place:** bump `[project].version` in `pyproject.toml` only.

Build scripts, CI, the in-app updater, and installers all read from there. When you tag a release, the tag must match (e.g. pyproject `0.2.0` → tag `v0.2.0`).

Each release also needs a committed notes file: `release-notes/vX.Y.Z.md` (copy from `release-notes/TEMPLATE.md`). CI publishes that file as the GitHub Release body — do not rely on auto-generated notes.

```powershell
# 1. Write release-notes/v0.2.0.md and bump version in pyproject.toml
# 2. Commit
git add pyproject.toml release-notes/v0.2.0.md
git commit -m "Release v0.2.0"
git push origin main

# 3. Releases come from the production branch: fast-forward it to main
git switch production && git merge --ff-only main && git push origin production

# 4. Tag the production commit and push the tag — CI builds Windows, macOS, and Linux installers
git tag v0.2.0 && git push origin v0.2.0
```

`main` is where work lands; `production` is the branch releases are cut from. CI refuses a version tag (or a manual run) whose commit is not on `production`.

Local Windows bundle:

```powershell
.\packaging\build.ps1
```

## Code style

- Match existing patterns in the file you edit.
- Keep `core/` free of web/CLI imports.
- Prefer focused diffs; avoid drive-by refactors.
- Python 3.11+ type hints where they clarify intent.

## Issues and PRs

Open an issue for large changes before starting work. PRs should describe what was tested (CLI command, UI flow, or packaging build).
