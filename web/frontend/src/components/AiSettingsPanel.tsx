import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import {
  fetchSettings,
  testAiConnection,
  updateSettings,
  type AiProviderId,
  type AiTestResult,
  type AppSettings,
} from "@/api/client";
import { Field, SelectField } from "@/components/fields";
import { ModelPerformanceIndicator } from "@/components/ModelPerformanceIndicator";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { AI_PROVIDERS, BASE_URL_PRESETS, isLocalUrl, providerInfo } from "@/lib/aiProviders";
import { getOpenAiModelProfile } from "@/lib/openaiModels";

export function AiSettingsPanel() {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<AiTestResult | null>(null);

  // Form drafts for the selected provider. The key is never sent back by the server,
  // so an empty draft means "leave it as it is".
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  const ids = useId();
  const modelListId = `${ids}-models`;
  const urlListId = `${ids}-urls`;

  const provider = settings?.ai.provider ?? "openai";
  const info = providerInfo(provider);
  const saved = settings?.ai.providers[provider];

  const resetDrafts = useCallback((data: AppSettings) => {
    const current = data.ai.providers[data.ai.provider];
    setApiKey("");
    setModel(current.model);
    setBaseUrl(current.base_url);
    setTestResult(null);
  }, []);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await fetchSettings();
      setSettings(data);
      resetDrafts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [resetDrafts]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (action: () => Promise<AppSettings>) => {
    setBusy(true);
    setError(null);
    try {
      const data = await action();
      setSettings(data);
      resetDrafts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleProviderChange = (next: string) =>
    run(() => updateSettings({ ai: { provider: next as AiProviderId } }));

  const dirty =
    !!saved &&
    (apiKey.trim() !== "" ||
      model.trim() !== saved.model ||
      (info.needsBaseUrl === true && baseUrl.trim() !== saved.base_url));

  const handleSave = () =>
    run(() =>
      updateSettings({
        ai: {
          providers: {
            [provider]: {
              // Never overwrite a saved key with an empty draft.
              ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
              // Saving the default id keeps following the default.
              model: model.trim() === saved?.default_model ? "" : model.trim(),
              ...(info.needsBaseUrl ? { base_url: baseUrl.trim() } : {}),
            },
          },
        },
      }),
    );

  const handleRemoveKey = () =>
    run(() => updateSettings({ ai: { providers: { [provider]: { api_key: "" } } } }));

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      setTestResult(
        await testAiConnection({
          provider,
          api_key: apiKey.trim(),
          model: model.trim(),
          base_url: info.needsBaseUrl ? baseUrl.trim() : "",
        }),
      );
    } catch (e) {
      setTestResult({ ok: false, message: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  };

  const profile = useMemo(
    () => (provider === "openai" ? getOpenAiModelProfile(model.trim()) : undefined),
    [provider, model],
  );

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading settings…
      </div>
    );
  }

  if (!settings || !saved) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm">
        {error ?? "Could not load settings."}
      </div>
    );
  }

  const local = info.needsBaseUrl === true && baseUrl.trim() !== "" && isLocalUrl(baseUrl);
  const privacy = info.privacy
    ? info.privacy
    : local
    ? "This is a local address, so your subtitles and file names stay on this computer."
    : `Subtitle text (translation) and example file names (AI rename profiles) are sent to ${info.label}.`;

  const keyHint = info.keyHint && !saved.api_key_set
    ? info.keyHint
    : saved.api_key_set
    ? saved.api_key_from_env
      ? `Using the ${info.envVar} environment variable. Paste a key here to override it.`
      : "A key is saved. Paste a new one to replace it."
    : info.keyOptional
      ? "Optional. Most local servers do not need a key."
      : `Required. You can also set ${info.envVar}.`;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>AI provider</CardTitle>
          <CardDescription>
            Used by subtitle translation and AI-generated rename profiles. Settings are stored locally in
            your app data folder, and each provider keeps its own key.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SelectField
            label="Provider"
            value={provider}
            onChange={(v) => void handleProviderChange(v)}
            options={AI_PROVIDERS.map((p) => ({ value: p.id, label: p.label }))}
            hint={
              provider === "openai_compatible"
                ? "Works with Ollama, LM Studio, OpenRouter, Groq, Together, Mistral, Azure OpenAI and other services that speak the OpenAI API."
                : undefined
            }
            disabled={busy}
          />

          {info.needsBaseUrl && (
            <Field
              label="Base URL"
              hint="The address of the server, e.g. http://localhost:11434/v1. If you give only a host, /v1 is added."
            >
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                list={urlListId}
                placeholder="http://localhost:11434/v1"
                autoComplete="off"
                spellCheck={false}
                disabled={busy}
              />
              <datalist id={urlListId}>
                {BASE_URL_PRESETS.map((p) => (
                  <option key={p.url} value={p.url}>
                    {p.label}
                  </option>
                ))}
              </datalist>
            </Field>
          )}

          <Field label={provider === "claude_subscription" ? "Token (optional)" : "API key"} hint={keyHint}>
            <div className="flex gap-2">
              <Input
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={saved.api_key_set ? "•••••••• (saved, enter to replace)" : info.keyPlaceholder}
                disabled={busy}
              />
              {saved.api_key_set && !saved.api_key_from_env && (
                <Button type="button" variant="outline" onClick={() => void handleRemoveKey()} disabled={busy}>
                  Remove
                </Button>
              )}
            </div>
          </Field>

          <Field
            label="Model"
            hint={
              info.modelPresets.length
                ? "Pick a suggestion or type any model id your account can use."
                : "The model id exactly as your server names it."
            }
          >
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              list={modelListId}
              placeholder={saved.default_model || info.modelPlaceholder}
              autoComplete="off"
              spellCheck={false}
              disabled={busy}
            />
            <datalist id={modelListId}>
              {info.modelPresets.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </Field>

          {profile && <ModelPerformanceIndicator profile={profile} />}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" onClick={() => void handleSave()} disabled={busy || !dirty}>
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              Save
            </Button>
            <Button type="button" variant="outline" onClick={() => void handleTest()} disabled={busy || testing}>
              {testing && <Loader2 className="h-4 w-4 animate-spin" />}
              Test connection
            </Button>
            {dirty && <span className="text-xs text-muted-foreground">Unsaved changes. Testing uses them.</span>}
          </div>

          {testResult && (
            <div
              role="status"
              className={
                testResult.ok
                  ? "flex items-start gap-2 rounded-lg border border-success/40 bg-success/10 px-4 py-3 text-sm"
                  : "flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
              }
            >
              {testResult.ok ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success-text" />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
              )}
              <span>{testResult.message}</span>
            </div>
          )}

          <p className="text-xs text-muted-foreground">{privacy}</p>
          {info.needsBaseUrl && (
            <p className="text-xs text-muted-foreground">
              Small local models may translate poorly or break the JSON format Toolbox needs. If that
              happens, try a larger model.
            </p>
          )}
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}
    </div>
  );
}
