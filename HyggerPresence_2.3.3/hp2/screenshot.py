"""Screenshot capture and storage.

Self contained: Qt for the grab, ctypes for the Win32 window geometry.

Everything the app writes lives under one folder, so screenshots taken by other
programs never show up in the gallery:

    <base>/HyggerPresence/<game title>/2026-10-19-14-07-33.png
    <base>/HyggerPresence/<game title>/2026-10-19-14-07-33_2.png   (same second)

<base> is the Pictures folder by default and can be changed in the settings.
"""

import ctypes
import os
import re
import time
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap

APP_FOLDER = "HyggerPresence"
FOLDER_FALLBACK = "Unknown game"
INVALID_CHARS = '<>:"/\\|?*'
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


# ------------------------------------------------------------------ pure helpers
def sanitise(name, fallback=FOLDER_FALLBACK):
    """Make a game title usable as a Windows folder name."""
    text = (name or "").strip()
    for char in INVALID_CHARS:
        text = text.replace(char, "_")
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:80] or fallback


def scale_rect(rect, factor, bounds):
    """Map a rectangle from widget coordinates to pixmap coordinates.

    The screen grab is in physical pixels while Qt lays widgets out in logical
    ones, so a selection made by the user has to be multiplied by
    physical / logical before it is used to crop the grab.
    """
    scaled = QRect(int(rect.x() * factor), int(rect.y() * factor),
                   int(rect.width() * factor), int(rect.height() * factor))
    return scaled.intersected(bounds)


def describe_size(rect):
    return "%d x %d" % (max(0, rect.width()), max(0, rect.height()))


def default_base_dir():
    """Pictures\\HyggerPresence, created on demand."""
    from PySide6.QtCore import QStandardPaths
    folder = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    base = Path(folder) if folder else Path.home()
    return base / APP_FOLDER


def _write_png(pixmap, path):
    """Encode with the fastest zlib level that still produces a real PNG."""
    from PySide6.QtGui import QImageWriter
    image = pixmap.toImage()
    for level in (1, 3, 6):
        writer = QImageWriter(str(path), b"png")
        try:
            writer.setCompression(level)
        except Exception:
            pass
        if writer.write(image):
            return True
    try:
        return bool(image.save(str(path), "PNG"))
    except Exception:
        return False


def trim_bars(pixmap, threshold=12, inset=4):
    """Remove uniform black borders (pillarbox or letterbox).

    A window border can leave one or two non-black pixels at the edge, so up to
    `inset` pixels are skipped before giving up on a side, and a column counts as
    a bar when 95% of the sampled pixels are black. Returns the original pixmap
    when no side looks like a bar, so a dark scene is never cropped by accident.
    """
    if pixmap is None or pixmap.isNull():
        return pixmap
    image = pixmap.toImage()
    width, height = image.width(), image.height()
    if width < 48 or height < 48:
        return pixmap

    def is_dark(value):
        return ((value >> 16 & 0xFF) <= threshold
                and (value >> 8 & 0xFF) <= threshold
                and (value & 0xFF) <= threshold)

    rows = [y for y in range(0, height, max(1, height // 80))]
    cols = [x for x in range(0, width, max(1, width // 80))]

    def column_dark(x):
        hits = sum(1 for y in rows if is_dark(image.pixel(x, y)))
        return hits >= max(1, int(len(rows) * 0.95))

    def row_dark(y):
        hits = sum(1 for x in cols if is_dark(image.pixel(x, y)))
        return hits >= max(1, int(len(cols) * 0.95))

    def run(start_, stop, step, dark):
        """Length of the leading run of dark lines, skipping a small inset."""
        skipped = 0
        index = start_
        while index != stop:
            if dark(index):
                break
            skipped += 1
            if skipped > inset:
                return 0
            index += step
        length = 0
        while index != stop and dark(index):
            length += 1
            index += step
        return length

    half_w, half_h = width // 2, height // 2
    left = run(0, half_w, 1, column_dark)
    right = run(width - 1, half_w - 1, -1, column_dark)
    top = run(0, half_h, 1, row_dark)
    bottom = run(height - 1, half_h - 1, -1, row_dark)

    if left + right + top + bottom == 0:
        return pixmap
    rect = QRect(left, top, max(8, width - left - right),
                 max(8, height - top - bottom))
    cropped = pixmap.copy(rect)
    if cropped.isNull():
        return pixmap
    try:
        from .core import debug_log
        debug_log("trim %dx%d -> %dx%d (l=%d r=%d t=%d b=%d)"
                  % (width, height, cropped.width(), cropped.height(),
                     left, right, top, bottom))
    except Exception:
        pass
    return cropped


class ScreenshotStore:
    """Folder layout and file naming."""

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else default_base_dir()
        if base_dir:
            try:
                self.base_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                # a config copied from another PC points at that PC's user
                # folder, where every save would fail without a word
                self.base_dir = default_base_dir()

    @property
    def root(self):
        return self.base_dir

    def folder_for(self, title):
        return self.root / sanitise(title)

    def next_path(self, title, when=None):
        folder = self.folder_for(title)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(when or time.time()))
        candidate = folder / ("%s.png" % stamp)
        counter = 2
        while candidate.exists():
            candidate = folder / ("%s_%d.png" % (stamp, counter))
            counter += 1
        return candidate

    def save(self, pixmap, title, when=None):
        path = self.next_path(title, when)
        # zlib level 1 instead of the default 6: ~4x faster encode, files are
        # bigger but the measured 270 ms per 1702x958 frame was the CPU spike.
        if not _write_png(pixmap, path):
            raise OSError("could not write %s" % path)
        return path

    # ------------------------------------------------------------------- read
    def games_with_shots(self):
        """[(folder name, count)], folders that hold at least one image."""
        result = []
        if not self.root.exists():
            return result
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir():
                continue
            images = [p for p in folder.iterdir()
                      if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
            if images:
                result.append((folder.name, len(images)))
        return result

    def shots_for(self, folder=""):
        """Newest first; an empty folder name means every game."""
        images = []
        if not self.root.exists():
            return images
        if folder:
            target = self.root / folder
            if not target.exists():
                return images
            images = [p for p in target.iterdir()
                      if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
        else:
            for sub in self.root.iterdir():
                if sub.is_dir():
                    images.extend(p for p in sub.iterdir()
                                  if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
        def age(path):
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0
        return sorted(images, key=age, reverse=True)

    @staticmethod
    def delete(path):
        try:
            Path(path).unlink()
            return True
        except OSError:
            return False


# --------------------------------------------------------------------- Win32
class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def foreground_client_rect():
    """Screen rectangle of the foreground window's client area (no title bar)."""
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return None
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = _RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = _POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    return QRect(origin.x, origin.y, width, height)


# --------------------------------------------------------------------- capture
def pixmap_crop_hints(pixmap, screen):
    """Candidate factors that map logical coordinates onto the grab."""
    logical = max(1, screen.geometry().width())
    factor = pixmap.width() / logical
    return (1.0,) if abs(factor - 1.0) < 0.01 else (1.0, factor)


UPSCALERS = ("magpie", "lossless scaling", "lsfg")


def foreground_process_name():
    """Executable name of the foreground window's process, lower case."""
    hwnd = foreground_hwnd()
    if not hwnd:
        return ""
    try:
        user32 = ctypes.windll.user32
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import psutil
        return psutil.Process(pid.value).name().lower()
    except Exception:
        return ""


def _window_rect(hwnd):
    rect = _RECT()
    try:
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
    except Exception:
        return None
    return rect


def _process_name(pid):
    try:
        import psutil
        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def foreground_hwnd():
    try:
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


# Magpie's scaling window. It is owned by the window it scales, in fullscreen
# and windowed mode alike, and the game keeps the keyboard focus meanwhile.
MAGPIE_CLASS = "Window_Magpie_967EB565-6F73-4E94-AE53-00CC42592A22"
# windowed mode draws into this child; the parent adds a border around it
MAGPIE_RENDERER_CLASS = "Magpie_Renderer"


def _class_name(hwnd):
    buffer = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _is_shown(hwnd):
    """Visible, not minimised and not cloaked (another virtual desktop)."""
    user32 = ctypes.windll.user32
    if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return False
    cloaked = ctypes.c_int(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))  # DWMWA_CLOAKED
    except Exception:
        pass
    return not cloaked.value


def _client_rect(hwnd):
    rect = _RECT()
    user32 = ctypes.windll.user32
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = _POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    if rect.right <= 0 or rect.bottom <= 0:
        return None
    return QRect(origin.x, origin.y, rect.right, rect.bottom)


def upscaled_rect(game_hwnd, game_rect):
    """Where an upscaler draws the game on screen, or None when nothing does.

    Magpie and friends leave the game window at its own size (1280x720, say)
    and paint the scaled picture in a topmost window of their own, so the
    pixels inside the game's client area are only a piece of the upscaled
    image. Windows above the game are walked top to bottom.
    """
    try:
        user32 = ctypes.windll.user32
    except Exception:
        return None
    centre = game_rect.center()
    hwnd = user32.GetTopWindow(0)
    for _ in range(1000):
        if not hwnd or hwnd == game_hwnd:
            break
        if _is_shown(hwnd):
            if _class_name(hwnd) == MAGPIE_CLASS:
                if user32.GetWindow(hwnd, 4) == game_hwnd:   # GW_OWNER
                    renderer = user32.FindWindowExW(hwnd, 0, MAGPIE_RENDERER_CLASS, None)
                    if renderer and _is_shown(renderer):
                        return _client_rect(renderer)
                    return _client_rect(hwnd)
            else:
                # other upscalers: a window of theirs that covers the game
                rect = _client_rect(hwnd)
                if (rect is not None and rect.contains(centre)
                        and rect.width() * rect.height()
                        > game_rect.width() * game_rect.height()):
                    pid = ctypes.c_ulong(0)
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    name = _process_name(pid.value).replace(" ", "")
                    if any(tool.replace(" ", "") in name for tool in UPSCALERS):
                        return rect
        hwnd = user32.GetWindow(hwnd, 2)   # GW_HWNDNEXT
    return None


def _grab_rect(rect):
    """Copy a rectangle of the composited desktop, in physical pixels.

    Win32 coordinates go straight to BitBlt, so the grab is right on any
    monitor and at any DPI scale. CAPTUREBLT includes layered windows, which
    is what Magpie draws with.
    """
    from PySide6.QtGui import QImage
    try:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
    except Exception:
        return None
    left = user32.GetSystemMetrics(76)     # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)
    desktop = QRect(left, top, user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))
    rect = rect.intersected(desktop)
    width, height = rect.width(), rect.height()
    if width < 4 or height < 4:
        return None

    handle = ctypes.c_void_p
    user32.GetDC.restype = handle
    user32.ReleaseDC.argtypes = (handle, handle)
    gdi32.CreateCompatibleDC.restype = handle
    gdi32.CreateCompatibleDC.argtypes = (handle,)
    gdi32.CreateCompatibleBitmap.restype = handle
    gdi32.CreateCompatibleBitmap.argtypes = (handle, ctypes.c_int, ctypes.c_int)
    gdi32.SelectObject.restype = handle
    gdi32.SelectObject.argtypes = (handle, handle)
    gdi32.BitBlt.argtypes = (handle, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, handle, ctypes.c_int, ctypes.c_int,
                             ctypes.c_uint)
    gdi32.GetDIBits.argtypes = (handle, handle, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
    gdi32.DeleteObject.argtypes = (handle,)
    gdi32.DeleteDC.argtypes = (handle,)

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc,
                            rect.x(), rect.y(), 0x00CC0020 | 0x40000000):  # SRCCOPY | CAPTUREBLT
            return None
        header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width,
                                   -height, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down BI_RGB
        buffer = ctypes.create_string_buffer(width * height * 4)
        if gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer,
                           ctypes.byref(header), 0) != height:
            return None
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
    image = QImage(buffer.raw, width, height, width * 4, QImage.Format_RGB32).copy()
    pixmap = QPixmap.fromImage(image)
    return None if pixmap.isNull() else pixmap


def capture_window():
    """What the player sees of the foreground game, title bar excluded.

    That is the game's client area, or the upscaled picture when Magpie (or a
    similar tool) is scaling the game, so one hotkey works either way.
    """
    hwnd = foreground_hwnd()
    rect = foreground_client_rect()
    if not hwnd or rect is None:
        return None
    # Grab the composited screen: a window grab (grabWindow(hwnd)) comes back
    # black for anything a game draws on the GPU.
    target = upscaled_rect(hwnd, rect) or rect
    try:
        from .core import debug_log
        debug_log("capture rect %d,%d %dx%d (%s)"
                  % (target.x(), target.y(), target.width(), target.height(),
                     "upscaled" if target is not rect else "game window"))
    except Exception:
        pass
    try:
        pixmap = _grab_rect(target)
    except Exception:
        pixmap = None
    if pixmap is not None:
        return pixmap

    # fallback: the old Qt grab of the primary screen
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    full = screen.grabWindow(0)
    if full.isNull():
        return None
    bounds = QRect(0, 0, full.width(), full.height())
    for factor in pixmap_crop_hints(full, screen):
        candidate = scale_rect(target, factor, bounds)
        if candidate.width() >= 4 and candidate.height() >= 4:
            return full.copy(candidate)
    return None


SHUTTER_NAMES = ("screenshot.wav", "shutter.wav")
LONG_FORMATS = (".mp3", ".wma", ".m4a", ".flac", ".ogg", ".aac", ".aiff", ".mid")


def sound_file(chosen=""):
    """A camera shutter sound dropped next to the data wins over the system one."""
    if chosen:
        candidate = Path(chosen)
        if candidate.exists():
            return candidate
    try:
        from .core import APP_DIR
    except Exception:
        return None
    for name in SHUTTER_NAMES:
        candidate = Path(APP_DIR) / name
        if candidate.exists():
            return candidate
    return None


def _play_media(path):
    """MCI handles mp3/wma/... without pulling in QtMultimedia."""
    try:
        mci = ctypes.windll.winmm.mciSendStringW
    except Exception:
        return False
    alias = "hp_sound"
    try:
        mci('close %s' % alias, None, 0, None)
    except Exception:
        pass
    buffer = pathlib_path = str(path)
    try:
        if mci('open "%s" type mpegvideo alias %s' % (buffer, alias), None, 0, None) != 0:
            if mci('open "%s" alias %s' % (buffer, alias), None, 0, None) != 0:
                return False
        return mci('play %s from 0' % alias, None, 0, None) == 0
    except Exception:
        return False


def beep(sound_path=""):
    """Play the shutter sound immediately, cutting off the previous one."""
    try:
        import winsound
    except Exception:
        return False
    custom = sound_file(sound_path)
    if custom is not None and custom.suffix.lower() not in (".wav", ""):
        if _play_media(custom):
            return True
    if custom is not None:
        try:
            winsound.PlaySound(str(custom),
                               winsound.SND_FILENAME | winsound.SND_ASYNC
                               | winsound.SND_NODEFAULT)
            return True
        except Exception:
            pass
    try:
        # SND_ASYNC stops whatever is still playing, so spamming is fine
        winsound.PlaySound("SystemAsterisk",
                           winsound.SND_ALIAS | winsound.SND_ASYNC
                           | winsound.SND_NODEFAULT)
        return True
    except Exception:
        pass
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        return True
    except Exception:
        return False


def reveal_in_explorer(path):
    """Show a file selected in Explorer, in front."""
    import subprocess
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
    except Exception:
        return False
    _raise_explorer(Path(path).parent.name)
    return True


def open_folder(path):
    """Open a folder in Explorer, in front."""
    import subprocess
    try:
        os.startfile(str(path))
    except Exception:
        try:
            subprocess.Popen(["explorer", str(path)])
        except Exception:
            return False
    _raise_explorer(Path(path).name)
    return True


def _is_explorer(pid):
    try:
        import psutil
        return psutil.Process(pid).name().lower().startswith("explorer")
    except Exception:
        return False


def _raise_explorer(title_part):
    """Explorer sometimes opens behind; bring the matching window forward."""
    import threading
    import time

    def worker():
        try:
            user32 = ctypes.windll.user32
        except Exception:
            return
        for _ in range(30):
            time.sleep(0.1)
            found = []
            prototype = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def callback(hwnd, _param):
                length = user32.GetWindowTextLengthW(hwnd)
                if not length:
                    return True
                # only Explorer: a game window carries the same title
                pid = ctypes.c_ulong(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if not _is_explorer(pid.value):
                    return True
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if title_part and title_part.lower() in buffer.value.lower():
                    found.append(hwnd)
                    return False
                return True

            try:
                user32.EnumWindows(prototype(callback), 0)
            except Exception:
                return
            if found:
                user32.ShowWindow(found[0], 9)
                user32.SetForegroundWindow(found[0])
                return

    threading.Thread(target=worker, daemon=True).start()
