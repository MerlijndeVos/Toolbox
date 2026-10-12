import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Download, House, Palette, Puzzle, ScrollText, type LucideIcon } from "lucide-react";
import { checkHealth, fetchSettings } from "@/api/client";
import { AppearancePanel } from "@/components/AppearancePanel";
import { HomePanel } from "@/components/HomePanel";
import { LogDrawer } from "@/components/LogDrawer";
import { ToolsBanner } from "@/components/ToolsBanner";
import { LoggingPanel } from "@/components/LoggingPanel";
import { ModsPanel } from "@/components/ModsPanel";
import { AiSettingsPanel } from "@/components/AiSettingsPanel";
import { AiUsagePanel } from "@/components/AiUsagePanel";
import { ToolPanel } from "@/components/ToolPanel";
import { UpdateModal } from "@/components/UpdateModal";
import { UpdatesPanel } from "@/components/UpdatesPanel";
import { StatusPill } from "@/components/ui/status-pill";
import { modIcon } from "@/lib/modIcons";
import { cn } from "@/lib/utils";
import { isDesktopApp } from "@/lib/desktop";
import { groupStyle } from "@/lib/groups";
import { useAppearance } from "@/hooks/useAppearance";
import { useMods } from "@/hooks/useMods";
import { useUpdates } from "@/hooks/useUpdates";
import type { DownloadJobMeta, ToolId } from "@/lib/types";
import { useJobRunner } from "@/hooks/useJobRunner";

type AppView = "home" | "tools" | "logs" | "ai" | "updates" | "appearance" | "mods";

/** The Toolbox glyph: three tiles and a turned one, stroked in the text colour. */
function ToolboxMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 36 36"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <rect x="6.5" y="6.5" width="9" height="9" rx="2" />
      <rect x="20.5" y="6.5" width="9" height="9" rx="2" />
      <rect x="6.5" y="20.5" width="9" height="9" rx="2" />
      <rect x="21.6" y="21.6" width="7" height="7" rx="1.6" transform="rotate(45 25.1 25.1)" />
    </svg>
  );
}

function NavItem({
  current,
  icon: Icon,
  onClick,
  badge,
  quiet,
  children,
}: {
  current: boolean;
  icon: LucideIcon;
  onClick: () => void;
  badge?: string;
  quiet?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={current ? "page" : undefined}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        current
          ? "bg-muted font-medium text-foreground"
          : cn("hover:bg-muted hover:text-foreground", quiet ? "text-muted-foreground/70" : "text-muted-foreground"),
      )}
    >
      <Icon className="size-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {badge && (
        <span className="shrink-0 rounded-full bg-ring/10 px-1.5 py-0.5 text-[11px] font-medium text-ring">
          {badge}
        </span>
      )}
    </button>
  );
}

export default function App() {
  const updates = useUpdates();
  const mods = useMods();
  const appearance = useAppearance(mods.themes, mods.loaded);
  const desktop = isDesktopApp();
  const [view, setView] = useState<AppView>("home");
  const [tool, setTool] = useState<ToolId>("convert");
  const [fileLogging, setFileLogging] = useState(true);
  const [logOpen, setLogOpen] = useState(true);
  const [logHeight, setLogHeight] = useState(256);
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [running, setRunning] = useState(false);
  const logClosedByUser = useRef(false);
  const {
    jobs,
    logs,
    startJob,
    startJobs,
    cancel,
    clearLogs,
    dismissFinishedDownloads,
    undoRename,
    undoing,
  } = useJobRunner();

  const undoableRenameJobs = useMemo(
    () =>
      jobs.filter(
        (j) =>
          !j.undo_of &&
          j.status === "completed" &&
          j.undo_available &&
          !j.undo_used,
      ),
    [jobs],
  );

  useEffect(() => {
    const tick = () => checkHealth().then(setApiOk);
    tick();
    const id = setInterval(tick, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    fetchSettings()
      .then((s) => setFileLogging(s.file_logging))
      .catch(() => undefined);
  }, []);

  const activeJob = useMemo(() => {
    if (tool === "download") return undefined;
    const running = jobs.find(
      (j) => j.command === tool && (j.status === "running" || j.status === "queued"),
    );
    if (running) return running;
    if (tool === "subtitle_translate" || tool === "subtitle_cleanup") {
      return jobs.find((j) => j.command === tool && j.status === "completed");
    }
    return undefined;
  }, [jobs, tool]);

  // The latest run of the open tool: what it showed (tables, counters, ...) appears under its form.
  const resultsJob = useMemo(
    () => jobs.find((j) => j.command === tool && !j.undo_of),
    [jobs, tool],
  );

  const downloadJobs = useMemo(
    () => jobs.filter((j) => j.command === "download"),
    [jobs],
  );

  // The latest rename that also renamed the folder the user had selected, so the Rename form can follow it.
  const renamedRoot = useMemo(() => {
    const job = jobs.find((j) => j.command === "rename" && !j.undo_of && j.status === "completed" && j.renamed_root);
    if (!job?.renamed_root) return undefined;
    return { ...job.renamed_root, jobId: job.id, undone: Boolean(job.undo_used) };
  }, [jobs]);

  const handleQueueDownloads = async (
    items: Array<{ params: Record<string, unknown>; downloadMeta: DownloadJobMeta }>,
  ) => {
    await startJobs(
      "download",
      items.map((item) => ({
        params: item.params,
        downloadMeta: item.downloadMeta,
      })),
      fileLogging,
    );
  };

  const handleRun = async (params: Record<string, unknown>) => {
    if (tool !== "download" && !logClosedByUser.current) {
      setLogOpen(true);
    }
    if (tool === "download") {
      await startJob(tool, params, fileLogging, {
        downloadMeta: {
          url: String(params.url),
          format: String(params.format ?? "mp4"),
          output: String(params.output),
          displayName: params.output_name ? String(params.output_name) : undefined,
        },
      });
      return;
    }
    setRunning(true);
    try {
      await startJob(tool, params, fileLogging);
    } finally {
      setRunning(false);
    }
  };

  const toolName = useMemo(
    () => mods.groups.flatMap((g) => g.mods).find((m) => m.id === tool)?.name,
    [mods.groups, tool],
  );
  const title =
    view === "home"
      ? "Home"
      : view === "tools"
        ? (toolName ?? "Tool")
        : { logs: "Logs", ai: "AI", updates: "Updates", appearance: "Appearance", mods: "Mods" }[view];
  const currentVersion = updates.check?.current_version;
  const apiLabel = apiOk === true ? "API connected" : apiOk === false ? "API offline" : "Checking…";

  return (
    <div className="min-h-screen" style={{ paddingBottom: logHeight }}>
      <ToolsBanner />
      <div className="grid lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside
          className="flex flex-col gap-5 border-b bg-chrome px-3 py-4 lg:sticky lg:top-0 lg:h-[calc(100vh-var(--log-h))] lg:self-start lg:overflow-y-auto lg:border-b-0 lg:border-r"
          style={{ "--log-h": `${logHeight}px` } as React.CSSProperties}
        >
          <button
            type="button"
            onClick={() => setView("home")}
            className="flex items-center gap-2.5 rounded-md px-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Toolbox home"
          >
            <ToolboxMark className="size-[26px] shrink-0" />
            <span className="text-base font-semibold tracking-tight">Toolbox</span>
          </button>

          <nav className="flex flex-col gap-0.5" aria-label="Tools">
            <NavItem current={view === "home"} icon={House} onClick={() => setView("home")}>
              Home
            </NavItem>
            {mods.groups.map((group) => {
              const muted = Boolean(groupStyle(group.name).muted);
              return (
                <div key={group.name} className="mt-3.5 flex flex-col gap-0.5">
                  <p className="px-2.5 pb-1 text-xs text-muted-foreground/80">{group.name}</p>
                  {group.mods.map((mod) => (
                    <NavItem
                      key={mod.id}
                      current={view === "tools" && tool === mod.id}
                      icon={modIcon(mod.icon)}
                      quiet={muted}
                      onClick={() => {
                        setView("tools");
                        setTool(mod.id);
                      }}
                    >
                      {mod.name}
                    </NavItem>
                  ))}
                </div>
              );
            })}
          </nav>

          <nav className="flex flex-col gap-0.5 border-t pt-4" aria-label="Settings">
            <p className="px-2.5 pb-1 text-xs text-muted-foreground/80">Settings</p>
            <NavItem current={view === "logs"} icon={ScrollText} onClick={() => setView("logs")}>
              Logs
            </NavItem>
            <NavItem current={view === "ai"} icon={Bot} onClick={() => setView("ai")}>
              AI
            </NavItem>
            {desktop && (
              <NavItem
                current={view === "updates"}
                icon={Download}
                onClick={() => setView("updates")}
                badge={updates.showUpdate ? "New" : undefined}
              >
                Updates
              </NavItem>
            )}
            <NavItem current={view === "mods"} icon={Puzzle} onClick={() => setView("mods")}>
              Mods
            </NavItem>
            <NavItem current={view === "appearance"} icon={Palette} onClick={() => setView("appearance")}>
              Appearance
            </NavItem>
          </nav>

          <div className="mt-auto flex flex-col gap-2 px-2.5 text-xs text-muted-foreground">
            <span className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={cn(
                  "size-1.5 rounded-full",
                  apiOk === true ? "bg-success" : apiOk === false ? "bg-danger" : "bg-muted-foreground/50",
                )}
              />
              {apiLabel}
            </span>
            {currentVersion && (
              <span className="font-mono text-[11px] text-muted-foreground/80">v{currentVersion}</span>
            )}
          </div>
        </aside>

        <div className="flex min-w-0 flex-col">
          <header className="sticky top-0 z-30 flex items-center gap-3 border-b bg-chrome px-4 py-3.5 sm:px-7">
            <h1 className="min-w-0 flex-1 truncate text-lg font-semibold tracking-tight">{title}</h1>
            <StatusPill tone={apiOk === true ? "ok" : apiOk === false ? "err" : "neutral"}>{apiLabel}</StatusPill>
          </header>

          <main className="flex-1 px-4 pb-10 pt-6 sm:px-7">
            <div className="mx-auto max-w-5xl">
              {apiOk === false && (
                <div className="mb-5 rounded-lg bg-warning/10 px-3.5 py-2.5 text-[13px] text-warning-text">
                  <strong className="font-semibold">The API server is not running:</strong> start it with{" "}
                  <code className="rounded bg-muted px-1 font-mono text-foreground">python -m web</code>
                  {import.meta.env.DEV && (
                    <>
                      {" "}
                      – the dev UI proxies <code className="rounded bg-muted px-1 font-mono text-foreground">/api</code>{" "}
                      to port 8765
                    </>
                  )}
                </div>
              )}
              {view === "home" ? (
                <HomePanel
                  groups={mods.groups}
                  desktop={desktop}
                  updateAvailable={updates.showUpdate}
                  jobs={jobs}
                  undoing={undoing}
                  onOpenTool={(id) => {
                    setTool(id);
                    setView("tools");
                  }}
                  onOpenSettings={setView}
                  onUndoRename={(jobId) => void undoRename(jobId)}
                />
              ) : view === "logs" ? (
                <LoggingPanel onFileLoggingChange={setFileLogging} />
              ) : view === "ai" ? (
                <div className="space-y-5">
                  <AiSettingsPanel />
                  <AiUsagePanel />
                </div>
              ) : view === "updates" ? (
                <UpdatesPanel {...updates} />
              ) : view === "appearance" ? (
                <AppearancePanel
                  appearance={appearance}
                  themes={mods.themes}
                  onOpenMods={() => setView("mods")}
                />
              ) : view === "mods" ? (
                <ModsPanel mods={mods} />
              ) : (
                <ToolPanel
                  tool={tool}
                  mods={mods.enabledMods}
                  onRun={handleRun}
                  onQueueDownloads={handleQueueDownloads}
                  running={running}
                  activeJob={activeJob}
                  downloadJobs={downloadJobs}
                  onCancelDownload={cancel}
                  onDismissFinishedDownloads={dismissFinishedDownloads}
                  renamedRoot={renamedRoot}
                  resultsJob={resultsJob}
                />
              )}
            </div>
          </main>
        </div>
      </div>

      {desktop && updates.showUpdate && updates.check?.latest_version && (
        <UpdateModal
          open={updates.modalOpen}
          currentVersion={updates.check.current_version}
          latestVersion={updates.check.latest_version}
          releaseNotes={updates.check.release_notes}
          releaseUrl={updates.check.release_url}
          applying={updates.applying}
          applyStatus={updates.applyStatus}
          onSkip={updates.handleSkip}
          onUpdate={updates.handleApply}
        />
      )}

      <LogDrawer
        open={logOpen}
        onToggle={() => {
          setLogOpen((open) => {
            const next = !open;
            logClosedByUser.current = !next;
            return next;
          });
        }}
        logs={logs}
        onClear={clearLogs}
        onHeightChange={setLogHeight}
        undoableJobs={undoableRenameJobs}
        onUndoRename={async (jobId) => {
          if (!logClosedByUser.current) setLogOpen(true);
          await undoRename(jobId);
        }}
        undoing={undoing}
      />
    </div>
  );
}
