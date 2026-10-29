# Hygger Presence 2.3.5

One switch stops the clock, and the Routes card no longer hides itself until you
have a route. Your library, settings and playtime are untouched.

## Record Time

Next to *Presence* on the Detection page there is a second switch: **Record
Time**. It is the master switch for every clock the app owns:

- the **session** time and the **total** playtime,
- the rows written to the **statistics** database,
- the **elapsed timer** on your Discord card.

Turn it off and all four freeze. The stretch that was still running is banked
first, so the second you switch it off is the second that gets recorded — what
comes after does not count at all, even if the game stays open for hours. Your
Discord card keeps showing the game, just without a running timer.

Turn it back on and the session continues from where it stopped: nothing is lost,
nothing is counted twice, and the card picks its timer up again.

The state is saved in `config.json`, so the app starts with the clock off if that
is how you left it.

## The Routes card

- **It is always there.** As soon as a game is seen the card shows *ROUTES*, the
  `+` and the hint. The **Route time** and **Accumulative** columns only appear
  when the first route exists, so the empty card is one short line instead of a
  table full of headings.
- **The `+` moved up.** It now sits on the total line, on the left, right where
  the next route is going to appear. The card ends one row sooner.
- **Set current time is the blue action.** It wears the same blue as the *Start*
  button in the library, and it only shows up once there is a route to fill in —
  on an empty list there is nothing to fill.
- **Messages sit next to the button.** "The recorded total is not larger than the
  route above" and the other hints share the action row, so a message never makes
  the card taller.

*Presence* and *Record Time* share the same chip and pick black or white text from
the theme's green, so the pair looks the same in the dark and the light theme.
*Record Time: OFF* turns red, like *Presence: OFF*, so an off switch reads as off
instead of as a disabled button.

## The odd square behind a cover

The Discord preview's thumbnail box and the cover on a screenshot card painted
the window colour behind the image. With a cover that was not exactly square, the
leftover strip showed as a darker square (or as bars down the sides). The art now
fills its box: the preview cover is cropped to the square, the gallery covers are
fitted, and both keep their rounded corners — the small image stays a circle.

## Under the hood

- Record Time is enforced inside the engine, not only in the UI: the clock never
  starts while it is off, so no code path can bank a second into `stats.db`, the
  session or the total.
- The routes card no longer collapses to nothing when a game has no routes; the
  captions are hidden individually instead.
- Every preview/gallery image goes through one `fill_pixmap` helper, so no label
  has to fake a background colour behind the art.

## Download

`HyggerPresence.exe`, about 32 MB, one file, no installer. Your data stays in
`%APPDATA%\HyggerPresence`.
