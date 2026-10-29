"""Hygger Presence 2.0 - foundation: paths, constants, helpers.

Vendored from the 1.x package (tkinter parts removed) so the Qt build is
standalone: no dependency on the old folder.
"""
import json
import re
import os
import sys
import threading
import time
import subprocess
import ctypes
from ctypes import wintypes
from pathlib import Path

import requests
import psutil

import re
import threading
import time
import requests
import ctypes
from ctypes import wintypes
from pathlib import Path
import os
import sys
import subprocess
from pypresence import Presence
import psutil
import sqlite3
import shutil
import tempfile
import csv
from datetime import datetime, timedelta

# ====================== CONFIG ======================
APP_VERSION = "2.3.4"          # bump on every release (match the GitHub tag)
GITHUB_REPO = "hyther1111/HyggerPresence"   # owner/repo - used by Check Update






DATA_DIR_NAME = "HyggerPresence"
DATA_FILES = ("games.json", "config.json", "stats.db",
              "stats.db-wal", "stats.db-shm", "presence_debug.log")


def _install_dir():
    """Folder the program itself lives in (read only for the data)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    argv0 = (sys.argv[0] or "").strip()
    if argv0:
        candidate = Path(argv0)
        try:
            if candidate.exists():
                return candidate.resolve().parent
        except Exception:
            pass
    return Path(__file__).resolve().parent.parent


def _base_dir():
    """Folder that holds games.json / config.json / stats.db.

    %APPDATA%\\HyggerPresence on Windows, so the install folder stays clean.
    HYGGER_DATA_DIR overrides it (portable mode / tests).
    """
    override = str(os.environ.get("HYGGER_DATA_DIR", "")).strip()
    if override:
        target = Path(override)
    elif os.name == "nt":
        root = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        target = Path(root) / DATA_DIR_NAME if root else Path.home() / ("." + DATA_DIR_NAME)
    else:
        target = Path.home() / (".config/" + DATA_DIR_NAME)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception:
        target = _install_dir()
    _migrate_if_needed(target)
    return target


def _migrate_if_needed(target):
    """Copy data files left next to the program into the new folder, once."""
    source = _install_dir()
    if source == target:
        return
    if (target / "games.json").exists():
        return
    moved = []
    for name in DATA_FILES:
        candidate = source / name
        if not candidate.exists():
            continue
        try:
            shutil.copy2(candidate, target / name)
            moved.append(name)
        except Exception:
            pass
    if moved:
        try:
            debug_log("migrated %s from %s" % (", ".join(moved), source))
        except Exception:
            pass


INSTALL_DIR = _install_dir()
APP_DIR = _base_dir()

if getattr(sys, "frozen", False):
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", INSTALL_DIR))
else:
    BUNDLE_DIR = INSTALL_DIR

GAMES_FILE = APP_DIR / "games.json"
CONFIG_FILE = APP_DIR / "config.json"
STATS_FILE = APP_DIR / "stats.db"
DEFAULT_CLIENT_ID = ""

# 1.0.3: diagnostics. OFF by default — turn it on in Presence Settings →
# Advanced → Debug mode. It writes presence_debug.log next to the app: which
# window was in front, which pids were matched, and why a status was chosen.
# Only state *transitions* are written (deduped), so the file stays small.
# HYGGER_DEBUG=1 / =0 only sets the *initial* value; the checkbox in
# Settings -> General always wins once it is saved.
DEBUG_ENV = str(os.environ.get("HYGGER_DEBUG", "")).strip().lower()
DEBUG_ENV_DEFAULT = DEBUG_ENV not in ("", "0", "false", "no", "off")
DEBUG_LOG_ENABLED = DEBUG_ENV_DEFAULT
DEBUG_LOG_FILE = APP_DIR / "presence_debug.log"
DEBUG_LOG_MAX_BYTES = 1024 * 1024


def set_debug_enabled(value):
    """Turn the log on/off at runtime. An explicit setting always wins; the
    HYGGER_DEBUG environment variable only provides the startup default."""
    global DEBUG_LOG_ENABLED
    DEBUG_LOG_ENABLED = bool(value)


def debug_log(msg):
    if not DEBUG_LOG_ENABLED:
        return
    try:
        if DEBUG_LOG_FILE.exists() and DEBUG_LOG_FILE.stat().st_size > DEBUG_LOG_MAX_BYTES:
            DEBUG_LOG_FILE.unlink()
    except Exception:
        pass
    try:
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

SMART_TIME_FORMAT = "{h?}{h}h {mm}m {ss}s{/h}{!h}{m?}{m}m {ss}s{/m}{!m}{s}s{/!m}{/!h}"
# Status tick (focus/idle/UI). Paused↔Reading is also driven by hooks (usually << 1s).
POLL_INTERVAL = 1
# Full process list scan only (expensive, but one Toolhelp pass). Does NOT delay
# Paused/Reading while a game is already tracked. See snapshot_processes().
PROCESS_SCAN_INTERVAL = 3
# How long a process snapshot may be reused. The focus hook forces a refresh when
# a library executable comes to the front, so a game launch is still noticed fast.
PROCESS_SNAPSHOT_MAX_AGE = 2.5
# 1.0.4: two independent knobs.
#   UI_SCALE       - window/dialog sizes. 1.0 = follow the display DPI (a 125 %
#                    display gets a 25 % bigger window, which is what the previous
#                    build did).
#   UI_FONT_SCALE  - text size. 1.0 = the 96-dpi text size the app always had
#                    (10 pt -> 13.3 px), i.e. smaller than the DPI-scaled window.
UI_SCALE = 1.0
UI_FONT_SCALE = 1.0
SYSTEM_DPI = 96.0
IDLE_THRESHOLD = 1 * 60  # seconds without input → Idle while focused

DEFAULT_TEMPLATES = {
    "Reading": {
        "name": "{title}",
        "name_enabled": True,
        "details": "{developer} | {year}",
        "details_enabled": True,
        "state": "{status} • Total {total_time}",
        "state_enabled": True,
    },
    "Paused": {
        "name": "{title}",
        "name_enabled": True,
        "details": "{developer} | {year}",
        "details_enabled": True,
        "state": "{status} • Session {session_time} • Total {total_time}",
        "state_enabled": True,
    },
    "Idle": {
        "name": "{title}",
        "name_enabled": True,
        "details": "{developer} | {year}",
        "details_enabled": True,
        "state": "{status} • Session {session_time} • Total {total_time}",
        "state_enabled": True,
    },
}

DEFAULT_PRESENCE_OPTS = {
    "large_image_mode": "vndb",
    "custom_large_image": "",
    "large_text": "{title}",
    "small_image_mode": "none",
    "custom_small_image": "",
    "small_text": "",
    "show_timer": True,
    "button_enabled": True,
    "button_label": "View on VNDB",
    "button_url": "https://vndb.org/{vndb}",
    "session_time_format": SMART_TIME_FORMAT,
    "total_time_format": SMART_TIME_FORMAT,
    "debug_log": False,             # 1.0.3: Advanced → Debug mode (off by default)
}
DEFAULT_LAUNCHERS = []

# 1.0.4: update preferences (Settings -> Updates)
DEFAULT_UPDATE_OPTS = {
    "auto_check": True,
    "notify_startup": True,
    "skip_version": "",
}


def format_time(seconds: float, fmt: str = None) -> str:
    """Format seconds using a template.

    Basic placeholders (longer tokens first):
      {hh} {mm} {ss}  — zero-padded (03, 15, 02)
      {h}  {m}  {s}   — no leading zero (3, 15, 2)

    Conditional blocks:
      {h?}...{/h}   — include ... only if hours > 0
      {m?}...{/m}   — only if minutes > 0
      {s?}...{/s}   — only if seconds > 0
      {!h}...{/!h}  — include ... only if hours == 0  (same for m/s)

    Convenience tokens (value + trailing colon, only if > 0):
      {h:} {hh:} {m:} {mm:} {s:} {ss:}
    """
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    fmt = (fmt or "").strip()
    if not fmt or fmt.lower() == "auto":
        fmt = SMART_TIME_FORMAT

    result = fmt

    def apply_inv(text, letter, value):
        pattern = re.compile(rf"\{{!{letter}\}}(.*?)\{{\/!{letter}\}}", re.DOTALL)
        return pattern.sub(lambda mo: mo.group(1) if value == 0 else "", text)

    def apply_cond(text, letter, value):
        pattern = re.compile(rf"\{{{letter}\?}}(.*?)\{{\/{letter}\}}", re.DOTALL)
        return pattern.sub(lambda mo: mo.group(1) if value > 0 else "", text)

    result = apply_inv(result, "h", h)
    result = apply_inv(result, "m", m)
    result = apply_inv(result, "s", s)
    result = apply_cond(result, "h", h)
    result = apply_cond(result, "m", m)
    result = apply_cond(result, "s", s)

    result = result.replace("{hh:}", f"{h:02d}:" if h > 0 else "")
    result = result.replace("{h:}", f"{h}:" if h > 0 else "")
    result = result.replace("{mm:}", f"{m:02d}:" if m > 0 else "")
    result = result.replace("{m:}", f"{m}:" if m > 0 else "")
    result = result.replace("{ss:}", f"{s:02d}:" if s > 0 else "")
    result = result.replace("{s:}", f"{s}:" if s > 0 else "")

    result = result.replace("{hh}", f"{h:02d}")
    result = result.replace("{mm}", f"{m:02d}")
    result = result.replace("{ss}", f"{s:02d}")
    result = result.replace("{h}", str(h))
    result = result.replace("{m}", str(m))
    result = result.replace("{s}", str(s))
    return result


def parse_time_input(text: str) -> int:
    text = text.strip().lower().replace(" ", "")
    if not text:
        return 0
    if re.match(r"^\d+:\d{1,2}(:\d{1,2})?$", text):
        parts = [int(p) for p in text.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
    total = 0
    for num, unit in re.findall(r"(\d+)([hms]?)", text):
        num = int(num)
        if unit == "h":
            total += num * 3600
        elif unit == "m":
            total += num * 60
        else:
            total += num
    return total