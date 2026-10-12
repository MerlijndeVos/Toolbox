import { useMemo } from "react";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { JobStatusPill } from "@/components/ui/status-pill";
import type { ModGroup } from "@/hooks/useMods";
import { ACCENT_STYLES, groupStyle } from "@/lib/groups";
import { modIcon } from "@/lib/modIcons";
import { cn } from "@/lib/utils";
import type { ActiveJob, ToolId } from "@/lib/types";

export type SettingsViewId = "logs" | "ai" | "updates" | "mods" | "appearance";

interface HomePanelProps {
  /** Enabled mods grouped for display (Files, Media, Subtitles, ...). */
  groups: ModGroup[];
  desktop: boolean;
  updateAvailable: boolean;
  jobs: ActiveJob[];
  undoing?: boolean;
  onOpenTool: (tool: ToolId) => void;
  onOpenSettings: (view: SettingsViewId) => void;
  onUndoRename: (jobId: string) => void;
}

const RECENT_LIMIT = 6;

function duration(job: ActiveJob): string {
  if (!job.started_at) return "";
  const end = job.finished_at ? Date.parse(job.finished_at) : Date.now();
  const seconds = Math.max(0, Math.round((end - Date.parse(job.started_at)) / 1000));
  if (Number.isNaN(seconds)) return "";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
}

function startedAt(job: ActiveJob): string {
  const when = new Date(job.started_at ?? job.created_at);
  return Number.isNaN(when.getTime())
    ? ""
    : when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function HomePanel({
  groups,
  desktop,
  updateAvailable,
  jobs,
  undoing,
  onOpenTool,
  onOpenSettings,
  onUndoRename,
}: HomePanelProps) {
  const names = useMemo(() => {
    const map = new Map<string, string>();
    for (const group of groups) for (const mod of group.mods) map.set(mod.id, mod.name);
    return map;
  }, [groups]);

  const recent = useMemo(() => jobs.filter((j) => !j.undo_of).slice(0, RECENT_LIMIT), [jobs]);

  return (
    <div className="space-y-5">
      {desktop && updateAvailable && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-ring/10 px-3.5 py-2.5 text-[13px]">
          <span>
            <strong className="font-semibold">Update available:</strong> a newer Toolbox is ready to install.
            Your files and settings stay as they are.
          </span>
          <Button size="sm" onClick={() => onOpenSettings("updates")}>
            View update
          </Button>
        </div>
      )}

      <div className="grid items-start gap-5 md:grid-cols-2">
        {groups.map((group) => {
          const { accent, subtitle, muted } = groupStyle(group.name);
          return (
            <Card key={group.name} className="overflow-hidden">
              <CardHeader className="flex-row items-start justify-between gap-3">
                <div className="min-w-0">
                  <CardTitle>{group.name}</CardTitle>
                  {subtitle && <CardDescription>{subtitle}</CardDescription>}
                </div>
                <span className="shrink-0 pt-0.5 font-mono text-[11px] text-muted-foreground">
                  {group.mods.length} {group.mods.length === 1 ? "tool" : "tools"}
                </span>
              </CardHeader>
              <ul>
                {group.mods.map((mod) => {
                  const Icon = modIcon(mod.icon);
                  const chip = ACCENT_STYLES[mod.accent || accent].chip;
                  return (
                    <li key={mod.id} className="border-b last:border-b-0">
                      <button
                        type="button"
                        onClick={() => onOpenTool(mod.id)}
                        className="grid w-full grid-cols-[32px_minmax(0,1fr)] items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                      >
                        <span className={cn("flex size-8 items-center justify-center rounded-lg", chip)}>
                          <Icon className="h-4 w-4" />
                        </span>
                        <span className="min-w-0">
                          <span
                            className={cn(
                              "block truncate text-sm",
                              muted ? "text-muted-foreground" : "font-medium",
                            )}
                          >
                            {mod.name}
                          </span>
                          {mod.description && (
                            <span className="block text-xs text-muted-foreground">{mod.description}</span>
                          )}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>
          );
        })}
      </div>

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle>Recent runs</CardTitle>
        </CardHeader>
        {recent.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            Nothing has run yet. Pick a tool above to start.
          </p>
        ) : (
          <ul>
            {recent.map((job) => {
              const time = duration(job);
              const canUndo = job.command === "rename" && job.undo_available && !job.undo_used;
              return (
                <li
                  key={job.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b px-4 py-2.5 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_120px_64px_112px]"
                >
                  <button
                    type="button"
                    onClick={() => onOpenTool(job.command)}
                    className="min-w-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="block truncate text-sm font-medium">
                      {names.get(job.command) ?? job.command}
                    </span>
                    <span className="block truncate font-mono text-[11px] text-muted-foreground">
                      {job.command} – {startedAt(job)}
                      {job.error ? ` – ${job.error}` : ""}
                    </span>
                  </button>
                  <span className="justify-self-start">
                    <JobStatusPill status={job.status} />
                  </span>
                  <span className="hidden text-right text-xs tabular-nums text-muted-foreground sm:block">
                    {time}
                  </span>
                  <span className="hidden justify-self-end sm:block">
                    {canUndo && (
                      <Button size="sm" variant="outline" disabled={undoing} onClick={() => onUndoRename(job.id)}>
                        Undo rename
                      </Button>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}
