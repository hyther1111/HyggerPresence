# Changelog

## 2.2.2 - 2026-10-23

**In short:** the play time in the Library counts up every second again instead of
every few seconds, the Chinese UI no longer shows English column titles, the
statistics chart keeps every game visible on long ranges, and the window is
slightly smaller.

### Changed
- The window opens at **1120×780** (minimum 940×640) instead of 1200×880, so it
  fits next to a game on a 1080p screen without covering half of it.

### Fixed
- The **Library** and **Launcher** tables stayed English in the Chinese UI: the
  column captions (*Title*, *Total time*, *Executable*, *Launcher*) were built
  without the translation helper. They now follow the selected language.
- The two message boxes of **Settings → Updates** (“this release has no .exe
  asset”, “this build runs from source”) were English only; both are translated
  now, including their window titles.
- **CPU while reading.** The live play time of the Library row rebuilt the whole
  table once per second — every row got new items and the list repainted from
  scratch — and every theme change added another one-second timer doing the same
  work, so the cost grew with each press of the light/dark button. The timer is
  created once now, and a tick rewrites only the one cell whose number changed
  (0.44 ms → 0.013 ms per tick here, and no full repaint).
- **CPU while idle.** That same timer also ran whenever the Library was on screen,
  even with no game running, so an idle window woke the process once a second for
  nothing. It now starts and stops with the game.
- **Statistics chart, wide ranges.** Past 60 days the chart switched to one
  `Total` bar per month, which threw away the per-game split. It still groups per
  month, but each bar keeps the games stacked (same colours and legend as the daily
  view); the `Total` pseudo-entry is gone. The switch-over point moved from 62 to
  60 days.
- **Live play time updated late.** The one-second refresh of the Library row was
  restarted by the main tick every second, so its deadline never came due — the
  number only moved when a tick happened to be late, which looked like a 2-3 s
  update. It is now refreshed on the same clock as the engine tick, so it steps
  once per second.

## 2.2.1 - 2026-10-23

**In short:** every game can carry a list of routes whose times you type in by
hand, the screenshot page gained a Refresh button and a second hotkey for the whole
screen, “Open in folder” was added to the library, the Chinese UI is translated
everywhere, and a statistics card keeps its selection after a double click.

### Added
- **Routes.** A game can keep a list of routes (chapters, character routes,
  endings) with the time spent in each. The times are **typed by hand**: the
  Detection page has its own **Routes** card that works like a small list editor —
  press **+**, type the name and the time, press the red bin to drop a route — and
  Library → Edit → **Routes** shows the same list. A route is just a name plus
  hours/minutes/seconds. Nothing is guessed from the game, no route time is taken
  from the session clock, nothing is sent to Discord and statistics are
  unaffected.
- **Open in folder** in the Library toolbar and in a game's right-click menu,
  which selects the game's executable in Explorer. In the toolbar it sits between
  **Change cover…** and the empty space before **Clear presence**.
- **Refresh** button on the Screenshots page, left of **Open folder**, so a folder
  that changed while the window was in the tray can be re-read on demand. It is a
  small drawn circular arrow next to the search field, in the text colour of the
  current theme.
- **Full screen capture.** Settings → Screenshots has a second hotkey,
  **Capture the whole screen**, unbound by default. Use it for games that another
  program upscales (Magpie and friends): those draw outside the game's own window,
  so a window grab would come out wrong. Both hotkeys are polled, so neither is
  registered with Windows and neither steals a key from another program.
- **Delete whole range** on the right click menu of a Statistics card, next to
  **Sessions…**: it removes that one visual novel's sessions inside the range on
  screen, after the same confirmation the Sessions dialog asks.

### Fixed
- Binding the screen hotkey also replaced the window hotkey (both dialogs wrote
  the same config key), so pressing the new key kept taking a **window** shot.
  Each **Set…** now writes its own field, and binding a combo that is already
  used by the other capture clears that one instead of leaving two meanings on
  one key.
- The **PER DAY** / **PER MONTH** caption of the Statistics chart and the
  **ROUTES** caption of the Detection card stayed English in the Chinese UI: they
  were built without the translation helper (and the chart caption was re-set on
  every redraw). Both now follow the selected language, like the other captions.
- The **Sessions** and **All sessions** dialogs stayed English: the window title,
  the line above the table and the `Date` / `Visual novel` / `Length` / `Started`
  columns are translated now, so the whole dialog follows the selected language.
- **The selection ring on a Statistics card disappeared** as soon as a card was
  double clicked to open its sessions: the second press of the double click
  toggled the selection off. A card now stays selected until another card is
  clicked.
- The Statistics card drew a **second, asymmetric ring** of its own on top of the
  stylesheet border (thicker on the right and bottom, with a tinted background),
  which is why it never looked like the selected card in the Screenshots gallery.
  Statistics cards now use exactly the same rule as the screenshot cards: a 2 px
  accent border and nothing else, in both themes.
- Screenshots: after **Back** from a folder the selection could not be made again
  until another folder was clicked — the page remembered what it had painted for
  the old cards, so re-selecting the same key looked like "nothing changed". A
  rebuilt gallery now resets that memory, and changing view drops the selection.
- **Set… for the screenshot hotkey did nothing** in the previous build: the
  dialog was created without a usable parent window, so clicking the button never
  opened anything. The dialog now centres on the window that asked for it and the
  open/close is written to the debug log.
- The Screenshots page could keep showing an outdated gallery after a capture
  taken while the page was hidden: the deferred refresh cleared its dirty flag
  without rebuilding the page, so the new game folder only appeared after
  switching pages or restarting.

### Changed
- Every page that can overflow — Detection, Statistics, Settings, Screenshots —
  scrolls, so no card or button is cut off on a small screen or a
  maximised-at-720p laptop.
- The window now always opens at a fixed **1200×880** (shrunk only when the
  display is smaller than that) instead of a percentage of the screen. The minimum
  size is 1000×700.
- **Statistics** scrolls as one page — the header, the range picker, the totals,
  the per-day chart and the cover cards move together instead of only the cards
  scrolling. The cover cards **wrap into as many rows as they need** instead of
  running off sideways behind a horizontal scrollbar.
- **Library** follows the play time live, like the other pages: the row of the
  game in progress counts up once a second, and the list is only rebuilt when a
  visible number actually changed.
- **Refresh list** moved out of the toolbar into a small flat icon (a drawn
  circular arrow, in the text colour of the current theme) on the right of the
  search field, freeing a button in a row that was getting crowded.
- Route rows are drawn like the rest of the app: a **+** and a red bin drawn from
  the palette (the native grey buttons stood out in both themes), and the row
  itself is transparent so the card shows through with no darker band between the
  fields.
- The Detection card has breathing room under its buttons instead of sitting
  flush on the card border.
- The screenshot hotkey is no longer registered with Windows. It is polled only
  while a tracked game is running, so it no longer swallows that key in every
  other program and it takes effect the moment it is changed. The field in
  Settings → Screenshots is read-only; **Set…** opens a small dialog that always
  starts empty and shows the combination as you press it. **Escape sets no
  hotkey** (the old combination is dropped), Cancel keeps the old one, and the
  dialog warns when the combination has no Ctrl, Alt or Shift.
- Library toolbar order: Add game… comes before Edit…. Edit… is disabled when no
  row is selected.

## 2.2.0 - 2026-10-22

**In short:** the app is now almost idle when nothing is running (about 5 % → about
1 % of one core here) and a game that starts is noticed in a fraction of a second
instead of up to three seconds. The Discord card also stopped disappearing at
random.

### Changed
- **Idle CPU is now a fraction of what it was.** The app used to wake up about
  eight times a second even with no game running: a 1 second detection tick, a
  250 ms clock redraw, a 300 ms cover decoder, a 5 second Discord keepalive check
  and a 6 second rebuild of the running-game dropdown. Detection is now event
  driven:
  - A window-show hook was added next to the existing foreground hook, so a game
    that starts (focused or not) triggers a scan within ~120 ms.
  - The 1 second tick only does real work while a game is tracked. When idle a
    single probe still runs every second — the cadence 2.1.2 already had, so
    detection is never slower than before — but it costs 0.11 ms instead of
    28 ms, and a window that appears fires the hook for an immediate scan.
  - The clock redraw is 1 second instead of 250 ms; it counts whole seconds, so
    three of those four redraws never changed a pixel.
  - The cover decoder stops as soon as there is nothing left to decode (and a
    cover that failed to download no longer keeps it polling forever).
  - The Discord keepalive check runs every 20 seconds instead of 5.
- **The running-game scan is 180x cheaper.** `running_games()` used to walk
  `psutil.process_iter()` once per library entry and resolve `process.exe()` for
  every process on the machine: measured at 112 ms with 12 games, called every
  6 seconds, i.e. ~1.9% of a core on its own. It now uses one Toolhelp snapshot
  plus a name filter and takes 0.61 ms. `pids_for_game()` drops from 10 ms to
  0.44 ms the same way.
- The running-game dropdown is only rebuilt when its contents actually change,
  so an open dropdown no longer loses its highlight every six seconds.

### Fixed
- **A missing `icon.ico` crashed the app at startup.** The fallback used
  `QStyle.SP_ApplicationIcon`, which PySide6 6 removed (the enums are scoped now)
  and raised `AttributeError` before the window appeared.
- **The app could crash at startup with
  `'MainWindow' object has no attribute 'cover_timer'`.** The screenshot page
  asks for cover art from its constructor, which runs before the cover timer is
  created; 2.2.0 started that timer from `request_cover()`, so a screenshot
  folder whose game had an uncached cover (for example right after "Change
  cover…") raised before any window was shown. The request now tolerates the
  timer not existing yet, and any cover asked for that early is picked up as
  soon as the timer is created.
- **Statistics no longer splits one game into two cards.** Playtime was grouped
  by title + VNDB id + exe name, so the same visual novel played through two
  exes (a patched build, a voice-fixed build) showed up as two entries with the
  time divided between them. It is grouped by title + VNDB id now, so every exe
  of the same game counts towards one card.
- **Closing a game no longer blanks the card when another game is running.**
  The exit watcher used to clear the presence for *any* game that exited, so
  closing game A while playing game B wiped B's card (and the watcher also fired
  for the old exe of a handover, which made the card blink right after launching).
  Now the card is only cleared when the game on the profile exits *and* nothing
  else from the library is running; otherwise the presence switches straight to
  the game that is still running, without passing through the empty state.
- **A cleared card comes back immediately.** `clear()` left the "already pushed"
  state behind, so the next push waited for the keepalive and the profile stayed
  empty; clearing now resets that state and any later tick re-sends.
- **The card no longer vanishes while a game is open.** One process snapshot that
  missed the game (a game renaming its own exe, or a slow Toolhelp snapshot) was
  treated as "the game closed" and cleared the card; the engine now waits two
  seconds before it believes that. The keepalive also runs every 20 s instead of
  40 s, a closed Discord pipe is detected and reconnected on the next push
  (`pypresence` has no health check of its own), and a failed connection resets
  the pushed state so the card is re-sent instead of waiting for the keepalive.
- **A game that swaps its own exe no longer makes the card blink.** Games that
  hand their window over to a shared engine exe (`sayagatari_chs.exe` ->
  `SiglusEngine.exe`) closed the old process, and the exit watcher cleared the
  card on the spot; Discord showed the activity drop and come back within a
  second. The watcher now keeps the card for the same two second window and only
  clears when nothing came back.
- **Session time now follows the rules it was supposed to follow.** A session
  belongs to a running game instead of to "whatever is focused right now":
  - switching between two open games no longer restarts either session, and the
    time played before the switch is banked into that game's total and into
    `stats.db` (it used to be dropped: the previous game was looked up by exe
    string while the session key is a tuple, so the lookup never matched);
  - a closed game keeps its session for 8 seconds, so a restart inside that
    window continues it while a later restart starts from zero;
  - a game that renames its own exe, or a launcher handing over to the engine,
    continues the same session because the previous exe is gone and the new one
    is the same game;
  - `Paused` stays with the last focused game while the foreground belongs to a
    non-game window.

## 2.1.2 - 2026-10-21

**In short:** the updater no longer freezes the window while it downloads — there
is a progress bar now — and it can restart the app for you when the download is
done.

### Added
- **"Restart now" or "Later".** When the download finishes the app asks what to
  do. "Later" keeps the app running and installs the update on the next normal
  exit, so nothing restarts under you in the middle of a game.
- **Tray badge for a waiting update.** While a downloaded update waits for the
  next exit, the tray icon carries a red dot, the tooltip names the version, and
  the tray menu gains "Restart to install the update".

### Fixed
- **"Update now" no longer freezes the window.** The release .exe was downloaded
  on the GUI thread, so the window stopped repainting (Windows showed "not
  responding") for as long as the download took, with no sign that anything was
  happening. The download now runs on a background thread: the Updates tab shows
  a progress bar and "Downloading the new version… 42%", the rest of the app stays
  usable, and the swap starts from the shutdown path once you pick "Restart now".
- **A failed swap is no longer silent.** The helper .bat that replaces the exe ran
  without a console, so if Windows still had the file locked it printed
  `Update failed.` into a hidden window, waited on `pause` forever and the app
  never came back. It now retries for up to 20 seconds, then writes
  `%TEMP%\hygger_update_error.txt` with the reason and where the new exe is.
- The wait loop uses `ping` instead of `timeout`, which fails immediately when its
  input is redirected.
- A download is rejected before the swap if the size differs from the release
  asset or the file does not start with `MZ`.
- **Launching the exe again while it sat in the tray opened an empty window.**
  The second copy restored the window from the outside with `ShowWindow`, and a
  window that Qt had hidden repainted as a blank dark frame. The second copy now
  asks the running one (a registered window message) to show itself, so the
  window comes back fully drawn and focused.
- The update tab's progress bar is themed (accent fill, rounded, no native
  green block) and matches both the light and the dark theme. The percentage is
  no longer drawn inside the bar - grey on accent was unreadable in both themes -
  it stays in the label above, which also shows the downloaded size while the
  total is unknown.
- **The Updates tab follows the language setting.** "Current version", "Skipped
  version: none", "Version x.y.z is available.", the release notes and the
  "Update now?" prompt were built once at start-up, so they stayed English (or
  mixed) until something else happened to refresh them. They are re-rendered
  whenever the language changes, and the missing strings were translated
  ("Update now?", "Version %s is available.", "none", "Presence: OFF",
  "Could not check for updates.").
- **"Start with Windows" now says what it points at, and repairs itself.** The
  checkbox only tested whether the Startup shortcut existed, so a shortcut left
  over from an older folder (or a deleted exe) looked fine while Windows started
  something else - or nothing. The tab now shows the shortcut target and marks it
  when the file is gone, and a launch whose shortcut points at a missing file
  rewrites it to the running exe. The check costs one `stat()` per launch; the
  target is recorded in `config.json` (`startup_exe`) so COM is not queried every
  time. Nothing outside the Startup folder is ever touched, and a copy running
  from `%TEMP%` never adopts the shortcut.

## 2.1.1 - 2026-10-19

**In short:** screenshots can drop the black bars an upscaler adds, and every
capture can be copied to the clipboard automatically.

### Added
- **Trim black bars.** Captures drop uniform black borders (left/right and
  top/bottom), which is what upscalers such as Magpie add when the game keeps
  its original aspect ratio. On by default; a dark scene is left untouched
  because both sides have to be solid black before anything is cropped.
- **Copy to clipboard.** A switch in Settings -> Screenshots puts every capture
  on the clipboard, ready to paste into Discord or an image editor. Off by
  default.

### Fixed
- The self updater no longer passes the PyInstaller `_MEIPASS2` environment to
  the relaunched executable. That variable pointed at the temporary folder the
  old process deletes on exit, so an updated build could fail with
  "Failed to load Python DLL ... python311.dll". The update itself always
  succeeded; only the automatic restart was affected.
- Gallery refreshes and clipboard copies run on the GUI thread through a signal
  instead of `QTimer.singleShot` from a worker thread, which never fired.

## 2.1.0 - 2026-10-19

**In short:** a new Screenshots page saves the running game's window into one
folder per game when you press a hotkey, and the gallery, search and session log
work like a small file browser.

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

**In short:** the interface was rebuilt in Qt. Detection, the Discord connection and
the playtime database are the same as 1.0.3, but everything you see is new: dark
and light themes, a window that snaps like a real Windows app, a searchable
library, and a statistics page with ranges, charts and a session log.

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

**In short:** the update loop was made much cheaper (CPU dropped to roughly
0–0.1 %, about a hundred times less than before) and status changes reach Discord in
about a millisecond instead of ~60 ms.

- Added library search, including romanised titles.
- Detect processes spawned by the selected executable.
- Rebuilt the update loop: CPU usage dropped to roughly 0–0.1 % (previously
  about 100× higher on the author's machine).
- Status update latency reduced from about 60 ms to 1–2 ms.
- Added a debug mode that writes `presence_debug.log` (foreground window,
  matched processes, status decisions).
- Minor fixes.

## 1.0.2 — 2026-10-14

**In short:** maintenance — internal fixes, no new features.

- Internal maintenance and bug fixes.

## 1.0.1 — 2026-10-06

**In short:** maintenance — internal fixes, no new features.

- Internal maintenance and bug fixes.

## 1.0.0 — 2026-10-05

**In short:** first release — a Discord card for whichever visual novel is running,
with a library, automatic detection, VNDB lookups, launchers, statistics and a
self-updater.

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
