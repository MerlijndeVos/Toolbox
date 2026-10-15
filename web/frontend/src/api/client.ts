import type {
  CommandName,
  DownloadProbeResult,
  JobCreateResponse,
  JobSummary,
  JobUndoResponse,
  MarketResponse,
  ModInstallPreview,
  ModPrompts,
  ModResult,
  ModSourceResponse,
  ModsResponse,
  ModUpdateStatus,
} from "@/lib/types";
import type { RenameMode, RenameProfile } from "@/lib/renameProfiles";
import type { ColorMode } from "@/lib/theme";
import type { SyntaxScheme } from "@/lib/syntax";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

function parseApiError(text: string, status: number): string {
  try {
    const body = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      const msg = body.detail.map((d) => d.msg).filter(Boolean).join("; ");
      if (msg) return msg;
    }
  } catch {
    /* not JSON */
  }
  if (status === 404) {
    return (
      "API endpoint not found. An older server may still be running on port 8765 " +
      "(stop it with: netstat -ano | findstr :8765, then taskkill /PID <pid> /F), " +
      "then restart with: python -m web"
    );
  }
  return text.trim() || `HTTP ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(parseApiError(text, res.status));
  }
  return res.json() as Promise<T>;
}

export async function checkHealth(): Promise<boolean> {
  try {
    await request<{ status: string; version: string }>("/api/health");
    return true;
  } catch {
    return false;
  }
}

export interface UpdateCheck {
  current_version: string;
  latest_version?: string | null;
  update_available: boolean;
  can_install: boolean;
  download_url?: string | null;
  asset_name?: string | null;
  release_url?: string | null;
  release_notes?: string | null;
  error?: string | null;
  status_message?: string | null;
  /** The offered build is an experimental one, not an official release. */
  experimental?: boolean;
}

export interface UpdateApplyStatus {
  phase: "idle" | "downloading" | "installing" | "error";
  progress: number;
  message: string;
  error?: string | null;
}

export function checkForUpdates(): Promise<UpdateCheck> {
  return request<UpdateCheck>("/api/updates/check");
}

export function applyUpdate(): Promise<{ ok: boolean; detail?: string | null }> {
  return request("/api/updates/apply", { method: "POST" });
}

export function fetchUpdateStatus(): Promise<UpdateApplyStatus> {
  return request<UpdateApplyStatus>("/api/updates/status");
}

export interface ToolsStatus {
  ffmpeg: {
    available: boolean;
    ffmpeg_path?: string | null;
    ffprobe_path?: string | null;
    source?: string;
  };
  bootstrap?: {
    phase: "idle" | "checking" | "downloading" | "verifying" | "ready" | "failed";
    message?: string;
    error?: string | null;
  };
}

export function fetchToolsStatus(): Promise<ToolsStatus> {
  return request<ToolsStatus>("/api/tools");
}

export function retryToolsBootstrap(): Promise<ToolsStatus> {
  return request<ToolsStatus>("/api/tools/bootstrap", { method: "POST" });
}

export function probeDownloadUrl(params: {
  url: string;
  format: string;
  video_quality: string;
  audio_bitrate: number;
}): Promise<DownloadProbeResult> {
  return request<DownloadProbeResult>("/api/download/probe", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export function createJob(
  command: CommandName,
  params: Record<string, unknown>,
  fileLogging = true,
): Promise<JobCreateResponse> {
  return request<JobCreateResponse>("/api/jobs", {
    method: "POST",
    body: JSON.stringify({ command, params, file_logging: fileLogging }),
  });
}

export function fetchMods(): Promise<ModsResponse> {
  return request<ModsResponse>("/api/mods");
}

export function reloadMods(): Promise<ModsResponse> {
  return request<ModsResponse>("/api/mods/reload", { method: "POST" });
}

export function setModEnabled(id: string, enabled: boolean): Promise<ModsResponse> {
  return request<ModsResponse>(`/api/mods/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

/** Runs one of a mod's `[[actions]]` (for example "Test connection") and returns what it shows. */
export function runModAction(
  modId: string,
  action: string,
  params: Record<string, unknown>,
): Promise<{ ok: boolean; results: ModResult[] }> {
  return request(`/api/mods/${encodeURIComponent(modId)}/actions/${encodeURIComponent(action)}`, {
    method: "POST",
    body: JSON.stringify({ params }),
  });
}

/** Open (or show in its folder) a file the job listed in a `files` result. */
export function openJobResult(jobId: string, path: string, reveal: boolean): Promise<{ ok: boolean }> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/results/open`, {
    method: "POST",
    body: JSON.stringify({ path, reveal }),
  });
}

export function openModsFolder(): Promise<{ ok: boolean }> {
  return request("/api/mods/open-folder", { method: "POST" });
}

export interface ModInstallRequest {
  /** A git address, or a path to a folder, .zip or .py file. */
  location: string;
  ref?: string;
  subdir?: string;
  update_of?: string;
  /** A market listing's claims, checked against the code that was downloaded. */
  expect?: Record<string, unknown>;
}

/** Downloads and checks a mod without running it; the answer is what the trust prompt shows. */
export function prepareModInstall(body: ModInstallRequest): Promise<ModInstallPreview> {
  return request<ModInstallPreview>("/api/mods/install/prepare", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function confirmModInstall(token: string, enable: boolean): Promise<ModsResponse> {
  return request<ModsResponse>("/api/mods/install/confirm", {
    method: "POST",
    body: JSON.stringify({ token, enable }),
  });
}

export function cancelModInstall(token: string): Promise<{ ok: boolean }> {
  return request(`/api/mods/install/${encodeURIComponent(token)}`, { method: "DELETE" });
}

export function removeMod(id: string): Promise<ModsResponse> {
  return request<ModsResponse>(`/api/mods/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function fetchModSource(id: string): Promise<ModSourceResponse> {
  return request<ModSourceResponse>(`/api/mods/${encodeURIComponent(id)}/source`);
}

export function checkModUpdate(id: string): Promise<ModUpdateStatus> {
  return request<ModUpdateStatus>(`/api/mods/${encodeURIComponent(id)}/update`);
}

export function prepareModUpdate(id: string): Promise<ModInstallPreview> {
  return request<ModInstallPreview>(`/api/mods/${encodeURIComponent(id)}/update/prepare`, {
    method: "POST",
  });
}

export function setModsSafeMode(enabled: boolean): Promise<ModsResponse> {
  return request<ModsResponse>("/api/mods/safe-mode", {
    method: "POST",
    body: JSON.stringify({ enabled }),
  });
}

export function fetchModPrompts(): Promise<ModPrompts> {
  return request<ModPrompts>("/api/mods/prompts");
}

export function fetchMarket(refresh = false): Promise<MarketResponse> {
  return request<MarketResponse>(`/api/mods/market${refresh ? "?refresh=true" : ""}`);
}

export function listJobs(): Promise<JobSummary[]> {
  return request<JobSummary[]>("/api/jobs");
}

export function getJob(id: string): Promise<JobSummary> {
  return request<JobSummary>(`/api/jobs/${id}`);
}

export function cancelJob(id: string): Promise<void> {
  return request(`/api/jobs/${id}/cancel`, { method: "POST" }).then(() => undefined);
}

export function undoRenameJob(sourceJobId: string): Promise<JobUndoResponse> {
  return request<JobUndoResponse>(`/api/jobs/${sourceJobId}/undo`, { method: "POST" });
}

export function jobEventsUrl(id: string): string {
  return `${API_BASE}/api/jobs/${id}/events`;
}

export interface LogFileInfo {
  name: string;
  size_bytes: number;
  modified_at: string;
}

export interface LogsStats {
  path: string;
  total_bytes: number;
  file_count: number;
  files: LogFileInfo[];
}

export type AiProviderId = "openai" | "openai_compatible" | "anthropic" | "gemini" | "claude_subscription";

export interface AiProviderSettings {
  api_key_set: boolean;
  /** The key comes from an environment variable rather than the saved settings. */
  api_key_from_env: boolean;
  /** Effective model id (the saved one, or the provider default). */
  model: string;
  default_model: string;
  base_url: string;
}

export interface AiSettings {
  provider: AiProviderId;
  providers: Record<AiProviderId, AiProviderSettings>;
}

export interface AppSettings {
  file_logging: boolean;
  ai: AiSettings;
  logs: LogsStats;
  /** The active theme mod and whether to follow the system's light/dark setting. */
  theme: string;
  color_mode: ColorMode;
  /** Syntax highlighting in code and log previews, and its colour scheme. */
  syntax_code: boolean;
  syntax_logs: boolean;
  syntax_scheme: SyntaxScheme;
  /** Offer experimental builds (the latest production commit) as updates. */
  experimental_updates: boolean;
}

/** Omitted fields are kept; an empty string clears the field. */
export interface AiProviderUpdate {
  api_key?: string;
  model?: string;
  base_url?: string;
}

export function fetchSettings(): Promise<AppSettings> {
  return request<AppSettings>("/api/settings");
}

export function updateSettings(patch: {
  file_logging?: boolean;
  theme?: string;
  color_mode?: ColorMode;
  syntax_code?: boolean;
  syntax_logs?: boolean;
  syntax_scheme?: SyntaxScheme;
  experimental_updates?: boolean;
  ai?: {
    provider?: AiProviderId;
    providers?: Partial<Record<AiProviderId, AiProviderUpdate>>;
  };
}): Promise<AppSettings> {
  return request<AppSettings>("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export interface AiTestResult {
  ok: boolean;
  message: string;
}

/** Try a provider with the form values; blank fields fall back to the saved ones. */
export function testAiConnection(
  body: AiProviderUpdate & { provider: AiProviderId },
): Promise<AiTestResult> {
  return request<AiTestResult>("/api/ai/test", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export interface AiUsageTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
  cost_usd: number | null;
}

export interface AiUsageGroup extends AiUsageTotals {
  name: string;
}

export interface AiUsageSummary {
  provider: AiProviderId;
  today: AiUsageTotals;
  week: AiUsageTotals;
  all: AiUsageTotals;
  /** Oldest first; `start` is the bucket's start (unix seconds). */
  days: (AiUsageTotals & { start: number })[];
  by_model: AiUsageGroup[];
  by_feature: AiUsageGroup[];
  /** The Claude plan windows, once a subscription call has reported them. */
  limits: {
    updated: number;
    status: string;
    limit_type: string;
    windows: Record<string, { utilization: number; resets_at: number | null }>;
  } | null;
  recent: {
    ts: number;
    label: string;
    model: string;
    feature: string;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number | null;
  }[];
}

export function fetchAiUsage(): Promise<AiUsageSummary> {
  return request<AiUsageSummary>("/api/ai/usage");
}

export function clearAiUsage(): Promise<AiUsageSummary> {
  return request<AiUsageSummary>("/api/ai/usage", { method: "DELETE" });
}

/** One tiny Claude call so the plan windows are current. */
export function refreshAiLimits(): Promise<AiUsageSummary> {
  return request<AiUsageSummary>("/api/ai/usage/refresh", { method: "POST" });
}

export interface SubtitleLanguage {
  code: string;
  label: string;
}

export interface SubtitleJunkItem {
  id: string;
  file: string;
  cue_index: number;
  line_index: number;
  text: string;
  reason: string;
  reason_label: string;
}

export interface SubtitleScanJunkResult {
  items: SubtitleJunkItem[];
  detected_source_lang?: string | null;
}

export function fetchSubtitleLanguages(): Promise<{ languages: SubtitleLanguage[] }> {
  return request("/api/subtitles/languages");
}

export function scanSubtitleJunk(input: string): Promise<SubtitleScanJunkResult> {
  return request<SubtitleScanJunkResult>("/api/subtitles/scan-junk", {
    method: "POST",
    body: JSON.stringify({ input }),
  });
}

export function clearLogFiles(): Promise<{ deleted_count: number; logs: LogsStats }> {
  return request("/api/settings/logs", { method: "DELETE" });
}

export interface LogChunk {
  name: string;
  size_bytes: number;
  /** Byte offset where this chunk starts; pass it as `end` to get the lines before it. */
  start: number;
  end: number;
  has_earlier: boolean;
  lines: string[];
}

/** Last `lines` lines of a stored log, or the lines before byte offset `end`. */
export function fetchLogChunk(name: string, opts: { end?: number; lines?: number } = {}): Promise<LogChunk> {
  const params = new URLSearchParams();
  if (opts.end != null) params.set("end", String(opts.end));
  if (opts.lines != null) params.set("lines", String(opts.lines));
  const query = params.toString();
  return request<LogChunk>(`/api/settings/logs/${encodeURIComponent(name)}${query ? `?${query}` : ""}`);
}

export function openLogFolder(): Promise<{ ok: boolean }> {
  return request("/api/settings/logs/open-folder", { method: "POST" });
}

export function openLogFile(name: string): Promise<{ ok: boolean }> {
  return request("/api/settings/logs/open-file", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

// ---------------------------------------------------------------------------
// Rename format profiles
// ---------------------------------------------------------------------------

export interface RenameTestResult {
  sample: string;
  result: string | null;
  note: string | null;
}

/** A before -> after pair. `parent`, `n` and `date` say where a real folder's name sat. */
export interface RenameExample {
  before: string;
  after: string;
  parent?: string;
  n?: number;
  date?: string | null;
}

/** A name picked from the folder, with what the profile makes of it, for the user to review. */
export interface RenameProposedExample extends RenameExample {
  kind: "folder" | "file";
  changed: boolean;
}

/** How much of the folder was sent to the AI. */
export interface RenameSampleInfo {
  sent: number;
  total: number;
  truncated: boolean;
  shapes: number;
  folders_with_files: number;
}

export interface RenameGenerateResult {
  profile: RenameProfile;
  verification: { before: string; expected: string; actual: string | null; ok: boolean }[];
  all_ok: boolean;
  attempts: number;
  model: string;
  sample: RenameSampleInfo | null;
  proposed_examples: RenameProposedExample[];
}

/** What to look at when the AI also reads the names in a folder. */
export interface RenameFolderScope {
  folder: string;
  targets: string;
  maxDepth: number;
  includeRoot: boolean;
}

export function fetchRenameProfiles(): Promise<{ profiles: RenameProfile[] }> {
  return request<{ profiles: RenameProfile[] }>("/api/rename/profiles");
}

export function saveRenameProfile(profile: RenameProfile): Promise<RenameProfile> {
  return request<RenameProfile>("/api/rename/profiles", {
    method: "POST",
    body: JSON.stringify({ profile }),
  });
}

export function deleteRenameProfile(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/rename/profiles/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function testRenameProfile(
  profile: RenameProfile,
  mode: RenameMode,
  samples: string[],
): Promise<{ results: RenameTestResult[] }> {
  return request<{ results: RenameTestResult[] }>("/api/rename/profiles/test", {
    method: "POST",
    body: JSON.stringify({ profile, mode, samples }),
  });
}

/**
 * Ask the AI for a profile. With `scope` it also gets a capped sample of the real names in that
 * folder (Other mode), so `examples` may be empty.
 */
export function generateRenameProfile(
  mode: RenameMode,
  examples: RenameExample[],
  scope?: RenameFolderScope,
): Promise<RenameGenerateResult> {
  const body: Record<string, unknown> = { mode, examples };
  if (scope) {
    body.folder = scope.folder;
    body.targets = scope.targets;
    body.max_depth = scope.maxDepth;
    body.include_root = scope.includeRoot;
  }
  return request<RenameGenerateResult>("/api/rename/profiles/generate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
