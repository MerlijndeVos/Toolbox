"""Theme mods: change how Toolbox looks with plain data, no code.

A theme is a mod with ``type = "theme"`` and a ``[theme]`` table (see ``MODDING.md``)::

    [theme]
    radius = "0.5rem"
    font = "serif"

    [theme.light]
    background = "#fdf6e3"

    [theme.dark]
    background = "#002b36"

    [theme.groups]          # accent colour per tool category, for both light and dark
    files = "#dc322f"

Everything is checked strictly. Only the tokens listed in :data:`COLOR_TOKENS` exist, and a value
has to be a colour (``#rrggbb``, ``hsl()`` or ``rgb()``), a short length or a font choice. There is
**no way to write CSS**: no ``url()``, ``@import``, selectors or ``calc()``, so a theme cannot load
anything or draw over the interface. Tokens that are not set fall back to the default theme, so old
themes keep working when new tokens appear.

A hostile theme must not be able to hide a warning. The tokens behind trust prompts, error text and
destructive buttons are *protected*: a theme that makes them unreadable, or turns the "danger"
colour into something that is not red, is refused. Other low-contrast pairs are reported as
warnings.

The default palette below has to match ``web/frontend/src/index.css`` (a test keeps them in sync).
"""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass, field
from typing import Any

from .manifest_errors import ManifestError

# --------------------------------------------------------------------------------------------
# The token list: the one source of truth (mirrored in MODDING.md)
# --------------------------------------------------------------------------------------------

# name -> (light, dark, what it colours). Values are "H S% L%" triplets, the form Tailwind reads.
_COLORS: tuple[tuple[str, str, str, str], ...] = (
    ("background", "48 20% 95.1%", "60 2.9% 6.9%", "Page background."),
    ("foreground", "45 8.3% 9.4%", "50 13.6% 91.4%", "Normal text."),
    ("card", "0 0% 100%", "60 3.7% 10.6%", "Panels, the header and dialogs."),
    ("card-foreground", "45 8.3% 9.4%", "50 13.6% 91.4%", "Text on panels."),
    ("chrome", "45 33.3% 97.6%", "60 2.2% 8.8%", "Sidebar, header, table heads and the log: one step apart from the page and the panels."),
    ("primary", "45 8.3% 9.4%", "50 13.6% 91.4%", "Main buttons and the selected menu item."),
    ("primary-foreground", "0 0% 100%", "60 2.6% 7.6%", "Text on primary."),
    ("secondary", "42.9 17.9% 92.4%", "40 4.1% 14.3%", "Secondary buttons."),
    ("secondary-foreground", "45 8.3% 9.4%", "50 13.6% 91.4%", "Text on secondary."),
    ("muted", "42.9 17.9% 92.4%", "40 4.1% 14.3%", "Quiet backgrounds (chips, code, tabs)."),
    ("muted-foreground", "41.5 6.5% 39.4%", "42.9 6.9% 60.4%", "Quiet text: hints and descriptions."),
    ("accent", "42.9 17.9% 92.4%", "40 4.1% 14.3%", "Hover background."),
    ("accent-foreground", "45 8.3% 9.4%", "50 13.6% 91.4%", "Text on hover."),
    ("border", "42 16.7% 88.2%", "45 4.8% 16.5%", "Lines and outlines."),
    ("input", "42 16.7% 88.2%", "45 4.8% 16.5%", "Outline of text boxes."),
    ("ring", "206.4 100% 35.3%", "210.2 89.3% 70.4%", "Keyboard focus ring."),
    ("destructive", "2.1 59.8% 48.3%", "2.1 59.8% 48.3%", "Buttons that delete or overwrite (Remove, Apply changes). Protected."),
    ("destructive-foreground", "0 0% 100%", "0 0% 100%", "Text on destructive buttons. Protected."),
    ("danger", "2.1 59.8% 48.3%", "2.1 59.8% 48.3%", "Errors and warnings about risk: fill, border and tint. Protected."),
    ("danger-text", "2.1 59.8% 48.3%", "5.3 94.5% 72.4%", "Error text and icons. Protected."),
    ("warning", "34.8 100% 29.6%", "34.8 100% 29.6%", "Cautions: fill, border and tint."),
    ("warning-text", "34.8 100% 29.6%", "38.4 73.4% 63.4%", "Caution text and icons. Protected."),
    ("success", "151.4 82.6% 25.5%", "151.4 82.6% 25.5%", "Good news: fill, border and tint."),
    ("success-text", "151.4 82.6% 25.5%", "142.8 43.6% 59.2%", "Good-news text and icons."),
    ("overlay", "0 0% 0%", "0 0% 0%", "The dim layer behind dialogs."),
    ("log-info", "41.5 6.5% 39.4%", "42.9 6.9% 60.4%", "Normal lines in the log panel."),
    ("log-warn", "34.8 100% 29.6%", "38.4 73.4% 63.4%", "Warning lines in the log panel."),
    ("log-error", "2.1 59.8% 48.3%", "5.3 94.5% 72.4%", "Error lines in the log panel."),
    ("syntax-keyword", "262 60% 50%", "262 85% 76%", "Keywords in code previews (def, import, if) and log level tags."),
    ("syntax-string", "150 75% 26%", "142 55% 62%", "Strings in code, quoted text and URLs in logs."),
    ("syntax-number", "24 90% 37%", "30 90% 65%", "Numbers and constants (true, null) in code and logs."),
    ("syntax-comment", "220 9% 44%", "217 12% 58%", "Comments in code and timestamps in logs."),
    ("syntax-function", "221 75% 46%", "213 90% 72%", "Function names in code and file paths in logs."),
    ("syntax-type", "188 85% 26%", "180 55% 58%", "Class names, types and built-ins; exception names in logs."),
    ("syntax-property", "340 70% 44%", "350 80% 74%", "Keys and attributes (TOML, JSON, YAML, HTML)."),
    ("syntax-meta", "32 85% 32%", "45 85% 62%", "Decorators, headings and section names ([table] in TOML)."),
    ("category-files", "45 8.3% 9.4%", "50 13.6% 91.4%", "Accent of the Files section."),
    ("category-media", "45 8.3% 9.4%", "50 13.6% 91.4%", "Accent of the Media section."),
    ("category-subtitles", "45 8.3% 9.4%", "50 13.6% 91.4%", "Accent of the Subtitles section."),
    ("category-experimental", "41.5 6.5% 39.4%", "42.9 6.9% 60.4%", "Accent of the Experimental section."),
    ("category-other", "45 8.3% 9.4%", "50 13.6% 91.4%", "Accent of the Other section and new categories."),
    ("category-settings", "41.5 6.5% 39.4%", "42.9 6.9% 60.4%", "Accent of the Settings tiles."),
    ("category-foreground", "0 0% 100%", "60 2.6% 7.6%", "Icon colour on the accent chips."),
)

COLOR_TOKENS: tuple[str, ...] = tuple(name for name, *_ in _COLORS)
TOKEN_HELP: dict[str, str] = {name: text for name, _l, _d, text in _COLORS}
DEFAULT_LIGHT: dict[str, str] = {name: light for name, light, _d, _t in _COLORS}
DEFAULT_DARK: dict[str, str] = {name: dark for name, _l, dark, _t in _COLORS}

# `[theme.groups]` keys are the category names; each sets the matching `category-*` token.
GROUP_KEYS: tuple[str, ...] = ("files", "media", "subtitles", "experimental", "other", "settings")

DEFAULT_RADIUS = "0.625rem"
MAX_RADIUS_REM = 2.0
MAX_RADIUS_PX = 32.0

DEFAULT_FONT = "system"
FONTS: dict[str, str] = {
    "system": '"Geist", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    "serif": 'Georgia, Cambria, "Times New Roman", serif',
    "mono": 'ui-monospace, "Cascadia Mono", "SF Mono", Consolas, Menlo, monospace',
    "rounded": 'ui-rounded, "Segoe UI Variable", "Nunito", "Quicksand", system-ui, sans-serif',
}

THEME_KEYS = frozenset({"radius", "font", "light", "dark", "groups"})

# Tokens that have to look like a warning colour (red to orange) so "Remove" cannot pass as harmless.
DANGER_TOKENS = ("destructive", "danger", "danger-text")

AA = 4.5
LARGE = 3.0

# (text token, background token, minimum ratio, protected?)
CONTRAST_PAIRS: tuple[tuple[str, str, float, bool], ...] = (
    ("foreground", "background", AA, True),
    ("card-foreground", "card", AA, True),
    ("destructive-foreground", "destructive", AA, True),
    ("danger-text", "background", AA, True),
    ("danger-text", "card", AA, True),
    ("warning-text", "background", AA, True),
    ("warning-text", "card", AA, True),
    ("primary-foreground", "primary", AA, False),
    ("secondary-foreground", "secondary", AA, False),
    ("accent-foreground", "accent", AA, False),
    ("muted-foreground", "background", AA, False),
    ("muted-foreground", "card", AA, False),
    ("muted-foreground", "muted", AA, False),
    ("success-text", "background", AA, False),
    ("success-text", "card", AA, False),
    ("log-info", "card", AA, False),
    ("log-warn", "card", AA, False),
    ("log-error", "card", AA, False),
    ("syntax-keyword", "card", AA, False),
    ("syntax-string", "card", AA, False),
    ("syntax-number", "card", AA, False),
    ("syntax-comment", "card", AA, False),
    ("syntax-function", "card", AA, False),
    ("syntax-type", "card", AA, False),
    ("syntax-property", "card", AA, False),
    ("syntax-meta", "card", AA, False),
    ("category-foreground", "category-files", LARGE, False),
    ("category-foreground", "category-media", LARGE, False),
    ("category-foreground", "category-subtitles", LARGE, False),
    ("category-foreground", "category-experimental", LARGE, False),
    ("category-foreground", "category-other", LARGE, False),
    ("category-foreground", "category-settings", LARGE, False),
)

# What a market card shows so a theme can be judged without installing it.
SWATCH_TOKENS = ("background", "card", "foreground", "primary", "category-files", "category-subtitles")

# --------------------------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_FUNC_RE = re.compile(r"^(hsl|rgb)\(\s*([^()]*?)\s*\)$", re.IGNORECASE)
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_TRIPLET_RE = re.compile(rf"^({_NUMBER})(?:deg)?\s*[,\s]\s*({_NUMBER})%\s*[,\s]\s*({_NUMBER})%$", re.IGNORECASE)
_RGB_RE = re.compile(rf"^({_NUMBER})\s*[,\s]\s*({_NUMBER})\s*[,\s]\s*({_NUMBER})$")
_LENGTH_RE = re.compile(r"^(\d+(?:\.\d+)?)(rem|px)$")

COLOR_HELP = "Use #rrggbb, hsl(210, 40%, 50%) or rgb(20, 40, 60). No transparency and no other CSS."


def _fmt(value: float) -> str:
    return f"{round(value, 1):g}"


def hsl_triplet(h: float, s: float, l: float) -> str:
    return f"{_fmt(h % 360)} {_fmt(s)}% {_fmt(l)}%"


def parse_color(value: Any, where: str) -> str:
    """Turn a colour written in a theme into the ``"H S% L%"`` triplet the app uses."""
    if not isinstance(value, str):
        raise ManifestError(f"{where}: must be a colour written as text. {COLOR_HELP}")
    text = value.strip()
    hexm = _HEX_RE.match(text)
    if hexm:
        digits = hexm.group(1)
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        r, g, b = (int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4))
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        return hsl_triplet(h * 360, s * 100, l * 100)
    func = _FUNC_RE.match(text)
    if func:
        kind, body = func.group(1).lower(), func.group(2)
        if kind == "hsl":
            m = _TRIPLET_RE.match(body)
            if m:
                h, s, l = (float(x) for x in m.groups())
                if 0 <= s <= 100 and 0 <= l <= 100:
                    return hsl_triplet(h, s, l)
        else:
            m = _RGB_RE.match(body)
            if m:
                r, g, b = (float(x) for x in m.groups())
                if all(0 <= x <= 255 for x in (r, g, b)):
                    hh, ll, ss = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
                    return hsl_triplet(hh * 360, ss * 100, ll * 100)
    raise ManifestError(f"{where}: {value!r} is not a colour I accept. {COLOR_HELP}")


def _split(triplet: str) -> tuple[float, float, float]:
    h, s, l = triplet.replace("%", "").split()
    return float(h), float(s), float(l)


def triplet_to_rgb(triplet: str) -> tuple[float, float, float]:
    h, s, l = _split(triplet)
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return r, g, b


def triplet_to_hex(triplet: str) -> str:
    r, g, b = triplet_to_rgb(triplet)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _luminance(triplet: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in triplet_to_rgb(triplet))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two ``"H S% L%"`` colours (1 to 21)."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = (la, lb) if la >= lb else (lb, la)
    return (hi + 0.05) / (lo + 0.05)


def _reddish(triplet: str) -> bool:
    h, s, _l = _split(triplet)
    return (h <= 45 or h >= 335) and s >= 35


# --------------------------------------------------------------------------------------------
# The parsed theme
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThemeSpec:
    """A validated theme: only what the theme sets. Missing tokens come from the default."""

    light: dict[str, str] = field(default_factory=dict)
    dark: dict[str, str] = field(default_factory=dict)
    radius: str | None = None
    font: str | None = None
    warnings: tuple[str, ...] = ()

    def palette(self, mode: str) -> dict[str, str]:
        """Every token for *mode* ("light" or "dark"): the default with this theme's values on top."""
        base = dict(DEFAULT_DARK if mode == "dark" else DEFAULT_LIGHT)
        base.update(self.dark if mode == "dark" else self.light)
        return base

    def swatches(self, mode: str = "light") -> list[str]:
        palette = self.palette(mode)
        return [triplet_to_hex(palette[t]) for t in SWATCH_TOKENS]

    def to_dict(self) -> dict[str, Any]:
        return {
            "light": dict(self.light),
            "dark": dict(self.dark),
            "radius": self.radius,
            "font": self.font,
            "resolved": {
                "light": self.palette("light"),
                "dark": self.palette("dark"),
                "radius": self.radius or DEFAULT_RADIUS,
                "font_stack": FONTS[self.font or DEFAULT_FONT],
            },
            "swatches": {"light": self.swatches("light"), "dark": self.swatches("dark")},
            "warnings": list(self.warnings),
        }


DEFAULT_THEME = ThemeSpec()


def check_contrast(light: dict[str, str], dark: dict[str, str]) -> tuple[list[str], list[str]]:
    """(problems, warnings) for the two palettes (each complete). Problems are refusals."""
    problems: list[str] = []
    warnings: list[str] = []
    for mode, palette in (("light", light), ("dark", dark)):
        for fg, bg, minimum, protected in CONTRAST_PAIRS:
            ratio = contrast_ratio(palette[fg], palette[bg])
            if ratio + 1e-9 >= minimum:
                continue
            text = (
                f"In {mode} mode '{fg}' on '{bg}' has a contrast of {ratio:.1f}:1; "
                f"at least {minimum:g}:1 is needed to read it."
            )
            (problems if protected else warnings).append(text)
        for token in DANGER_TOKENS:
            if not _reddish(palette[token]):
                problems.append(
                    f"In {mode} mode '{token}' must stay red or orange, so that a delete button "
                    "and a warning cannot be mistaken for something harmless."
                )
    return problems, warnings


def _colors(table: Any, where: str, allowed: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(table, dict):
        raise ManifestError(f"{where} must be a table.")
    out: dict[str, str] = {}
    for key, value in table.items():
        if key not in allowed:
            raise ManifestError(
                f"{where}: unknown token '{key}'. Only these exist: {', '.join(allowed)}."
            )
        out[key] = parse_color(value, f"{where} '{key}'")
    return out


def _parse_radius(value: Any) -> str:
    if not isinstance(value, str) or not (m := _LENGTH_RE.match(value.strip())):
        raise ManifestError("[theme] 'radius' must be a length in rem or px, for example \"0.5rem\".")
    number, unit = float(m.group(1)), m.group(2)
    if number > (MAX_RADIUS_REM if unit == "rem" else MAX_RADIUS_PX):
        raise ManifestError(f"[theme] 'radius' is too large (at most {MAX_RADIUS_REM:g}rem or {MAX_RADIUS_PX:g}px).")
    return f"{m.group(1)}{unit}"


def parse_theme(raw: Any) -> ThemeSpec:
    """Validate a ``[theme]`` table. Raises :class:`ManifestError` with what to fix."""
    if not isinstance(raw, dict):
        raise ManifestError("a theme needs a [theme] table.")
    unknown = sorted(set(raw) - THEME_KEYS)
    if unknown:
        raise ManifestError(
            f"[theme] has unknown key '{unknown[0]}'. A theme only has: {', '.join(sorted(THEME_KEYS))}. "
            "There is no way to add CSS."
        )

    light = _colors(raw.get("light", {}), "[theme.light]", COLOR_TOKENS)
    dark = _colors(raw.get("dark", {}), "[theme.dark]", COLOR_TOKENS)
    groups = _colors(raw.get("groups", {}), "[theme.groups]", GROUP_KEYS)
    for key, triplet in groups.items():
        # A mode table that names the token itself wins over the shared `[theme.groups]` value.
        light.setdefault(f"category-{key}", triplet)
        dark.setdefault(f"category-{key}", triplet)

    radius = _parse_radius(raw["radius"]) if "radius" in raw else None
    font = None
    if "font" in raw:
        font = raw["font"]
        if font not in FONTS:
            raise ManifestError(f"[theme] 'font' must be one of: {', '.join(FONTS)}. Custom fonts are not supported.")

    palettes = {"light": {**DEFAULT_LIGHT, **light}, "dark": {**DEFAULT_DARK, **dark}}
    problems, warnings = check_contrast(palettes["light"], palettes["dark"])
    if problems:
        raise ManifestError("this theme would make the interface unsafe to read. " + " ".join(problems))
    return ThemeSpec(light=light, dark=dark, radius=radius, font=font, warnings=tuple(warnings))


def default_theme_dict() -> dict[str, Any]:
    return DEFAULT_THEME.to_dict()


def tokens_help() -> str:
    """The token list as text (for the AI theme prompt): one line per token with its default colours."""
    return "\n".join(
        f"- {name}: {text} (default light {triplet_to_hex(DEFAULT_LIGHT[name])}, "
        f"dark {triplet_to_hex(DEFAULT_DARK[name])})"
        for name, text in TOKEN_HELP.items()
    )
