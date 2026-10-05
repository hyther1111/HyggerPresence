# HyggerPresence
visual novel presence built for myself and add features that i needed (locale emulator and galfc support)

# Time format logic brief explaination
yes i dont know how do i explain this perfectly so i tried to put example but turn out its still quite complex

there is no {hh?} / {!hh} and their minutes and seconds variations since i think those wouldnt be needed anyways

### Token
| Token | Explaination | Example format | Output |
|---|---|---|---|
| `{h}` / `{m}` / `{s}` | doesn't show 0 if value is single digit | `{h}h {m}m {s}s` | `1h 2m 3s` / `1h 23m 45s` |
| `{hh}` / `{mm}` / `{ss}` | show 0 if value is single digit | `{hh}h {mm}m {ss}s` | `01h 02m 03s` / `01h 23m 45s` |
| `{h:}` / `{hh:}` / `{m:}` / `{mm:}` / `{s:}` / `{ss:}` | show value and colon if value > 0 | `{hh:}h {mm}m {ss}s` | `02m 03s` (example 00h 02m 03s) / `01h 02m 03s` (example 01h 02m 03s) |

### Block
| Block | When it shows | Example format | Time | Output |
|--------|----------------|----------------|------|--------|
| `{h?}…{/h}` | hours > 0 | `{h?}{h}h {/h}{mm}m {ss}s` | 1h 2m 3s | `1h 02m 03s` |
| | | | 0h 2m 3s | `02m 03s` |
| `{m?}…{/m}` | minutes > 0 | `{h}h {m?}{m}m {/m}{ss}s` | 1h 0m 3s | `1h 03s` |
| | | | 1h 2m 3s | `1h 2m 03s` |
| `{s?}…{/s}` | seconds > 0 | `{m}m {s?}{s}s{/s}` | 5m 0s | `5m ` |
| | | | 5m 3s | `5m 3s` |
| `{!h}…{/!h}` | hours == 0 | `{h?}{h}h {/h}{!h}{mm}:{ss}{/!h}` | 1h 2m 3s | `1h ` |
| | | | 0h 2m 3s | `02:03` |
| `{!m}…{/!m}` | minutes == 0 | `{m?}{m}m {/m}{!m}{ss}s{/!m}` | 2m 3s | `2m ` |
| | | | 0m 3s | `03s` |

**Short version for a README:**

| Syntax | Meaning |
|--------|---------|
| `{h?}…{/h}` | include `…` only if hours > 0 |
| `{m?}…{/m}` | only if minutes > 0 |
| `{s?}…{/s}` | only if seconds > 0 |
| `{!h}…{/!h}` | only if hours == 0 |
| `{!m}…{/!m}` | only if minutes == 0 |
| `{!s}…{/!s}` | only if seconds == 0 |

Avoid placeholder junk like `123` / `456` — always use real time parts (`{h}`, `{mm}`, etc.) so the Expected Output column stays obvious.

## Default time format explaination
`{h?}{h}h {mm}m {ss}s{/h}{!h}{m?}{m}m {ss}s{/m}{!m}{s}s{/!m}{/!h}`

### break down into parts:
| Variable | Explaination |
|---|---|
| `{h?}{h}h {mm}m {ss}s{/h}` | only show `{h}h {mm}m {ss}s` when hour > 0 |
| `{m?}{m}m {ss}s{/m}` | only show `{m}m {ss}s` when minute > 0 |
| `{!m}{s}s{/!m}` | only show `{s}s` when minute == 0 |
| `{!h}{m?}{m}m {ss}s{/m}{!m}{s}s{/!m}{/!h}` | only show `{m?}{m}m {ss}s{/m}` and `{!m}{s}s{/!m}` when hour == 0 |

## What it does?
| Time | Output |
|---|---|
| 12h 34m 56s | 12h 34m 56s |
| 01h 23m 45s | 1h 23m 45s |
| 00h 12m 34s | 12m 34s |
| 00h 01m 23s | 1m 23s |
| 00h 01m 02s | 1m 02s |
| 00h 00m 12s | 12s |
| 00h 00m 01s | 1s |
| 00h 00m 00s | 0s |
