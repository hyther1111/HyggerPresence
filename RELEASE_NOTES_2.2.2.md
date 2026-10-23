# 2.2.2

Small follow-up to 2.2.1: faster UI in the places that ticked every second, a
Statistics chart that keeps the per-game split on wide ranges, and the last
untranslated captions.

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
