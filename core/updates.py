"""Check GitHub Releases and apply in-app updates for the packaged desktop app."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from .runtime import app_data_dir, is_frozen
from .settings_store import load_settings
from .version import app_version, normalize_version

logger = logging.getLogger(__name__)

GITHUB_REPO = "MerlijndeVos/Toolbox"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
GITHUB_LATEST = f"{GITHUB_API}/releases/latest"
# Rolling pre-release rebuilt from the production branch on every push (see experimental.yml).
EXPERIMENTAL_TAG = "experimental"
GITHUB_EXPERIMENTAL = f"{GITHUB_API}/releases/tags/{EXPERIMENTAL_TAG}"
_BUILD_MARKER = re.compile(r"build:\s*(\S+)")
USER_AGENT = "Toolbox-updater"

UpdatePhase = Literal["idle", "downloading", "installing", "error"]

_quit_callback: Callable[[], None] | None = None
_lock = threading.Lock()
_state: dict = {
    "phase": "idle",
    "progress": 0.0,
    "message": "",
    "error": None,
}


def register_quit_callback(fn: Callable[[], None]) -> None:
    global _quit_callback
    _quit_callback = fn


def _github_headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _github_get(url: str, timeout: float) -> tuple[int, dict | None, str | None]:
    req = urllib.request.Request(url, headers=_github_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return exc.code, None, body
    except Exception as exc:
        return -1, None, str(exc)


def _parse_version(raw: str) -> tuple[int, int, int]:
    text = normalize_version(raw)
    parts: list[int] = []
    for segment in text.split(".")[:3]:
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def is_experimental_version(version: str) -> bool:
    return "-exp." in normalize_version(version)


def _is_newer(latest: str, current: str) -> bool:
    latest_key, current_key = _parse_version(latest), _parse_version(current)
    if latest_key != current_key:
        return latest_key > current_key
    # X.Y.Z-exp.<sha> is the production branch on top of release X.Y.Z, so it is ahead of it.
    return is_experimental_version(latest) and not is_experimental_version(current)


def _versions_equal(left: str, right: str) -> bool:
    return normalize_version(left) == normalize_version(right)


def _linux_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine in {"aarch64", "arm64"}:
        return "aarch64"
    return machine


def _asset_pattern() -> str:
    if sys.platform == "win32":
        return "-win64.exe"
    if sys.platform == "darwin":
        return "-macos.dmg"
    return f"-linux-{_linux_arch()}.AppImage"


def _pick_asset(assets: list[dict]) -> dict | None:
    pattern = _asset_pattern()
    for asset in assets:
        name = str(asset.get("name", ""))
        if name.endswith(pattern) or (
            sys.platform == "linux"
            and name.endswith(".AppImage")
            and pattern.split("-linux-")[-1] in name
        ):
            return asset
    if sys.platform == "linux":
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.endswith(".AppImage"):
                return asset
    return None


def _asset_download_url(asset: dict) -> str | None:
    url = asset.get("browser_download_url")
    return str(url) if url else None


def _releases_error_message(http_code: int) -> str:
    if http_code in {403, 429}:
        return "GitHub is rate-limiting update checks. Try again in a few minutes."
    if http_code == 404:
        return "No published releases yet."
    if http_code > 0:
        return f"Could not check for updates (HTTP {http_code})."
    return "Could not check for updates (network error)."


def _status_message(
    *,
    current: str,
    latest_version: str | None,
    update_available: bool,
    download_url: str | None,
    error: str | None,
) -> str | None:
    if error:
        return None
    if update_available:
        return None
    if latest_version and _is_newer(latest_version, current) and not download_url:
        return f"v{latest_version} is available — no installer for this platform on the release."
    if latest_version and not _is_newer(latest_version, current):
        return "You're up to date."
    return None


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str | None
    update_available: bool
    can_install: bool
    download_url: str | None
    asset_name: str | None
    release_url: str | None
    release_notes: str | None
    error: str | None = None
    status_message: str | None = None
    experimental: bool = False

    def to_dict(self) -> dict:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "can_install": self.can_install,
            "download_url": self.download_url,
            "asset_name": self.asset_name,
            "release_url": self.release_url,
            "release_notes": self.release_notes,
            "error": self.error,
            "status_message": self.status_message,
            "experimental": self.experimental,
        }


def _base_info(current: str, can_install: bool) -> dict:
    return {
        "current_version": current,
        "can_install": can_install,
        "release_url": f"https://github.com/{GITHUB_REPO}/releases",
    }


def _experimental_info(current: str, can_install: bool, timeout: float) -> UpdateInfo | None:
    """The rolling experimental pre-release, or None when it is missing or unusable."""
    status, payload, _ = _github_get(GITHUB_EXPERIMENTAL, timeout)
    if status != 200 or not payload:
        return None
    body = str(payload.get("body") or "")
    marker = _BUILD_MARKER.search(body)
    if not marker:
        return None
    version = normalize_version(marker.group(1))
    asset = _pick_asset(list(payload.get("assets") or []))
    download_url = _asset_download_url(asset) if asset else None
    update_available = bool(
        download_url and not _versions_equal(version, current) and not _is_newer(current, version)
    )
    return UpdateInfo(
        current_version=current,
        latest_version=version,
        update_available=update_available,
        can_install=can_install,
        download_url=download_url,
        asset_name=str(asset.get("name")) if asset else None,
        release_url=str(payload.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases"),
        release_notes=body.strip() or None,
        status_message=None if update_available else "You're on the latest experimental build.",
        experimental=True,
    )


def check_for_update(timeout: float = 15.0) -> UpdateInfo:
    current = app_version()
    can_install = is_frozen()
    official = _check_official(current, can_install, timeout)
    if not load_settings().get("experimental_updates"):
        return official

    experimental = _experimental_info(current, can_install, timeout)
    if experimental is None:
        return official
    # An official release at or past the experimental base always wins, so nobody is left behind.
    experimental_key = _parse_version(experimental.latest_version or "")
    official_key = _parse_version(official.latest_version or "0")
    if official.latest_version and official_key > experimental_key:
        return official
    if _parse_version(current) > experimental_key:
        return official
    return experimental


def _check_official(current: str, can_install: bool, timeout: float) -> UpdateInfo:

    status, payload, err_body = _github_get(GITHUB_LATEST, timeout)
    if status != 200 or not payload:
        error = _releases_error_message(status)
        if status not in {403, 404, 429} and err_body:
            logger.debug("Update check failed: %s", err_body[:500])
        base = _base_info(current, can_install)
        return UpdateInfo(
            **base,
            latest_version=None,
            update_available=False,
            download_url=None,
            asset_name=None,
            release_notes=None,
            error=error,
            status_message=None,
        )

    tag = normalize_version(str(payload.get("tag_name", "")))
    latest_version = tag or None
    asset = _pick_asset(list(payload.get("assets") or []))
    download_url = _asset_download_url(asset) if asset else None
    asset_name = str(asset.get("name")) if asset else None
    release_url = str(payload.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases")
    release_notes = str(payload.get("body") or "").strip() or None
    update_available = bool(
        latest_version
        and not _versions_equal(latest_version, current)
        and _is_newer(latest_version, current)
        and download_url
    )
    error = None
    status_message = _status_message(
        current=current,
        latest_version=latest_version,
        update_available=update_available,
        download_url=download_url,
        error=error,
    )

    return UpdateInfo(
        current_version=current,
        latest_version=latest_version,
        update_available=update_available,
        can_install=can_install,
        download_url=download_url,
        asset_name=asset_name,
        release_url=release_url,
        release_notes=release_notes,
        error=error,
        status_message=status_message,
    )


def get_apply_status() -> dict:
    with _lock:
        return dict(_state)


def _set_state(
    *,
    phase: UpdatePhase | None = None,
    progress: float | None = None,
    message: str | None = None,
    error: str | None = None,
    clear_error: bool = False,
) -> None:
    with _lock:
        if phase is not None:
            _state["phase"] = phase
        if progress is not None:
            _state["progress"] = progress
        if message is not None:
            _state["message"] = message
        if clear_error:
            _state["error"] = None
        if error is not None:
            _state["error"] = error


def _download_file(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        chunk_size = 256 * 1024
        with dest.open("wb") as out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                read += len(chunk)
                if total > 0:
                    pct = min(99.0, (read / total) * 100.0)
                    _set_state(
                        progress=pct,
                        message=f"Downloading update… {pct:.0f}%",
                    )


def _launch_installer(path: Path) -> None:
    if sys.platform == "win32":
        subprocess.Popen(
            [
                str(path),
                "/SILENT",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
            ],
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], close_fds=True)
        return

    path.chmod(path.stat().st_mode | 0o111)
    subprocess.Popen([str(path)], close_fds=True, start_new_session=True)


def _quit_app() -> None:
    if _quit_callback is not None:
        try:
            _quit_callback()
        except Exception:
            logger.debug("Quit callback failed", exc_info=True)
    os._exit(0)


def _apply_update_worker(info: UpdateInfo) -> None:
    if not info.download_url or not info.asset_name:
        _set_state(phase="error", error="No installer found for this platform.")
        return

    cache_dir = app_data_dir() / "updates"
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / info.asset_name

    try:
        _set_state(phase="downloading", progress=0.0, message="Downloading update…", clear_error=True)
        _download_file(info.download_url, dest)
        _set_state(phase="installing", progress=100.0, message="Installing update — follow the setup progress window…")
        _launch_installer(dest)
        threading.Timer(0.5, _quit_app).start()
    except Exception as exc:
        logger.exception("Update apply failed")
        _set_state(phase="error", error=str(exc))


def start_apply_update(info: UpdateInfo) -> tuple[bool, str | None]:
    if not is_frozen():
        return False, "In-app updates are only available in the installed desktop app."
    if not info.update_available or not info.download_url:
        return False, "No update is available."

    with _lock:
        if _state["phase"] in {"downloading", "installing"}:
            return False, "An update is already in progress."

    thread = threading.Thread(target=_apply_update_worker, args=(info,), daemon=True, name="toolbox-update")
    thread.start()
    return True, None
