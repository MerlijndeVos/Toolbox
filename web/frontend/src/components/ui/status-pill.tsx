import { cn } from "@/lib/utils";
import type { JobStatus } from "@/lib/types";

export type PillTone = "running" | "ok" | "wait" | "err" | "neutral";

const TONES: Record<PillTone, string> = {
  running: "bg-ring/10 text-ring",
  ok: "bg-success/10 text-success-text",
  wait: "bg-warning/10 text-warning-text",
  err: "bg-danger/10 text-danger-text",
  neutral: "bg-muted text-muted-foreground",
};

const STATUS: Record<JobStatus, { tone: PillTone; label: string }> = {
  queued: { tone: "neutral", label: "Queued" },
  running: { tone: "running", label: "Running" },
  completed: { tone: "ok", label: "Completed" },
  failed: { tone: "err", label: "Failed" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

/** A state is a dot and a word: colour never carries it alone. The dot pulses only while running. */
export function StatusPill({
  tone,
  children,
  dot = true,
  pulse = false,
  className,
}: {
  tone: PillTone;
  children: React.ReactNode;
  dot?: boolean;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-[3px] text-xs font-medium leading-none",
        TONES[tone],
        className,
      )}
    >
      {dot && (
        <span
          aria-hidden="true"
          className={cn("size-1.5 rounded-full bg-current", pulse && "motion-safe:animate-pulse")}
        />
      )}
      {children}
    </span>
  );
}

export function JobStatusPill({ status, className }: { status: JobStatus; className?: string }) {
  const { tone, label } = STATUS[status];
  return (
    <StatusPill tone={tone} pulse={status === "running"} className={className}>
      {label}
    </StatusPill>
  );
}
