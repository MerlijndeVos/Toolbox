"""FastAPI application for the Toolbox local web API."""

from __future__ import annotations

import asyncio
import json
import logging
import queue
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional, get_args

from core.ai import (
    PROVIDERS as AI_PROVIDERS,
    AiConfigError,
    AiError,
    check_connection,
    resolve_provider,
    save_ai_settings,
    stored_ai_settings,
    usage as ai_usage,
)
from core.download import probe_url
from core.rename import preview_media_name
from core.rename_ai import FolderContext, generate_profile
from core.rename_generic import preview_generic
from core.rename_profiles import (
    ProfileError,
    delete_profile,
    list_profiles,
    profile_from_dict,
    save_profile,
)
from core.subtitles import detect_lang_from_path, scan_junk
from core.subtitle_languages import language_options
from core.log_storage import clear_logs, logs_dir, logs_stats, read_log_chunk, resolve_log_file
from core.mods import ModCancelled, ModContext, ModError, install as mod_install, market as mod_market, prompts as mod_prompts
from core.mods import registry, safe_mode, set_safe_mode, user_mods_dir
from core.mods.groups import BUILTIN_GROUPS
from core.mods.results import ResultError, build_result, from_return
from core.settings_store import load_settings, save_settings
from core.shell import can_open_directly, open_path, reveal_path
from core.tools import get_tools_status, retry_bootstrap_background, start_bootstrap_background
from core.updates import check_for_update, get_apply_status, start_apply_update
from core.version import app_version
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .jobs import job_manager
from .mod_params import action_params_model, get_enabled_mod, params_model, validate_params
from .schemas import (
    ClearLogsResponse,
    CommandInfo,
    CommandsResponse,
    DownloadProbeRequest,
    DownloadProbeResponse,
    HealthResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobSummary,
    JobUndoResponse,
    LogChunkResponse,
    LogsStatsResponse,
    ModActionRequest,
    ModActionResponse,
    ModEnableRequest,
    ModInstallConfirmRequest,
    ModInstallPrepareRequest,
    ModPromptsResponse,
    ModsResponse,
    OpenLogFileRequest,
    OpenPathResponse,
    OpenResultRequest,
    RenameProfileGenerateRequest,
    RenameProfileGenerateResponse,
    SafeModeRequest,
    RenameProfileSaveRequest,
    RenameProfilesResponse,
    RenameProfileTestItem,
    RenameProfileTestRequest,
    RenameProfileTestResponse,
    AiProviderSettings,
    AiSettingsResponse,
    AiTestRequest,
    AiTestResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    SyntaxScheme,
    SubtitleLanguagesResponse,
    SubtitleScanJunkRequest,
    SubtitleScanJunkResponse,
    LanguageOption,
    SubtitleJunkItem,
    UpdateApplyResponse,
    UpdateApplyStatusResponse,
    UpdateCheckResponse,
)

from .paths import FRONTEND_DIST

logger = logging.getLogger(__name__)

# A mod action runs while the page waits, so it gets a limit. (Python cannot stop a running
# thread: a slow action is abandoned, not killed.)
ACTION_TIMEOUT_SECONDS = 120.0
_action_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mod-action")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    start_bootstrap_background()
    yield


app = FastAPI(
    title="Toolbox API",
    description="Local REST + SSE API for video conversion, rename, download, and related tools.",
    version=app_version(),
    lifespan=_lifespan,
)

# Allow the future React dev server and pywebview origin to call localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(version=app_version())


@app.get("/api/updates/check", response_model=UpdateCheckResponse)
def updates_check() -> UpdateCheckResponse:
    return UpdateCheckResponse(**check_for_update().to_dict())


@app.post("/api/updates/apply", response_model=UpdateApplyResponse)
def updates_apply() -> UpdateApplyResponse:
    info = check_for_update()
    ok, detail = start_apply_update(info)
    return UpdateApplyResponse(ok=ok, detail=detail)


@app.get("/api/updates/status", response_model=UpdateApplyStatusResponse)
def updates_status() -> UpdateApplyStatusResponse:
    return UpdateApplyStatusResponse(**get_apply_status())


@app.get("/api/tools")
def tools_status() -> dict:
    return get_tools_status(auto_bootstrap=True)


@app.post("/api/tools/bootstrap")
def tools_bootstrap_retry() -> dict:
    retry_bootstrap_background()
    return get_tools_status(auto_bootstrap=False)


def _ai_settings_response() -> AiSettingsResponse:
    providers = {}
    for pid, spec in AI_PROVIDERS.items():
        resolved = resolve_provider(pid)
        providers[pid] = AiProviderSettings(
            api_key_set=bool(resolved.api_key),
            api_key_from_env=resolved.key_from_env,
            model=resolved.model,
            default_model=spec.default_model,
            base_url=resolved.base_url,
        )
    return AiSettingsResponse(provider=stored_ai_settings()["provider"], providers=providers)


def _settings_response() -> SettingsResponse:
    settings = load_settings()
    return SettingsResponse(
        file_logging=bool(settings.get("file_logging", True)),
        ai=_ai_settings_response(),
        logs=LogsStatsResponse(**logs_stats()),
        theme=str(settings.get("theme") or "theme-default"),
        color_mode=settings.get("color_mode") if settings.get("color_mode") in ("system", "light", "dark") else "system",
        syntax_code=bool(settings.get("syntax_code", True)),
        syntax_logs=bool(settings.get("syntax_logs", True)),
        syntax_scheme=scheme if (scheme := settings.get("syntax_scheme")) in get_args(SyntaxScheme) else "theme",
        experimental_updates=bool(settings.get("experimental_updates", False)),
    )


@app.get("/api/settings", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    return _settings_response()


@app.patch("/api/settings", response_model=SettingsResponse)
def update_settings(body: SettingsUpdateRequest) -> SettingsResponse:
    updates = body.model_dump(exclude_unset=True)
    ai_update = updates.pop("ai", None)
    if ai_update:
        try:
            save_ai_settings(provider=ai_update.get("provider"), providers=ai_update.get("providers"))
        except AiConfigError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updates:
        save_settings(**updates)
    return _settings_response()


@app.post("/api/ai/test", response_model=AiTestResponse)
def ai_test(body: AiTestRequest) -> AiTestResponse:
    """Blocking network call, so a plain ``def`` (FastAPI runs it in a worker thread)."""
    try:
        message = check_connection(
            body.provider,
            overrides={"api_key": body.api_key or "", "model": body.model or "", "base_url": body.base_url or ""},
        )
    except AiError as exc:
        return AiTestResponse(ok=False, message=str(exc))
    except Exception as exc:  # a broken SDK/TLS setup should still reach the UI as text
        return AiTestResponse(ok=False, message=f"Unexpected error: {exc}")
    return AiTestResponse(ok=True, message=message)


@app.get("/api/ai/usage")
def ai_usage_summary() -> dict:
    """Token usage from the local ledger, plus the Claude plan windows when a subscription is used."""
    return {**ai_usage.summary(), "provider": stored_ai_settings()["provider"]}


@app.delete("/api/ai/usage")
def ai_usage_clear() -> dict:
    ai_usage.clear()
    return {**ai_usage.summary(), "provider": stored_ai_settings()["provider"]}


@app.post("/api/ai/usage/refresh")
def ai_usage_refresh() -> dict:
    """Make one tiny Claude call so the plan windows are current. Costs a few hundred tokens."""
    try:
        check_connection("claude_subscription")
    except AiError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**ai_usage.summary(), "provider": stored_ai_settings()["provider"]}


@app.get("/api/rename/profiles", response_model=RenameProfilesResponse)
def rename_profiles() -> RenameProfilesResponse:
    return RenameProfilesResponse(profiles=[p.to_dict() for p in list_profiles()])


@app.post("/api/rename/profiles")
def rename_profile_save(body: RenameProfileSaveRequest) -> dict:
    try:
        return save_profile(body.profile).to_dict()
    except ProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/rename/profiles/{profile_id}")
def rename_profile_delete(profile_id: str) -> dict:
    try:
        deleted = delete_profile(profile_id)
    except ProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"ok": True}


@app.post("/api/rename/profiles/test", response_model=RenameProfileTestResponse)
def rename_profile_test(body: RenameProfileTestRequest) -> RenameProfileTestResponse:
    try:
        profile = profile_from_dict(body.profile)
    except ProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    results: list[RenameProfileTestItem] = []
    for sample in body.samples:
        sample = sample.strip()
        if not sample:
            continue
        if body.mode == "media":
            result = preview_media_name(profile, sample)
            note = None if result else "Not recognised as an episode or movie (needs SxxExx or a year)."
        else:
            result, note = preview_generic(profile, sample)
        results.append(RenameProfileTestItem(sample=sample, result=result, note=note))
    return RenameProfileTestResponse(results=results)


@app.post("/api/rename/profiles/generate", response_model=RenameProfileGenerateResponse)
def rename_profile_generate(body: RenameProfileGenerateRequest) -> RenameProfileGenerateResponse:
    from pathlib import Path

    from core.paths import clean_path_string, path_is_dir

    context: Optional[FolderContext] = None
    if body.folder:
        folder = Path(clean_path_string(body.folder))
        if not path_is_dir(folder):
            raise HTTPException(status_code=422, detail=f"Folder not found: {folder}")
        try:
            context = FolderContext.scan(folder, body.targets, body.max_depth, body.include_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not context.items:
            raise HTTPException(
                status_code=422,
                detail="There is nothing in this folder to look at with the chosen options.",
            )
    try:
        result = generate_profile(
            [e.model_dump(exclude_none=True) for e in body.examples], body.mode, folder=context
        )
    except ValueError as exc:  # invalid input/profile or missing API key
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}") from exc
    return RenameProfileGenerateResponse(**result)


@app.get("/api/subtitles/languages", response_model=SubtitleLanguagesResponse)
def subtitle_languages() -> SubtitleLanguagesResponse:
    return SubtitleLanguagesResponse(
        languages=[LanguageOption(**item) for item in language_options()],
    )


@app.post("/api/subtitles/scan-junk", response_model=SubtitleScanJunkResponse)
def subtitle_scan_junk(body: SubtitleScanJunkRequest) -> SubtitleScanJunkResponse:
    from pathlib import Path

    from core.paths import clean_path_string, path_exists, path_is_dir, path_is_file

    input_path = Path(clean_path_string(body.input))
    if not path_exists(input_path):
        raise HTTPException(status_code=422, detail=f"Input path not found: {input_path}")
    try:
        items = scan_junk(input_path)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    detected: Optional[str] = None
    if path_is_file(input_path):
        detected = detect_lang_from_path(input_path)
    elif path_is_dir(input_path):
        for path in sorted(input_path.rglob("*.srt")):
            detected = detect_lang_from_path(path)
            if detected:
                break

    return SubtitleScanJunkResponse(
        items=[SubtitleJunkItem(**item.to_dict()) for item in items],
        detected_source_lang=detected,
    )


@app.delete("/api/settings/logs", response_model=ClearLogsResponse)
def delete_logs() -> ClearLogsResponse:
    deleted = clear_logs()
    return ClearLogsResponse(deleted_count=deleted, logs=LogsStatsResponse(**logs_stats()))


@app.get("/api/settings/logs/{name}", response_model=LogChunkResponse)
def read_log_file(
    name: str,
    end: Optional[int] = Query(None, ge=0),
    lines: int = Query(500, ge=1, le=5000),
) -> LogChunkResponse:
    """Read the last ``lines`` lines of a stored log, or the lines before byte offset ``end``."""
    try:
        return LogChunkResponse(**read_log_chunk(name, end=end, max_lines=lines))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/settings/logs/open-folder", response_model=OpenPathResponse)
def open_logs_folder() -> OpenPathResponse:
    try:
        open_path(logs_dir())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return OpenPathResponse()


@app.post("/api/settings/logs/open-file", response_model=OpenPathResponse)
def open_log_file(body: OpenLogFileRequest) -> OpenPathResponse:
    try:
        open_path(resolve_log_file(body.name))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return OpenPathResponse()


@app.get("/api/commands", response_model=CommandsResponse)
def list_commands() -> CommandsResponse:
    commands = [
        CommandInfo(name=mod.id, description=mod.manifest.description)
        for mod in registry.enabled("tool")
    ]
    return CommandsResponse(commands=commands)


@app.get("/api/commands/{command}/schema")
def command_schema(command: str) -> dict:
    mod = registry.get(command)
    if mod is None or not mod.enabled or mod.is_theme:
        raise HTTPException(status_code=404, detail=f"Unknown command: {command}")
    try:
        return params_model(mod).model_json_schema()
    except ModError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _mods_response() -> ModsResponse:
    return ModsResponse(
        mods=[mod.to_dict() for mod in registry.all()],
        errors=[err.to_dict() for err in registry.errors()],
        notices=[note.to_dict() for note in registry.notices()],
        groups=[{"name": name, "description": text} for name, text in BUILTIN_GROUPS],
        safe_mode=safe_mode(),
        mods_dir=str(user_mods_dir()),
    )


@app.get("/api/mods", response_model=ModsResponse)
def list_mods() -> ModsResponse:
    """Every mod (built-in features and user-installed), with its manifest and on/off state."""
    return _mods_response()


@app.post("/api/mods/reload", response_model=ModsResponse)
def reload_mods() -> ModsResponse:
    registry.reload()
    return _mods_response()


@app.patch("/api/mods/{mod_id}", response_model=ModsResponse)
def set_mod_enabled(mod_id: str, body: ModEnableRequest) -> ModsResponse:
    try:
        registry.set_enabled(mod_id, body.enabled)
    except ModError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _mods_response()


@app.post("/api/mods/safe-mode", response_model=ModsResponse)
def set_mods_safe_mode(body: SafeModeRequest) -> ModsResponse:
    """Turn every user mod off (or back on) until the app is restarted. Built-in features stay on."""
    set_safe_mode(body.enabled)
    registry.reload()
    return _mods_response()


@app.get("/api/mods/prompts", response_model=ModPromptsResponse)
def mod_ai_prompts() -> ModPromptsResponse:
    """The copy-paste prompts for building a mod, and for reviewing someone else's, with an AI assistant."""
    return ModPromptsResponse(
        build=mod_prompts.BUILD_PROMPT, review=mod_prompts.REVIEW_PROMPT, theme=mod_prompts.THEME_PROMPT
    )


@app.get("/api/mods/market")
def mods_market(refresh: bool = False) -> dict:
    """Mods listed in the public market index. Listing is not a review."""
    return mod_market.fetch_market(force=refresh)


@app.post("/api/mods/install/prepare")
def prepare_mod_install(body: ModInstallPrepareRequest) -> dict:
    """Download and check a mod without running it; the answer is what the trust prompt shows."""
    try:
        return mod_install.prepare(
            body.location,
            ref=body.ref,
            subdir=body.subdir,
            update_of=body.update_of,
            expect=body.expect,
        )
    except ModError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mods/install/confirm", response_model=ModsResponse)
def confirm_mod_install(body: ModInstallConfirmRequest) -> ModsResponse:
    try:
        mod_install.commit(body.token, enable=body.enable)
    except ModError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _mods_response()


@app.delete("/api/mods/install/{token}", response_model=OpenPathResponse)
def cancel_mod_install(token: str) -> OpenPathResponse:
    try:
        mod_install.discard(token)
    except ModError:
        pass  # already gone
    return OpenPathResponse()


@app.post("/api/mods/{mod_id}/actions/{action}", response_model=ModActionResponse)
def run_mod_action(mod_id: str, action: str, body: ModActionRequest) -> ModActionResponse:
    """Run one of a mod's ``[[actions]]`` (for example "Test connection") and return what it shows.

    The function is ``action_<name>(params, ctx)`` in the mod's ``main.py``. It may call
    ``ctx.result(...)`` and/or return text or a result dict. Only actions the manifest declares can be called.
    """
    try:
        mod = get_enabled_mod(mod_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    spec = next((a for a in mod.manifest.actions if a.name == action), None)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"'{mod_id}' has no action '{action}'.")
    try:
        params = action_params_model(mod, spec.params).model_validate(body.params).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        fn = getattr(mod.load_module(), f"action_{action}", None)
    except ModError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not callable(fn):
        raise HTTPException(status_code=500, detail=f"'{mod_id}' declares the action '{action}' but does not define action_{action}(params, ctx).")

    results: list[dict] = []
    ctx = ModContext(mod.id, on_result=results.append)
    future = _action_pool.submit(fn, params, ctx)
    try:
        value = future.result(timeout=ACTION_TIMEOUT_SECONDS)
        results.extend(from_return(value))
    except FutureTimeout:
        return ModActionResponse(
            ok=False,
            results=[build_result("message", {"text": f"'{spec.label}' took longer than {ACTION_TIMEOUT_SECONDS:.0f} seconds and was given up on.", "level": "error"})],
        )
    except ModCancelled:
        return ModActionResponse(ok=False, results=[build_result("message", {"text": "Cancelled.", "level": "warning"})])
    except ResultError as exc:
        return ModActionResponse(ok=False, results=[build_result("message", {"text": f"The mod returned something that cannot be shown: {exc}", "level": "error"})])
    except Exception as exc:  # a broken mod must not look like a crash of Toolbox
        logger.exception("Action %s of mod %s failed", action, mod_id)
        return ModActionResponse(ok=False, results=[build_result("message", {"text": str(exc) or exc.__class__.__name__, "level": "error"})])
    return ModActionResponse(ok=True, results=results)


@app.get("/api/mods/{mod_id}/source")
def mod_source(mod_id: str) -> dict:
    """The files of an installed mod, so the user can read the code."""
    try:
        return mod_install.describe_installed(mod_id)
    except ModError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/mods/{mod_id}/update")
def mod_update_status(mod_id: str) -> dict:
    """Is a newer commit available for a git-installed mod? Only looks, never updates."""
    try:
        return mod_install.check_update(mod_id)
    except ModError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mods/{mod_id}/update/prepare")
def prepare_mod_update(mod_id: str) -> dict:
    """Stage the newest commit for review. Nothing changes until it is confirmed."""
    try:
        return mod_install.prepare_update(mod_id)
    except ModError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/mods/{mod_id}", response_model=ModsResponse)
def remove_mod(mod_id: str) -> ModsResponse:
    try:
        mod_install.remove(mod_id)
    except ModError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _mods_response()


@app.post("/api/mods/open-folder", response_model=OpenPathResponse)
def open_mods_folder() -> OpenPathResponse:
    try:
        open_path(user_mods_dir(create=True))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return OpenPathResponse()


@app.get("/api/jobs", response_model=list[JobSummary])
def list_jobs() -> list[JobSummary]:
    jobs = sorted(job_manager.list_jobs(), key=lambda j: j.created_at, reverse=True)
    return [JobSummary(**j.to_dict()) for j in jobs]


@app.get("/api/jobs/{job_id}", response_model=JobSummary)
def get_job(job_id: str) -> JobSummary:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobSummary(**job.to_dict())


@app.post("/api/download/probe", response_model=DownloadProbeResponse)
def download_probe(body: DownloadProbeRequest) -> DownloadProbeResponse:
    try:
        result = probe_url(
            url=body.url,
            out_format=body.format,
            video_quality=body.video_quality,
            audio_bitrate=body.audio_bitrate,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DownloadProbeResponse(**result)


@app.post("/api/jobs", response_model=JobCreateResponse, status_code=201)
def create_job(body: JobCreateRequest) -> JobCreateResponse:
    try:
        validate_params(body.command, body.params)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = job_manager.create(
        body.command,
        body.params,
        file_logging=body.file_logging,
    )
    summary = JobSummary(**job.to_dict())
    return JobCreateResponse(
        job=summary,
        events_url=f"/api/jobs/{job.id}/events",
    )


@app.post("/api/jobs/{job_id}/results/open", response_model=OpenPathResponse)
def open_job_result(job_id: str, body: OpenResultRequest) -> OpenPathResponse:
    """Open (or show in its folder) a file a job listed in a ``files`` result.

    Only paths the job itself reported can be opened, so a page cannot use this to start
    arbitrary files; anything that could run a program is only ever shown in its folder.
    """
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if body.path not in job.result_paths():
        raise HTTPException(status_code=403, detail="That path was not listed by this job.")
    path = Path(body.path)
    try:
        if body.reveal or not can_open_directly(path):
            reveal_path(path)
        else:
            open_path(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="That file no longer exists.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return OpenPathResponse()


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    if not job_manager.cancel(job_id):
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        raise HTTPException(status_code=409, detail=f"Job cannot be cancelled (status={job.status})")
    return {"ok": True, "job_id": job_id}


@app.post("/api/jobs/{job_id}/undo", response_model=JobUndoResponse, status_code=201)
def undo_job(job_id: str) -> JobUndoResponse:
    try:
        job = job_manager.undo_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    summary = JobSummary(**job.to_dict())
    return JobUndoResponse(
        job=summary,
        events_url=f"/api/jobs/{job.id}/events",
        source_job_id=job_id,
    )


async def _sse_stream(job_id: str) -> AsyncIterator[str]:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    loop = asyncio.get_running_loop()

    while True:
        try:
            item = await loop.run_in_executor(None, job.events.get, True, 30.0)
        except queue.Empty:  # timeout waiting for events
            yield ": keepalive\n\n"
            continue

        if item is None:
            yield f"event: end\ndata: {json.dumps({'job_id': job_id})}\n\n"
            break

        event_type = item.get("type", "message")
        data = json.dumps(item.get("data", {}))
        yield f"event: {event_type}\ndata: {data}\n\n"


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return StreamingResponse(
        _sse_stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
def root() -> dict:
    return {
        "name": "Toolbox API",
        "docs": "/docs",
        "health": "/api/health",
        "app": "/app/" if FRONTEND_DIST.is_dir() else None,
    }


if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/app/assets", StaticFiles(directory=assets_dir), name="app-assets")

    @app.get("/app")
    @app.get("/app/{rest:path}")
    def spa_app(rest: str = "") -> FileResponse:
        """React UI (production build from ``web/frontend``)."""
        candidate = FRONTEND_DIST / rest
        if rest and candidate.is_file():
            return FileResponse(candidate)
        index = FRONTEND_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="Frontend not built. Run: cd web/frontend && npm run build")
        return FileResponse(index)
