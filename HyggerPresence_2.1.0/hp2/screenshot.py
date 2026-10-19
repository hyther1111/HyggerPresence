"""Screenshot capture and storage.

Self contained: Qt for the grab, ctypes for the Win32 window geometry.

Everything the app writes lives under one folder, so screenshots taken by other
programs never show up in the gallery:

    <base>/HyggerPresence/<game title>/2026-10-19-14-07-33.png
    <base>/HyggerPresence/<game title>/2026-10-19-14-07-33_2.png   (same second)

<base> is the Pictures folder by default and can be changed in the settings.
"""

import ctypes
import re
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

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
    from PySide6.QtCore import QStandardPaths
    folder = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    return Path(folder) if folder else Path.home()


class ScreenshotStore:
    """Folder layout and file naming."""

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else default_base_dir()

    @property
    def root(self):
        return self.base_dir / APP_FOLDER

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
        if not pixmap.save(str(path), "PNG"):
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
        return sorted(images, key=lambda p: p.stat().st_mtime, reverse=True)

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
def capture_screen():
    """The primary screen as a pixmap, or None."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    pixmap = screen.grabWindow(0)
    return None if pixmap.isNull() else pixmap


def pixmap_crop_hints(pixmap, screen):
    """Candidate factors that map logical coordinates onto the grab."""
    logical = max(1, screen.geometry().width())
    factor = pixmap.width() / logical
    return (1.0,) if abs(factor - 1.0) < 0.01 else (1.0, factor)


def capture_window():
    """Contents of the foreground window, title bar excluded."""
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
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


class RegionSelector(QWidget):
    """Overlay: drag a rectangle to grab that part of the screen."""

    picked = Signal(object)          # QPixmap or None

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        screen = QGuiApplication.primaryScreen()
        self._screen = screen
        self.setGeometry(screen.geometry())
        self._background = screen.grabWindow(0)
        self._factor = self._background.width() / max(1, self.width())
        self._preview = self._background.scaled(self.size(), Qt.IgnoreAspectRatio,
                                                Qt.SmoothTransformation)

    # ------------------------------------------------------------------ events
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        rect = self._selection()
        self.hide()
        if rect.width() < 3 or rect.height() < 3:
            self.picked.emit(None)
            self.close()
            return
        bounds = QRect(0, 0, self._background.width(), self._background.height())
        source = scale_rect(rect, self._factor, bounds)
        self.picked.emit(self._background.copy(source) if source.isValid() else None)
        self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            self.picked.emit(None)
            self.close()

    # ----------------------------------------------------------------- drawing
    def _selection(self):
        return QRect(self._origin, self._current).normalized()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._preview)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        rect = self._selection()
        if not rect.isValid() or rect.width() < 2:
            return
        bounds = QRect(0, 0, self._background.width(), self._background.height())
        painter.drawPixmap(rect, self._background, scale_rect(rect, self._factor, bounds))
        painter.setPen(QPen(QColor("#5b8def"), 2))
        painter.drawRect(rect)
        painter.setPen(QColor("#ffffff"))
        offset = rect.topLeft() + QPoint(6, -8 if rect.top() > 20 else 16)
        painter.drawText(offset, describe_size(rect))


def start_region_capture(on_done):
    """Show the overlay; on_done(pixmap_or_None) runs when the user finished."""
    selector = RegionSelector()

    def finished(pixmap):
        try:
            on_done(pixmap)
        finally:
            selector.deleteLater()

    selector.picked.connect(finished)
    selector.show()
    selector.raise_()
    selector.activateWindow()
    return selector
