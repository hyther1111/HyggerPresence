# Hygger Presence 2.3.0

The Library learned to show covers, the window remembers where it was, and the
clock stops when you walk away.

## New

- **Cover view.** The button next to the search field switches the Library
  between the list and a wall of posters. Each card fills its box with the cover
  and shows the title, total time, last read date and .exe on hover, VNDB style.
  Click selects, double-click edits, right-click opens the game menu.
- **Last read column** in the Library list: the date of that game's newest
  session, `—` when there is none, matched by VNDB id, then title, then .exe.
- **Column tools** in the Library and in the session dialogs: drag a column to a
  new place, right-click the header to hide or show columns, *Show all columns*
  to get them back. The last visible column can never be hidden, and your
  arrangement is remembered. The row menu mirrors the button row in the same
  order (*Change cover…* before *Open in folder*) and no longer carries a second
  *Columns* sub-menu.
- **Idle status.** Settings → General → *Idle after*: after that many **seconds**
  without keyboard or mouse input the status becomes *Idle* (10 s up to 4 h,
  5 minutes by default). While idle the clock stops at the last real input, so
  time away never lands in the session, the total or the statistics.
- **Start ▸** in the right-click game menu lists every launcher, plus
  *Manage launchers…*.
- **Window memory.** Size, position and maximised state are restored, and a saved
  position is ignored when it would land off-screen.

## Changed

- Covers are drawn at the screen's pixel ratio, so they are sharp instead of
  blurry, and they are cached downscaled (320×440) in memory.
- The Library table stretches its last column, so a wide window leaves no empty
  strip on the right.
- *Library title* is two buttons now (*Original title* / *Romanised title*), not a
  drop-down that the mouse wheel could change by accident, and every remaining
  combo and the *Idle after* field ignore the wheel until they are focused.
- The image pickers in *Presence → Advanced* fit their text (*VNDB cover*,
  *Custom*) instead of clipping it.
- Menus and the numeric fields now use the app's own rounded style instead of the
  plain Windows look; sub-menu arrows are small chevrons, dropdown entries light up
  in the selected blue on hover, and the list/grid icons were redrawn.
- The game menu follows the button row left to right, so *Open in folder* comes
  last.
- The Chinese UI is complete: table headers translate now, and every string of the
  new features is in `zh_TW.json` / `zh_CN.json`.

## Performance

- Covers are cached on disk (`covers\cache\`, capped at 400 files) and fetched by
  four workers over one keep-alive session, instead of a new thread and a new TLS
  handshake per cover on every start.
- Decoded covers are released as soon as they reach their pixmap, and a full
  process scan only runs every two seconds while nothing is detected.
- The *Discord preview* panel only rebuilds when something actually changed; that
  once-a-second rebuild was the biggest idle cost. Measured over an 8 s window with
  the app's own timer loop: idle **10.5 % → 3.9 %** CPU, playing **10.0 % → 6.2 %**,
  at the same ~100 MB resident memory.

## Fixed

- Dead duplicate methods left over from earlier refactors are gone; nothing that
  is still called was removed.
- The cover wall no longer comes up empty after *Refresh* or after switching
  list → grid → list; the cards are shown as they are added and the panel refits
  itself, so no window resize is needed.
- The Discord card no longer keeps saying *Reading* (with a running timer) after
  the app went *Idle*: a new status must hold one second before it is pushed, so a
  *Reading/Paused* flap cannot use up Discord's five updates per 20 s, and an RPC
  call that stalls for more than 8 s now reconnects instead of freezing the card.
- The Library layout setting has a single home in the config, and "Last read" also
  finds games whose stats rows use another spelling of the title.
