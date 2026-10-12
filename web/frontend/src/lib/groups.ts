/**
 * How each tool category is presented. Which tools belong to which category, and the order of the
 * categories, comes from the API (`group` and `order` in mod.toml, resolved by core/mods/groups.py):
 * the sidebar and the home screen both render that same list, and this file only adds the look and
 * the one-line subtitle. The colours themselves are theme tokens (`--category-*`, see lib/theme.ts).
 */
export type Accent =
  | "files"
  | "media"
  | "subtitles"
  | "experimental"
  | "other"
  | "settings"
  | "primary"
  | "success"
  | "warning"
  | "danger";

/** The accents a mod can ask for with `accent = "..."` in mod.toml. */
export type ModAccent = Accent | "";

interface GroupStyle {
  accent: Accent;
  subtitle?: string;
  /** Quieter menu entries, for categories that are not the everyday ones. */
  muted?: boolean;
}

const GROUP_STYLES: Record<string, GroupStyle> = {
  files: { accent: "files", subtitle: "Rename and organize files and folders." },
  media: { accent: "media", subtitle: "Convert, cut, join, and download video and audio." },
  subtitles: { accent: "subtitles", subtitle: "Translate and clean up SRT subtitle files." },
  experimental: {
    accent: "experimental",
    subtitle: "Specialised utilities for less common jobs.",
    muted: true,
  },
};

const FALLBACK: GroupStyle = { accent: "other" };

export function groupStyle(group: string): GroupStyle {
  return GROUP_STYLES[group.trim().toLowerCase()] ?? FALLBACK;
}

// Full class strings so Tailwind can see them. A category only tints its glyph: the default theme
// sets every category accent to the text colour, so the interface stays neutral unless a theme asks.
export const ACCENT_STYLES: Record<Accent, { chip: string }> = {
  files: { chip: "bg-muted text-category-files" },
  media: { chip: "bg-muted text-category-media" },
  subtitles: { chip: "bg-muted text-category-subtitles" },
  experimental: { chip: "bg-muted text-category-experimental" },
  other: { chip: "bg-muted text-category-other" },
  settings: { chip: "bg-muted text-category-settings" },
  primary: { chip: "bg-muted text-primary" },
  success: { chip: "bg-success/10 text-success-text" },
  warning: { chip: "bg-warning/10 text-warning-text" },
  danger: { chip: "bg-danger/10 text-danger-text" },
};
