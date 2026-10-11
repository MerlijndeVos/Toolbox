import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import {
  clearAiUsage,
  fetchAiUsage,
  refreshAiLimits,
  type AiUsageGroup,
  type AiUsageSummary,
  type AiUsageTotals,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

const WINDOW_LABELS: Record<string, string> = {
  five_hour: "5-hour window",
  seven_day: "Weekly window",
  seven_day_opus: "Weekly (Opus)",
  seven_day_sonnet: "Weekly (Sonnet)",
};

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function tokens(t: AiUsageTotals): number {
  return t.input_tokens + t.output_tokens;
}

function untilReset(resetsAt: number | null | undefined): string {
  if (!resetsAt) return "";
  const seconds = resetsAt - Date.now() / 1000;
  if (seconds <= 0) return "resets now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `resets in ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `resets in ${hours} h ${minutes % 60} min`;
  return `resets in ${Math.round(hours / 24)} days`;
}

function ago(ts: number): string {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}

function Tile({ label, totals }: { label: string; totals: AiUsageTotals }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{compact(tokens(totals))}</p>
      <p className="text-xs text-muted-foreground">
        {totals.calls} {totals.calls === 1 ? "call" : "calls"}
        {totals.cache_tokens > 0 && ` – ${compact(totals.cache_tokens)} cached`}
      </p>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: AiUsageGroup[] }) {
  if (rows.length === 0) return null;
  const max = Math.max(1, ...rows.map(tokens));
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">{title}</h4>
      <ul className="space-y-2">
        {rows.slice(0, 6).map((row) => (
          <li key={row.name} className="space-y-1">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate">{row.name}</span>
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {compact(row.input_tokens)} in / {compact(row.output_tokens)} out
              </span>
            </div>
            <Progress value={(tokens(row) / max) * 100} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function DayBars({ days }: { days: AiUsageSummary["days"] }) {
  const max = Math.max(1, ...days.map(tokens));
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Last 7 days</h4>
      <div className="flex h-24 items-end gap-2" role="img" aria-label="Tokens per day for the last 7 days">
        {days.map((day) => {
          const label = new Date((day.start + 86400) * 1000).toLocaleDateString(undefined, { weekday: "short" });
          const height = (tokens(day) / max) * 100;
          return (
            <div key={day.start} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
              <div
                className="w-full rounded-t bg-primary/80"
                style={{ height: `${Math.max(tokens(day) > 0 ? 3 : 0, height)}%` }}
                title={`${label}: ${tokens(day).toLocaleString()} tokens in ${day.calls} calls`}
              />
              <span className="text-[10px] text-muted-foreground">{label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function AiUsagePanel() {
  const [data, setData] = useState<AiUsageSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await fetchAiUsage());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const handleClear = async () => {
    setBusy(true);
    try {
      setData(await clearAiUsage());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setError(null);
    try {
      setData(await refreshAiLimits());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const windows = data?.limits ? Object.entries(data.limits.windows) : [];
  const onSubscription = data?.provider === "claude_subscription";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Usage</CardTitle>
        <CardDescription>
          Tokens used by translation and rename assist on this computer, counted from each reply. Providers
          bill by their own rules, so treat this as an estimate.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {!data && !error && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading usage…
          </div>
        )}

        {data && (onSubscription || windows.length > 0) && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-medium">Claude plan limits</h4>
              {onSubscription && (
                <Button type="button" size="sm" variant="outline" onClick={() => void handleRefresh()} disabled={refreshing}>
                  {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Refresh
                </Button>
              )}
            </div>
            {windows.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No plan numbers yet. They arrive with the first translation, or press Refresh (one tiny call).
              </p>
            ) : (
              <ul className="space-y-3">
                {windows.map(([name, w]) => {
                  const pct = Math.round(w.utilization * 100);
                  return (
                    <li key={name} className="space-y-1">
                      <div className="flex items-baseline justify-between gap-3 text-sm">
                        <span>{WINDOW_LABELS[name] ?? name}</span>
                        <span className={cn("tabular-nums", pct >= 80 && "text-warning-text")}>
                          {pct}% used {untilReset(w.resets_at) && `– ${untilReset(w.resets_at)}`}
                        </span>
                      </div>
                      <Progress value={pct} />
                    </li>
                  );
                })}
              </ul>
            )}
            {data.limits && data.limits.status && data.limits.status !== "allowed" && (
              <p className="text-sm text-warning-text">Plan status: {data.limits.status.replace(/_/g, " ")}.</p>
            )}
            {data.limits && (
              <p className="text-xs text-muted-foreground">
                Last updated {ago(data.limits.updated)}. Numbers come from Claude Code itself.
              </p>
            )}
          </div>
        )}

        {data && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Tile label="Last 24 hours" totals={data.today} />
              <Tile label="Last 7 days" totals={data.week} />
              <Tile label="Since tracking began" totals={data.all} />
            </div>

            {data.all.calls === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing recorded yet. Usage appears here after your first translation or AI rename.
              </p>
            ) : (
              <>
                <DayBars days={data.days} />
                <div className="grid gap-6 sm:grid-cols-2">
                  <Breakdown title="By task (7 days)" rows={data.by_feature} />
                  <Breakdown title="By model (7 days)" rows={data.by_model} />
                </div>

                <details className="text-sm">
                  <summary className="cursor-pointer text-muted-foreground">Recent calls</summary>
                  <ul className="mt-2 divide-y rounded-lg border">
                    {data.recent.map((e, i) => (
                      <li key={`${e.ts}-${i}`} className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
                        <span className="truncate">
                          {e.feature} – {e.model}
                        </span>
                        <span className="tabular-nums text-xs text-muted-foreground">
                          {compact(e.input_tokens)} in / {compact(e.output_tokens)} out – {ago(e.ts)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>

                <div className="flex justify-end">
                  <Button type="button" size="sm" variant="ghost" onClick={() => void handleClear()} disabled={busy}>
                    <Trash2 className="h-4 w-4" />
                    Clear history
                  </Button>
                </div>
              </>
            )}
          </>
        )}

        {error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
