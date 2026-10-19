"""Hygger Presence 1.0.4 - Windows API layer (no UI, no app state).

ctypes prototypes, the foreground window, idle time, one Toolhelp process
snapshot per scan, parent/ancestor lookups and the "what .exe files live in this
folder" scan. Everything here is process-wide and thread-safe enough for the
app's polling model (values are read/assigned atomically).
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

from .core import PROCESS_SNAPSHOT_MAX_AGE

# caches shared with the app (imported explicitly by name where needed)
_proc_cache = {"time": 0.0, "rows": [], "parents": {}, "names": {}}
_resolve_cache = {}
_folder_exe_cache = {}

__all__ = [
    "user32", "kernel32", "LASTINPUTINFO", "PROCESSENTRY32W",
    "get_foreground_pid", "get_idle_seconds", "snapshot_processes",
    "expire_process_snapshot", "get_parent_map", "get_ancestor_pids", "is_under",
    "folder_exe_names", "wait_for_process_exit",
    "_proc_cache", "_resolve_cache", "_folder_exe_cache",
]


# ---------- Windows helpers ----------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


# 1.0.3: declare prototypes instead of relying on ctypes defaults. With defaults
# every HWND comes back as a signed 32-bit int and DWORD as a signed int, which is
# undefined behaviour on 64-bit Windows: a truncated HWND made
# GetWindowThreadProcessId return pid 0 (= "no foreground window" = Paused), and
# GetTickCount() went negative after ~24.8 days of uptime (Idle never fired).
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetForegroundWindow.argtypes = []
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetLastInputInfo.restype = wintypes.BOOL
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.GetTickCount.argtypes = []
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def get_foreground_pid(retries=3, delay=0.01):
    """PID owning the foreground window, or None.

    Games report "no foreground window" for a moment while switching in/out of
    fullscreen (and while UAC / the lock screen / another virtual desktop owns
    the input), so sample a few times before giving up. 1.0.2 treated a single
    failed sample as "Paused", which is how a game could look permanently paused.
    """
    for attempt in range(max(1, retries)):
        try:
            hwnd = user32.GetForegroundWindow()
        except Exception:
            hwnd = None
        if hwnd:
            pid = wintypes.DWORD()
            try:
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            except Exception:
                pid.value = 0
            if pid.value:
                return pid.value
        if attempt + 1 < retries:
            time.sleep(delay)
    return None


def get_idle_seconds():
    """Seconds since last keyboard/mouse input (OS API — no input hooks)."""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    try:
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        # Both are 32-bit tick counters: mask to unsigned and use the wrap-around
        # difference, so a tick value with bit 31 set never yields a negative
        # (which would silently disable the Idle state).
        tick = kernel32.GetTickCount() & 0xFFFFFFFF
        last = lii.dwTime & 0xFFFFFFFF
        return ((tick - last) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0.0





def snapshot_processes(max_age=PROCESS_SNAPSHOT_MAX_AGE):
    """[(pid, ppid, name_lower)] for every process, from ONE Toolhelp pass.

    This is the CPU fix. psutil.process_iter(["pid","name","exe"]) opens a handle
    for *every* process (≈300 OpenProcess + 2 queries each) and the old code then
    ran Path.resolve() on each result, every 3 s — that burst is what showed up as
    a 1–2 % spike. Toolhelp returns pid/ppid/name for the whole system in a single
    call, needs no handles, and also works for elevated games where psutil gets
    AccessDenied. Exe paths (the only expensive lookup left) are now fetched only
    for processes whose name could belong to the library.

    Cached for `max_age` seconds; focus events shorten it (see the hook).
    """
    now = time.monotonic()
    if _proc_cache["rows"] and (now - _proc_cache["time"]) < max_age:
        return _proc_cache["rows"]

    rows, parents, names = [], {}, {}
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return _proc_cache["rows"]
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            if pid:
                ppid = int(entry.th32ParentProcessID)
                name = (entry.szExeFile or "").lower()
                rows.append((pid, ppid, name))
                parents[pid] = ppid
                names[pid] = name
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    except Exception:
        pass
    finally:
        try:
            kernel32.CloseHandle(snap)
        except Exception:
            pass

    if rows:
        _proc_cache.update({"time": now, "rows": rows, "parents": parents, "names": names})
    return _proc_cache["rows"]


def expire_process_snapshot(min_age=2.0):
    """Force the next snapshot to re-enumerate (used by callers that need fresh
    data right now). NOT called on every focus event: a Toolhelp pass over ~300
    processes costs several ms, and pids + parent map already come from the same
    snapshot, so a focus-only refresh buys nothing but a CPU spike.
    """
    if (time.monotonic() - _proc_cache["time"]) >= min_age:
        _proc_cache["time"] = 0.0


def get_parent_map(max_age=PROCESS_SNAPSHOT_MAX_AGE):
    """{pid: ppid} — same snapshot data, no extra syscall."""
    snapshot_processes(max_age)
    return _proc_cache["parents"]


def get_ancestor_pids(pid, max_depth=12):
    """[parent, grandparent, ...] of pid — the task-manager tree, upwards."""
    parents = get_parent_map()
    out = []
    seen = {pid}
    cur = pid
    for _ in range(max_depth):
        nxt = parents.get(cur)
        if not nxt or nxt == cur or nxt in seen:
            break
        out.append(nxt)
        seen.add(nxt)
        cur = nxt
    return out


def is_under(path, folder, max_depth=2):
    """True when `path` is inside `folder` (0 = same folder, 1 = bin\\, ...)."""
    if not path or not folder:
        return False
    try:
        p = str(path).lower().rstrip("\\/")
        f = str(folder).lower().rstrip("\\/")
    except Exception:
        return False
    if not f or not p.startswith(f + os.sep):
        return False
    return p[len(f) + 1:].count(os.sep) <= max_depth





def folder_exe_names(folder, max_depth=2, limit=400, max_age=600.0):
    """Lowercased names of the .exe files inside `folder` (and a couple of subdirs).

    1.0.3: this is what lets the app work without the user knowing about
    "process_names". A game very often starts a *differently named* executable
    from its own directory (patched exe, bundled engine, SiglusEngine.exe...);
    that is exactly when detection used to fail and people blamed the app.

    Cached per folder, invalidated by the folder's mtime or after `max_age`.
    """
    if not folder:
        return frozenset()
    key = str(folder).lower()
    now = time.monotonic()
    try:
        mtime = os.stat(folder).st_mtime
    except Exception:
        return frozenset()
    hit = _folder_exe_cache.get(key)
    if hit and hit[0] == mtime and (now - hit[1]) < max_age:
        return hit[2]

    names = set()

    def scan(directory, depth):
        if depth > max_depth or len(names) >= limit:
            return
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_file():
                            if entry.name.lower().endswith(".exe"):
                                names.add(entry.name.lower())
                        elif entry.is_dir() and depth < max_depth:
                            scan(entry.path, depth + 1)
                    except Exception:
                        continue
        except Exception:
            pass

    scan(str(folder), 0)
    result = frozenset(names)
    _folder_exe_cache[key] = (mtime, now, result)
    return result

def wait_for_process_exit(pid, callback, timeout=None):
    """Call `callback()` the moment `pid` exits - no polling, no CPU.

    Opening with SYNCHRONIZE and blocking in WaitForSingleObject costs one handle
    and one sleeping thread, which is how the presence can be cleared the instant
    a game closes instead of on the next poll. Returns a threading.Thread (daemon)
    or None when the handle could not be opened (elevated game, etc.).
    """
    SYNCHRONIZE = 0x00100000
    INFINITE = 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32
    try:
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    except Exception:
        pass
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        return None
    ms = INFINITE if timeout is None else int(timeout * 1000)
    thread_ref = {}

    def waiter():
        try:
            kernel32.WaitForSingleObject(handle, ms)
        except Exception:
            pass
        finally:
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
        if thread_ref.get("cancelled"):
            return
        try:
            callback()
        except Exception:
            pass

    def cancel():
        thread_ref["cancelled"] = True

    thread = threading.Thread(target=waiter, daemon=True, name="proc-exit-wait")
    thread_ref["thread"] = thread
    thread.cancel = cancel
    thread.start()
    return thread
