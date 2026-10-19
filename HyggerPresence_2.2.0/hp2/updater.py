"""Hygger Presence 2.0 - update check and self update.

The check is a GitHub release lookup. Installing means: download the release .exe,
then hand the swap to a tiny .bat that waits for this process to exit, replaces
the executable in place and relaunches it. Only the exe is touched - games.json,
config.json and stats.db stay where they are.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

GITHUB_REPO = "hyther1111/HyggerPresence"


def version_tuple(value):
    parts = []
    for piece in re.split(r"[^\d]+", str(value or "")):
        if piece.isdigit():
            parts.append(int(piece))
    return tuple(parts) if parts else (0,)


def is_newer(candidate, current):
    return version_tuple(candidate) > version_tuple(current)


def latest_release(timeout=12):
    """-> dict(status='ok'|'no-release', version, url, notes, assets) or raises."""
    url = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO
    response = requests.get(url, timeout=timeout,
                            headers={"Accept": "application/vnd.github+json"})
    if response.status_code == 404:
        return {"status": "no-release",
                "url": "https://github.com/%s/releases" % GITHUB_REPO}
    response.raise_for_status()
    data = response.json()
    return {
        "status": "ok",
        "version": (data.get("tag_name") or "").lstrip("vV"),
        "tag": data.get("tag_name") or "",
        "url": data.get("html_url") or "https://github.com/%s/releases/latest" % GITHUB_REPO,
        "notes": (data.get("body") or "").strip(),
        "assets": data.get("assets") or [],
    }


def pick_exe(info):
    assets = [a for a in info.get("assets") or []
              if str(a.get("name", "")).lower().endswith(".exe")]
    for asset in assets:
        if "hygger" in str(asset.get("name", "")).lower():
            return asset
    return assets[0] if assets else None


def _unblock(path):
    """Remove the mark-of-the-web so Windows does not refuse to run the file."""
    try:
        os.remove("%s:Zone.Identifier" % path)
    except OSError:
        pass


def download(asset, target, timeout=120):
    with requests.get(asset["browser_download_url"], stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with open(target, "wb") as handle:
            for chunk in response.iter_content(1 << 16):
                if chunk:
                    handle.write(chunk)
    _unblock(target)
    return Path(target).stat().st_size


def update_script(new_exe, target):
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        'set "_MEIPASS2="\r\n'
        'set "_MEIPASS="\r\n'
        'set "PYTHONHOME="\r\n'
        'set "PYTHONPATH="\r\n'
        ":wait\r\n"
        'tasklist /FI "PID eq @PID@" 2>NUL | find "@PID@" >NUL\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >NUL\r\n"
        "  goto wait\r\n"
        ")\r\n"
        'move /Y "@NEW@" "@TARGET@" >NUL\r\n'
        "if errorlevel 1 (\r\n"
        "  echo Update failed.\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        'start "" "@TARGET@"\r\n'
        'del "%~f0"\r\n'
    ).replace("@PID@", str(os.getpid())).replace("@NEW@", str(new_exe)) \
     .replace("@TARGET@", str(target))


def can_self_update():
    """Only a frozen build can replace itself."""
    return bool(getattr(sys, "frozen", False))


def apply_update(asset):
    """Download + schedule the swap. Returns (ok, message)."""
    if not can_self_update():
        return False, "This build runs from source, so it cannot replace itself."
    target = Path(sys.executable)
    new_exe = Path(tempfile.gettempdir()) / ("HyggerPresence-%s.exe"
                                             % (asset.get("name") or "new"))
    try:
        size = download(asset, new_exe)
    except Exception as error:
        return False, "Download failed: %s" % error
    if size < 100_000:
        return False, "The download looks incomplete (%d bytes)." % size
    script = new_exe.parent / "hygger_update.bat"
    script.write_text(update_script(new_exe, target), encoding="ascii", errors="ignore")
    # do not hand our PyInstaller environment to the updater
    clean_env = {key: value for key, value in os.environ.items()
                 if not key.upper().startswith(("_MEI", "PYTHON"))}
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000,
                     close_fds=True, env=clean_env)
    return True, "Restarting to finish the update."
