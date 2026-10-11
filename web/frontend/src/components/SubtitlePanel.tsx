import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, ScanSearch } from "lucide-react";
import {
  fetchSubtitleLanguages,
  scanSubtitleJunk,
  type SubtitleJunkItem,
  type SubtitleLanguage,
} from "@/api/client";
import {
  CheckField,
  Field,
  LanguageCombobox,
  ToolRunActions,
} from "@/components/fields";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isDesktopApp, pickFiles, pickFolder } from "@/lib/desktop";
import { cn, normalizeFilePath } from "@/lib/utils";

const TEXTAREA_CLASS =
  "flex min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

const FLAG_TOKENS = new Set(["forced", "sdh", "cc", "hi", "default", "foreign"]);

function basename(path: string): string {
  const norm = path.replace(/\\/g, "/");
  return norm.split("/").pop() ?? path;
}

function detectLangFromFilename(path: string, languages: SubtitleLanguage[]): string | null {
  const stem = basename(path).replace(/\.srt$/i, "");
  const parts = stem.split(".");
  const codes = new Set(languages.map((l) => l.code.toLowerCase()));
  while (parts.length > 1) {
    const last = parts[parts.length - 1].toLowerCase();
    if (FLAG_TOKENS.has(last)) {
      parts.pop();
      continue;
    }
    if (codes.has(last)) return last;
    break;
  }
  return null;
}

function SubtitlePathInput({
  value,
  onChange,
  hint,
  placeholder = "C:\\media\\Show.en.srt or folder",
}: {
  value: string;
  onChange: (value: string) => void;
  hint: string;
  placeholder?: string;
}) {
  const [picking, setPicking] = useState(false);

  const handleBrowseFile = async () => {
    if (!isDesktopApp()) return;
    setPicking(true);
    try {
      const files = await pickFiles(false);
      if (files[0]) onChange(files[0]);
    } finally {
      setPicking(false);
    }
  };

  const handleBrowseFolder = async () => {
    setPicking(true);
    try {
      const path = await pickFolder();
      if (path) onChange(path);
    } finally {
      setPicking(false);
    }
  };

  return (
    <Field label="SRT file or folder" hint={hint}>
      <div className="flex flex-wrap gap-2">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={() => onChange(normalizeFilePath(value))}
          placeholder={placeholder}
          className="min-w-0 flex-1"
        />
        {isDesktopApp() && (
          <>
            <Button type="button" variant="outline" onClick={handleBrowseFile} disabled={picking}>
              File
            </Button>
            <Button type="button" variant="outline" onClick={handleBrowseFolder} disabled={picking}>
              Folder
            </Button>
          </>
        )}
      </div>
    </Field>
  );
}

function JunkReviewSection({
  input,
  disabled,
  junkItems,
  confirmedIds,
  scanning,
  scanError,
  junkScanned,
  onScan,
  onToggle,
  onSetAll,
  reviewHint,
}: {
  input: string;
  disabled?: boolean;
  junkItems: SubtitleJunkItem[];
  confirmedIds: Set<string>;
  scanning: boolean;
  scanError: string | null;
  junkScanned: boolean;
  onScan: () => void;
  onToggle: (id: string, remove: boolean) => void;
  onSetAll: (remove: boolean) => void;
  reviewHint: string;
}) {
  const normalizedInput = normalizeFilePath(input);
  const junkReviewRequired = !junkScanned;

  const groupedJunk = useMemo(() => {
    const groups = new Map<string, SubtitleJunkItem[]>();
    for (const item of junkItems) {
      const key = basename(item.file);
      const list = groups.get(key) ?? [];
      list.push(item);
      groups.set(key, list);
    }
    return groups;
  }, [junkItems]);

  return (
    <div className="space-y-3 rounded-lg border border-border/60 bg-muted/20 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">Junk line review</p>
          <p className="text-xs text-muted-foreground">{reviewHint}</p>
        </div>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={onScan}
          disabled={disabled || scanning || !normalizedInput}
        >
          {scanning ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <ScanSearch className="h-4 w-4" />
          )}
          Scan for junk
        </Button>
      </div>

      {scanError && <p className="text-sm text-destructive">{scanError}</p>}

      {junkScanned && junkItems.length === 0 && (
        <p className="text-sm text-muted-foreground">No junk lines detected.</p>
      )}

      {junkItems.length > 0 && (
        <>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => onSetAll(true)}>
              Remove all
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => onSetAll(false)}>
              Keep all
            </Button>
            <span className="self-center text-xs text-muted-foreground">
              {confirmedIds.size} of {junkItems.length} marked for removal
            </span>
          </div>

          <div className="max-h-80 space-y-4 overflow-y-auto rounded-md border bg-background p-2">
            {[...groupedJunk.entries()].map(([fileName, items]) => (
              <div key={fileName} className="space-y-2">
                <p className="px-1 text-xs font-medium text-muted-foreground">{fileName}</p>
                {items.map((item) => {
                  const remove = confirmedIds.has(item.id);
                  return (
                    <label
                      key={item.id}
                      className={cn(
                        "flex cursor-pointer gap-3 rounded-md border px-3 py-2 text-sm transition-colors",
                        remove
                          ? "border-warning/40 bg-warning/10"
                          : "border-border/60 bg-muted/30",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="mt-1 shrink-0"
                        checked={remove}
                        onChange={(e) => onToggle(item.id, e.target.checked)}
                      />
                      <div className="min-w-0 space-y-1">
                        <p className="text-xs text-muted-foreground">
                          Cue {item.cue_index + 1} — {item.reason_label}
                        </p>
                        <p className="break-words font-mono text-xs">{item.text || "(empty line)"}</p>
                      </div>
                    </label>
                  );
                })}
              </div>
            ))}
          </div>
        </>
      )}

      {junkReviewRequired && normalizedInput && (
        <p className="text-xs text-warning-text">
          Run “Scan for junk” and review lines before Preview or Apply.
        </p>
      )}
    </div>
  );
}

function useJunkReview(input: string) {
  const [junkItems, setJunkItems] = useState<SubtitleJunkItem[]>([]);
  const [confirmedIds, setConfirmedIds] = useState<Set<string>>(new Set());
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [junkScanned, setJunkScanned] = useState(false);

  useEffect(() => {
    setJunkItems([]);
    setConfirmedIds(new Set());
    setJunkScanned(false);
    setScanError(null);
  }, [input]);

  const handleScanJunk = useCallback(async () => {
    const path = normalizeFilePath(input);
    if (!path) return;
    setScanning(true);
    setScanError(null);
    try {
      const result = await scanSubtitleJunk(path);
      setJunkItems(result.items);
      setConfirmedIds(new Set(result.items.map((i) => i.id)));
      setJunkScanned(true);
      return result;
    } catch (e) {
      setScanError(e instanceof Error ? e.message : String(e));
      setJunkItems([]);
      setConfirmedIds(new Set());
      setJunkScanned(false);
      return null;
    } finally {
      setScanning(false);
    }
  }, [input]);

  const toggleJunk = (id: string, remove: boolean) => {
    setConfirmedIds((prev) => {
      const next = new Set(prev);
      if (remove) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const setAllJunk = (remove: boolean) => {
    setConfirmedIds(remove ? new Set(junkItems.map((i) => i.id)) : new Set());
  };

  return {
    junkItems,
    confirmedIds,
    scanning,
    scanError,
    junkScanned,
    handleScanJunk,
    toggleJunk,
    setAllJunk,
  };
}

export function SubtitleTranslateForm({
  onRun,
  disabled,
}: {
  onRun: (p: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const [input, setInput] = useState("");
  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("en");
  const [overwrite, setOverwrite] = useState(false);
  const [removeJunk, setRemoveJunk] = useState(true);
  const [glossary, setGlossary] = useState("");
  const [notes, setNotes] = useState("");
  const [languages, setLanguages] = useState<SubtitleLanguage[]>([]);

  useEffect(() => {
    fetchSubtitleLanguages()
      .then((res) => setLanguages(res.languages))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!input.trim() || sourceLang !== "auto") return;
    const detected = detectLangFromFilename(input, languages);
    if (detected) setSourceLang(detected);
  }, [input, languages, sourceLang]);

  const normalizedInput = normalizeFilePath(input);

  const runParams = (dryRun: boolean) => ({
    input: normalizedInput,
    source_lang: sourceLang,
    target_lang: targetLang,
    overwrite,
    remove_junk: removeJunk,
    glossary,
    notes,
    dry_run: dryRun,
  });

  const canRun = Boolean(normalizedInput && targetLang.trim() && targetLang !== "auto");

  return (
    <div className="space-y-5">
      <SubtitlePathInput
        value={input}
        onChange={setInput}
        hint="Output uses the target language suffix, e.g. Show.en.srt → Show.de.srt."
      />

      <div className="grid gap-4 sm:grid-cols-2">
        <LanguageCombobox
          label="Source language"
          value={sourceLang}
          onChange={setSourceLang}
          languages={languages}
          includeAuto
          hint="Auto reads the language tag from the filename (.en, .de, …); without one, the model detects it."
        />
        <LanguageCombobox
          label="Target language"
          value={targetLang}
          onChange={setTargetLang}
          languages={languages}
          hint="Output suffix, e.g. Show.en.srt → Show.de.srt"
        />
      </div>

      <CheckField
        label="Overwrite existing output files"
        checked={overwrite}
        onChange={setOverwrite}
        hint="Replace translated .srt files that already exist."
      />

      <CheckField
        label="Drop ad and credit lines first"
        checked={removeJunk}
        onChange={setRemoveJunk}
        hint="Removes lines with web addresses, emails, release tags and “subtitles by …” credits before translating."
      />

      <Field label="Notes for the translator" hint="Optional, e.g. “Teen drama, informal register, keep English names”.">
        <textarea
          className={TEXTAREA_CLASS}
          value={notes}
          maxLength={1000}
          onChange={(e) => setNotes(e.target.value)}
        />
      </Field>

      <Field
        label="Glossary"
        hint="One per line: term = translation. A term on its own is kept untranslated."
      >
        <textarea
          className={cn(TEXTAREA_CLASS, "font-mono")}
          value={glossary}
          placeholder={"Hawkins\nUpside Down = De Andere Kant"}
          onChange={(e) => setGlossary(e.target.value)}
        />
      </Field>

      <ToolRunActions
        onPreview={() => onRun(runParams(true))}
        onApply={() => onRun(runParams(false))}
        disabled={disabled || !canRun}
        applyHint="Writes new translated SRT files next to the originals."
      />
    </div>
  );
}

export function SubtitleCleanupForm({
  onRun,
  disabled,
}: {
  onRun: (p: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const [input, setInput] = useState("");
  const {
    junkItems,
    confirmedIds,
    scanning,
    scanError,
    junkScanned,
    handleScanJunk,
    toggleJunk,
    setAllJunk,
  } = useJunkReview(input);

  const normalizedInput = normalizeFilePath(input);

  const runParams = (dryRun: boolean) => ({
    input: normalizedInput,
    confirmed_removals: [...confirmedIds],
    junk_reviewed: junkScanned,
    dry_run: dryRun,
  });

  const canRun = Boolean(normalizedInput);
  const runBlocked = !canRun || !junkScanned;

  return (
    <div className="space-y-5">
      <SubtitlePathInput
        value={input}
        onChange={setInput}
        hint="Removes junk lines from the selected .srt files in place."
      />

      <JunkReviewSection
        input={input}
        disabled={disabled}
        junkItems={junkItems}
        confirmedIds={confirmedIds}
        scanning={scanning}
        scanError={scanError}
        junkScanned={junkScanned}
        onScan={() => void handleScanJunk()}
        onToggle={toggleJunk}
        onSetAll={setAllJunk}
        reviewHint="Scan first, then confirm each line to remove before applying."
      />

      <ToolRunActions
        onPreview={() => onRun(runParams(true))}
        onApply={() => onRun(runParams(false))}
        disabled={disabled || runBlocked}
        applyHint="Overwrites the original SRT files with junk lines removed."
      />
    </div>
  );
}
