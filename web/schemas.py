"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.paths import clean_path_string

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class DownloadProbeRequest(BaseModel):
    url: str
    format: Literal["mp4", "mp3"] = "mp4"
    video_quality: Literal["best", "2160", "1440", "1080", "720", "480", "360"] = "best"
    audio_bitrate: int = Field(default=192, ge=64, le=320)


class DownloadProbeEntry(BaseModel):
    id: str
    title: str
    url: str
    duration: Optional[int] = None
    filesize: Optional[int] = None
    playlist_index: int = 1


class DownloadProbeResponse(BaseModel):
    url: str
    is_playlist: bool
    playlist_title: Optional[str] = None
    entries: list[DownloadProbeEntry]


class SubtitleScanJunkRequest(BaseModel):
    input: str

    @field_validator("input")
    @classmethod
    def normalize_input(cls, value: str) -> str:
        return clean_path_string(value)


class SubtitleJunkItem(BaseModel):
    id: str
    file: str
    cue_index: int
    line_index: int
    text: str
    reason: str
    reason_label: str


class SubtitleScanJunkResponse(BaseModel):
    items: list[SubtitleJunkItem]
    detected_source_lang: Optional[str] = None


class LanguageOption(BaseModel):
    code: str
    label: str


class SubtitleLanguagesResponse(BaseModel):
    languages: list[LanguageOption]


class JobCreateRequest(BaseModel):
    command: str
    params: dict[str, Any] = Field(default_factory=dict)
    file_logging: bool = True


class JobSummary(BaseModel):
    id: str
    command: str
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    exit_code: Optional[int] = None
    undo_available: bool = False
    undo_used: bool = False
    undo_op_count: Optional[int] = None
    undo_of: Optional[str] = None
    # Set when the job renamed the folder the user had selected: {"from": old path, "to": new path}.
    renamed_root: Optional[dict[str, str]] = None


class JobUndoResponse(BaseModel):
    job: JobSummary
    events_url: str
    source_job_id: str


class JobCreateResponse(BaseModel):
    job: JobSummary
    events_url: str


class RenameProfilesResponse(BaseModel):
    profiles: list[dict[str, Any]]


class RenameProfileSaveRequest(BaseModel):
    profile: dict[str, Any]


class RenameProfileTestRequest(BaseModel):
    profile: dict[str, Any]
    mode: Literal["media", "generic"] = "media"
    samples: list[str] = Field(min_length=1, max_length=20)


class RenameProfileTestItem(BaseModel):
    sample: str
    result: Optional[str] = None
    note: Optional[str] = None


class RenameProfileTestResponse(BaseModel):
    results: list[RenameProfileTestItem]


class RenameExample(BaseModel):
    before: str
    after: str
    # Where the name sat, so a real folder's result can be checked exactly (see core.rename_ai).
    parent: Optional[str] = None
    n: Optional[int] = None
    date: Optional[str] = None


class RenameProfileGenerateRequest(BaseModel):
    mode: Literal["media", "generic"] = "media"
    examples: list[RenameExample] = Field(default_factory=list, max_length=12)
    # Other mode: also look at (a capped sample of) the real names in this folder.
    folder: Optional[str] = None
    targets: Literal["folders", "files", "both"] = "folders"
    max_depth: int = Field(default=1, ge=1, le=50)
    include_root: bool = False

    @model_validator(mode="after")
    def _needs_examples_or_folder(self) -> "RenameProfileGenerateRequest":
        if self.folder is not None and not self.folder.strip():
            self.folder = None
        if self.folder is not None and self.mode != "generic":
            raise ValueError("Suggesting from a folder only works in the Other mode.")
        if not self.examples and self.folder is None:
            raise ValueError("Give at least one example, or pick a folder to look at.")
        return self


class RenameProfileVerification(BaseModel):
    before: str
    expected: str
    actual: Optional[str] = None
    ok: bool


class RenameProposedExample(BaseModel):
    """A name picked from the folder, with what the profile makes of it (for the user to review)."""

    before: str
    after: str
    kind: str
    parent: str
    n: int
    date: Optional[str] = None
    changed: bool


class RenameSampleInfo(BaseModel):
    """How much of the folder was sent to the model."""

    sent: int
    total: int
    truncated: bool
    shapes: int
    folders_with_files: int


class RenameProfileGenerateResponse(BaseModel):
    profile: dict[str, Any]
    verification: list[RenameProfileVerification]
    all_ok: bool
    attempts: int
    model: str
    sample: Optional[RenameSampleInfo] = None
    proposed_examples: list[RenameProposedExample] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str


class UpdateCheckResponse(BaseModel):
    current_version: str
    latest_version: Optional[str] = None
    update_available: bool = False
    can_install: bool = False
    download_url: Optional[str] = None
    asset_name: Optional[str] = None
    release_url: Optional[str] = None
    release_notes: Optional[str] = None
    error: Optional[str] = None
    status_message: Optional[str] = None
    experimental: bool = False


class UpdateApplyResponse(BaseModel):
    ok: bool
    detail: Optional[str] = None


class UpdateApplyStatusResponse(BaseModel):
    phase: Literal["idle", "downloading", "installing", "error"] = "idle"
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None


class CommandInfo(BaseModel):
    name: str
    description: str


class CommandsResponse(BaseModel):
    commands: list[CommandInfo]


class ModsResponse(BaseModel):
    mods: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    # Things that do not stop a mod from loading but are worth a look (for example a category
    # name that looks like an existing one).
    notices: list[dict[str, Any]] = Field(default_factory=list)
    # The built-in categories with what belongs in each, in on-screen order.
    groups: list[dict[str, Any]] = Field(default_factory=list)
    safe_mode: bool = False
    mods_dir: str


class ModEnableRequest(BaseModel):
    enabled: bool


class ModInstallPrepareRequest(BaseModel):
    """What to install: a git address, or a path to a folder, .zip or .py file."""

    location: str
    ref: str = ""
    subdir: str = ""
    # Set when updating an installed mod; the new code must have the same id.
    update_of: Optional[str] = None
    # A market listing's claims (id, version, permissions), checked against the real code.
    expect: Optional[dict[str, Any]] = None


class ModInstallConfirmRequest(BaseModel):
    token: str
    enable: bool = False


class SafeModeRequest(BaseModel):
    enabled: bool


class ModPromptsResponse(BaseModel):
    build: str
    review: str
    theme: str = ""


class ModActionRequest(BaseModel):
    """The current form values; only the params the action declares are used."""

    params: dict[str, Any] = Field(default_factory=dict)


class ModActionResponse(BaseModel):
    ok: bool
    results: list[dict[str, Any]]


class OpenResultRequest(BaseModel):
    path: str
    reveal: bool = False


class LogFileInfo(BaseModel):
    name: str
    size_bytes: int
    modified_at: str


class LogsStatsResponse(BaseModel):
    path: str
    total_bytes: int
    file_count: int
    files: list[LogFileInfo]


class AiProviderSettings(BaseModel):
    """One provider's saved settings. The key itself is never sent back."""

    api_key_set: bool = False
    api_key_from_env: bool = False
    model: str = ""
    default_model: str = ""
    base_url: str = ""


class AiSettingsResponse(BaseModel):
    provider: str
    providers: dict[str, AiProviderSettings]


SyntaxScheme = Literal["theme", "github", "one", "contrast"]


class SettingsResponse(BaseModel):
    file_logging: bool
    ai: AiSettingsResponse
    logs: LogsStatsResponse
    # Appearance: the active theme mod and light / dark / follow the system.
    theme: str = "theme-default"
    color_mode: Literal["system", "light", "dark"] = "system"
    # Syntax highlighting in code and log previews ("theme" takes the colours from the theme).
    syntax_code: bool = True
    syntax_logs: bool = True
    syntax_scheme: SyntaxScheme = "theme"
    # Offer experimental builds (the latest production commit) as updates.
    experimental_updates: bool = False


class AiProviderUpdate(BaseModel):
    """Omitted/null fields are kept; an empty string clears the field."""

    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


class AiSettingsUpdate(BaseModel):
    provider: Optional[str] = None
    providers: Optional[dict[str, AiProviderUpdate]] = None


class SettingsUpdateRequest(BaseModel):
    file_logging: Optional[bool] = None
    ai: Optional[AiSettingsUpdate] = None
    theme: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    color_mode: Optional[Literal["system", "light", "dark"]] = None
    syntax_code: Optional[bool] = None
    syntax_logs: Optional[bool] = None
    syntax_scheme: Optional[SyntaxScheme] = None
    experimental_updates: Optional[bool] = None


class AiTestRequest(AiProviderUpdate):
    """Try a provider with the (possibly unsaved) form values; blank fields use saved ones."""

    provider: str


class AiTestResponse(BaseModel):
    ok: bool
    message: str


class ClearLogsResponse(BaseModel):
    deleted_count: int
    logs: LogsStatsResponse


class OpenLogFileRequest(BaseModel):
    name: str


class LogChunkResponse(BaseModel):
    name: str
    size_bytes: int
    start: int
    end: int
    has_earlier: bool
    lines: list[str]


class OpenPathResponse(BaseModel):
    ok: bool = True


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
