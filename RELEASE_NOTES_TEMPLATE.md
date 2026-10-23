# <version> — <date>

<!--
How to use this file
--------------------
1. Copy it to RELEASE_NOTES_<version>.md and fill in the two blocks below.
2. The "What Hygger Presence is" block almost never changes: keep it as it is, so
   every release page starts with the same short introduction.
3. "What's new" is the part to write each time: three to six bullets in plain
   language, most important first, no file names and no code.
4. Paste the whole file into the GitHub release body and attach
   dist\HyggerPresence.exe as the asset (the updater looks for an .exe asset).
-->

## What Hygger Presence is

Hygger Presence keeps your Discord status in sync with the visual novel you are
playing: it detects the running game, shows its title, developer, cover, session
time and total playtime on your profile, and records how long you played each game.
It comes with a searchable library, VNDB lookups, launchers for Japanese games
(Locale Emulator, GalFC), a statistics page, a screenshot tool with one hotkey per
game, optional hand-typed route times, three languages and a dark and a light theme.
Everything stays on your machine — the library, the settings and the playtime live in
`%APPDATA%\HyggerPresence`, and Discord only ever receives the card text and images.

## What's new in <version>

- **<the single most important change, in one line>** — what it means for the user.
- **<second change>** — what it means for the user.
- **<third change>** — what it means for the user.

### Fixed

- <bug that was visible to users, and what it does now>

### Added

- <new feature, and when to use it>

### Changed

- <behaviour that works differently now, and why>

## Upgrading

Download `HyggerPresence.exe` and replace the old one — or press **Update now** in
Settings → Updates. `games.json`, `config.json` and `stats.db` in
`%APPDATA%\HyggerPresence` are kept; the updater only replaces the `.exe`.

## Requirements

Windows 10 or 11 and the Discord desktop client. Running from source needs Python
3.11 or newer.
