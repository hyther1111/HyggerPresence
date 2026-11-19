# Hygger Presence 2.4.0

**Optional VNDB list integration, multi-platform ratings, an interactive Share Statistics canvas, and major performance & UI improvements.**

## Highlights

### Optional VNDB API Integration (`Settings → VNDB & Ratings`)
Link a personal VNDB token (`vndb.org/u/tokens`) to unlock optional, independently toggleable features:
- **Search VNDB by Title:** Look up visual novels directly from *Add game* and *Game Details*.
- **VNDB Library Sync:** Import your VNDB list into the Library with label filters, startup sync, and a **Stop** button.
- **Inline VNDB List Management:** Update labels, vote (`1`–`10`), pick start/finish dates with calendar popups, edit notes, and manage releases directly inside **Game Details**.
- **Auto-Mark "Playing":** Automatically set *Playing* on launch (requires `listwrite`; never overwrites *Finished*).

### Multi-Platform Ratings & Rankings
Fetch and display scores, ranks, and vote counts across **VNDB** (Weighted / Average, Rank, Popularity), **Bangumi**, and **ErogameScape** (best-effort when accessible), with new Presence variables (`{vndb_rank}`, `{vndb_popularity}`, `{bangumi_rating}`, `{egs_median}`, `{vndb_user_vote}`, `{vndb_label}`, and more).

### Redesigned Game Details & Library Pagination
- **Game Details:** Single scrollable view with a header **Start** launcher button, clear platform rating cards, collapsible advanced fields, embedded VNDB List editor, and inline Routes editor.
- **Library:** Dual `Manual` + `On VNDB List` source flags, configurable pagination (`25 / 50 / 100 / 200 / All`), and persistent filter selection.

### Interactive Share Statistics Canvas (`Statistics → Share…`)
Design custom stats summary cards on a live drag-and-drop canvas:
- Drag and resize **Title & date range**, **Summary cards**, **Activity chart**, and **Most read visual novels**.
- 1-click presets (*Stacked*, *2-Column*, *Wide Banner*), alignment guides, grid snap, Light/Dark themes, **Copy image**, **Save image…**, and **Export CSV…**.

### Screenshot Cursor Control & Performance Fixes
- **Hide cursor toggle** in *Settings → Screenshots* (and OS cursor compositing on unscaled captures when unchecked).
- Eliminated Light/Dark theme switch freezes, bounded in-memory cover caching, and sped up metadata/list loading.
- Fixed live detection dropping when opening **Game Details**, fixed dialog startup flash, fixed `&` underline mnemonics, and fixed the Activity chart inside Share Statistics.
