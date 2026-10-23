# 2.2.2 — 2026-10-23

Small follow-up to 2.2.1: the playtime counter ticks every second again, the
Statistics chart keeps the per-game split on wide ranges, and the last untranslated
captions are translated.

## What Hygger Presence is

Hygger Presence keeps your Discord status in sync with the visual novel you are
playing: it detects the running game, shows its title, developer, cover, session
time and total playtime on your profile, and records how long you played each game.
It comes with a searchable library, VNDB lookups, launchers for Japanese games
(Locale Emulator, GalFC), a statistics page, a screenshot tool with one hotkey per
game, optional hand-typed route times, three languages and a dark and a light theme.
Everything stays on your machine — the library, the settings and the playtime live in
`%APPDATA%\HyggerPresence`, and Discord only ever receives the card text and images.

## What's new in 2.2.2

- **The play time in the Library counts up every second again.** It used to step
  every two or three seconds, and it no longer costs extra CPU to do so.
- **The Chinese UI speaks Chinese everywhere.** The Library and Launcher column
  titles and the two update message boxes were the last English leftovers.
- **Long statistics ranges keep every game.** Past 60 days the chart used to merge
  everything into one `Total` bar per month; now each month keeps the per-game split.
- **The window is a little smaller** — 1120×780 instead of 1200×880 — so it fits
  next to a game on a 1080p screen.

## Fixed

- **CPU while reading.** The Library row that shows the live play time rebuilt the
  whole table once per second (36 new items for 12 games) and repainted every row.
  It now rewrites only the cell whose number changed — 0.44 ms → 0.015 ms per tick.
- **CPU while idle.** That same one-second timer also ran whenever the Library was
  visible, even with no game running, so an idle window woke the process every
  second for nothing. It starts and stops with the game now.
- **Duplicate timers.** The timer was created inside the icon/theme refresh, so each
  press of the light/dark button added another one-second timer doing the same work.
  It is created once.
- **Live play time updated late.** The refresh timer was restarted by the main tick
  every second, so its deadline never came due; the number only moved when a tick
  was late, which looked like a 2–3 s update. It is refreshed on the engine tick now
  and steps once per second.
- **Statistics, ranges longer than 60 days.** The chart used to collapse into one
  `Total` bar per month. It still groups per month, but each bar keeps the games
  stacked with the same colours and legend as the daily view, and the `Total`
  pseudo-entry is gone. The switch-over point is 60 days.
- **Library and Launcher captions.** The column headers (*Title*, *Total time*,
  *Executable*, *Launcher*) were built without the translation helper and stayed
  English in the Chinese UI. They follow the selected language now.
- **Updates dialogs.** “This release has no .exe asset” and “this build runs from
  source” were English only; both are translated, including their window titles.

## Changed

- The window opens at **1120×780** (minimum 940×640) instead of 1200×880, so it fits
  next to a game on a 1080p screen.

## Install

Download `HyggerPresence.exe` and replace the old one. `games.json`, `config.json`
and `stats.db` in `%APPDATA%\HyggerPresence` are kept — the updater replaces the
`.exe` in place.
