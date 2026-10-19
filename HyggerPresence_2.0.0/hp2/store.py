"""Hygger Presence 2.0 - config.json / games.json next to the entry script."""
import json
import os
import sys
import subprocess
from pathlib import Path

# Data lives next to the entry point: beside main.py when running from source,
# and beside the .exe in a PyInstaller build (where __file__ points into the
# temporary _MEIxxxx folder, which is deleted when the app exits).
from .core import APP_DIR
GAMES_FILE = APP_DIR / "games.json"
CONFIG_FILE = APP_DIR / "config.json"
STATS_FILE = APP_DIR / "stats.db"

TIMEFORMAT = "{h?}{h}h {mm}m {ss}s{/h}{!h}{m?}{m}m {ss}s{/m}{!m}{s}s{/!m}{/!h}"

DEFAULT_PRESENCE = {
    "large_image_mode": "vndb",        # vndb | custom
    "custom_large_image": "",
    "large_text": "{title}",
    "small_image_mode": "none",        # custom | none
    "custom_small_image": "",
    "small_text": "",
    "show_timer": True,
    "button_enabled": True,
    "button_label": "View on VNDB",
    "button_url": "https://vndb.org/{vndb}",
    "session_time_format": TIMEFORMAT,
    "total_time_format": TIMEFORMAT,
}

DEFAULT_CONFIG = {
    "client_id": "",
    "templates": {
        "Reading": {"name": "{title}", "details": "{developer} | {year}",
                    "details_enabled": True, "state_enabled": True,
                    "state": "{status} \u2022 Total {total_time}"},
        "Paused": {"name": "{title}", "details": "{developer} | {year}",
                   "details_enabled": True, "state_enabled": True,
                   "state": "{status} \u2022 Session {session_time} \u2022 Total {total_time}"},
        "Idle": {"name": "{title}", "details": "{developer} | {year}",
                 "details_enabled": True, "state_enabled": True,
                 "state": "{status} \u2022 Session {session_time} \u2022 Total {total_time}"},
    },
    "theme": "dark",
    "debug_log": False,
    "presence": dict(DEFAULT_PRESENCE),
    "launchers": [],
    "close_to_tray": True,
}


def _quarantine(path, reason):
    """Copy a file we could not read next to the original before touching it."""
    import time as _time
    stamp = _time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + ".corrupt-%s" % stamp)
    try:
        backup.write_bytes(path.read_bytes())
    except Exception:
        backup = None
    try:
        from .core import debug_log
        debug_log("could not read %s (%s); kept a copy at %s"
                  % (path.name, reason, backup.name if backup else "?"))
    except Exception:
        pass
    return backup


def _write_json(path, payload):
    """Write atomically, keeping one .bak of the previous good file."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if path.exists():
        try:
            path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
        except Exception:
            pass
    tmp.replace(path)


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_CONFIG)
            merged.update(data)
            # 1.x config: presence options lived in "presence_opts"
            if "presence_opts" in data and "presence" not in data:
                opts = dict(DEFAULT_PRESENCE)
                opts.update(data.get("presence_opts") or {})
                merged["presence"] = opts
            merged.setdefault("presence", dict(DEFAULT_PRESENCE))
            merged["presence"] = {**DEFAULT_PRESENCE, **merged.get("presence", {})}
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    _write_json(CONFIG_FILE, config)


LEGACY_DIR = APP_DIR.parent     # one level up: where the 1.x scripts live


def _json_is_empty(path):
    try:
        return path.read_text(encoding="utf-8").strip() in ("", "[]", "{}")
    except Exception:
        return False


def _stats_is_empty(path):
    """A stats.db with no sessions can safely be replaced."""
    if not path.exists():
        return True
    try:
        import sqlite3
        connection = sqlite3.connect(str(path))
        try:
            rows = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        except Exception:
            rows = 0
        finally:
            connection.close()
        return rows == 0
    except Exception:
        return False


def can_replace(name, path):
    """True when importing over `path` would not lose anything."""
    if not path.exists():
        return True
    if name.endswith(".json"):
        return _json_is_empty(path)
    if name == "stats.db":
        return _stats_is_empty(path)
    return False


def import_file(source):
    """Copy one file into the app folder if it would not clobber real data."""
    import shutil
    source = Path(source)
    name = source.name
    if name not in ("games.json", "config.json", "stats.db",
                    "stats.db-wal", "stats.db-shm"):
        return None
    target = APP_DIR / name
    if not can_replace(name, target):
        return None
    try:
        shutil.copy2(source, target)
        if name == "stats.db":
            for suffix in ("-wal", "-shm"):
                extra = Path(str(source) + suffix)
                if extra.exists():
                    shutil.copy2(extra, APP_DIR / (name + suffix))
        return name
    except Exception:
        return None


def import_legacy():
    """Copy games.json / config.json / stats.db from the folder one level up.

    Overwrites a target only when it is empty (an empty games.json is what the app
    writes when it closes with no library, which used to block the import).
    """
    imported = []
    for name in ("games.json", "config.json"):
        source = LEGACY_DIR / name
        if source.exists():
            done = import_file(source)
            if done:
                imported.append(done)
    if (LEGACY_DIR / "stats.db").exists():
        done = import_file(LEGACY_DIR / "stats.db")
        if done:
            imported.append(done)
    return imported


def startup_shortcut_path():
    appdata = os.environ.get("APPDATA") or ""
    return (Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            / "Startup" / "Hygger Presence.lnk")


def startup_enabled():
    return startup_shortcut_path().exists()


def set_startup(enabled):
    """Create/remove the Startup shortcut (same approach as 1.x)."""
    import subprocess
    path = startup_shortcut_path()
    if not enabled:
        try:
            path.unlink()
        except Exception:
            pass
        return not path.exists()
    entry = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else Path.cwd()
    target = sys.executable
    arguments = "" if getattr(sys, "frozen", False) else '"%s"' % entry
    if getattr(sys, "frozen", False):
        arguments = "--tray"
    script = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
              "$s.TargetPath='%s';$s.Arguments='%s';$s.WorkingDirectory='%s';"
              "$s.WindowStyle=7;$s.Save()"
              % (path, target, arguments, entry.parent))
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=False, creationflags=0x08000000)
    except Exception:
        return False
    return path.exists()


def sessions_count():
    """How many playtime sessions are in stats.db (0 when missing/broken)."""
    try:
        import sqlite3
        if not STATS_FILE.exists():
            return 0
        connection = sqlite3.connect(str(STATS_FILE))
        try:
            return connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        finally:
            connection.close()
    except Exception:
        return 0


def data_summary():
    return {"games": len(load_games()), "sessions": sessions_count()}


def load_games():
    if GAMES_FILE.exists():
        try:
            games = json.loads(GAMES_FILE.read_text(encoding="utf-8"))
            if not isinstance(games, list):
                raise ValueError("games.json is not a list")
            for game in games:
                game.setdefault("total_seconds", 0)
                game.setdefault("process_names", [])
            return games
        except Exception as error:
            _quarantine(GAMES_FILE, error)
            return []
    return []


def save_games(games):
    # an empty list must never silently replace a library that failed to load
    if not games and GAMES_FILE.exists() and not _json_is_empty(GAMES_FILE):
        _quarantine(GAMES_FILE, "refusing to overwrite a non-empty library with []")
    _write_json(GAMES_FILE, games)
