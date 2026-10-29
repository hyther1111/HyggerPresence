# Hygger Presence 2.3.4

Route times got a second dimension — how long one route took, and how far the
game had progressed when it ended — one switch now stops every clock, and the
Discord preview finally looks like the card Discord draws. Your library,
settings and playtime are untouched.

## Record Time

Next to *Presence* on the Detection page there is a second switch: **Record
Time**. It is the master switch for every clock the app owns:

- the **session** time and the **total** playtime,
- the rows written to the **statistics** database,
- the **elapsed timer** on your Discord card.

Turn it off and all of them freeze. The stretch that was still running is banked
first, so the second you switch it off is the second that gets recorded — what
comes after does not count at all, even if the game stays open for hours. Your
Discord card keeps showing the game, just without a running timer.

Turn it back on and the session continues from where it stopped: nothing is lost,
nothing is counted twice, and the card picks its timer up again.

The state is saved in `config.json`, so the app starts with the clock off if that
is how you left it.

## Route time and accumulative time

The Routes list on the Detection page — and the one in the game editor — shows
two numbers per route:

| Route | Route time | Accumulative |
| --- | --- | --- |
| common route | 4h 00m 00s | 4h 00m 00s |
| tanomi route | 7h 00m 00s | 11h 00m 00s |

Type **either** one and the other follows:

- Type the route time (4h) and the accumulative column becomes the time above
  plus what you typed.
- Type the accumulative time (11h) and the route time becomes the difference to
  the route above (7h).

Change a route in the middle and the rows below are renumbered, so the running
total never goes backwards or skips.

## The Routes card

- **It is always there.** As soon as a game is seen the card shows *ROUTES*, the
  `+` and the hint. The **Route time** and **Accumulative** columns only appear
  when the first route exists, so the empty card is one short line instead of a
  table full of headings.
- **A total strip.** Under the list, right-aligned with the accumulative column,
  the total row repeats the number from the last route — the playtime that
  matters, without hunting for the bottom row.
- **The `+` moved up.** It now sits on the total line, on the left, right where
  the next route is going to appear. The card ends one row sooner.
- **Set current time is the blue action.** It copies the playtime the app has
  already recorded into the last route and works out its route time for you. It
  wears the same blue as the *Start* button in the library, and it only shows up
  once there is a route to fill in — on an empty list there is nothing to fill.
- **Messages sit next to the button.** "The recorded total is not larger than the
  route above" and the other hints share the action row, so a message never makes
  the card taller.

## The Discord preview

- **Four rounded corners.** The thumbnail is clipped properly on all four
  corners, with a smaller radius that matches the card Discord draws.
- **Sharper picture.** The thumbnail is cropped from the full cover at the
  screen's pixel ratio instead of being fitted into the box first, so it no
  longer gets stretched up from a small image.
- **Paused and Idle count from 0:00.** Discord restarts the green clock every
  time the state flips, and the preview now does the same: switch to *Paused* and
  the timer starts again from `0:00`. The *Session* line keeps its hours, exactly
  like the presence does. Nothing about the real card changed — this only draws
  the preview.
- **A fully translated window.** Tooltips, the minimise / maximise / close
  buttons and the labels that carry a number or a state (the version line, the
  data summary, Record Time: ON/OFF) were still English in the Chinese UI.
  They follow the language now, and switching language updates them without a
  restart.
- **Hover texts again.** Hovering the large or the small image shows the text
  Discord shows next to it, and it appears as soon as the mouse is on the
  picture rather than after a pause.
- **No more odd square behind a cover.** The preview's thumbnail box and the
  cover on a screenshot card painted the window colour behind the image, which
  showed as a darker square around the art. The art now fills its box, and the
  small image stays a circle.

## Small things

- **Save says Saved.** Saving the settings no longer opens a window you have to
  dismiss: a green *Saved* appears next to the button and fades on its own. The
  save itself works exactly as before.
- *Presence* and *Record Time* now print in white in both themes, so the two
  chips match. *Record Time: OFF* turns red, like *Presence: OFF*, so an off
  switch reads as off instead of as a disabled button.

## Under the hood

- Record Time is enforced inside the engine, not only in the UI: the clock never
  starts while it is off, so no code path can bank a second into `stats.db`, the
  session or the total.
- Route lists saved by older versions had one number per route. That number is
  read as the route time, and the accumulative column is rebuilt from it — no
  library rewrite, no lost data.
- Every preview/gallery image goes through one `fill_pixmap` helper, so no label
  has to fake a background colour behind the art.
- Version 2.3.3 was a separate compact build; this release continues from 2.3.2.

## Download

`HyggerPresence.exe`, about 32 MB, one file, no installer. Your data stays in
`%APPDATA%\HyggerPresence`.
