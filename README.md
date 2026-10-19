# Hygger Presence

Discord Rich Presence for visual novels on Windows. The application watches
which game is running, publishes a Discord card with the game, developer,
session time and total playtime, and records playtime per game.

Current release: **2.1.1** — screenshot gallery with global hotkey, black bar
trimming and clipboard copy.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer (only when running from source)
- Discord desktop client running

## Install and run

Download `HyggerPresence.exe` from the releases page and run it.

Your data lives in `%APPDATA%\HyggerPresence` (`games.json`, `config.json`,
`stats.db`, `presence_debug.log`). Nothing is written next to the executable, so
replacing the exe keeps the library, the settings and the playtime. Data next to
an older build is copied into that folder on first start.

From source:

```bash
git clone https://github.com/hyther1111/HyggerPresence.git
cd HyggerPresence/HyggerPresence_2.1.0
pip install -r requirements.txt
python main.py
```

## Build the executable

```bat
build.bat
```

The script picks a Python 3 installation that has the dependencies, installs
PyInstaller if necessary and writes `dist\HyggerPresence.exe` (single file,
no console). Data files are never bundled; the executable creates them next to
itself, so replacing the executable keeps the library and playtime.

## Features

### Library
- One row per game with title, total playtime and executable.
- Search over title, romanised title, developer and executable.
- Titles can be shown in their original script or romanised
  (Settings → General → Library title).
- Actions: Start (directly or through a launcher), Edit, Add game, Remove,
  View on VNDB, Refresh list, Change cover.
- Cover images from VNDB, several candidates per visual novel.

### Detection
- Matching order: executable path, same name and folder, configured process
  names, any other executable in the game folder.
- Foreground tracking through the process tree, so launchers and engine
  handovers are treated as one game.
- Statuses: Reading (game focused), Paused (game running, another window
  focused), Idle (no input for 60 seconds).
- A game that restarts its own process keeps the session; closing it resets the
  session.

### Discord presence
- Three independent templates (Reading / Paused / Idle), each with a title line
  and two optional extra lines.
- Large image from VNDB or a custom asset key / URL, with hover text; optional
  small image.
- Optional elapsed timer and a single optional button.
- Presence can be disabled globally from the Detection page or the tray icon;
  playtime continues to be recorded.

### Statistics
- Playtime stored in SQLite.
- Ranges: 7 / 30 / 90 days, this and last week, this and last month, this and
  last year, all time, or a custom range chosen in a calendar.
- Per-visual-novel cards, a bar chart, and a session log per visual novel.
- Delete individual sessions, delete a range for one visual novel, export CSV.
- Idle time is excluded, so session time, total time and statistics agree.

### Other
- Tray icon with Open, Presence on/off and Quit; closing can minimise to the
  tray.
- Start with Windows.
- Launchers: Locale Emulator profiles (read from `LEConfig.xml`), GalFC, or a
  custom command; all appear in the Start menu.
- Import of 1.x data (Settings → General → Import 1.x data).
- Self-updater using GitHub releases; the executable is replaced in place and
  the data files are kept.
- Languages: English, Traditional Chinese, Simplified Chinese (instant switch).
- Debug mode writes `presence_debug.log` with the foreground window, the
  matched processes and the reason a status was chosen.

## Screenshots

Settings -> Screenshots:

| Field | Meaning |
|---|---|
| Screenshot folder | Where the gallery lives. Defaults to `Pictures\HyggerPresence`; move it to another drive if you like. |
| Hotkey | Global shortcut that captures the active window. Click the field, press the combination, press Escape to clear it. Unbound by default. |
| Sound | Shutter sound played after each capture. Any WAV or MCI supported file (mp3, wma, m4a, flac, ogg); empty uses the Windows sound. |
| Capture area | `Auto` (default) captures the whole screen while an upscaler such as Magpie is in front, and only the game window otherwise. `Game window` and `Whole screen` force one behaviour. |
| Trim black bars left and right | Removes the solid black borders an upscaler adds when the game keeps its aspect ratio (Magpie, 4:3 games on a 16:9 screen). On by default. |
| Copy the screenshot to the clipboard | Puts the capture on the clipboard so it can be pasted into Discord or an editor. Off by default. |

Each capture is stored as

```
<Pictures>\HyggerPresence\<game title>\2026-10-19-21-03-11.png
<Pictures>\HyggerPresence\<game title>\2026-10-19-21-03-11_2.png   same second
```

The folder name is the title in its original script, so different games never mix.
A capture only happens when the detected game owns the foreground window, and the
title bar is never included.

The **Screenshots** page lists one card per game with its cover, its title and how
many screenshots it holds. Double click a card to open the game, double click a
screenshot to view it full size; `Esc` goes one level up. `Ctrl+A` selects all,
`Ctrl+C` copies, `Delete` removes (confirmation above one file), and the right
click menu offers Copy / Open / Show in folder / Delete.

## Templates

Every line of a presence template accepts these placeholders:

| Placeholder | Value |
|---|---|
| `{title}` | Game title (original script) |
| `{romanized_title}` | Romanised title |
| `{developer}` | Developer |
| `{year}` | Release year |
| `{status}` | Reading, Paused or Idle |
| `{session_time}` | Session time, using the session time format |
| `{total_time}` | Total playtime, using the total time format |
| `{rating_average}` | VNDB average rating |
| `{rating_weighted}` | VNDB weighted rating |
| `{vndb}` | VNDB id (used in the button URL) |

The same list is shown in the application under
Settings → Presence → Variables.

## Time format

Session time and total time each have a format string in
Settings → Presence → Advanced. The default is:

```
{h?}{h}h {mm}m {ss}s{/h}{!h}{m?}{m}m {ss}s{/!h}
```

With one hour or more this renders `3h 15m 02s`; below one hour it renders
`15m 02s`.

Tokens:

| Token | Output | Example |
|---|---|---|
| `{h}` | hours, no leading zero | `3` |
| `{hh}` | hours, zero padded | `03` |
| `{m}` / `{mm}` | minutes, no zero / padded | `7` / `07` |
| `{s}` / `{ss}` | seconds, no zero / padded | `5` / `05` |
| `{h:}` | hour followed by a colon, empty when zero | `3:`, `` |
| `{mm}:{ss}` | minutes:seconds | `15:02` |

Conditional sections are only rendered when their test passes:

- `{h?}…{/h}` when hours > 0, `{!h}…{/!h}` when hours == 0
- the same for `{m?}`, `{!m}`, `{s?}`, `{!s}`

Examples:

| Format | 1 h 23 m 04 s | 23 m 04 s |
|---|---|---|
| `{h}h {mm}m {ss}s` | `1h 23m 04s` | `0h 23m 04s` |
| `{h:}{mm}:{ss}` | `1:23:04` | `00:23:04` |
| `{h?}{h:}{/h}{mm}:{ss}` | `1:23:04` | `00:23:04` |
| `{h?}{h}h {m}m{/h}{!h}{m}m {ss}s{/!h}` | `1h 23m` | `23m 04s` |

## Project layout

```
HyggerPresence_2.0.0/
  main.py            entry point (QApplication, tray)
  hp2/
    core.py          constants, time formatting, debug log
    winapi.py        Win32 helpers: foreground window, idle time, process
                     snapshot, parent map, process-exit waiter
    detector.py      process matching and focus resolution
    vndb.py          VNDB API
    store.py         games.json / config.json, 1.x import
    stats.py         SQLite playtime store
    engine.py        detection tick, Discord RPC, session clock, statistics
    ui.py            window, pages, dialogs, theming
    winframe.py      native Windows frame for the frameless window
    i18n.py          translations and live language switching
    locales/         en.json, zh_TW.json, zh_CN.json
  requirements.txt
```

## Translating

Translations are JSON files in `hp2/locales/`. Keys are the English source
strings; change only the values, then press
Settings → General → Reload translations. To add a language, copy `en.json`,
translate it and add the code and display name to `LANGUAGES` in
`hp2/i18n.py`.

## Platform support

Windows only. The application uses Win32 APIs for process enumeration, the
foreground window and the native window frame (`winapi.py`, `winframe.py`).
Running it on Linux or macOS would require replacing those modules.

## Troubleshooting

| Problem | Cause / fix |
|---|---|
| The Discord card does not appear | Discord must be running. Verify the Application ID in Settings → General. |
| The card stops updating | Discord allows five presence updates per 20 seconds. Rapid window switching is debounced, but once the limit is reached it takes about 20 seconds to recover. |
| A game is not detected | Pin it on the Detection page, or add its executable name under Process names in the game editor. |
| Library total differs from statistics | The library total is stored in `games.json`, statistics in `stats.db`. Import the 1.x data once after upgrading. |
| CPU usage is noticeable | Disable debug mode; it writes a log line for every status change. |

## Licence

MIT. See `LICENSE`.
