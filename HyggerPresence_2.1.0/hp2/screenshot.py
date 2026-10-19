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


def trim_bars(pixmap, threshold=10):
    """Remove uniform near-black borders, e.g. the pillarbox an upscaler adds.

    Returns the original pixmap when nothing looks like a bar, so a dark scene is
    never cropped by accident.
    """
    if pixmap is None or pixmap.isNull():
        return pixmap
    image = pixmap.toImage()
    width, height = image.width(), image.height()
    if width < 32 or height < 32:
        return pixmap

    def dark(value):
        return ((value >> 16 & 0xFF) <= threshold
                and (value >> 8 & 0xFF) <= threshold
                and (value & 0xFF) <= threshold)

    def column_dark(x):
        step = max(1, height // 64)
        return all(dark(image.pixel(x, y)) for y in range(0, height, step))

    def row_dark(y):
        step = max(1, width // 64)
        return all(dark(image.pixel(x, y)) for x in range(0, width, step))

    left = 0
    while left < width // 3 and column_dark(left):
        left += 1
    right = width - 1
    while right > width * 2 // 3 and column_dark(right):
        right -= 1
    top = 0
    while top < height // 3 and row_dark(top):
        top += 1
    bottom = height - 1
    while bottom > height * 2 // 3 and row_dark(bottom):
        bottom -= 1

    if left == 0 and top == 0 and right == width - 1 and bottom == height - 1:
        return pixmap
    cropped = pixmap.copy(QRect(left, top, right - left + 1, bottom - top + 1))
    return cropped if not cropped.isNull() else pixmap


class ScreenshotStore:
    """Folder layout and file naming."""

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else default_base_dir()

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


def foreground_is_upscaler():
    """True while an upscaler window is the one on screen."""
    name = foreground_process_name()
    return any(key in name for key in UPSCALERS)


def foreground_hwnd():
    try:
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


def capture_screen():
    """The whole composited desktop (what an upscaler draws on screen)."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    pixmap = screen.grabWindow(0)
    return None if pixmap.isNull() else pixmap


def capture_window():
    """Contents of the foreground window, title bar excluded.

    Grabbing one window is much cheaper than grabbing the whole screen, but on
    some setups the frame comes along, so the title bar height is trimmed.
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    # Grab the composited screen and crop the client area: a window grab
    # (grabWindow(hwnd)) comes back black for anything a game draws on the GPU.
    full = screen.grabWindow(0)
    rect = foreground_client_rect()
    if full.isNull() or rect is None:
        return None
    bounds = QRect(0, 0, full.width(), full.height())
    for factor in pixmap_crop_hints(full, screen):
        candidate = scale_rect(rect, factor, bounds)
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
