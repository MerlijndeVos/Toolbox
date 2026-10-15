# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — desktop app (--onedir).

Build (from repo root, after ``npm run build`` in web/frontend)::

    pip install -e ".[desktop,pack]"
    pyinstaller packaging/toolbox.spec --noconfirm --clean
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

import tomllib

REPO_ROOT = Path(SPECPATH).resolve().parent
FRONTEND_DIST = REPO_ROOT / "web" / "frontend" / "dist"
ICON_DIR = REPO_ROOT / "packaging" / "icons"
WINDOWS_ICON = ICON_DIR / "toolbox.ico"
MACOS_ICON = ICON_DIR / "toolbox.icns"

if not FRONTEND_DIST.is_dir():
    raise SystemExit(
        f"Frontend build missing: {FRONTEND_DIST}\n"
        "Run: cd web/frontend && npm install && npm run build"
    )

block_cipher = None

datas: list[tuple[str, str]] = [(str(FRONTEND_DIST), "web/frontend/dist")]
if ICON_DIR.is_dir():
    datas.append((str(ICON_DIR), "packaging/icons"))
_bundled_version_file = REPO_ROOT / "packaging" / ".bundled-version"
with (REPO_ROOT / "pyproject.toml").open("rb") as _pf:
    _pyproject_version = tomllib.load(_pf)["project"]["version"]
# Experimental builds set TOOLBOX_BUNDLED_VERSION (e.g. 3.6.0-exp.3e0bc3f) so the app knows what it is.
_bundled_version = os.environ.get("TOOLBOX_BUNDLED_VERSION", "").strip() or _pyproject_version
_bundled_version_file.write_text(_bundled_version + "\n", encoding="utf-8")
datas.append((str(_bundled_version_file), "."))
# Built-in features are mods: a mod.toml + main.py per folder, loaded from files at runtime.
# (Their imports are bundled through the hidden imports below.)
BUILTIN_MODS = REPO_ROOT / "builtin_mods"
for _mod_file in sorted(BUILTIN_MODS.glob("*/*")):
    if _mod_file.suffix in {".toml", ".py"}:
        datas.append((str(_mod_file), f"builtin_mods/{_mod_file.parent.name}"))
try:
    datas += copy_metadata("toolbox")
except Exception:
    pass
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "app",
    "core",
    "core.runtime",
    "core.version",
    "core.ffmpeg_bootstrap",
    "core.updates",
    "cli",
    "web",
    "web.server",
    "web.desktop",
    "web.desktop_api",
    "web.jobs",
    "web.schemas",
    "web.paths",
    "web.run",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.importer",
    "httptools",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    "watchfiles",
    "pythonnet",
    "clr_loader",
]

# Mods are plain Python loaded at runtime, so PyInstaller cannot see what they import.
# Bundle everything the built-in mods use, and the parts of the standard library a mod
# is likely to want (PyInstaller only includes stdlib modules the app itself imports).
hiddenimports += collect_submodules("core")
hiddenimports += [
    "argparse", "base64", "bisect", "collections", "concurrent.futures", "copy", "csv",
    "dataclasses", "datetime", "decimal", "difflib", "enum", "fnmatch", "fractions", "functools",
    "glob", "gzip", "hashlib", "heapq", "html", "html.parser", "http.client", "io", "itertools",
    "json", "logging", "math", "mimetypes", "operator", "os", "pathlib", "platform", "random",
    "re", "secrets", "shlex", "shutil", "sqlite3", "statistics", "string", "struct",
    "subprocess", "tempfile", "textwrap", "time", "typing", "unicodedata", "urllib.parse",
    "urllib.request", "uuid", "xml.etree.ElementTree", "zipfile",
]

for pkg in (
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "yt_dlp",
    "webview",
    "anyio",
    "sniffio",
    # certifi's own hook only ships cacert.pem; without its code in the bundle,
    # ``import certifi`` resolves to the bare data folder and yt-dlp fails with
    # "module 'certifi' has no attribute 'where'".
    "certifi",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        hiddenimports += collect_submodules(pkg)

a = Analysis(
    [str(REPO_ROOT / "app.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

_bundled_modules = {entry[0] for entry in a.pure}
_missing_modules = [m for m in ("certifi", "yt_dlp") if m not in _bundled_modules]
if _missing_modules:
    raise SystemExit(f"Required modules missing from the bundle: {', '.join(_missing_modules)}")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Toolbox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(WINDOWS_ICON) if sys.platform == "win32" and WINDOWS_ICON.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Toolbox",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Toolbox.app",
        icon=str(MACOS_ICON) if MACOS_ICON.is_file() else None,
        bundle_identifier="local.toolbox.app",
    )
