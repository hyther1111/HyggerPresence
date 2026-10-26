# Hygger Presence 2.3.1

Screenshots of a game upscaled by Magpie come out whole, with one hotkey.

## Changed

- **One screenshot hotkey.** *Capture the game* saves Magpie's upscaled picture
  while Magpie scales the game (fullscreen or windowed) and the game's window
  otherwise. Before, a 1280×720 game scaled to 1080p was saved as a 1280×720
  piece of the upscaled image.
- *Capture the whole screen* was removed from Settings → Screenshots. If it was
  your only hotkey, its key becomes the main hotkey.
- Captures are right on a second monitor and at 150 % / 200 % Windows display
  scaling.

## Fixed

- A screenshot folder that does not exist on this PC (a `config.json` copied from
  another computer) falls back to `Pictures\HyggerPresence` instead of silently
  saving nothing.
