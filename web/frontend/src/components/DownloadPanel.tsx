import { useMemo, useState } from "react";
import {
  ArrowDown,
  CheckCircle2,
  Download,
  Loader2,
  Search,
  X,
  XCircle,
} from "lucide-react";
import { probeDownloadUrl } from "@/api/client";
import { Button } from "@/components/ui/button";
import { CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { CheckField, Field, PathField, SelectField } from "@/components/fields";
import { Input } from "@/components/ui/input";
import type { ActiveJob, DownloadJobMeta, DownloadProbeResult, JobStatus } from "@/lib/types";
import {
  cn,
  formatBytes,
  formatDuration,
  formatEta,
  formatSpeed,
} from "@/lib/utils";

interface DownloadPanelProps {
  jobs: ActiveJob[];
  onQueueDownloads: (
    items: Array<{ params: Record<string, unknown>; downloadMeta: DownloadJobMeta }>,
  ) => Promise<void>;
  onCancel: (jobId: string) => void;
  onDismissFinished: () => void;
}

const TERMINAL: JobStatus[] = ["completed", "failed", "cancelled"];

const BITRATE_OPTIONS = ["192", "256", "320"].map((v) => ({ value: v, label: `${v} kbps` }));

const FORMATS = [
  { value: "mp4", label: "MP4 video", hint: "Keeps video and audio" },
  { value: "mp3", label: "MP3 audio", hint: "Extracts audio only" },
];

interface PendingEntry {
  id: string;
  title: string;
  url: string;
  duration?: number | null;
  filesize?: number | null;
  playlist_index: number;
  selected: boolean;
  outputName: string;
}

function StatusIcon({ status }: { status: JobStatus }) {
  if (status === "running" || status === "queued") {
    return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />;
  }
  if (status === "completed") {
    return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success-text" />;
  }
  return <XCircle className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
}

function TorrentTableHeader() {
  return (
    <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,2fr)_3.5rem_minmax(0,1fr)_3.5rem_3rem_2rem] gap-2 border-b bg-muted px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      <span>Name</span>
      <span className="text-right">Size</span>
      <span>Progress</span>
      <span className="text-right">Down</span>
      <span className="text-right">ETA</span>
      <span />
    </div>
  );
}

function DownloadRow({
  job,
  selected,
  onToggle,
  onCancel,
}: {
  job: ActiveJob;
  selected: boolean;
  onToggle: (id: string, selected: boolean) => void;
  onCancel: (id: string) => void;
}) {
  const active = job.status === "queued" || job.status === "running";
  const prog = job.downloadProgress;
  const name =
    job.downloadMeta?.displayName ||
    prog?.title ||
    job.progressLabel?.split(" — ")[0]?.trim() ||
    `Download ${job.id.slice(0, 8)}`;
  const pct = job.progress ?? (job.status === "completed" ? 100 : null);
  const total = prog?.total ?? job.downloadMeta?.expectedSize ?? null;
  const downloaded = prog?.downloaded ?? null;
  const sizeLabel =
    total != null
      ? formatBytes(total)
      : downloaded != null && pct != null && pct > 0
        ? formatBytes(Math.round((downloaded * 100) / pct))
        : "—";

  return (
    <div className="grid grid-cols-[minmax(0,2fr)_3.5rem_minmax(0,1fr)_3.5rem_3rem_2rem] items-center gap-2 border-b px-3 py-2.5 text-sm last:border-b-0">
      <div className="flex min-w-0 items-center gap-2.5">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onToggle(job.id, e.target.checked)}
          className="h-4 w-4 shrink-0 rounded border-input"
          aria-label={`Select ${name}`}
        />
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md">
          <StatusIcon status={job.status} />
        </div>
        <div className="min-w-0">
          <p className="truncate font-medium" title={name}>
            {name}
          </p>
          {job.downloadMeta?.format && (
            <p className="truncate text-[11px] text-muted-foreground">
              {job.downloadMeta.format.toUpperCase()}
              {job.downloadMeta.output ? ` — ${job.downloadMeta.output}` : ""}
            </p>
          )}
        </div>
      </div>
      <span className="text-right text-xs tabular-nums text-muted-foreground">{sizeLabel}</span>
      <div className="flex min-w-0 items-center gap-2">
        {pct != null ? (
          <>
            <span className="w-9 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground">
              {Math.round(pct)}%
            </span>
            <Progress
              value={Math.min(100, Math.max(0, pct))}
              className="h-1.5 min-w-0 flex-1"
            />
          </>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </div>
      <span className="text-right text-xs tabular-nums text-muted-foreground">
        {active ? formatSpeed(prog?.speed) : "—"}
      </span>
      <span className="text-right text-xs tabular-nums text-muted-foreground">
        {active ? formatEta(prog?.eta) : "—"}
      </span>
      <div className="flex justify-end">
        {active && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-destructive"
            aria-label="Cancel download"
            onClick={() => onCancel(job.id)}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
      {job.status === "failed" && job.error && (
        <p className="col-span-full text-xs text-danger-text">{job.error}</p>
      )}
    </div>
  );
}

export function DownloadPanel({
  jobs,
  onQueueDownloads,
  onCancel,
  onDismissFinished,
}: DownloadPanelProps) {
  const [url, setUrl] = useState("");
  const [output, setOutput] = useState("");
  const [format, setFormat] = useState("mp4");
  const [quality, setQuality] = useState("best");
  const [bitrate, setBitrate] = useState("320");
  const [usePlaylistFolder, setUsePlaylistFolder] = useState(true);

  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [probeResult, setProbeResult] = useState<DownloadProbeResult | null>(null);
  const [pendingEntries, setPendingEntries] = useState<PendingEntry[]>([]);
  const [queueing, setQueueing] = useState(false);
  const [queueError, setQueueError] = useState<string | null>(null);
  const [selectedJobs, setSelectedJobs] = useState<Set<string>>(new Set());

  const activeCount = useMemo(
    () => jobs.filter((j) => j.status === "queued" || j.status === "running").length,
    [jobs],
  );
  const finishedCount = useMemo(() => jobs.filter((j) => TERMINAL.includes(j.status)).length, [jobs]);

  const maxPlaylistIndexDigits = useMemo(() => {
    if (!probeResult?.is_playlist || pendingEntries.length === 0) return 1;
    return Math.max(
      ...pendingEntries.map((e) => String(e.playlist_index).length),
      1,
    );
  }, [probeResult, pendingEntries]);

  const selectedJobIds = jobs.filter((j) => selectedJobs.has(j.id)).map((j) => j.id);
  const allJobsSelected = jobs.length > 0 && selectedJobIds.length === jobs.length;
  const selectedActiveJobs = jobs.filter(
    (j) => selectedJobs.has(j.id) && (j.status === "queued" || j.status === "running"),
  );

  const toggleJob = (id: string, selected: boolean) => {
    setSelectedJobs((prev) => {
      const next = new Set(prev);
      if (selected) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const toggleAllJobs = () => {
    setSelectedJobs(allJobsSelected ? new Set() : new Set(jobs.map((j) => j.id)));
  };

  const selectedCount = pendingEntries.filter((e) => e.selected).length;
  const canProbe = Boolean(url.trim()) && !probing;
  const canStart =
    Boolean(output.trim()) &&
    selectedCount > 0 &&
    !queueing &&
    !probing;

  const clearProbeResults = () => {
    setProbeResult(null);
    setPendingEntries([]);
  };

  const loadUrl = async () => {
    const trimmed = url.trim();
    if (!trimmed) return;
    setProbing(true);
    setProbeError(null);
    setQueueError(null);
    clearProbeResults();
    try {
      const result = await probeDownloadUrl({
        url: trimmed,
        format,
        video_quality: quality,
        audio_bitrate: Number(bitrate),
      });
      setProbeResult(result);
      setPendingEntries(
        result.entries.map((entry) => ({
          ...entry,
          selected: true,
          outputName: entry.title,
        })),
      );
      if (result.is_playlist) setUsePlaylistFolder(true);
    } catch (e) {
      clearProbeResults();
      setProbeError(e instanceof Error ? e.message : String(e));
    } finally {
      setProbing(false);
    }
  };

  const toggleAll = (selected: boolean) => {
    setPendingEntries((prev) => prev.map((e) => ({ ...e, selected })));
  };

  const updateEntry = (id: string, patch: Partial<PendingEntry>) => {
    setPendingEntries((prev) => prev.map((e) => (e.id === id ? { ...e, ...patch } : e)));
  };

  const startDownloads = async () => {
    if (!canStart || !probeResult) return;
    setQueueError(null);
    setQueueing(true);
    const selected = pendingEntries.filter((e) => e.selected);
    setUrl("");
    clearProbeResults();
    setProbeError(null);
    try {
      await onQueueDownloads(
        selected.map((entry) => ({
          params: {
            url: entry.url,
            output,
            format,
            video_quality: quality,
            audio_bitrate: Number(bitrate),
            playlist: false,
            no_playlist_index: true,
            output_name: entry.outputName.trim() || entry.title,
            playlist_subdir:
              probeResult.is_playlist && usePlaylistFolder
                ? probeResult.playlist_title ?? "Playlist"
                : null,
            playlist_index: probeResult.is_playlist ? entry.playlist_index : null,
          },
          downloadMeta: {
            url: entry.url,
            format,
            output,
            displayName: entry.outputName.trim() || entry.title,
            expectedSize: entry.filesize ?? null,
          },
        })),
      );
    } catch (e) {
      setQueueError(e instanceof Error ? e.message : String(e));
    } finally {
      setQueueing(false);
    }
  };

  return (
    <>
      <CardHeader>
        <CardTitle>Download</CardTitle>
        <CardDescription>Download videos or playlists from yt-dlp-supported sites as MP4 or MP3.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <Field
            label="Video or playlist URL"
            tooltip="Paste a link from any site supported by yt-dlp, then load it to preview available files."
          >
            <div className="flex gap-2">
              <Input
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  if (probeResult || probeError) {
                    clearProbeResults();
                    setProbeError(null);
                  }
                }}
                placeholder="https://…"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && canProbe) void loadUrl();
                }}
              />
              <Button
                type="button"
                variant="secondary"
                className="shrink-0 gap-1.5"
                disabled={!canProbe}
                onClick={() => void loadUrl()}
              >
                {probing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
                Load
              </Button>
            </div>
          </Field>
          {probing && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading URL — fetching video info from yt-dlp…
            </p>
          )}
          {probeError && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger-text">
              {probeError}
            </div>
          )}
        </div>

        <div
          role="tablist"
          aria-label="Download format"
          className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1"
        >
          {FORMATS.map((f) => (
            <button
              key={f.value}
              type="button"
              role="tab"
              aria-selected={format === f.value}
              onClick={() => setFormat(f.value)}
              className={cn(
                "rounded-md px-3 py-2 text-left transition-colors",
                format === f.value ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="block text-sm font-medium">{f.label}</span>
              <span className="block text-xs text-muted-foreground">{f.hint}</span>
            </button>
          ))}
        </div>
        {format === "mp4" && (
          <SelectField
            label="Max quality"
            value={quality}
            onChange={setQuality}
            tooltip="Maximum video height. Best picks the highest available."
            options={["best", "2160", "1440", "1080", "720", "480", "360"].map((v) => ({
              value: v,
              label: v === "best" ? "Best" : `${v}p`,
            }))}
          />
        )}
        {format === "mp3" && (
          <SelectField
            label="Audio bitrate (kbps)"
            value={bitrate}
            onChange={setBitrate}
            tooltip="MP3 quality in kbps. Higher is better quality and a larger file."
            options={BITRATE_OPTIONS}
          />
        )}

        {probeResult && pendingEntries.length > 0 && (
          <div className="space-y-4 rounded-lg border bg-muted/20 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">
                  {probeResult.is_playlist
                    ? probeResult.playlist_title ?? "Playlist"
                    : "Single video"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {pendingEntries.length} file{pendingEntries.length !== 1 ? "s" : ""} found
                  {selectedCount !== pendingEntries.length
                    ? ` — ${selectedCount} selected`
                    : ""}
                </p>
              </div>
              <div className="flex gap-2">
                <Button type="button" variant="outline" size="sm" onClick={() => toggleAll(true)}>
                  Select all
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={() => toggleAll(false)}>
                  Select none
                </Button>
              </div>
            </div>

            <PathField
              label="Save to folder"
              value={output}
              onChange={setOutput}
              hint="Downloads are written here. Playlist items can use a subfolder below."
              tooltip="Destination folder for the selected downloads."
            />

            {probeResult.is_playlist && (
              <CheckField
                label="Save inside playlist subfolder"
                checked={usePlaylistFolder}
                onChange={setUsePlaylistFolder}
                tooltip='When on, files go to "Save folder / Playlist name / file".'
              />
            )}

            <div className="overflow-hidden rounded-lg border bg-card">
              <div className="max-h-[min(320px,40vh)] overflow-y-auto overflow-x-hidden">
                <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1.6fr)_3rem_3rem_minmax(0,1fr)] gap-x-2 border-b bg-muted py-2 pl-4 pr-3 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  <span>Name</span>
                  <span className="text-right">Length</span>
                  <span className="text-right">Size</span>
                  <span className="pl-3">Output filename</span>
                </div>
                <ul>
                {pendingEntries.map((entry) => (
                  <li
                    key={entry.id}
                    className={cn(
                      "grid grid-cols-[minmax(0,1.6fr)_3rem_3rem_minmax(0,1fr)] items-center gap-x-2 border-b py-2 pl-4 pr-3 last:border-b-0",
                      !entry.selected && "opacity-50",
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <input
                        type="checkbox"
                        checked={entry.selected}
                        onChange={(e) => updateEntry(entry.id, { selected: e.target.checked })}
                        className="h-4 w-4 shrink-0 rounded border-input"
                        aria-label={`Select ${entry.title}`}
                      />
                      {probeResult.is_playlist && (
                        <span
                          className="shrink-0 text-right text-xs tabular-nums text-muted-foreground"
                          style={{ width: `${maxPlaylistIndexDigits + 1}ch` }}
                        >
                          {entry.playlist_index}.
                        </span>
                      )}
                      <p className="min-w-0 truncate text-sm font-medium" title={entry.title}>
                        {entry.title}
                      </p>
                    </div>
                    <span className="text-right text-xs tabular-nums text-muted-foreground">
                      {formatDuration(entry.duration)}
                    </span>
                    <span className="text-right text-xs tabular-nums text-muted-foreground">
                      {formatBytes(entry.filesize)}
                    </span>
                    <div className="min-w-0 pl-3">
                      <Input
                        value={entry.outputName}
                        onChange={(e) => updateEntry(entry.id, { outputName: e.target.value })}
                        className="h-8 w-full min-w-0 text-xs"
                        disabled={!entry.selected}
                      />
                    </div>
                  </li>
                ))}
                </ul>
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-4">
              <p className="text-xs text-muted-foreground">
                Edit filenames before downloading. Uncheck items you want to skip.
              </p>
              <Button
                type="button"
                size="lg"
                className="gap-1.5"
                disabled={!canStart}
                onClick={() => void startDownloads()}
              >
                {queueing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Download className="h-4 w-4" />
                )}
                Start {selectedCount} download{selectedCount !== 1 ? "s" : ""}
              </Button>
            </div>
            {queueError && <p className="text-sm text-danger-text">{queueError}</p>}
          </div>
        )}

        <div className="overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center justify-between gap-2 border-b bg-muted/50 px-3 py-2">
            <p className="flex items-center gap-1.5 text-sm font-medium">
              <ArrowDown className="h-4 w-4 text-muted-foreground" />
              Download queue
              {jobs.length > 0 && (
                <span className="font-normal text-muted-foreground">
                  ({activeCount} active{jobs.length !== activeCount ? `, ${jobs.length} total` : ""})
                </span>
              )}
            </p>
            <div className="flex items-center gap-1">
            {jobs.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={toggleAllJobs}
              >
                {allJobsSelected ? "Unselect all" : "Select all"}
              </Button>
            )}
            {selectedActiveJobs.length > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs hover:text-destructive"
                onClick={() => {
                  selectedActiveJobs.forEach((j) => onCancel(j.id));
                  setSelectedJobs(new Set());
                }}
              >
                Cancel selected ({selectedActiveJobs.length})
              </Button>
            )}
            {finishedCount > 0 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={onDismissFinished}
              >
                Clear finished
              </Button>
            )}
            </div>
          </div>
          {jobs.length === 0 ? (
            <p className="px-3 py-10 text-center text-sm text-muted-foreground">
              No active downloads. Load a URL above to add files to the queue.
            </p>
          ) : (
            <div className="max-h-[min(420px,50vh)] overflow-y-auto overflow-x-hidden">
              <TorrentTableHeader />
              {jobs.map((job) => (
                <DownloadRow
                  key={job.id}
                  job={job}
                  selected={selectedJobs.has(job.id)}
                  onToggle={toggleJob}
                  onCancel={onCancel}
                />
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </>
  );
}
