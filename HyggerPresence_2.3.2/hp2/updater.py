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

from . import net

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
    response = net.get(url, timeout=timeout,
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


def download(asset, target, timeout=120, progress=None):
    """Stream the release .exe to `target`.

    `progress(received_bytes, total_bytes)` is called after every chunk so the
    caller can show a percentage. total is 0 when the server sends no
    Content-Length.
    """
    with net.get(asset["browser_download_url"], stream=True, timeout=timeout) as response:
        response.raise_for_status()
        try:
            total = int(response.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        received = 0
        with open(target, "wb") as handle:
            for chunk in response.iter_content(1 << 16):
                if not chunk:
                    continue
                handle.write(chunk)
                received += len(chunk)
                if progress is not None:
                    try:
                        progress(received, total)
                    except Exception:
                        pass          # a broken progress callback must not kill the download
    _unblock(target)
    return Path(target).stat().st_size


def update_script(new_exe, target):
    """Batch file that swaps the exe once this process is gone.

    It runs without a console window, so nothing here may block on input: every
    failure is written to %TEMP%\\hygger_update_error.txt instead of `pause`.
    """
    log = Path(tempfile.gettempdir()) / "hygger_update_error.txt"
    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        # PyInstaller leaves the extraction folder in the environment. A new
        # process that inherits it tries to reuse the OLD _MEI folder - which
        # this process deletes on exit - and dies with
        # "Failed to load Python DLL ...\_MEIxxxxx\python311.dll".
        'set "_MEIPASS2="\r\n'
        'set "_MEIPASS="\r\n'
        'set "_PYI_ARCHIVE_FILE="\r\n'
        'set "_PYI_PARENT_PROCESS_LEVEL="\r\n'
        'set "_PYI_SPLASH_IPC="\r\n'
        'set "PYTHONHOME="\r\n'
        'set "PYTHONPATH="\r\n'
        'set "PYTHONSTARTUP="\r\n'
        'set "TCL_LIBRARY="\r\n'
        'set "TK_LIBRARY="\r\n'
        "set /a tries=0\r\n"
        ":wait\r\n"
        # the spaces matter: without them a PID can match a memory/session column
        'tasklist /FI "PID eq @PID@" 2>NUL | find " @PID@ " >NUL\r\n'
        "if not errorlevel 1 (\r\n"
        "  ping -n 2 127.0.0.1 >NUL\r\n"
        "  goto wait\r\n"
        ")\r\n"
        "ping -n 3 127.0.0.1 >NUL\r\n"      # let the bootloader delete its folder
        ":move\r\n"
        'move /Y "@NEW@" "@TARGET@" >NUL 2>&1\r\n'
        "if not errorlevel 1 goto started\r\n"
        "set /a tries+=1\r\n"
        "if %tries% geq 20 goto failed\r\n"
        "ping -n 2 127.0.0.1 >NUL\r\n"
        "goto move\r\n"
        ":failed\r\n"
        'echo Could not replace "@TARGET@" (still in use?) %date% %time% > "@LOG@"\r\n'
        'echo The new version is at "@NEW@" >> "@LOG@"\r\n'
        'del "%~f0"\r\n'
        "exit /b 1\r\n"
        ":started\r\n"
        # start the new exe from the folder it now lives in, so relative data
        # paths (%APPDATA% is used, but a portable copy may not have that) work
        'cd /d "@DIR@"\r\n'
        'start "" /D "@DIR@" "@TARGET@"\r\n'
        'del "%~f0"\r\n'
    )
    return (script.replace("@PID@", str(os.getpid()))
            .replace("@NEW@", str(new_exe))
            .replace("@TARGET@", str(target))
            .replace("@DIR@", str(Path(target).parent))
            .replace("@LOG@", str(log)))


def can_self_update():
    """Only a frozen build can replace itself."""
    return bool(getattr(sys, "frozen", False))


_ENV_KEEP = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "PATH",
             "COMSPEC", "PATHEXT", "USERPROFILE", "USERNAME", "USERDOMAIN",
             "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
             "PROGRAMDATA", "HOMEDRIVE", "HOMEPATH", "HOMESHARE", "OS",
             "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
             "PUBLIC", "ALLUSERSPROFILE", "SESSIONNAME")


def clean_env():
    """A minimal environment: nothing from PyInstaller may reach the updater.

    Inheriting _MEIPASS / _PYI_* made the relaunched exe load the Python DLL
    from the _MEI folder of the process that was just replaced (it had been
    deleted by then), which failed with "Failed to load Python DLL".
    """
    return {key: value for key, value in os.environ.items()
            if key.upper() in _ENV_KEEP}


def download_update(asset, progress=None):
    """Download the release exe to %TEMP% and check it. -> (ok, message, path)."""
    if not can_self_update():
        return False, "This build runs from source, so it cannot replace itself.", None
    new_exe = Path(tempfile.gettempdir()) / ("HyggerPresence-%s.exe"
                                             % (asset.get("name") or "new"))
    try:
        size = download(asset, new_exe, progress=progress)
    except Exception as error:
        return False, "Download failed: %s" % error, None
    if size < 100_000:
        return False, "The download looks incomplete (%d bytes)." % size, None
    expected = asset.get("size")
    if expected and size != expected:
        return False, ("The download looks incomplete (%d of %s bytes). "
                       "Try again." % (size, expected)), None
    try:
        with open(new_exe, "rb") as handle:
            head = handle.read(2)
    except OSError as error:
        return False, "Could not read the download: %s" % error, None
    if head != b"MZ":
        return False, "The downloaded file is not a Windows executable.", None
    return True, "", new_exe


def install_on_exit(new_exe, target=None):
    """Hand the swap to a .bat that waits for this process to exit.

    Call this from the shutdown path only: the batch waits for our PID, so
    scheduling it while the app keeps running leaves a hidden cmd.exe waiting.
    """
    if not can_self_update() or not new_exe:
        return False
    new_exe = Path(new_exe)
    if not new_exe.exists():
        return False
    target = Path(target or sys.executable)
    script = Path(tempfile.gettempdir()) / "hygger_update.bat"
    try:
        script.write_text(update_script(new_exe, target), encoding="ascii",
                          errors="ignore")
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000,
                         close_fds=True, env=clean_env())
    except Exception:
        return False
    return True


def apply_update(asset, progress=None):
    """Download the update and install it on exit. Returns (ok, message).

    Kept for callers that do not need the restart prompt; the UI downloads with
    download_update() and decides when to call install_on_exit().
    """
    ok, message, new_exe = download_update(asset, progress=progress)
    if not ok:
        return False, message
    if not install_on_exit(new_exe):
        return False, "Could not schedule the update."
    return True, "Restarting to finish the update."
