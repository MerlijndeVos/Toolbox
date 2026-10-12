import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDownToLine, Check, ChevronDown, ChevronUp, Copy, Terminal, WrapText } from "lucide-react";
import { LogStream, UndoRenameBar } from "@/components/LogStream";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { ActiveJob, LogLine } from "@/lib/types";

const HEADER_HEIGHT = 44;
const DEFAULT_HEIGHT = 256;
const MIN_HEIGHT = 120;
const HEIGHT_STORAGE_KEY = "log-drawer-height";
const WRAP_STORAGE_KEY = "log-drawer-wrap";
const STICK_STORAGE_KEY = "log-drawer-stick";

interface LogDrawerProps {
  open: boolean;
  onToggle: () => void;
  logs: LogLine[];
  onClear: () => void;
  onHeightChange?: (height: number) => void;
  undoableJobs?: ActiveJob[];
  onUndoRename?: (jobId: string) => void;
  undoing?: boolean;
}

function readStoredHeight(): number {
  if (typeof window === "undefined") return DEFAULT_HEIGHT;
  const stored = localStorage.getItem(HEIGHT_STORAGE_KEY);
  const parsed = stored ? Number(stored) : DEFAULT_HEIGHT;
  return Number.isFinite(parsed) && parsed >= MIN_HEIGHT ? parsed : DEFAULT_HEIGHT;
}

function readStoredWrap(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(WRAP_STORAGE_KEY) === "1";
}

/** Following the newest line is the default; only an explicit "0" turns it off. */
function readStoredStick(): boolean {
  if (typeof window === "undefined") return true;
  return localStorage.getItem(STICK_STORAGE_KEY) !== "0";
}

export function LogDrawer({
  open,
  onToggle,
  logs,
  onClear,
  onHeightChange,
  undoableJobs = [],
  onUndoRename,
  undoing = false,
}: LogDrawerProps) {
  const [height, setHeight] = useState(readStoredHeight);
  const [copied, setCopied] = useState(false);
  const [wrap, setWrap] = useState(readStoredWrap);
  const [stick, setStick] = useState(readStoredStick);
  const dragging = useRef(false);
  const startY = useRef(0);
  const startHeight = useRef(0);
  const heightRef = useRef(height);
  heightRef.current = height;

  useEffect(() => {
    onHeightChange?.(open ? height : HEADER_HEIGHT);
  }, [open, height, onHeightChange]);

  const onCopy = useCallback(async () => {
    const text = logs.map((line) => line.message).join("\n");
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }, [logs]);

  const onToggleWrap = useCallback(() => {
    setWrap((prev) => {
      const next = !prev;
      localStorage.setItem(WRAP_STORAGE_KEY, next ? "1" : "0");
      return next;
    });
  }, []);

  // Scrolling up to read unsticks the log and scrolling back down sticks it again; the button does it explicitly.
  const updateStick = useCallback((next: boolean) => {
    setStick(next);
    localStorage.setItem(STICK_STORAGE_KEY, next ? "1" : "0");
  }, []);

  const onResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      dragging.current = true;
      startY.current = e.clientY;
      startHeight.current = height;
      document.body.style.cursor = "ns-resize";
      document.body.style.userSelect = "none";
    },
    [height],
  );

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const maxHeight = window.innerHeight * 0.8;
      const delta = startY.current - e.clientY;
      const next = Math.min(maxHeight, Math.max(MIN_HEIGHT, startHeight.current + delta));
      setHeight(next);
    };

    const onMouseUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      localStorage.setItem(HEIGHT_STORAGE_KEY, String(heightRef.current));
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
    return () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  return (
    <div
      className={cn(
        "fixed bottom-0 left-0 right-0 z-40 border-t bg-chrome",
        !open && "h-11 transition-all",
      )}
      style={open ? { height } : undefined}
    >
      {open && (
        <div
          className="absolute inset-x-0 top-0 z-10 h-2 -translate-y-1/2 cursor-ns-resize"
          onMouseDown={onResizeStart}
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize log panel"
        />
      )}
      <div className="flex h-11 items-center justify-between border-b px-4">
        <button
          type="button"
          onClick={onToggle}
          className="flex items-center gap-2 text-sm font-medium hover:text-primary"
        >
          <Terminal className="h-4 w-4" />
          Log
          <span className="text-muted-foreground">({logs.length})</span>
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </button>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggleWrap}
            className={cn(wrap && "bg-accent")}
            aria-pressed={wrap}
            title={wrap ? "Disable line wrap" : "Enable line wrap"}
          >
            <WrapText className="h-4 w-4" />
            Wrap
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => updateStick(!stick)}
            className={cn(stick && "bg-accent")}
            aria-pressed={stick}
            aria-label="Stick to bottom"
            title={stick ? "Stuck to the bottom: new lines stay in view (click to stop)" : "Stick to the bottom so new lines stay in view"}
          >
            <ArrowDownToLine className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void onCopy()}
            disabled={logs.length === 0}
          >
            {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button variant="ghost" size="sm" onClick={onClear}>
            Clear
          </Button>
        </div>
      </div>
      {open && (
        <div className="flex h-[calc(100%-2.75rem)] flex-col">
          {onUndoRename && (
            <UndoRenameBar jobs={undoableJobs} onUndo={onUndoRename} undoing={undoing} />
          )}
          <LogStream logs={logs} wrap={wrap} stick={stick} onStickChange={updateStick} className="flex-1 p-4" />
        </div>
      )}
    </div>
  );
}
