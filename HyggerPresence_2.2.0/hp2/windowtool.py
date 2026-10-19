"""Resize another window to a given client size.

Games that only offer "drag the corner" scaling can be put back to their native
resolution with SetWindowPos. The frame is taken into account, so asking for
1920x1080 gives a 1920x1080 drawing area, not a 1920x1080 outer window.

Limitations that cannot be worked around from outside the game:
  * exclusive full screen windows ignore it (switch to windowed first),
  * a game that enforces its own aspect ratio may snap back immediately,
  * some engines only read the size at start up.
"""

import ctypes

GWL_STYLE = -16
GWL_EXSTYLE = -20
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _user32():
    try:
        return ctypes.windll.user32
    except Exception:
        return None


def foreground_window():
    """(hwnd, title, client width, client height) of the foreground window."""
    user32 = _user32()
    if user32 is None:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    width, height = client_size(hwnd)
    return hwnd, buffer.value, width, height


def client_size(hwnd):
    user32 = _user32()
    if user32 is None or not hwnd:
        return (0, 0)
    rect = _RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return (0, 0)
    return (rect.right - rect.left, rect.bottom - rect.top)


def _dpi(hwnd):
    user32 = _user32()
    try:
        return int(user32.GetDpiForWindow(hwnd)) or 96
    except Exception:
        return 96


def _frame_size(hwnd, width, height):
    """Outer size that gives the requested client area."""
    user32 = _user32()
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    rect = _RECT(0, 0, width, height)
    dpi = _dpi(hwnd)
    try:
        # Windows 10 1607+: correct for the monitor's scaling
        if user32.AdjustWindowRectExForDpi(ctypes.byref(rect), style, False,
                                           exstyle, dpi):
            return (rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        pass
    if user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, exstyle):
        return (rect.right - rect.left, rect.bottom - rect.top)
    return (width, height)


def resize_client(hwnd, width, height):
    """Resize a window so its client area becomes width x height."""
    user32 = _user32()
    if user32 is None or not hwnd:
        return False, "No window selected."
    width = max(320, min(7680, int(width)))
    height = max(240, min(4320, int(height)))
    outer_w, outer_h = _frame_size(hwnd, width, height)
    rect = _RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
    ok = user32.SetWindowPos(hwnd, 0, rect.left, rect.top, outer_w, outer_h, flags)
    if not ok:
        return False, "Windows refused the resize."
    got_w, got_h = client_size(hwnd)
    if (got_w, got_h) != (width, height):
        return False, ("The game kept its own size (%dx%d)." % (got_w, got_h))
    return True, "%dx%d" % (got_w, got_h)


def resize_foreground(width, height):
    """Convenience wrapper: resize whatever is in front."""
    found = foreground_window()
    if found is None:
        return False, "No foreground window."
    hwnd, title, _w, _h = found
    ok, message = resize_client(hwnd, width, height)
    return ok, ("%s: %s" % (title or "window", message)) if ok else message


PRESETS = ((1280, 720), (1366, 768), (1600, 900), (1920, 1080), (2560, 1440))


def list_windows():
    """Visible top level windows: [(hwnd, title, width, height, process)]."""
    import os
    user32 = _user32()
    if user32 is None:
        return []
    own = os.getpid()
    found = []
    prototype = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _param):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own:
                return True
            width, height = client_size(hwnd)
            if width < 320 or height < 240:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip()
            if not title:
                return True
            try:
                import psutil
                name = psutil.Process(pid.value).name()
            except Exception:
                name = ""
            found.append((int(hwnd), title, width, height, name))
        except Exception:
            return True
        return True

    try:
        user32.EnumWindows(prototype(callback), 0)
    except Exception:
        return []
    found.sort(key=lambda item: item[1].lower())
    return found
