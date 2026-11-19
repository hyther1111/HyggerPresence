# Hygger Presence

Automatic Discord Rich Presence, playtime tracking, multi-platform VN ratings, route timing, and screenshot management for visual novels on Windows.

---

## Quick Start

1. Download and run `HyggerPresence.exe` (keep the Discord desktop client running if you want Rich Presence).
2. *(Optional)* To show your status on Discord:
   - Open [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
   - Copy the **Application ID** from **General Information**.
   - Paste it in **Settings → General → Discord Application ID** and click **Save**.
   *(Playtime tracking, statistics, routes, and screenshots all work even without a Discord ID.)*
3. Add a game in **Library → Add game**:
   - Pick the game's `.exe`.
   - Search for the title directly using **Search VNDB** (or paste a VNDB link/ID like `v2002`), then click **Add**.
4. Launch the game — Hygger Presence detects it automatically, tracks your active reading time, and updates your Discord profile.

---

## Key Features

### Automatic Detection & Smart Clock
- **Reading / Paused / Idle:**
  - **Reading:** The game window is focused and you are active.
  - **Paused:** Another window is in front of the game.
  - **Idle:** No keyboard or mouse input for a configurable duration (*Settings → General → Idle after*, 5 minutes by default). Idle time is excluded from session time, total playtime, and statistics.
- **Record Time toggle:** On the **Detection** page, you can pause all timers at any time without losing recorded progress.
- **Process Tree Aware:** Automatically handles Locale Emulator, GalFC, launcher handovers, and executables inside the game's folder.

### Library & Optional VNDB Integration
- **List & Cover Grid Views + Pagination:** Switch between a detailed table and a visual cover wall from the top-right toggle, with configurable page sizes (`25 / 50 / 100 / 200 / All`, default `50`) and persistent filter selection.
- **Manual + VNDB Dual Source Tracking:** Games can carry both `Manual` and `On VNDB List` flags, so turning VNDB sync off keeps your manual titles (including manual entries that are also on your VNDB list).
- **VNDB Search:** Search visual novels by title (English, Japanese, or romaji) directly inside **Add game** and **Game Details**.
- **VNDB API Token *(Optional)*:** Link a personal token from [vndb.org/u/tokens](https://vndb.org/u/tokens) under **Settings → VNDB & Ratings** to unlock optional, individually toggleable features:
  - **VNDB Library Sync:** Import your entire VNDB list (Playing, Finished, Stalled, Dropped, Wishlist) into your Library with a **Stop** button for long jobs. Unlinked entries can be attached to a local `.exe` anytime.
  - **Inline VNDB List Management:** Edit your VNDB list entry directly inside **Game Details** — change labels, cast integer votes (`1`–`10`), pick start/finish dates via calendar popups, edit personal notes, attach releases, or open VNDB to vote playtime.
  - **Auto-Mark "Playing":** Automatically set a game's status to *Playing* on VNDB when launched (requires `listwrite` permission; never overwrites *Finished* titles).

### Multi-Platform Ratings & Rankings
Fetch scores and rankings across major visual novel databases concurrently (individually toggleable in **Settings → VNDB & Ratings**, with a **Stop** button on bulk fetches):
- **VNDB:** Bayesian weighted score, raw average, rating rank, popularity rank, and vote count.
- **Bangumi (bgm.tv):** Score, rank, and vote count.
- **ErogameScape (批評空間):** Median, average, and rank *(best-effort; displays `N/A` when region-blocked outside Japan)*.

### Game Details
Double-click any game (or click **Edit**) to open **Game Details** in one clean view:
- **Start** button with normal launch and configured launcher presets right in the header.
- Dedicated platform rating cards for **VNDB (Weighted / Average)**, **Bangumi**, and **ErogameScape (Median / Average)**.
- Original & romanized titles, `.exe` path, collapsible advanced fields (extra process names, Bangumi/EGS IDs), total playtime, and cover picker.
- Embedded **VNDB List** card and inline **Routes** editor with read-order tracking, categories, drag-and-drop reordering, and cumulative totals.

### Discord Rich Presence & Variables
Customize **Reading**, **Paused**, and **Idle** templates independently under **Settings → Presence**, with live previews on the **Detection** page.

| Variable | Output |
|---|---|
| `{title}` / `{romanized_title}` | Original or romanized title |
| `{developer}` / `{year}` | Developer and release year |
| `{status}` | `Reading`, `Paused`, or `Idle` |
| `{session_time}` / `{total_time}` | Formatted session or total playtime |
| `{rating_average}` / `{rating_weighted}` | VNDB raw average / Bayesian rating |
| `{vndb_rank}` / `{vndb_popularity}` | VNDB rating rank / popularity rank |
| `{bangumi_rating}` / `{bangumi_rank}` | Bangumi score and rank |
| `{egs_median}` / `{egs_average}` / `{egs_rank}` | ErogameScape median, average, and rank |
| `{vndb_user_vote}` / `{vndb_label}` | Your VNDB personal vote and list status |
| `{vndb}` | VNDB ID (useful for the button URL) |

**Time format tokens:** `{h}` `{m}` `{s}` (no leading zero), `{hh}` `{mm}` `{ss}` (zero-padded), `{h:}` (hour + colon when > 0), and conditional blocks `{h?}…{/h}` (`hours > 0`) / `{!h}…{/!h}` (`hours == 0`).

### Statistics & Screenshots
- **Statistics & Share Canvas:** SQLite-backed playtime history with daily/monthly charts, preset & custom calendar ranges, per-game session logs, and **Share…** — an interactive canvas creator where you can drag and resize blocks, apply presets, toggle Dark/Light matching themes, copy/save PNGs, or export CSV.
- **Screenshots:** Capture the active game window (or Magpie upscaled output) with a game-only hotkey, optional **Hide cursor** mode, auto-trim black bars, optional clipboard copy, and a built-in gallery organized by game.

### Launchers, Themes & Languages
- **Launchers:** Start games via Locale Emulator (auto-reads `LEConfig.xml`), GalFC, or custom commands.
- **Themes & Languages:** Dark/Light themes and instant switching between English, Traditional Chinese (`繁體中文`), and Simplified Chinese (`简体中文`).

---

## Data Storage & Backup

All user data is stored locally in `%APPDATA%\HyggerPresence`:
- `games.json` — Library entries, metadata, ratings, and routes
- `config.json` — Settings, presence templates, launchers, and VNDB preferences
- `stats.db` — SQLite playtime session history

Nothing is bundled inside the executable, so upgrading `.exe` releases preserves all your data.

---

## Running from Source & Building

Requirements: Windows 10/11 and Python 3.11+.

```bash
git clone https://github.com/hyther1111/HyggerPresence.git
cd HyggerPresence/HyggerPresence_2.4.0
pip install -r requirements.txt
python main.py
```

To build a standalone single-file executable (`dist\HyggerPresence.exe`):

```bat
build.bat
```

`build.bat` creates an isolated `buildenv\` environment from `requirements.txt` and packages via `HyggerPresence.spec`.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| **Discord card does not appear** | Ensure the Discord desktop app is running and your Application ID is saved in **Settings → General**. |
| **Discord card stops updating briefly** | Discord rate-limits activity updates to 5 per 20 seconds; it recovers automatically within ~20 seconds. |
| **Game is not detected** | Use the **Detect** dropdown on the Detection page to pin it, or add its process name under **Edit → Extra process names**. |
| **ErogameScape shows `N/A`** | ErogameScape restricts connections from many non-Japanese IP ranges; `N/A` is shown automatically when unreachable. |
| **Wrong Bangumi / EGS match** | Open **Edit** on the game, enter the exact Bangumi or ErogameScape ID, and click **Fetch metadata & ratings**. |

---

## License

MIT — see [LICENSE](LICENSE).
