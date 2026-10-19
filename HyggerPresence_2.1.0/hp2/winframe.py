"""Native Windows frame helpers for the frameless window.

Windows only performs Aero Snap (drag to the top = maximise, left/right = half
screen) and the smooth maximise/restore animation for windows that own a caption
and a thick frame. A Qt frameless window is a WS_POPUP, so it gets none of that.

The trick used here is the one every custom-chrome app uses:

  * give the HWND WS_THICKFRAME | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX |
    WS_MAXIMIZEBOX so Windows treats it as a normal resizable window;
  * answer WM_NCCALCSIZE with 0, so the client area covers the whole window and
    nothing of the native frame is painted;
  * answer WM_NCHITTEST with HTCAPTION over our own title bar, so dragging it is
    done by Windows (which is what enables snapping) and HTCLIENT everywhere
    else, so the buttons keep working.

The native frame is on by default; set HYGGER_NO_SNAP=1 to fall back to the
hand-drawn title bar.
"""

import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_CLIPCHILDREN = 0x02000000

WM_NCCALCSIZE = 0x0083
SM_CXSIZEFRAME = 32
SM_CXPADDEDBORDER = 92


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("hwndInsertAfter", ctypes.c_void_p),
                ("x", ctypes.c_int), ("y", ctypes.c_int),
                ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                ("flags", ctypes.c_uint)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3),
                ("lppos", ctypes.POINTER(WINDOWPOS))]
WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTCAPTION = 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

_LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

user32 = ctypes.windll.user32
try:
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SendMessageW.restype = _LONG_PTR
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
except Exception:                                    # pragma: no cover
    pass
try:
    user32.GetWindowLongPtrW.restype = _LONG_PTR
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = _LONG_PTR
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
except Exception:                                    # pragma: no cover
    pass


def native_snap_enabled():
    """Native frame is on by default; HYGGER_NO_SNAP=1 restores the hand-drawn one."""
    return os.environ.get("HYGGER_NO_SNAP", "") not in ("1", "true", "yes")


def apply_native_frame(widget):
    """Turn the frameless window into a native captioned window (invisible frame)."""
    if not native_snap_enabled():
        return False
    try:
        hwnd = int(widget.winId())
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style |= (WS_THICKFRAME | WS_CAPTION | WS_SYSMENU
                  | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_CLIPCHILDREN)
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        # ask DWM to keep the native shadow
        try:
            margins = wintypes.MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        except Exception:
            pass
        widget.update()
        return True
    except Exception:
        return False


def handle_native_event(widget, event_type, message, title_height=36,
                        border=6, skip_rects=()):
    """Answer WM_NCCALCSIZE / WM_NCHITTEST.

    All hit testing is done in PHYSICAL window coordinates (what Windows sends),
    never in Qt's logical pixels - on a 125% display the two differ by 1.25x and
    everything lands in the wrong place.

    Returns (handled, result) for Qt's nativeEvent, or None to let Qt handle it.
    """
    _dbg = os.environ.get("HYGGER_SNAP_DEBUG", "")
    if not native_snap_enabled():
        if _dbg:
            print("[snap] disabled", flush=True)
        return None
    try:
        msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
    except Exception as error:
        if os.environ.get("HYGGER_SNAP_DEBUG"):
            print("[snap] cast failed:", error, flush=True)
        return None

    if os.environ.get("HYGGER_SNAP_DEBUG"):
        print("[snap] msg=0x%x lparam=%s" % (msg.message, msg.lParam), flush=True)

    if msg.message == WM_NCCALCSIZE:
        # A maximised window is sized including the invisible frame, so without
        # this inset the top of the title bar ends up above the screen.
        if msg.wParam:
            try:
                raw = getattr(msg, "hWnd", None) or getattr(msg, "hwnd", None)
                handle = int(getattr(raw, "value", raw) or 0)
                if handle and user32.IsZoomed(handle):
                    params = ctypes.cast(
                        msg.lParam, ctypes.POINTER(NCCALCSIZE_PARAMS)).contents
                    pad = (user32.GetSystemMetrics(SM_CXSIZEFRAME)
                           + user32.GetSystemMetrics(SM_CXPADDEDBORDER))
                    frame = params.rgrc[0]
                    frame.left += pad
                    frame.right -= pad
                    frame.top += pad
                    frame.bottom -= pad
            except Exception:
                pass
        return True, 0

    if msg.message != WM_NCHITTEST:
        return None

    rect = wintypes.RECT()
    try:
        # NOTE: ctypes names the field hWnd (capital W); msg.hwnd silently
        # created a dummy attribute and GetWindowRect then failed.
        raw_handle = getattr(msg, "hWnd", None) or getattr(msg, "hwnd", None)
        handle = getattr(raw_handle, "value", raw_handle)
        if not user32.GetWindowRect(int(handle or 0), ctypes.byref(rect)):
            if os.environ.get("HYGGER_SNAP_DEBUG"):
                print("[snap] GetWindowRect failed", flush=True)
            return None
    except Exception as error:
        if os.environ.get("HYGGER_SNAP_DEBUG"):
            print("[snap] rect error:", error, flush=True)
        return None

    try:
        ratio = float(widget.devicePixelRatioF())
    except Exception:
        ratio = 1.0
    if ratio <= 0.1:
        ratio = 1.0

    x_screen = ctypes.c_short(msg.lParam & 0xFFFF).value
    y_screen = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
    x = x_screen - rect.left          # window relative, physical pixels
    y = y_screen - rect.top
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    edge = max(4, int(round(border * ratio)))
    if y < edge and x < edge:
        return True, HTTOPLEFT
    if y < edge and x > width - edge:
        return True, HTTOPRIGHT
    if y > height - edge and x < edge:
        return True, HTBOTTOMLEFT
    if y > height - edge and x > width - edge:
        return True, HTBOTTOMRIGHT
    if y < edge:
        return True, HTTOP
    if y > height - edge:
        return True, HTBOTTOM
    if x < edge:
        return True, HTLEFT
    if x > width - edge:
        return True, HTRIGHT

    title = int(round(title_height * ratio))
    if 0 <= y <= title:
        for item in skip_rects:
            bx = int(round(item.x() * ratio))
            by = int(round(item.y() * ratio))
            bw = int(round(item.width() * ratio))
            bh = int(round(item.height() * ratio))
            if bx <= x <= bx + bw and by <= y <= by + bh:
                return True, HTCLIENT      # a real button: let Qt click it
        return True, HTCAPTION             # native drag -> native Aero Snap
    return True, HTCLIENT


class NativeFrameFilter(QAbstractNativeEventFilter):
    """Application level filter: guarantees we see WM_NCHITTEST / WM_NCCALCSIZE.

    Overriding QWidget.nativeEvent is not reliable for these two messages on Qt 6,
    an application wide native event filter is.
    """

    def __init__(self, getter):
        super().__init__()
        self._getter = getter

    def nativeEventFilter(self, event_type, message):
        widget = self._getter()
        if widget is None:
            return False, 0
        # ONLY our own main window: otherwise every dialog loses its native frame
        # and its clicks get tested against the main window's geometry.
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            raw = getattr(msg, "hWnd", None) or getattr(msg, "hwnd", None)
            hwnd = int(getattr(raw, "value", raw) or 0)
            if hwnd != int(widget.winId()):
                return False, 0
        except Exception:
            return False, 0
        handled = handle_native_event(
            widget, event_type, message,
            title_height=widget.title_bar.height() + 2,
            skip_rects=widget.caption_button_rects())
        if handled is None:
            return False, 0
        return handled[0], int(handled[1])
