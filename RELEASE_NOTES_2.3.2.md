# Hygger Presence 2.3.2

Three fixes on top of 2.3.1, nothing new to learn. Your library, settings and
playtime are untouched.

## Fixed

- **VNDB ratings were ten times too big.** VNDB's new API sends `rating` on a
  0–100 scale, so 7.61 on the site arrived as 76.1 and the card showed 76.10.
  Everything is normalised back to 0–10, so `{rating_average}` and
  `{rating_weighted}` read the same as on vndb.org again. Values already in your
  library are kept; only a re-fetch is corrected.

- **Variables stayed literal in some texts.** `{title}`, `{session_time}` and the
  rest were filled in on the first and second line of the card, but the large
  image hover text, the small image hover text and the button label showed the
  braces as typed — a card could literally say `{title}`. All of them now go
  through the same substitution.

- **The small image was missing from the Detection preview.** If you set a small
  image, the preview on the Detection page now draws it in the corner, so you can
  see what Discord will show before saving.

## Added

- Resting the pointer on the preview's big or small image shows the hover text
  Discord would show there.
- Settings → Presence says that variables work in the hover texts too.

## Download

`HyggerPresence.exe` — about 32 MB now, down from 54 MB. The build runs from a
clean virtual environment and the spec leaves out the Qt pieces this application
never loads (software OpenGL, Direct2D platform plugin, TIFF, Qt's own OpenSSL).
Nothing a normal install uses was removed; if you do run it on a machine without
a GPU driver, `HP_KEEP_SOFTGL=1 build.bat` puts the software OpenGL back.

Building from source is unchanged: `build.bat`, then `dist\HyggerPresence.exe`.
