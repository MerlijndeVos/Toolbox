import type { AiProviderId } from "@/api/client";
import { OPENAI_MODEL_PROFILES } from "@/lib/openaiModels";

export interface AiProviderInfo {
  id: AiProviderId;
  label: string;
  /** Shown as the API key placeholder. */
  keyPlaceholder: string;
  /** Environment variable that also supplies the key. */
  envVar?: string;
  /** Base URL is asked for (OpenAI-compatible only). */
  needsBaseUrl?: boolean;
  /** Local servers usually need no key. */
  keyOptional?: boolean;
  /** Replaces the default API key hint. */
  keyHint?: string;
  /** Replaces the default privacy line. */
  privacy?: string;
  /** Suggestions only; any model id can be typed. */
  modelPresets: string[];
  modelPlaceholder?: string;
}

export const BASE_URL_PRESETS: { label: string; url: string }[] = [
  { label: "Ollama", url: "http://localhost:11434/v1" },
  { label: "LM Studio", url: "http://localhost:1234/v1" },
  { label: "OpenRouter", url: "https://openrouter.ai/api/v1" },
  { label: "Groq", url: "https://api.groq.com/openai/v1" },
  { label: "Together", url: "https://api.together.xyz/v1" },
  { label: "Mistral", url: "https://api.mistral.ai/v1" },
];

export const AI_PROVIDERS: AiProviderInfo[] = [
  {
    id: "openai",
    label: "OpenAI",
    keyPlaceholder: "sk-…",
    envVar: "OPENAI_API_KEY",
    modelPresets: OPENAI_MODEL_PROFILES.map((m) => m.value),
  },
  {
    id: "openai_compatible",
    label: "OpenAI-compatible",
    keyPlaceholder: "Only if the service asks for one",
    keyOptional: true,
    needsBaseUrl: true,
    modelPresets: [],
    modelPlaceholder: "e.g. llama3.1 (as named by your server)",
  },
  {
    id: "anthropic",
    label: "Anthropic (Claude)",
    keyPlaceholder: "sk-ant-…",
    envVar: "ANTHROPIC_API_KEY",
    modelPresets: ["claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5"],
  },
  {
    id: "gemini",
    label: "Google Gemini",
    keyPlaceholder: "AIza…",
    envVar: "GEMINI_API_KEY",
    modelPresets: ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-pro"],
  },
  {
    id: "claude_subscription",
    label: "Claude subscription (Claude Code)",
    keyPlaceholder: "Token from `claude setup-token` (optional)",
    envVar: "CLAUDE_CODE_OAUTH_TOKEN",
    keyOptional: true,
    keyHint:
      "Optional. Leave empty to use the account Claude Code is signed in with (run `claude`, then /login). A token from `claude setup-token` also works.",
    privacy:
      "Subtitle text is sent to Anthropic through the Claude Code program on this computer, using your Claude plan instead of an API key. Calls count against your plan's 5-hour and weekly limits.",
    modelPresets: ["sonnet", "opus", "haiku", "fable"],
  },
];

export function providerInfo(id: AiProviderId): AiProviderInfo {
  return AI_PROVIDERS.find((p) => p.id === id) ?? AI_PROVIDERS[0];
}

/** True when the base URL points at this computer, so nothing leaves the machine. */
export function isLocalUrl(url: string): boolean {
  const match = /^(?:[a-z]+:\/\/)?(\[[^\]]+\]|[^/:?#]+)/i.exec(url.trim());
  if (!match) return false;
  const host = match[1].toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host.endsWith(".localhost");
}
