# Hygger Presence 2.3.5

Two things in this release: the Detection total and the Statistics card finally
agree to the second, and the routes card is rebuilt around the way a long game is
actually read. Your library, settings and playtime are untouched — the exe is a
straight replacement, and the first start repairs the totals the old build left
a fraction of a second apart.

## The two numbers

### What was really wrong

2.3.4 was built on the assumption that the two cards disagreed only because they
were painted a moment apart. Measuring your library showed something else: the
two numbers were not two views of one figure, they were two different figures.

`stats.db` said your current game had **23232.002 s**. `games.json` said
**23231.247 s**. Both cards were telling the truth about their own ledger, and
the 0.756 s between them is exactly the width of a second boundary — so one card
printed `6h 27m 11s` and the other `6h 27m 12s`.

Where the missing 0.756 s went: `Engine.flush_open_segment()` is the "bank the
running stretch now" path that the Statistics page uses when you press Refresh
while reading. It inserted the whole open stretch into `stats.db` and added it to
the session — but never to the game's stored total. Statistics was ahead from
that moment on, permanently. The same debt is in three other titles here:
0.231 s, 0.174 s, 0.0005 s.

Two more faults were stacked on top:

- **The unbanked buffer was counted twice on the Detection side.**
  `game["total_seconds"]` already contains the seconds that sit in
  `_stat_buffer`, but the Detection total added the buffer again while waiting
  for the 5 s write — up to five seconds the other way round.
- **Each card still sampled the clock for itself.** 2.3.4 merged the timers, not
  the samplings: tick, clock timer and `pending_seconds()` each called
  `time.time()`, and `format_time()` truncates, so two samples milliseconds
  apart can show different seconds.

### What 2.3.5 does

- `flush_open_segment()` banks into the total too, so the two ledgers cannot
  drift apart again.
- The Detection total is `game["total_seconds"]` + the open stretch only; the
  buffer is added on the `stats.db` side, where it is genuinely missing.
- `engine.sample_clock(now)` stamps the session and the total from one sample,
  and `MainWindow._paint_live()` is the only painter: it paints Detection, the
  status bar and the Statistics page from that single sample, and hands the
  sample down to `pending_seconds(now)`.
- **Quitting writes the last seconds to `stats.db`.** They sit in a buffer that
  only flushes at 5 s, so quitting with less than that left the tail inside the
  total and outside the database — the clock and the Statistics page drifted
  apart by a second, and stayed apart. `engine.close()` now flushes first.
- **On first start, both directions of damage are repaired.**
  `engine.repair_leaked_totals()` fixes gaps of one buffer's size either way,
  and never deletes time: `stats.db` ahead (`0 < gap <= 5 s`) is folded back into
  the total, and a total ahead by up to 5 s is completed by writing the missing
  row. Anything bigger is left alone on purpose — a total far above `stats.db`
  is the normal shape for hours played before the Statistics page existed
  (they were never in the database and are never taken away), and large gaps
  below it are real disagreements (a game renamed after its rows were written,
  an edited total) that stay with *Library → Sync totals*. Titles with no rows
  at all are never touched.
- **Editing a game no longer shaves its total.** *Library → Edit game* rewrote the
  total through a whole-second parser on every OK, so fixing a title could cut a
  fraction off a figure `stats.db` still held exactly — and the two displays were
  a second apart again. The field is now written only when you actually change it.
- **A leftover gap is folded while idle.** A card handover can add a fraction
  *after* the startup repair; `engine._maybe_heal()` repeats the repair every
  five minutes while nothing is tracked, so it closes in minutes, not on the
  next launch.

For your library that means: the next start adds 0.756 s to the stored total of
the game you are reading (and 0.231 s / 0.174 s to two others), writes the lost
1.23 s tail of the same game into `stats.db`, and from then on both cards print
the same second, including the moment the number rolls over.

## The routes card

The old card was a table that renumbered itself: every edit rewrote the numbers
of the rows below it, so the number you typed was never the number you saw, and
there was no way to say "these five routes are the common route" — the only
grouping was the order they happened to be typed in. 2.3.5 replaces it with the
three things you were doing by hand:

- **The read order is yours.** Each row has an *order* number. `+` gives the new
  row the highest number plus one, the field can be typed over, and nothing
  renumbers on its own: adding a route at the top no longer shifts the others,
  and deleting one leaves the rest alone. Two routes may share a number — both
  are outlined in red, with a note explaining why it is allowed — because two
  branches read at the same time are one step of the read order.
- **Categories.** A *Category* box per row, holding the ones already in use and
  *New category…*. The card groups itself: a heading per category, its routes
  under it, and the category's own time next to the name (*No category* collects
  the rest). A heading is also a grip — dragging it moves the whole group.
- **A tick per route.** A route without a tick keeps its own time but is left out
  of the *Accumulative* column and out of *Total counted*: for the route that is
  not finished yet, or one replayed out of order.

*Accumulative* is now the sum of the counted routes up to that row **in read
order**, so a route numbered 3 that ends a chapter shows the total up to 3
wherever it sits in the list; two routes with the same number keep the order
they appear in. Rows are moved by dragging them (the grip on the left, or the row
itself), and a dragged row takes the category of the row it lands on — dropping
it at the end of a category keeps it in that category, which the old drop test
got wrong. *Set current time* is unchanged in spirit: it fills the route that is
last in read order with the playtime the app recorded, and asks first.

Underneath, three bugs are gone:

- **Clicking a second row duplicated the first one.** Every refresh destroyed and
  recreated the row widgets, so a click that arrived between the two halves
  landed on a widget about to be deleted and left a duplicate behind (it went
  away on restart because nothing on disk had changed). Rows are now reused and
  only their fields are updated — which is also why the card no longer flashes
  white on every edit.
- **Scrolling over a *Category* box could change its category.** The box now
  ignores the wheel.
- **Dropping a route at the end of a category put it in the next one**, for the
  same "only rows are drop targets" reason.

Route times still live with the game in `games.json`, nothing about them is sent
to Discord, and they never touch the session clock or the statistics.

A headless test (`_devtools/_test_clock_235.py`) drives the real engine against a
real `stats.db` over every millisecond of a second and fails if the two cards
differ, if a flush moves them, or if the repair touches a real disagreement.
The routes card has its own headless tests (`_devtools/_probe_routes5.py`,
`_probe_routes6.py`, `_probe_bands.py`, `_probe_wheel.py`): they click through the
real widgets — order numbers, categories, ticks, both kinds of drag — and fail if
the stored list and the visible list disagree.
