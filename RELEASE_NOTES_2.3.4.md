# Hygger Presence 2.3.4

Route times just got a second dimension: how long one route took, and how far the
game had progressed when that route ended. Your library, settings and playtime
are untouched.

## Route time and accumulative time

The Routes list on the Detection page — and the one in the game editor — now
shows two numbers per route:

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

## A total strip

Under the list, right-aligned with the accumulative column, the total row repeats
the number from the last route — the playtime that matters, without hunting for
the bottom row.

## Set current time

For the route you are reading right now: one button copies the playtime the app
has already recorded into the last route and works out its route time for you. It
asks for confirmation first, because it replaces what you typed.

## Under the hood

- Route lists saved by older versions had one number per route. That number is
  read as the route time, and the accumulative column is rebuilt from it — no
  library rewrite, no lost data.
- Version 2.3.3 was a separate compact build; this release continues from 2.3.2.

## Download

`HyggerPresence.exe`, about 32 MB, one file, no installer. Your data stays in
`%APPDATA%\HyggerPresence`.
