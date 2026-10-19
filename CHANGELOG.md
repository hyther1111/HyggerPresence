# Changelog

## 2.0.0 — 2026-10-19

The interface was rewritten in Qt (PySide6). Detection, the Discord connection
and the playtime database were carried over from 1.0.3 and then revised.

### New interface
- Frameless window with a native frame underneath: Aero Snap (drag to the top to
  maximise, drag to a side to snap, double-click the title bar), native resize
  borders and the system maximise/restore animation.
- Dark and light theme, both fully styled by the application.
- Sidebar navigation: Library, Detection, Statistics, Settings.
- Settings split into General / Presence / Launchers / Updates; the Presence
  tab has Reading, Paused, Idle, Advanced and a Variables reference.

### Library
- Search across title, romanised title, developer and executable.
- Display the title in its original script or romanised.
- Start (directly or through a launcher), Edit, Add game, Remove, View on VNDB,
  Refresh list, Change cover, Clear presence.

### Detection
- Same matching rules as 1.0.3: executable path, then name + folder, then
  configured process names, then other executables in the game folder.
- Foreground tracking through the process tree, so a launcher handing over to
  the engine executable stays one session.
- A game that blinks (its process restarts) keeps its session; closing it resets
  the session.

### Discord Rich Presence
- Separate templates for Reading / Paused / Idle, with two optional extra lines
  and a placeholder reference page.
- Cover image from VNDB or a custom asset key / URL, hover texts, optional
  elapsed timer, optional single button with configurable label and URL.
- Status changes are debounced by 0.5 s so switching windows cannot exhaust
  Discord's limit of five updates per 20 seconds.
- Discord calls run synchronously on the RPC thread (1.0.3 behaviour). A failed
  call retries after 3 seconds instead of leaving a broken socket behind, which
  previously required restarting the application.

### Statistics
- Quick ranges (7 / 30 / 90 days, this and last week, month, year, all time) and
  a custom range.
- Per-VN cards, bar chart and a session log per VN; CSV export.
- Idle time is excluded, so session time, total time and statistics agree.

### Other
- English, Traditional Chinese and Simplified Chinese. One JSON file per
  language; switching is immediate and edited files can be reloaded from the
  Settings page.
- Launchers: Locale Emulator profiles, GalFC and custom commands.
- Tray icon, start with Windows, import of 1.x data files, self-updater.

## 1.0.3 — 2026-10-17

- Added library search, including romanised titles.
- Detect processes spawned by the selected executable.
- Rebuilt the update loop: CPU usage dropped to roughly 0–0.1 % (previously
  about 100× higher on the author's machine).
- Status update latency reduced from about 60 ms to 1–2 ms.
- Added a debug mode that writes `presence_debug.log` (foreground window,
  matched processes, status decisions).
- Minor fixes.

## 1.0.2 — 2026-10-14

- Internal maintenance and bug fixes.

## 1.0.1 — 2026-10-06

- Internal maintenance and bug fixes.

## 1.0.0 — 2026-10-05

First release.

- Discord Rich Presence for visual novels.
- Separate presence templates for Reading, Paused and Idle, each with a title
  line and two optional extra lines.
- Library of games with per-game total playtime stored in `games.json`.
- Executable detection: game path, executable name, and additional process
  names per game.
- Automatic detection of a running game, plus foreground-window tracking so the
  status changes between Reading and Paused.
- Idle detection (no input for a while) with its own status.
- VNDB integration: look up a visual novel by link or id, fetch developer, year,
  ratings, cover image and romanised title.
- Launchers: Locale Emulator profiles read from `LEConfig.xml`, GalFC, or a
  custom command; a game can be started through them from the library.
- Dark and light theme.
- System tray icon and minimise-to-tray.
- Start with Windows.
- Discord presence options: cover image, large/small image hover texts, elapsed
  timer and one optional button.
- Configurable time formats for session and total time.
- Import and export of the data files.
- Self-updater that checks GitHub releases and replaces the executable in place.
