import { useEffect, useState } from "react";
import { Download, FlaskConical, Loader2, RefreshCw } from "lucide-react";
import { fetchSettings, updateSettings } from "@/api/client";
import { CheckField } from "@/components/fields";
import { UpdateProgress } from "@/components/UpdateProgress";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { UpdatesState } from "@/hooks/useUpdates";

export function UpdatesPanel({
  check,
  checking,
  networkError,
  applyStatus,
  applyError,
  applying,
  showUpdate,
  runCheck,
  setModalOpen,
}: UpdatesState) {
  const [experimental, setExperimental] = useState(false);
  const [settingError, setSettingError] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings()
      .then((s) => setExperimental(s.experimental_updates))
      .catch(() => {});
  }, []);

  const toggleExperimental = async (value: boolean) => {
    setSettingError(null);
    setExperimental(value);
    try {
      await updateSettings({ experimental_updates: value });
      runCheck();
    } catch (err) {
      setExperimental(!value);
      setSettingError(err instanceof Error ? err.message : "Could not save the setting.");
    }
  };

  const error = settingError ?? networkError ?? check?.error ?? applyError;
  const status = checking
    ? "Checking for updates…"
    : applyStatus?.phase === "error"
      ? applyStatus.error
      : check?.status_message;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Updates</CardTitle>
        <CardDescription>
          Check for new versions and install updates from GitHub releases, or opt in to experimental builds.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="default"
            disabled={checking || applying}
            onClick={runCheck}
            className="gap-1.5"
          >
            {checking ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Check for updates
          </Button>
          {showUpdate && check?.latest_version && (
            <Button
              type="button"
              size="default"
              disabled={applying}
              onClick={() => setModalOpen(true)}
              className="min-w-[9.5rem] gap-1.5 whitespace-nowrap"
            >
              {applying ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {applyStatus?.phase === "installing" ? "Installing…" : "Downloading…"}
                </>
              ) : (
                <>
                  <Download className="h-4 w-4" />
                  Update to v{check.latest_version}
                </>
              )}
            </Button>
          )}
        </div>

        <CheckField
          label="Experimental builds"
          checked={experimental}
          onChange={(v) => void toggleExperimental(v)}
          disabled={applying}
          hint="Get the latest changes on the production branch before they are released. These builds can be unstable. An official release that is newer always replaces them."
          tooltip="Updates to a rolling pre-release rebuilt on every push to production."
        />

        <UpdateProgress applyStatus={applyStatus} applying={applying} />

        {check && (
          <p className="text-sm text-muted-foreground">
            Installed version: <span className="font-medium text-foreground">v{check.current_version}</span>
            {check.current_version.includes("-exp.") && (
              <span className="ml-1.5 inline-flex items-center gap-1 text-xs">
                <FlaskConical className="h-3.5 w-3.5" />
                Experimental
              </span>
            )}
            {check.latest_version && (
              <>
                {" "}
                — {check.experimental ? "Latest experimental build" : "Latest release"}:{" "}
                <span className="font-medium text-foreground">v{check.latest_version}</span>
              </>
            )}
          </p>
        )}

        {error && (
          <p className={cn("text-sm", "text-danger-text")}>{error}</p>
        )}
        {!error && status && !applying && (
          <p className="text-sm text-muted-foreground">{status}</p>
        )}
      </CardContent>
    </Card>
  );
}
