# Changelog

## 2.1.1 - 2026-10-19

### Added
- **Capture area: auto, game window or whole screen.** In the default `Auto`
  mode the app looks at the foreground window: while an upscaler is showing the
  game, the whole composited desktop is captured at native resolution; the rest
  of the time only the game's client area is taken. An upscaler is recognised
  either by its process name (Magpie, Lossless Scaling) or by geometry - a
  window that belongs to another process and covers the screen while the game
  window itself does not. Nothing is hidden for the grab, because an upscaler
  being in front means this window is not.
- **Trim black bars.** Captures drop uniform black borders (left/right or
  top/bottom), which is what upscalers add when the game keeps its original
  aspect ratio. On by default; a dark scene is left untouched because both sides
  have to be solid black before anything is cropped.
- **Copy to clipboard.** A switch in Settings -> Screenshots puts every capture
  on the clipboard, ready to paste into Discord or an image editor. Off by
  default.

### Fixed
- The self updater no longer passes the PyInstaller `_MEIPASS2` environment to
  the relaunched executable. That variable pointed at the temporary folder the
  old process deletes on exit, so an updated build could fail with
  "Failed to load Python DLL ... python311.dll". The update itself always
  succeeded; only the automatic restart was affected.
- Gallery refreshes and clipboard copies now happen on the GUI thread via a
  signal instead of `QTimer.singleShot` from a worker thread, which never fired.

## 2.1.0 - 2026-10-19

### Screenshots (new)
- New page between Statistics and Settings. Cards behave like folders: one card
  per game with its cover, title and screenshot count, double click to open the
  game, double click a screenshot to view it full size in the same page.
- Search by title, romanised title, developer, year or executable, exactly like
  the library. `Esc` goes one level up, `Ctrl+A` selects everything, `Ctrl+C`
  copies the selection and `Delete` removes it.
- Right click menu: Copy, Open, Show in folder (single selection) and Delete.
  Deleting more than one file asks for confirmation.
- Window capture only, title bar excluded. A capture is refused unless the game
  owns the foreground window, so switching windows cannot produce stray images.
- Global hotkey, unbound by default; click the field, press the combination, or
  press Escape to clear it. A shutter sound plays after each capture and can be
  replaced with any WAV or MCI supported file.
- Files are stored in `Pictures\\HyggerPresence\\<game title>\\yyyy-mm-dd-hh-mm-ss.png`
  (`_2`, `_3` when two shots land in the same second). The folder can be moved in
  Settings -> Screenshots.
- Thumbnails are decoded at display size and cached in
  `%LOCALAPPDATA%\\HyggerPresence\\thumbs`, so large folders open instantly and
  fill in as you watch.

### Fixed
- Saving the settings no longer drops keys the page does not own: `client_id`,
  `launchers`, `presence_opts`, `last_le_path` and `ui` survive every save.
- The Discord card no longer disappears every ~30 seconds. The presence watchdog
  used to close a healthy connection and reconnect; it now only republishes.
- Status changes reach Discord in about a second again (150 ms debounce, token
  bucket instead of a flat 4.2 s gate, so 5 updates per 20 s is still respected).
- Two pushes in the same second are skipped, which previously made Discord redraw
  the card twice and look like a disconnect.
- Captures are refused unless the game is in the foreground, and no window is
  hidden while capturing, so stray screenshots are gone.
- Session bookkeeping is keyed by the game instead of the raw executable string.
- PNG encoding dropped from ~270 ms to ~30 ms per 1080p frame; the gallery is
  rebuilt once after a burst of captures instead of after every shot.
- A data file that cannot be read is quarantined instead of being replaced, and
  a library is never overwritten by an empty list.

### Changed
- User data (games.json, config.json, stats.db, presence_debug.log) moved to
  `%APPDATA%\\HyggerPresence`. Existing files next to the executable are copied
  there on first start.
- The screenshot hotkey replaces the old behaviour of capturing whatever window
  had focus.

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
