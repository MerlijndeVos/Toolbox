# Writing mods

A **mod** adds something to Toolbox. There are two kinds:

- A **tool** adds one tool: it shows up in the sidebar and home screen, gets an automatically
  generated form, runs as a normal background job (live log, progress, cancel), and is also a
  `toolbox <id>` command. Toolbox's own features are tools too. Their folders in
  [`builtin_mods/`](builtin_mods) are working examples.
- A **theme** changes how Toolbox looks (colours, corners, font) from one small data file. There is
  no code in it. See [Theme mods](#theme-mods).

A tool is a folder with two files:

```
my-mod/
  mod.toml    # what the mod is and what it asks for (plain data, never runs code)
  main.py     # def run(params, ctx): ...
```

## Try the examples

Three examples live in [`examples/mods`](examples/mods). Add any of them with **Settings → Mods →
Add a mod** (choose the folder), or `toolbox mods install examples/mods/<name>`. Toolbox shows what
it is and asks first.

| Example | Kind | Shows |
| --- | --- | --- |
| [`count-files`](examples/mods/count-files) | tool | The smallest useful mod: three fields and a log. Works on mod API 1. |
| [`folder-report`](examples/mods/folder-report) | tool | Everything the declarative form can do: sections, fields that appear only when they matter, a slider, a multi-choice list, a date, an extra button, and results as counters, a table and a file list. |
| [`solarized-theme`](examples/mods/solarized-theme) | theme | A complete colour theme in one file. |

For example: add **Count Files**, turn it on (the install prompt has a checkbox for it, or
`toolbox mods enable count-files`), open it in the sidebar under *Files*, or run
`toolbox count-files --folder D:\Videos`. For the theme, add it, turn it on, then pick it under
**Settings → Appearance**.

Mods you add yourself start **off** unless you tick *Turn on after installing*. Nothing from a
mod runs until it is on, and `main.py` is only imported when you actually run the mod. Start
Toolbox with `--no-mods` (or set `TOOLBOX_NO_MODS=1`), or press **Safe mode** in Settings → Mods,
to load none of them, for example if one misbehaves.

## Installing, updating and removing

Everything below shows a **trust prompt** first (what the mod is, who wrote it, where it comes
from, the exact commit, which menu section it appears in, what it declares it needs, and every
file) and installs nothing until you say yes. The mod is downloaded and checked, but not run.

| From | In the app (Settings → Mods → Add a mod) | Command line |
| --- | --- | --- |
| A git address | paste `https://github.com/name/my-mod`, optionally a tag, branch or commit | `toolbox mods install https://github.com/name/my-mod --ref v1.2` |
| A folder | *Choose folder* | `toolbox mods install D:\mods\my-mod` |
| A `.zip` | *Choose file* | `toolbox mods install my-mod.zip` |
| A single `.py` file | *Choose file* | `toolbox mods install my-mod.py` |
| A single `.toml` file (themes only) | *Choose file* | `toolbox mods install my-theme.toml` |
| The market | Settings → Mods → **Browse** | `toolbox mods search subtitles` |

- **Git installs are pinned.** The ref you give (or the default branch) is turned into a full
  commit hash first, and exactly that commit is downloaded and recorded. GitHub repositories are
  fetched as an archive, so you do not need `git`; other `https://` hosts need `git` installed.
  A repository can hold several mods: point at one with a folder (`--subdir mods/my-mod`, or a
  `https://github.com/name/repo/tree/<ref>/<folder>` address).
- **Updates are never automatic.** *Check for updates* (or `toolbox mods update`) compares the
  recorded commit with the current one. To apply an update you review the changed files, and
  approve, the same way as an install. Whether the mod is on or off stays as it was.
- **Remove** deletes the mod's folder and forgets that it was enabled (`toolbox mods remove <id>`).
- **View code** in the mods list shows every file of an installed mod.
- A **single `.py` file** has no `mod.toml`, so the manifest goes in a comment block at the top:

  ```python
  # /// toolbox-mod
  # id = "hello"
  # name = "Hello"
  # [ui]
  # run_mode = "run"
  # ///
  def run(params, ctx):
      ctx.log("hello")
  ```

  The block holds the same TOML as `mod.toml`; the file is installed as `main.py`.
- A mod folder, zip or repository can have at most 500 files and 20 MB, and cannot contain
  symbolic links.

## Share your mod

Put it in a public git repository, then **list it in the [market](market/README.md)** by opening a
pull request that adds an entry to `market/index.json`. Anyone can then find it under
**Settings → Mods → Browse** or on the website, and install it pinned to the commit you listed.
The market can be filtered by *Tools* and *Themes*, shows the menu section of a tool and colour
swatches for a theme.

## `mod.toml`

```toml
id = "count-files"            # required: lowercase letters, digits, - and _
name = "Count Files"          # required: what the sidebar shows
description = "Count the files in a folder, grouped by extension."
version = "1.0.0"
author = "You"
api_version = 1               # the mod API this mod was written for (2 for the newer features below)
group = "Files"               # the menu section: Files, Media, Subtitles, Experimental or Other
order = 1000                  # position inside that section (lower = earlier)
icon = "puzzle"               # see the list of icons below
accent = "files"              # optional (API 2): tile colour, see "Presentation"
entry = "main.py"             # optional

[ui]
run_mode = "run"              # "run" = one Run button, "preview_apply" = Preview + Apply buttons
# For preview_apply: the bool param the two buttons set. Preview -> dry_run = true.
mode_param = "dry_run"        # default; use "apply" together with mode_inverted = true
mode_inverted = false         #   when the param means "really do it" (Preview -> apply = false)
apply_hint = ""               # extra sentence in the "Apply changes?" confirmation
layout = "sections"           # optional (API 2): "sections" or "tabs", see "Sections and tabs"

[run]
undo = false                  # true if the mod records an undo manifest (see below)
max_concurrent = 0            # limit parallel runs of this mod (0 = no limit)
cancel = "immediate"          # or "cooperative": the mod stops itself, the job ends when it does
loggers = []                  # extra logger names whose file handlers are closed after a run

[permissions]                 # advisory: shown in Settings → Mods, NOT enforced
network = false
writes_files = false
runs_programs = false
```

If you leave `[ui]` out, `run_mode` defaults to `preview_apply`, which needs a bool param named
`dry_run`. Mods that only read data should set `run_mode = "run"`.

Icons (`icon = "..."`, lucide names; an unknown name shows a puzzle piece):

```text
archive audio-lines bar-chart-3 calendar camera clipboard-list clock cloud code combine copy
cpu database disc-3 download eraser file file-audio file-image file-search file-text
file-video files film folder folder-pen folder-search gauge globe hard-drive hash history
image inbox languages layers link list-checks lock mail monitor music palette pen-line play
puzzle scissors search settings shield sliders-horizontal sparkles star table tag trash-2
upload video wand-sparkles wrench zap
```

### Mod API versions

`api_version` says which mod API the manifest was written for. Toolbox refuses a mod that needs a
newer API than it has, with a message that says so, so an old Toolbox never half-loads a new mod.

- **1**: tools with fields, `[run]`, `[permissions]`, undo.
- **2**: theme mods (`type = "theme"`), form sections and tabs, `show_if`, the `multichoice`,
  `color` and `date` fields and the slider, actions, `accent`, and `ctx.result(...)`. A manifest
  that uses any of these has to say `api_version = 2`. Mods written for 1 keep working unchanged.

## Categories

A tool appears in one **category**, a section of the sidebar and the home screen. The mod picks it
with `group`:

| `group` | What belongs there |
| --- | --- |
| `Files` | Tools that rename, move or organize files and folders. |
| `Media` | Tools that convert, cut, join or download video and audio. |
| `Subtitles` | Tools that translate or clean up subtitle files. |
| `Experimental` | Specialised or unfinished utilities for less common jobs. |
| `Other` | Anything that does not fit above. The default when a mod sets no group. |

- **Case and spacing do not matter.** `media`, `Media` and `" Media "` are the same section, shown
  as the existing `Media`. A mod without `group` goes to *Other*.
- **The built-in sections have a fixed place**, in the order above. A mod's `order` only places it
  *inside* its section; it can never move a section.
- **A new name creates a new section**, after the five above (new sections are sorted A to Z).
  Two mods that spell a new name differently (`my tools`, `My Tools`) share one section.
- **A name that only looks like an existing one is not merged**, but it is reported: `Subtitle`,
  `Sub-titles` or `Medias` become their own section, with a warning in Settings → Mods and in the
  install prompt saying which section you probably meant.
- The install prompt, **Settings → Mods** and the market list show where a tool will appear.

When in doubt use one of the five: a tool that fits a section next to the built-in ones is easier
to find than one in a section of its own.

## Parameters

Each `[[params]]` table becomes a form field, a `--flag` on the command line, and a validated
field in the API. There is no frontend code to write.

```toml
[[params]]
name = "top"                  # required: lowercase, digits, underscores. Key in `params`.
type = "integer"              # see the table below (default "text")
label = "Show the top N extensions"
help = "How many extensions to list."   # tooltip in the form, --help text on the CLI
default = 10                  # no default = the field is required
min = 1
max = 100
```

| `type` | Form field | Arrives in `run()` as |
|--------|------------|-----------------------|
| `text` | text box | `str` |
| `integer`, `number` | number box (`min`, `max`); a slider with `widget = "slider"` | `int`, `float` |
| `bool` | switch | `bool` |
| `choice` | dropdown from `choices` | `str` |
| `multichoice` | tick boxes from `choices` (API 2) | `list[str]` |
| `folder`, `file` | path box with a Browse button in the desktop app | `str` (path) |
| `files`, `list` | one entry per line | `list[str]` |
| `color` | colour picker, `"#rrggbb"` (API 2) | `str` |
| `date` | date picker, `"YYYY-MM-DD"` (API 2) | `str` |
| `json` | JSON text box | `dict` |

More fields: `placeholder`, `required` (defaults to "no default given"), `nullable = true`
(empty field becomes `None`), `ui = false` (accepted by the API and CLI but not shown in the
form), `width = "half"` (put two short fields side by side), and for `choice` and `multichoice`:

```toml
choices = ["low", "high"]                                  # or
choices = [{ value = "low", label = "Low quality" }, { value = "high", label = "High" }]
strict = false               # choice only: the dropdown only suggests values; any string is accepted
```

`initial` sets what the form starts with when that differs from the API `default`. A slider needs
`min` and `max`, and takes an optional `step`:

```toml
[[params]]
name = "min_size_mb"
type = "integer"
widget = "slider"
min = 0
max = 500
step = 10
default = 0
```

## Sections, tabs and conditional fields (API 2)

A long form can be grouped, and fields that only matter sometimes can stay out of the way. This is
all data in `mod.toml`: no code from the mod runs in the page.

```toml
api_version = 2

[ui]
layout = "sections"           # or "tabs": each section becomes a tab

[[sections]]
id = "advanced"               # required: lowercase letters, digits, - and _
title = "Advanced"            # defaults to the id
text = "These change **how** the report is made. See the [docs](https://example.org)."
show_if = { param = "show_advanced", truthy = true }   # optional: the whole section appears with it

[[params]]
name = "show_advanced"        # not in a section: shown above all sections
type = "bool"
default = false

[[params]]
name = "depth"
section = "advanced"          # which section the field sits in
type = "integer"
default = 2
show_if = { param = "mode", equals = "deep" }          # optional: only while `mode` is "deep"
```

- **Where fields go.** Fields without `section` come first; sections follow in the order they are
  written. With `layout = "tabs"` the fields without a section stay on top and every section is a
  tab.
- **`text`** is markdown-lite: paragraphs, `# headings`, `- lists`, `**bold**`, `*italic*`,
  `` `code` `` and `[links](https://...)`. It is never treated as HTML, and only `https` links
  work.
- **`show_if`** takes `param` (another field) and one of `equals`, `not_equals`, `in = [...]`,
  `truthy = true` or `truthy = false`. With only `param` it means "has a value". It works on
  fields and on whole sections.
- **A hidden field sends nothing**, so `run()` gets its default. That is why a field that can be
  hidden needs a `default` (or `nullable = true`). Toolbox checks this when it reads the manifest.
- `show_if` only steers the form. The command line and the API accept every field, so validate
  in `run()` what really matters.

## Actions (API 2)

An action is an extra button next to Run, for something quick that is not a full run: "Test
connection", "Check folder". It calls a named function in `main.py` and shows what it returns.

```toml
[[actions]]
name = "check_folder"         # calls action_check_folder(params, ctx)
label = "Check folder"
help = "Count the files quickly, without running the whole report."
params = ["folder", "recursive"]   # the fields it receives; leave out for all of them
```

```python
def action_check_folder(params, ctx):
    ...
    return "12 files found"           # text is shown as a message
    # or: return {"view": "message", "level": "error", "text": "Not a folder"}
    # or call ctx.result(...) as in a run; a list of results works too
```

Only actions declared in the manifest can be called, and only while the mod is on. The fields it
receives are validated like a run. An action that takes longer than two minutes is given up on
(Python cannot stop it, so keep actions short), and one that raises an error shows the message.

## Results (API 2)

Instead of putting everything in the log, a mod can show its findings with `ctx.result(...)`. The
page draws them under the form with its own components; the mod never sends HTML.

| Call | Shows |
| --- | --- |
| `ctx.result("table", title="By kind", columns=["Kind", "Files"], rows=[["Video", 12]])` | A table (up to 500 rows and 20 columns). Numbers are right-aligned. |
| `ctx.result("counters", items={"Files": 12, "Size": "3.4 GB"})` | Big-number tiles (up to 24). |
| `ctx.result("files", files=["D:/a.mkv", {"path": "D:/b.mkv", "label": "1.2 GB"}])` | A file list (up to 300) with **Open** and **Show** buttons. |
| `ctx.result("markdown", text="**Done.** See the log.")` | Markdown-lite text (see above). |
| `ctx.result("image", path="D:/preview.png")` | A picture: `.png`, `.jpg`, `.gif` or `.webp`, up to 3 MB. |
| `ctx.result("message", text="Connected.", level="success")` | A note; `level` is `info`, `success`, `warning` or `error`. |

All take an optional `title`. A run can show up to 20 results. The page only opens files a run
listed in a `files` result, and anything that could start a program (`.exe`, `.bat`, `.py`, ...) is
only shown in its folder, never opened. On the command line the results are printed as plain text.

## Presentation (API 2)

- `icon`: one of the icons listed above.
- `accent`: the colour of the tool's tile on the home screen. One of `files`, `media`,
  `subtitles`, `experimental`, `other`, `settings`, `primary`, `success`, `warning` or `danger`.
  These are colours of the active theme, so a tool cannot clash with the look. Without it the tile
  uses its section's colour.

## `main.py`

```python
def run(params, ctx):
    ctx.log(f"Looking in {params['folder']}")
    ...
```

`params` is a plain `dict` of the validated values. Raise an exception to fail the job; its
message is shown to the user. Return normally to finish.

### `ctx`

| | |
|---|---|
| `ctx.log(message, level=logging.INFO)` | Write a line to the job log. |
| `ctx.progress(0.5, "Halfway")` | Report progress: a fraction from 0.0 to 1.0, plus optional text. |
| `ctx.result(view, ...)` | Show a table, counters, files, markdown, an image or a message. See [Results](#results-api-2). |
| `ctx.cancelled()` | `True` once the user pressed cancel. Check it in loops. |
| `ctx.raise_if_cancelled()` | Stop and mark the job cancelled if the user cancelled. |
| `ctx.ffmpeg`, `ctx.ffprobe` | Paths to the tools (downloads them first if needed). |
| `ctx.run([...])` | Run a program from an argument **list** (never a shell string). Output goes to the log; cancelling stops it. Raises on a non-zero exit unless `check=False`. |
| `ctx.set_undo_manifest(data)` | See below. |
| `ctx.job_id`, `ctx.mod_id`, `ctx.cancel_event` | Identifiers and the raw cancel event. |

### Undo (optional)

Set `undo = true` under `[run]`, call `ctx.set_undo_manifest({...})` with whatever you need
to reverse the run (only when something changed), and export:

```python
def undo(manifest, ctx):
    ...
    return {"restored": 3, "failed": 0, "skipped": 0}
```

The log drawer then offers an Undo button for that job. The built-in Rename mod works this way.

### Advanced: your own validation

A mod without `[[params]]` may export a pydantic model named `Params`; it is used to validate
requests instead. Built-in mods with a custom panel do this (see `builtin_mods/rename`).

## Theme mods

A theme changes the look of Toolbox: the colour scheme (light and dark), the roundness of corners,
the font and the accent colour of each menu section. It is **one data file**, no code, so it is the
safest kind of mod.

```toml
id = "solarized"              # required: lowercase letters, digits, - and _
name = "Solarized"
description = "Warm cream in light mode, deep teal in dark mode."
version = "1.0.0"
author = "You"
type = "theme"                # this is what makes it a theme
api_version = 2               # required

[theme]
radius = "0.5rem"             # optional: 0 up to 2rem (or 32px)
font = "system"               # optional: system, serif, mono or rounded

[theme.light]                 # only the tokens you want to change; the rest use the default
background = "#fdf6e3"
foreground = "#073642"
primary = "#1f6f9f"

[theme.dark]
background = "#002b36"

[theme.groups]                # accent colour per menu section, for light and dark together
files = "#c42b78"             # files, media, subtitles, experimental, other, settings
```

The complete example is [`examples/mods/solarized-theme`](examples/mods/solarized-theme). A theme
folder has just `mod.toml`, and a theme can also be installed as that one `.toml` file.

### Tokens

Every colour is a token, and this is the whole list. Values are `#rrggbb`, `hsl(210, 40%, 50%)` or
`rgb(20, 40, 60)`. The defaults are what Toolbox looks like without a theme.

| Token | Light | Dark | What it colours |
| --- | --- | --- | --- |
| `background` | `#f5f4f0` | `#0f121a` | Page background. |
| `foreground` | `#1a1916` | `#f2f5f7` | Normal text. |
| `card` | `#ffffff` | `#151923` | Panels, the header and dialogs. |
| `card-foreground` | `#1a1916` | `#f2f5f7` | Text on panels. |
| `chrome` | `#fbfaf7` | `#12151f` | Sidebar, header, table heads and the log: one step apart from the page and the panels. |
| `primary` | `#2463eb` | `#3c83f6` | Main buttons and the selected menu item. |
| `primary-foreground` | `#f8fafc` | `#0e121b` | Text on primary. |
| `secondary` | `#efede8` | `#212530` | Secondary buttons. |
| `secondary-foreground` | `#1a1916` | `#e0e6eb` | Text on secondary. |
| `muted` | `#efede8` | `#212530` | Quiet backgrounds (chips, code, tabs). |
| `muted-foreground` | `#6b675e` | `#8491a4` | Quiet text: hints and descriptions. |
| `accent` | `#efede8` | `#262a36` | Hover background. |
| `accent-foreground` | `#1a1916` | `#f2f5f7` | Text on hover. |
| `border` | `#e6e3dc` | `#2b2f3b` | Lines and outlines. |
| `input` | `#e6e3dc` | `#2b2f3b` | Outline of text boxes. |
| `ring` | `#2463eb` | `#3c83f6` | Keyboard focus ring. |
| `destructive` | `#c53732` | `#c53732` | Buttons that delete or overwrite (Remove, Apply changes). Protected. |
| `destructive-foreground` | `#ffffff` | `#ffffff` | Text on destructive buttons. Protected. |
| `danger` | `#c53732` | `#c53732` | Errors and warnings about risk: fill, border and tint. Protected. |
| `danger-text` | `#c53732` | `#fb8276` | Error text and icons. Protected. |
| `warning` | `#975800` | `#975800` | Cautions: fill, border and tint. |
| `warning-text` | `#975800` | `#e6b55d` | Caution text and icons. Protected. |
| `success` | `#0b7744` | `#0b7744` | Good news: fill, border and tint. |
| `success-text` | `#0b7744` | `#6ac48c` | Good-news text and icons. |
| `overlay` | `#000000` | `#000000` | The dim layer behind dialogs. |
| `log-info` | `#6b675e` | `#8491a4` | Normal lines in the log panel. |
| `log-warn` | `#975800` | `#e6b55d` | Warning lines in the log panel. |
| `log-error` | `#c53732` | `#fb8276` | Error lines in the log panel. |
| `syntax-keyword` | `#6b33cc` | `#b48ef6` | Keywords in code previews (def, import, if) and log level tags. |
| `syntax-string` | `#117442` | `#69d390` | Strings in code, quoted text and URLs in logs. |
| `syntax-number` | `#b34d09` | `#f6a655` | Numbers and constants (true, null) in code and logs. |
| `syntax-comment` | `#666d7a` | `#8791a1` | Comments in code and timestamps in logs. |
| `syntax-function` | `#1d55cd` | `#77b1f8` | Function names in code and file paths in logs. |
| `syntax-type` | `#0a6c7b` | `#59cfcf` | Class names, types and built-ins; exception names in logs. |
| `syntax-property` | `#bf2256` | `#f28899` | Keys and attributes (TOML, JSON, YAML, HTML). |
| `syntax-meta` | `#97560c` | `#f0c74c` | Decorators, headings and section names ([table] in TOML). |
| `category-files` | `#2463eb` | `#3c83f6` | Accent of the Files section. |
| `category-media` | `#2463eb` | `#3c83f6` | Accent of the Media section. |
| `category-subtitles` | `#2463eb` | `#3c83f6` | Accent of the Subtitles section. |
| `category-experimental` | `#6b675e` | `#8491a4` | Accent of the Experimental section. |
| `category-other` | `#2463eb` | `#3c83f6` | Accent of the Other section and new categories. |
| `category-settings` | `#6b675e` | `#8491a4` | Accent of the Settings tiles. |
| `category-foreground` | `#ffffff` | `#0e121b` | Icon colour on the accent chips. |

`[theme.groups]` is shorthand: `files = "#..."` sets `category-files` for light and dark. If
`[theme.light]` or `[theme.dark]` names the token itself, that wins for its mode.

The `syntax-*` tokens colour code and log previews when **Settings → Appearance → Syntax
highlighting** is set to *From the theme* (the default). The other schemes there (GitHub, One,
High contrast) ignore them.

### What is checked

Toolbox reads a theme strictly, when it is installed and every time it starts:

- **Only known tokens and value shapes.** Anything else is refused with a message that says what
  to fix: an unknown token, a colour written as a name (`red`), with transparency, or as
  `var(...)`, `calc(...)` or `url(...)`, a radius that is not a short length, a font that is not
  one of the four. **There is no way to write CSS**: no `url()`, no `@import`, no selectors. A theme
  cannot load anything from the internet or draw over the interface.
- **A theme cannot hide a warning.** The text of errors and cautions and the text on the **Remove**
  and **Apply changes** buttons are *protected*: `foreground` on `background`, `card-foreground` on
  `card`, `destructive-foreground` on `destructive`, and `danger-text` and `warning-text` on both
  `background` and `card` must have a contrast of at least 4.5:1 (WCAG AA), in light and in dark.
  `destructive`, `danger` and `danger-text` must also stay red or orange, so a delete button never
  looks harmless. A theme that breaks one of these is refused.
- **Other low-contrast pairs are warnings**: quiet text, secondary buttons, the log colours and the
  icons on the section chips. The warnings show in the install prompt and under **Settings →
  Appearance**.
- Missing tokens fall back to the default, so an old theme keeps working when Toolbox gets new
  tokens.

### Using themes

- **Settings → Appearance** shows every theme that is on, with a preview in light and dark and its
  contrast warnings. **Use** switches at once; **Reset to default** goes back to the built-in
  *Default*. *Light*, *Dark* and *Follow system* are separate from the theme, and every theme
  covers both.
- **Copy as theme file** copies the current look as a theme file, a good starting point to edit.
- Toolbox ships two themes, made the same way: *Default* and *High contrast* (see
  [`builtin_mods/theme_high_contrast`](builtin_mods/theme_high_contrast)).
- Turning the active theme off, removing it, or starting in safe mode returns to the default.
- Install a theme like any mod (a git address, folder, zip, a single `.toml` file or the market).
  The trust prompt is shorter because there is no code: it shows a preview and the contrast checks.
  A theme folder that also contains `.py` files is flagged; nothing in it would ever run.
- `toolbox mods prompt --theme`, or **Settings → Mods → Copy AI theme prompt**, gives a prompt for
  an AI assistant to design a theme from a description (see below).

## What a mod can import

Mods run inside Toolbox's own Python, so they can use the **standard library** and the
packages Toolbox ships with (`yt_dlp`, `openai`, `httpx`, `pydantic`, `certifi`). To call an AI model, use `core.ai.get_provider()` so the user's chosen provider is used. There is no way to
install extra packages for a mod. If your mod has helper modules, put them next to `main.py`
and import them relatively: `from .helpers import tidy`.

In the installed (packaged) app only the parts of the standard library that Toolbox or the
list in `packaging/toolbox.spec` use are bundled. If a mod needs an unusual stdlib module and
fails with `ModuleNotFoundError`, that module needs adding to the list.

## Security

**A tool mod is code that runs with the same access as Toolbox.** It can read, change and delete
any file you can, use the network and start programs. Python cannot sandbox that, so:

- Only turn on mods from people you trust, and read the code first (or use the
  [review prompt](#ask-an-ai-assistant-to-review-a-mod) below).
- The `[permissions]` table is what the author says the mod does. It is shown to you, but it is
  not enforced.
- Installing shows the source, the exact commit, the author and the declared access before
  anything is copied, and installs nothing until you approve. Git installs are pinned to a commit.
- Mods start off (unless you tick the box when installing), are opt-in one at a time, and are
  never updated automatically: an update shows you what changed and waits for your approval.
- Safe mode (`--no-mods`, or the **Safe mode** button in Settings → Mods) runs the app without
  any user mods. A mod that crashes fails its own job with the error in the log; it does not
  take the app down.
- **Mods are third-party code. The project does not vet them**, and neither the market nor any
  other list says a mod is safe. AI-written mods can be wrong too.

**Themes and the declarative form are data, and are treated that way.**

- A theme has no code and cannot reach the network, your files or the API. It is validated down to
  colours, one length and a font choice, and the tokens behind warnings and the **Remove** button
  are protected (see [What is checked](#what-is-checked)).
- The form a mod describes (sections, `show_if`, widgets) and the results it reports are drawn by
  Toolbox's own components. Nothing a mod sends is treated as HTML, links must be `https`, and images
  are inline pictures of a known type with a size limit. **No code of a mod ever runs in the page.**
- Actions and the run itself are code in `main.py`, so they fall under the trust model above.
- A *listing* that says a mod is a theme cannot be delivered with a tool: if the downloaded code
  is a different kind than the listing, nothing is installed.
- Mod-supplied HTML or JavaScript panels (in a sandboxed frame) are **not** supported. They would
  be a separate security decision.

Built-in features cannot be turned off, and a user mod cannot take over a built-in id.

## Ask an AI assistant to write one

Paste this into any AI assistant and replace the last paragraph with what you want. Then check
the result (see Security above) before you install it. In the app, **Settings → Mods → Copy AI
prompt** copies exactly this text (and `toolbox mods prompt` prints it).

````text
You are helping me build a mod for Toolbox, a desktop app that converts, renames and
organizes media files with ffmpeg and yt-dlp. A mod adds one new tool to the app. Write the
complete mod for the feature I describe at the bottom.

## What to produce
A folder with exactly these files, each in its own code block labelled with its path:
1. `mod.toml`: the manifest
2. `main.py`: the code
3. `README.md`: 3-5 lines on what it does and how to use it

## mod.toml
- Top level: `id` (lowercase letters, digits, `-`, `_`; e.g. "strip-metadata"), `name`,
  `description`, `version = "1.0.0"`, `author`, `api_version = 2`, optional `group`
  and `icon` (one of these, default "puzzle"):
  archive audio-lines bar-chart-3 calendar camera clipboard-list clock cloud code
  combine copy cpu database disc-3 download eraser file file-audio file-image
  file-search file-text file-video files film folder folder-pen folder-search gauge
  globe hard-drive hash history image inbox languages layers link list-checks lock mail
  monitor music palette pen-line play puzzle scissors search settings shield
  sliders-horizontal sparkles star table tag trash-2 upload video wand-sparkles wrench
  zap
- `group` is the menu section the tool appears in. Use exactly one of these names, whichever
  fits best, spelled exactly like that. Do not invent a new one unless I ask for it:
  - Files: Tools that rename, move or organize files and folders.
  - Media: Tools that convert, cut, join or download video and audio.
  - Subtitles: Tools that translate or clean up subtitle files.
  - Experimental: Specialised or unfinished utilities for less common jobs.
  - Other: Anything that does not fit above. The default when a mod sets no group.
- `[ui]`: `run_mode = "run"` (one Run button) for tools that only read or create new files.
  For tools that change existing files use `run_mode = "preview_apply"` and declare a bool
  param `dry_run` with `default = true` (Preview sets it to true, Apply to false).
- `[permissions]` (advisory, shown to the user, be honest): `network`, `writes_files`,
  `runs_programs`, each true or false.
- One `[[params]]` table per input. Fields: `name` (lowercase, underscores), `type`, `label`,
  `help` (a short tooltip), `default` (omit it to make the field required), `placeholder`,
  `min`/`max` (numbers), `nullable = true` (empty means None), `width = "half"`.
  Types: `text`, `integer`, `number`, `bool`, `choice` (add `choices = ["a", "b"]`),
  `multichoice` (choices too; the default is a list), `folder`, `file`, `files` (list of
  paths, one per line), `list`, `json`, `color` ("#rrggbb"), `date` ("YYYY-MM-DD").
  `widget = "slider"` (with `min` and `max`) shows a number as a slider.
- Only when the form gets long, or some options only matter sometimes: group fields with
  `[[sections]]` tables (`id`, `title`, `text`) and `section = "<id>"` on a param, and show a
  param or a whole section only while another field has a value with
  `show_if = { param = "mode", equals = "advanced" }` (also `not_equals`, `in = [...]`,
  `truthy`). A param that can be hidden needs a `default`.

## main.py
It must define `run(params, ctx)`. `params` is a dict with the values declared above.
`ctx` provides:
- `ctx.log(message)`: write a line to the job log
- `ctx.result("table", title="...", columns=[...], rows=[[...], ...])`: show what you found
  after the run. Also `"counters"` (`items={"Files": 12}`), `"files"` (`files=[paths]`),
  `"markdown"` (`text="..."`), `"image"` (`path="..."`) and `"message"` (`text="..."`,
  `level="info"|"success"|"warning"|"error"`). Prefer this to dumping results in the log.
- `ctx.progress(fraction, text=None)`: 0.0 to 1.0
- `ctx.cancelled()` and `ctx.raise_if_cancelled()`: check these in loops so cancel works
- `ctx.ffmpeg` and `ctx.ffprobe`: paths to the tools
- `ctx.run([args...])`: run a program from an argument list (never a shell string); its
  output goes to the log and a non-zero exit raises an error

## Rules
- Python standard library only, plus `yt_dlp`, `openai`, `pydantic` if truly needed. No other
  packages, no pip installs.
- Never delete or overwrite the user's files. Write results to a new file or folder, or, if
  the feature has to change files, support `dry_run` (default true) that only logs what it
  would do.
- Use `pathlib`. Paths may contain spaces and non-ASCII characters, and the user may be on
  Windows, macOS or Linux.
- No network access unless the feature needs it (then declare `network = true`).
- Log what you do so the user can follow along. Report problems with
  `raise RuntimeError("clear message")`, not a bare traceback.
- Keep it simple and readable. No unrelated extras.

## How to answer
First, in 2-4 sentences, restate what you understood and list any assumptions. If something
important is unclear, ask me at most 3 short questions BEFORE writing code. Then give the
files. Finally, list 2-3 things I should test before trusting it.

## The feature I want
<DESCRIBE YOUR FEATURE HERE: what goes in, what should come out, and any examples. For
example: "For every video in a folder, cut the first 10 seconds and save the result next to
the original with '_trimmed' added to the name.">
````

## Ask an AI assistant to design a theme

The same idea for a look: describe it in plain words ("warm dark theme, rounded corners, green
accent") and paste the answer into a `.toml` file. Toolbox checks the theme when you add it, and
**Settings → Appearance** has a preview, so a wrong colour is easy to spot. **Settings → Mods → Copy
AI theme prompt** copies exactly this text (and `toolbox mods prompt --theme` prints it).

````text
You are helping me design a theme for Toolbox, a desktop app that converts, renames and
organizes media files. A theme is one small data file with no code in it: it changes the
colours, the roundness of corners and the font of the app. Write the complete theme for the
look I describe at the bottom.

## What to produce
One code block labelled `mod.toml`, and a short sentence or two about the look. Nothing else.

## mod.toml
- Top level: `id` (lowercase letters, digits, `-`, `_`; e.g. "warm-dark"), `name`, `description`,
  `version = "1.0.0"`, `author`, `type = "theme"` and `api_version = 2`.
- `[theme]`: optional `radius` (corner roundness, for example "0.5rem"; 0 up to 2rem or 32px)
  and `font` (one of: system, serif, mono, rounded).
- `[theme.light]` and `[theme.dark]`: colours for light and dark mode. Set only the tokens
  you want to change; every other token keeps the default. Do both modes, so it looks right
  whichever the person uses.
- `[theme.groups]`: optional accent colour per menu section, used in both modes. The names
  are files, media, subtitles, experimental, other and settings.
- Write every colour as "#rrggbb" (or hsl(...) / rgb(...)). No transparency.

## Rules
- Use only the tokens listed below and only the keys above. There is no other CSS: no
  `url()`, no `@import`, no selectors, no `calc()`, no variables. A theme that uses anything
  else is refused.
- Keep text readable: at least 4.5:1 contrast for `foreground` on `background`,
  `card-foreground` on `card`, `destructive-foreground` on `destructive`, and `danger-text` and
  `warning-text` on both `background` and `card`. A theme that breaks these is refused.
- `destructive`, `danger` and `danger-text` must stay red or orange (hue 335-360 or 0-45,
  clearly saturated), so a delete button and a warning always look like a warning.
- Tokens (with the default light and dark colour):
- background: Page background. (default light #f5f4f0, dark #0f121a)
- foreground: Normal text. (default light #1a1916, dark #f2f5f7)
- card: Panels, the header and dialogs. (default light #ffffff, dark #151923)
- card-foreground: Text on panels. (default light #1a1916, dark #f2f5f7)
- chrome: Sidebar, header, table heads and the log: one step apart from the page and the panels. (default light #fbfaf7, dark #12151f)
- primary: Main buttons and the selected menu item. (default light #2463eb, dark #3c83f6)
- primary-foreground: Text on primary. (default light #f8fafc, dark #0e121b)
- secondary: Secondary buttons. (default light #efede8, dark #212530)
- secondary-foreground: Text on secondary. (default light #1a1916, dark #e0e6eb)
- muted: Quiet backgrounds (chips, code, tabs). (default light #efede8, dark #212530)
- muted-foreground: Quiet text: hints and descriptions. (default light #6b675e, dark #8491a4)
- accent: Hover background. (default light #efede8, dark #262a36)
- accent-foreground: Text on hover. (default light #1a1916, dark #f2f5f7)
- border: Lines and outlines. (default light #e6e3dc, dark #2b2f3b)
- input: Outline of text boxes. (default light #e6e3dc, dark #2b2f3b)
- ring: Keyboard focus ring. (default light #2463eb, dark #3c83f6)
- destructive: Buttons that delete or overwrite (Remove, Apply changes). Protected. (default light #c53732, dark #c53732)
- destructive-foreground: Text on destructive buttons. Protected. (default light #ffffff, dark #ffffff)
- danger: Errors and warnings about risk: fill, border and tint. Protected. (default light #c53732, dark #c53732)
- danger-text: Error text and icons. Protected. (default light #c53732, dark #fb8276)
- warning: Cautions: fill, border and tint. (default light #975800, dark #975800)
- warning-text: Caution text and icons. Protected. (default light #975800, dark #e6b55d)
- success: Good news: fill, border and tint. (default light #0b7744, dark #0b7744)
- success-text: Good-news text and icons. (default light #0b7744, dark #6ac48c)
- overlay: The dim layer behind dialogs. (default light #000000, dark #000000)
- log-info: Normal lines in the log panel. (default light #6b675e, dark #8491a4)
- log-warn: Warning lines in the log panel. (default light #975800, dark #e6b55d)
- log-error: Error lines in the log panel. (default light #c53732, dark #fb8276)
- syntax-keyword: Keywords in code previews (def, import, if) and log level tags. (default light #6b33cc, dark #b48ef6)
- syntax-string: Strings in code, quoted text and URLs in logs. (default light #117442, dark #69d390)
- syntax-number: Numbers and constants (true, null) in code and logs. (default light #b34d09, dark #f6a655)
- syntax-comment: Comments in code and timestamps in logs. (default light #666d7a, dark #8791a1)
- syntax-function: Function names in code and file paths in logs. (default light #1d55cd, dark #77b1f8)
- syntax-type: Class names, types and built-ins; exception names in logs. (default light #0a6c7b, dark #59cfcf)
- syntax-property: Keys and attributes (TOML, JSON, YAML, HTML). (default light #bf2256, dark #f28899)
- syntax-meta: Decorators, headings and section names ([table] in TOML). (default light #97560c, dark #f0c74c)
- category-files: Accent of the Files section. (default light #2463eb, dark #3c83f6)
- category-media: Accent of the Media section. (default light #2463eb, dark #3c83f6)
- category-subtitles: Accent of the Subtitles section. (default light #2463eb, dark #3c83f6)
- category-experimental: Accent of the Experimental section. (default light #6b675e, dark #8491a4)
- category-other: Accent of the Other section and new categories. (default light #2463eb, dark #3c83f6)
- category-settings: Accent of the Settings tiles. (default light #6b675e, dark #8491a4)
- category-foreground: Icon colour on the accent chips. (default light #ffffff, dark #0e121b)

## How to answer
First, in 1-2 sentences, describe the look you are making and any assumptions. Then give the
file. Finally, remind me that Settings, then Appearance, has a preview and a contrast check
before I keep it.

## The look I want
<DESCRIBE THE LOOK HERE: for example "a warm dark theme with rounded corners and a green
accent" or "a calm light theme in blue-grey, square corners".>
````

## Ask an AI assistant to review a mod

Before you install a mod someone else wrote, paste this into an AI assistant together with the
mod's files. It explains in plain language what the code does, which files and programs it
touches, and whether that matches what the mod declares. It cannot run the code, so treat the
answer as a second opinion, not a guarantee. In the app, the install prompt has a
**Copy review prompt with the code** button (and `toolbox mods prompt --review` prints this text).

````text
You are a careful, plain-spoken code reviewer. I am thinking about installing a mod for
Toolbox, a desktop app that converts, renames and organizes media files. A mod is code that
runs on my computer with the same access as the app: it can read, change and delete my files,
use the network and start programs. Below are the mod's manifest and code. I am not a
programmer, so explain in plain language.

## What I want from you
1. **What it does**: 2-4 sentences, based on the code and not only on its description.
2. **Files**: every file or folder it reads, creates, changes, moves or deletes, and when.
3. **Programs and network**: every program it starts and every web address it contacts.
4. **Anything suspicious**: code unrelated to what it claims to do; code that downloads and
   runs other code (exec, eval, pip, curl, PowerShell, base64 blobs); anything that reads
   passwords, API keys, browser data, SSH keys or environment variables; obfuscated or
   deliberately hard-to-read code; deleting or overwriting my files without a preview.
5. **Does it match its manifest?** Compare what it really does with the `[permissions]`
   it declares (network, writes_files, runs_programs) and say where they disagree.
6. **Verdict**: "looks consistent with what it says" or "has concerns", with the 2-3 most
   important reasons.

Be honest about what you cannot tell. You cannot run the code and you may have missed
something, so say so rather than guessing, and do not call anything "safe".

## The mod
<PASTE mod.toml AND main.py HERE, plus any other .py files in the mod folder.>
````
