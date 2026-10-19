"""Hygger Presence 2.0 (Qt) - user interface.

Frameless window with a self-drawn title bar (identical in dark and light mode),
a left sidebar and four pages: Library, Now reading, Statistics, Settings.
The engine does all detection/presence work; this file only renders + forwards
clicks.

Icons are painted with QPainter (sun / moon / window buttons) so they look the
same on every machine and never change the layout when the theme flips.
"""
import os
import threading
import threading
import time
from pathlib import Path

from PySide6.QtCore import (QDate, QEasingCurve, QEvent, QObject, QPoint,
                            QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QColor, QIcon, QImage, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QComboBox, QCheckBox,
                               QDialog,
                               QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QSizeGrip, QStackedWidget,
                               QListWidget, QListWidgetItem, QTabWidget,
                               QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from .engine import Engine, DEFAULT_TEMPLATES
from . import updater
from . import winframe
from . import i18n
from .i18n import LANGUAGES, set_language, tr
from . import screenshot as shots
from .hotkey import HotkeyManager, describe, from_qt
from . import hotkey as hotkey_mod
from .stats import StatsStore
from . import store

def _as_point(value):
    """Qt gives QPointF; accept a plain QPoint too (tests / other wrappers)."""
    return value.toPoint() if hasattr(value, "toPoint") else value

def paint_burger(size=18):
    """Three rounded lines (no border) for the sidebar toggle."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#8b95a5"), 1.8, Qt.SolidLine, Qt.RoundCap))
    step = size / 4.0
    for index in range(3):
        y = step * (index + 1)
        painter.drawLine(int(size * 0.18), int(y), int(size * 0.82), int(y))
    painter.end()
    return QIcon(pixmap)


def paint_caption(kind, size=13, colour="#9aa4b2"):
    """Minimise / maximise / restore / close drawn as icons instead of glyphs."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(colour), 1.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    margin = 2.5
    if kind == "min":
        y = size - margin - 1
        painter.drawLine(int(margin), int(y), int(size - margin), int(y))
    elif kind == "max":
        painter.drawRoundedRect(QRectF(margin, margin, size - 2 * margin,
                                       size - 2 * margin), 1.5, 1.5)
    elif kind == "restore":
        painter.drawRoundedRect(QRectF(margin, margin + 2, size - 2 * margin - 2,
                                       size - 2 * margin - 2), 1.5, 1.5)
        painter.drawLine(int(margin + 2), int(margin + 2), int(size - margin),
                         int(margin + 2))
        painter.drawLine(int(size - margin), int(margin + 2), int(size - margin),
                         int(size - margin - 1))
    elif kind == "close":
        painter.drawLine(int(margin), int(margin), int(size - margin),
                         int(size - margin))
        painter.drawLine(int(size - margin), int(margin), int(margin),
                         int(size - margin))
    painter.end()
    return QIcon(pixmap)


def apply_dark_title(widget, dark=True):
    """Ask DWM for a dark title bar (dialogs, message boxes)."""
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


class DarkDialogFilter(QObject):
    """Every QDialog gets a dark caption while the app is in dark mode."""

    def __init__(self, get_dark):
        super().__init__()
        self._get_dark = get_dark

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QDialog):
            apply_dark_title(obj, bool(self._get_dark()))
        return False


# --------------------------------------------------------------------------- themes
DARK = {
    "bg": "#121212", "surface": "#1c1c1e", "surface2": "#26262a", "border": "#2f2f34",
    "text": "#e8e8ea", "subtext": "#9aa0aa", "accent": "#5b8def",
    "green": "#4ade80", "red": "#ef4444", "yellow": "#facc15",
}
LIGHT = {
    "bg": "#f4f5f7", "surface": "#ffffff", "surface2": "#e9ebef", "border": "#d5d8de",
    "text": "#17181a", "subtext": "#5d626b", "accent": "#2f6fed",
    "green": "#16a34a", "red": "#dc2626", "yellow": "#d97706",
}


def arrow_icon_path():
    """Small chevron used by the combo boxes (no native arrows)."""
    from .store import APP_DIR
    path = Path(APP_DIR) / "_arrow.png"
    if not path.exists():
        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#8b95a5"), 1.6, Qt.SolidLine, Qt.RoundCap))
        painter.drawPolyline([QPoint(3, 5), QPoint(6, 8), QPoint(9, 5)])
        painter.end()
        try:
            pixmap.save(str(path))
        except Exception:
            pass
    return str(path).replace("\\", "/")


def check_icon_path():
    """A tiny white check used by the QSS checkbox indicator (both themes)."""
    if QApplication.instance() is None:
        return ""              # QPixmap needs a QGuiApplication first
    from .store import APP_DIR
    path = Path(APP_DIR) / "_check.png"
    if not path.exists():
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff"), 2.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawPolyline([QPoint(3, 7), QPoint(6, 10), QPoint(11, 4)])
        painter.end()
        try:
            pixmap.save(str(path))
        except Exception:
            pass
    return str(path).replace("\\", "/")


def qss(p):
    p = dict(p)
    if not p.get("check"):
        p["check"] = check_icon_path()
    if not p.get("arrow"):
        p["arrow"] = arrow_icon_path()
    # the title bar must be visibly different from the window background
    p.setdefault("titlebar", p["surface2"])
    return f"""
    QWidget {{ background: {p['bg']}; color: {p['text']};
               font-family: "Segoe UI"; font-size: 9pt; }}
    /* labels/checkboxes must not paint the window colour inside cards
       (that produced a dark band under every line of text) */
    QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p['surface2']};
               border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {p['accent']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {p['surface2']};
               border-radius: 5px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: {p['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QFrame#card, QFrame#panel {{ background: {p['surface']};
               border: 1px solid {p['border']}; border-radius: 10px; }}
    QLabel#h1 {{ font-size: 15pt; font-weight: 600; }}
    QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
    QLabel#sub {{ color: {p['subtext']}; }}
    QLabel#caps {{ color: {p['subtext']}; font-size: 8pt; letter-spacing: 1px; }}
    QLabel#value {{ font-size: 18pt; font-weight: 600; }}
    QPushButton {{ background: {p['surface2']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 7px;
               padding: 6px 12px; }}
    QPushButton:hover {{ background: {p['accent']}; color: #ffffff; }}
    QPushButton:pressed {{ background: {p['accent']}; color: #ffffff; }}
    QPushButton:disabled {{ color: {p['subtext']}; }}
    QPushButton {{ background: {p['surface2']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 7px;
               padding: 6px 12px; }}
    QPushButton:hover {{ background: {p['border']}; }}
    QPushButton:pressed {{ background: {p['border']}; border-color: {p['accent']}; }}
    QComboBox {{ padding-right: 18px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right;
               width: 18px; border: none; background: transparent; }}
    QComboBox::down-arrow {{ image: url({p['arrow']}); width: 9px; height: 9px; }}
    QLabel#pill {{ font-family: Consolas, "Courier New", monospace;
    background: {p['surface2']}; color: {p['text']};
    padding: 2px 8px; border-radius: 4px; }}
QLabel#tick {{ background: transparent; color: {p['green']}; }}
QComboBox QAbstractItemView::item {{ padding: 4px 6px; border: none;
    color: {p['text']}; }}
QComboBox QAbstractItemView::item:selected {{ background: {p['accent']};
    color: #ffffff; }}
    QToolButton#cover {{ background: {p['surface2']}; border: 1px solid {p['border']};
               border-radius: 8px; padding: 0px; }}
    QToolButton#cover:hover {{ border-color: {p['accent']}; }}
    QToolButton#cover:pressed {{ background: {p['surface2']}; border-color: {p['accent']}; }}
    QPushButton#date {{ background: {p['surface']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 7px;
               padding: 5px 10px; font-size: 8pt; text-align: left; }}
    QPushButton#date:hover {{ border-color: {p['accent']}; }}
    QToolButton#step {{ background: {p['surface2']}; color: {p['text']};
               border: none; border-radius: 7px; padding: 4px 9px; }}
    QToolButton#step:hover {{ background: {p['border']}; }}
    QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {p['surface']}; }}
    QCalendarWidget QToolButton {{ color: {p['text']}; background: transparent;
               border: none; border-radius: 6px; padding: 4px 8px; }}
    QCalendarWidget QToolButton:hover {{ background: {p['surface2']}; }}
    QCalendarWidget QSpinBox {{ background: {p['surface']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 6px;
               selection-background-color: {p['accent']}; }}
    QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button {{
               width: 0px; border: none; }}
    QCalendarWidget QWidget {{ alternate-background-color: {p['surface']};
               background: {p['surface']}; color: {p['text']}; }}
    QCalendarWidget QTableView {{ background: {p['surface']}; color: {p['text']};
               selection-background-color: {p['accent']}; selection-color: #ffffff; }}
    QCalendarWidget QHeaderView {{ background: {p['surface']}; }}
    QCalendarWidget QHeaderView::section {{ background: {p['surface']};
               color: {p['subtext']}; border: none; padding: 3px; }}
    QCalendarWidget QAbstractItemView:enabled {{ background: {p['surface']};
               color: {p['text']}; selection-background-color: {p['accent']};
               selection-color: #ffffff; outline: 0; }}
    QWidget#popup {{ background: {p['surface']}; border: 1px solid {p['border']};
               border-radius: 10px; }}
    QPushButton#danger {{ background: #b23a3a; color: #ffffff; border: none; }}
    QPushButton#danger:hover {{ background: #c94a4a; }}
    QPushButton#danger:pressed {{ background: #9a3232; }}
    QPushButton#primary {{ background: {p['accent']}; color: #ffffff;
               border: none; font-weight: 600; }}
    QPushButton#nav {{ text-align: left; border: none; border-radius: 8px;
               padding: 9px 12px; background: transparent;
               color: {p['subtext']}; }}
    QPushButton#nav:hover {{ background: {p['surface2']}; color: {p['text']}; }}
    QPushButton#nav:checked {{ background: {p['accent']}; color: #ffffff; }}
    QLineEdit, QComboBox {{ background: {p['surface']}; border: 1px solid {p['border']};
               border-radius: 7px; padding: 5px 8px; selection-background-color: {p['accent']}; }}
    QLineEdit:focus {{ border-color: {p['accent']}; }}
    QTableWidget {{ background: {p['surface']}; border: 1px solid {p['border']};
               border-radius: 10px; gridline-color: {p['border']}; }}
    QHeaderView::section {{ background: {p['surface2']}; color: {p['subtext']};
               border: none; padding: 6px; }}
    QTableWidget::item:selected {{ background: {p['accent']}; color: #ffffff; }}
    QCheckBox {{ padding: 2px; }}
    QToolButton#titlebar {{ background: transparent; border: none; border-radius: 6px; }}
    QToolButton#titlebar:hover {{ background: {p['border']}; }}
    QToolButton#winbtn {{ background: transparent; border: none;
               border-radius: 7px; }}
    QToolButton#winbtn:hover {{ background: {p['border']}; }}
    QToolButton#winbtn:pressed {{ background: {p['border']}; }}
    QToolButton#close {{ background: transparent; border: none;
               border-radius: 7px; }}
    QToolButton#close:hover {{ background: #c0392b; }}
    QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px;
               top: -1px; background: {p['bg']}; }}
    QTabBar::tab {{ background: {p['surface2']}; color: {p['subtext']};
               border: none; padding: 7px 16px; margin-right: 4px;
               border-top-left-radius: 8px; border-top-right-radius: 8px; }}
    QTabBar::tab:selected {{ background: {p['accent']}; color: #ffffff;
               font-weight: 600; }}
    QTabBar::tab:hover:!selected {{ background: {p['border']}; color: {p['text']}; }}
    QDialog, QMessageBox, QInputDialog, QFileDialog {{ background: {p['bg']};
               color: {p['text']}; }}
    QMessageBox QLabel, QInputDialog QLabel {{ color: {p['text']}; }}
    QPushButton:focus, QToolButton:focus, QComboBox:focus, QCheckBox:focus,
    QTableWidget:focus, QLineEdit:focus, QListWidget:focus {{ outline: none; }}
    QAbstractItemView {{ outline: 0; }}
    QTableWidget::item {{ border: none; }}
    QTableWidget::item:focus {{ border: none; outline: 0; }}
    QLineEdit, QComboBox, QTextEdit {{ outline: 0; }}
    QMenu {{ background: {p['surface']}; border: 1px solid {p['border']};
               border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 20px; border-radius: 6px; color: {p['text']}; }}
    QMenu::item:selected {{ background: {p['accent']}; color: #ffffff; }}
    QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 8px; }}
    QComboBox QAbstractItemView {{ background: {p['surface']};
               border: 1px solid {p['border']}; border-radius: 8px;
               selection-background-color: {p['accent']}; selection-color: #ffffff;
               outline: 0; }}
    QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
               border: 1px solid {p['border']}; background: {p['surface']}; }}
    QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']};
               image: url({p['check']}); }}
    QLabel#help {{ color: {p['subtext']}; font-size: 8pt; }}
    QLabel#h3 {{ font-size: 10pt; font-weight: 600; }}
    QLabel#chip {{ border-radius: 7px; padding: 4px 10px; font-size: 8pt; }}
    QPushButton#fakebutton {{ background: {p['surface2']}; color: {p['text']};
               border: 1px solid {p['border']}; border-radius: 6px;
               padding: 5px 12px; font-size: 8pt; }}
    QPushButton#fakebutton:hover {{ background: {p['border']}; }}
    QFrame#card[selected="true"] {{ border: 2px solid {p['accent']}; }}
    QToolButton#range {{ background: {p['surface2']}; color: {p['text']};
               border: none; border-radius: 7px; padding: 6px 12px; font-size: 8pt; }}
    QToolButton#range:hover {{ background: {p['border']}; }}
    QToolButton#range::menu-indicator {{ image: none; width: 0; }}
    TitleBar#titlebar {{ background: {p['titlebar']}; }}
    QToolButton#burger {{ background: transparent; border: none; border-radius: 6px;
               padding: 3px 5px; }}
    QToolButton#burger:hover {{ background: {p['border']}; }}
    QPushButton#chip {{ background: {p['surface2']}; color: {p['subtext']};
               border: none; border-radius: 7px; padding: 5px 12px; font-size: 8pt; }}
    QPushButton#chip:hover {{ background: {p['border']}; color: {p['text']}; }}
    QPushButton#chip:checked {{ background: {p['accent']}; color: #ffffff;
               font-weight: 600; }}
    QPushButton:disabled {{ color: {p['subtext']}; background: {p['surface2']};
               border-color: {p['border']}; opacity: 0.55; }}
    QLineEdit:disabled, QComboBox:disabled, QTableWidget:disabled {{
               color: {p['subtext']}; background: {p['surface']};
               border-color: {p['border']}; }}
    QLabel:disabled, QCheckBox:disabled {{ color: {p['subtext']}; }}
    QListWidget::indicator {{ width: 15px; height: 15px; border-radius: 4px;
               border: 1px solid {p['border']}; background: {p['surface']}; }}
    QListWidget::indicator:hover {{ border-color: {p['accent']}; }}
    QListWidget::indicator:checked {{ background: {p['accent']};
               border-color: {p['accent']}; image: url({p['check']}); }}
    QTabWidget#sub > QTabBar::tab {{ background: transparent; color: {p['subtext']};
               border: none; border-bottom: 2px solid transparent;
               padding: 6px 14px; margin-right: 2px; border-radius: 0; }}
    QTabWidget#sub > QTabBar::tab:selected {{ color: {p['text']}; font-weight: 600;
               border-bottom: 2px solid {p['accent']}; background: transparent; }}
    QTabWidget#sub > QTabBar::tab:hover:!selected {{ color: {p['text']}; }}
    QTabWidget#sub::pane {{ border: none; top: 0; margin-top: 6px; }}
    QToolTip {{ background: {p['surface2']}; color: {p['text']};
               border: 1px solid {p['border']}; }}
    """


def paint_sun(size=18, colour="#f5c451"):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    centre = size / 2
    painter.setBrush(QColor(colour))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(centre - 4, centre - 4, 8, 8))
    painter.setPen(QPen(QColor(colour), 1.6, Qt.SolidLine, Qt.RoundCap))
    import math
    for step in range(8):
        angle = math.radians(step * 45)
        painter.drawLine(
            centre + 5.6 * math.cos(angle), centre + 5.6 * math.sin(angle),
            centre + 8.0 * math.cos(angle), centre + 8.0 * math.sin(angle))
    painter.end()
    return QIcon(pixmap)


def paint_moon(size=18, colour="#f2f4f8", hole="#121212"):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(3, 3, 12, 12))
    cut = QPainterPath()
    cut.addEllipse(QRectF(7, 1.5, 12, 12))
    painter.setBrush(QColor(colour))
    painter.setPen(Qt.NoPen)
    painter.drawPath(path.subtracted(cut))
    painter.end()
    return QIcon(pixmap)


# --------------------------------------------------------------------------- title bar
class SnapPreview(QWidget):
    """Windows-style "drop here to maximise" hint while dragging the title bar."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._anim = None
        self._target = QRect()

    def show_target(self, target, animate_from=None):
        self._target = QRect(target)
        if animate_from is not None:
            self.setGeometry(QRect(animate_from))
            self._anim = QPropertyAnimation(self, b"geometry", self)
            self._anim.setDuration(130)
            self._anim.setStartValue(QRect(animate_from))
            self._anim.setEndValue(QRect(target))
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()
        else:
            self.setGeometry(QRect(target))
        self.show()
        self.raise_()

    def hide_preview(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self.hide()

    def paintEvent(self, event):
        from PySide6.QtGui import QColor, QPainter, QPen
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(150, 175, 255, 200), 1.5))
        painter.setBrush(QColor(90, 130, 240, 45))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)


class TitleLine(QFrame):
    """2px separator; fills itself so the colour is predictable."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(2)

    def paintEvent(self, event):
        theme = getattr(self.window(), "palette", DARK)
        if not isinstance(theme, dict):
            theme = DARK
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme["border"]))
        painter.end()


class TitleStrip(QFrame):
    """Paints the title bar background itself.

    No stylesheet is used here on purpose: a stylesheet set on a parent leaks into
    its children and killed the hover state of the caption buttons.
    """

    def __init__(self):
        super().__init__()
        self.setFixedHeight(38)

    def paintEvent(self, event):
        theme = getattr(self.window(), "palette", DARK)
        if not isinstance(theme, dict):
            theme = DARK
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.get("surface2", theme["surface"])))
        painter.setPen(QColor(theme["border"]))
        line_y = max(0, self.height() - 2)
        painter.drawLine(0, line_y, self.width(), line_y)
        painter.end()


class TitleBar(QWidget):
    def __init__(self, window, on_theme):
        super().__init__(window)
        self._window = window
        self._drag = None
        self._was_maximized = False
        self.setObjectName("titlebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setFixedHeight(36)

        row = QHBoxLayout(self)
        row.setContentsMargins(EDGE, 0, 8, 0)
        row.setSpacing(6)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(18, 18)
        row.addWidget(self.icon_label)
        self.title = QLabel("Hygger Presence")
        self.title.setObjectName("h2")
        # the first glyph was clipped: give the label a little breathing room
        self.title.setContentsMargins(3, 0, 0, 0)
        self.title.setIndent(0)
        row.addWidget(self.title)
        row.addStretch(1)

        self.theme_button = QToolButton()
        self.theme_button.setObjectName("titlebar")
        self.theme_button.setFixedSize(28, 28)
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.setToolTip(tr("Dark / light mode"))
        self.theme_button.clicked.connect(on_theme)
        row.addWidget(self.theme_button)

        for name, kind, handler, object_name, tooltip in (
                ("minimise", "min", self._window.showMinimized, "winbtn", "Minimise"),
                ("maximise", "max", self._toggle_max, "winbtn", "Maximise"),
                ("close", "close", self._window.close, "close", "Close")):
            button = QToolButton()
            button.setObjectName(object_name)
            button.setIcon(paint_caption(kind))
            button.setIconSize(QSize(13, 13))
            button.setFixedSize(32, 26)
            button.setToolTip(tooltip)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(handler)
            setattr(self, name + "_button", button)
            row.addWidget(button)
        self.refresh_caption_icons()

    def refresh_caption_icons(self):
        maximised = self._window.isMaximized()
        self.maximise_button.setIcon(paint_caption("restore" if maximised else "max"))
        self.maximise_button.setToolTip("Restore" if maximised else "Maximise")

    def set_title_icon(self, icon):
        self.icon_label.setPixmap(icon.pixmap(18, 18))

    def paintEvent(self, event):
        from PySide6.QtGui import QColor, QPainter
        theme = getattr(self._window, "palette", DARK)
        painter = QPainter(self)
        painter.fillRect(self.rect(),
                         QColor(theme.get("surface2", theme["surface"])))
        painter.setPen(QColor(theme["border"]))
        line_y = max(0, self.height() - 1)
        painter.drawLine(0, line_y, self.width(), line_y)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.refresh_caption_icons()

    def mousePressEvent(self, event):
        if getattr(self._window, "native_snap", False):
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            self._drag = _as_point(event.globalPosition()) - self._window.frameGeometry().topLeft()
            self._was_maximized = self._window.isMaximized()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self._window, "native_snap", False):
            super().mouseMoveEvent(event)
            return
        if self._drag and event.buttons() & Qt.LeftButton:
            if self._was_maximized:
                # restore to the size the window had before it was maximised and
                # keep the pointer on the same spot of the title bar
                position = _as_point(event.globalPosition())
                normal = self._window.normalGeometry()
                width = normal.width() if normal.width() >= 400 else max(
                    900, self._window.width() // 2)
                height = normal.height() if normal.height() >= 300 else max(
                    620, self._window.height() // 2)
                screen = QApplication.screenAt(position) or QApplication.primaryScreen()
                area = screen.availableGeometry() if screen is not None else None
                ratio = position.x() / max(1, self._window.width())
                ratio = min(0.9, max(0.1, ratio))
                self._window.showNormal()
                self._window.resize(int(width), int(height))
                x = int(position.x() - width * ratio)
                y = int(position.y() - 18)
                if area is not None:
                    x = min(max(x, area.left()), max(area.left(), area.right() - width))
                    y = min(max(y, area.top()), max(area.top(), area.bottom() - height))
                self._window.move(x, y)
                self._drag = position - self._window.frameGeometry().topLeft()
                self._was_maximized = False
                self.refresh_caption_icons()
                super().mouseMoveEvent(event)
                return
            position = _as_point(event.globalPosition())
            self._window.move(position - self._drag)
            screen = QApplication.screenAt(position) or QApplication.primaryScreen()
            if screen is not None and position.y() <= screen.geometry().top() + 8 \
                    and not self._window.isMaximized():
                target = screen.availableGeometry()
                start = QRect(position.x() - 90, target.top() + 36, 180, 96)
                self._window.show_snap_preview(target, start)
            else:
                self._window.hide_snap_preview()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self._window, "native_snap", False):
            super().mouseReleaseEvent(event)
            return
        if self._window.snap_preview_visible():
            self._window.hide_snap_preview()
            self._window.showMaximized()
            self.refresh_caption_icons()
        else:
            self._window.hide_snap_preview()
        self._drag = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if getattr(self._window, "native_snap", False):
            super().mouseDoubleClickEvent(event)
            return
        self._toggle_max()
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._window.palette_bg))
        painter.drawRect(self.rect())
        painter.end()


# --------------------------------------------------------------------------- pages
class Page(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.app = window.app
        self.engine = window.engine


class LibraryPage(Page):
    def __init__(self, window):
        super().__init__(window)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel(tr("Library"))
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search title, developer, exe…"))
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.refresh)
        head.addWidget(self.search)
        outer.addLayout(head)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Title", "Total time", "Executable"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        # no in-place editors: double-click opens the editor dialog instead
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.horizontalHeader().setStretchLastSection(True)
        stored = (self.window.config.get("ui") or {}).get("library_columns")
        for index, width in enumerate(stored or (420, 130, 160)):
            self.table.setColumnWidth(index, int(width))
        self.table.horizontalHeader().sectionResized.connect(self._remember_columns)
        self.table.doubleClicked.connect(lambda _i: self.edit_selected())
        self.empty_hint = QLabel(
            "No games yet.\n\nUse \u201cAdd game\u2026\u201d, or bring your 1.x data over with\n"
            "Settings \u2192 General \u2192 \u201cImport 1.x data\u2026\u201d")
        self.empty_hint.setObjectName("sub")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_hint, 1)
        outer.addWidget(self.table, 1)

        toolbar = QHBoxLayout()
        self.start_button = QPushButton(tr("Start"))
        self.start_button.setObjectName("primary")
        self.start_button.setMenu(self._build_start_menu())
        self.edit_button = QPushButton(tr("Edit\u2026"))
        self.add_button = QPushButton(tr("Add game\u2026"))
        self.remove_button = QPushButton(tr("Remove"))
        self.vndb_button = QPushButton(tr("View on VNDB"))
        self.refresh_button = QPushButton(tr("Refresh list"))
        self.cover_button = QPushButton(tr("Change cover\u2026"))
        self.cover_button.setToolTip(tr("Pick one of the VN covers from VNDB"))
        self.clear_button = QPushButton(tr("Clear presence"))
        self.clear_button.setObjectName("danger")
        self.clear_button.setToolTip(tr("Clear the Discord card now (it comes back on the next tick)"))
        for button in (self.start_button, self.edit_button, self.add_button,
                       self.remove_button, self.vndb_button, self.refresh_button,
                       self.cover_button):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.clear_button)
        outer.addLayout(toolbar)

        self.add_button.clicked.connect(self.add_game)
        self.edit_button.clicked.connect(self.edit_selected)
        self.remove_button.clicked.connect(self.remove_selected)
        self.vndb_button.clicked.connect(self.open_vndb)
        self.refresh_button.clicked.connect(self.refresh)
        self.clear_button.clicked.connect(lambda: self.engine.clear_now())
        self.cover_button.clicked.connect(self.change_cover)
        self.refresh()

    def display_title(self, game):
        """Library title: original script or romanised, per the setting."""
        mode = (getattr(self.window, "config", {}) or {}).get("library_title_mode")
        if mode == "romanized":
            romanised = (game.get("romanized") or "").strip()
            if romanised:
                return romanised
        return game.get("original") or game.get("title") or ""

    # ---------- start menu ----------
    def _build_start_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction("Start (normal)", self.start_selected)
        launchers = (self.window.config.get("launchers") or [])
        if launchers:
            menu.addSeparator()
            for launcher in launchers:
                menu.addAction(launcher.get("name", "launcher"),
                               lambda item=launcher: self.start_with_launcher(item))
        menu.addSeparator()
        menu.addAction("Manage launchers\u2026", self.window.goto_launchers)
        return menu

    def refresh_menu(self):
        self.start_button.setMenu(self._build_start_menu())

    def _remember_columns(self, *_args):
        ui = self.window.config.setdefault("ui", {})
        ui["library_columns"] = [self.table.columnWidth(i) for i in range(3)]

    def save_state(self):
        self._remember_columns()

    # ---------- data ----------
    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        index = rows[0].row()
        if 0 <= index < len(self.window.visible_games):
            return self.window.visible_games[index]
        return None

    def refresh(self):
        from .core import format_time
        needle = (self.search.text() or "").strip().lower()
        games = []
        for game in self.engine.games:
            blob = " ".join(str(game.get(key, "")) for key in
                            ("original", "title", "romanized", "developer", "year",
                             "vndb_id", "exe")).lower()
            if needle and needle not in blob:
                continue
            games.append(game)
        self.window.visible_games = games
        self.table.setRowCount(len(games))
        if hasattr(self, "empty_hint"):
            self.empty_hint.setVisible(not games)
            self.table.setVisible(bool(games))
        for row, game in enumerate(games):
            title_item = QTableWidgetItem(self.display_title(game))
            title_item.setToolTip("%s\n%s | %s\n%s"
                                  % (title_item.text(), game.get("developer") or "?",
                                     game.get("year") or "?", game.get("exe") or ""))
            self.table.setItem(row, 0, title_item)
            total = game.get("total_seconds", 0)
            if self.engine.game is game:
                total = self.engine.total_seconds     # includes the open stretch
            self.table.setItem(row, 1, QTableWidgetItem(format_time(total)))
            self.table.setItem(row, 2, QTableWidgetItem(
                Path(game.get("exe", "")).name))

    # ---------- actions ----------
    def add_game(self):
        dialog = AddGameDialog(self.window)
        if dialog.exec():
            self.window.engine.games.append(dialog.game)
            store.save_games(self.window.engine.games)
            self.refresh()
            self.window.now_page.update_from_engine()

    def edit_selected(self):
        game = self.selected()
        if not game:
            return
        dialog = GameEditorDialog(self.window, game)
        if dialog.exec():
            store.save_games(self.window.engine.games)
            self.refresh()
            self.window.now_page.update_from_engine()

    def remove_selected(self):
        game = self.selected()
        if not game:
            return
        if QMessageBox.question(self, "Remove", tr("Remove this game and its saved time?")) \
                != QMessageBox.Yes:
            return
        self.window.engine.games = [g for g in self.window.engine.games if g is not game]
        store.save_games(self.window.engine.games)
        self.refresh()

    def _exe_ok(self, game):
        exe = Path(game.get("exe", ""))
        if not exe.exists():
            QMessageBox.warning(self, "Start", "Executable not found:\n%s" % exe)
            return None
        return exe

    def start_selected(self):
        game = self.selected()
        if not game:
            return
        exe = self._exe_ok(game)
        if exe:
            import subprocess
            subprocess.Popen([str(exe)], cwd=str(exe.parent))

    def start_with_launcher(self, launcher):
        import subprocess
        game = self.selected()
        if not game:
            return
        exe = self._exe_ok(game)
        if not exe:
            return
        kind = launcher.get("type")
        try:
            if kind == "le":
                le_path = launcher.get("le_path", "")
                if not Path(le_path).exists():
                    QMessageBox.warning(self, "Launch", "LEProc.exe not found:\n%s" % le_path)
                    return
                subprocess.Popen([le_path, "-runas", launcher.get("guid", ""), str(exe)],
                                 cwd=str(exe.parent))
            elif kind == "galfc":
                path = launcher.get("galfc_path", "")
                if not Path(path).exists():
                    QMessageBox.warning(self, "Launch", "GalFC.exe not found:\n%s" % path)
                    return
                subprocess.Popen([path, str(exe)], cwd=str(exe.parent))
            else:
                command = (launcher.get("command") or "").replace("%1", '"%s"' % exe)
                subprocess.Popen(command, shell=True, cwd=str(exe.parent))
        except Exception as error:
            QMessageBox.warning(self, "Launch", "Failed:\n%s" % error)

    def change_cover(self):
        game = self.selected()
        if not game:
            QMessageBox.information(self, "Cover", "Select a game first.")
            return
        if not game.get("vndb_id"):
            QMessageBox.warning(self, "Cover", "This game has no VNDB id yet.")
            return
        dialog = CoverPickerDialog(self.window, game["vndb_id"])
        if dialog.exec() and dialog.selected is not None:
            if dialog.selected:
                game["image"] = dialog.selected
            store.save_games(self.window.engine.games)
            self.refresh()
            self.window.now_page.update_from_engine()

    def open_vndb(self):
        game = self.selected()
        if game and game.get("vndb_id"):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl("https://vndb.org/%s" % game["vndb_id"]))


class NowPage(Page):
    """Info on top, then the Discord preview (what friends see)."""

    def __init__(self, window):
        super().__init__(window)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel(tr("Detection"))
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch(1)
        self.presence_button = QPushButton()
        self.presence_button.clicked.connect(self.toggle_presence)
        head.addWidget(self.presence_button)
        outer.addLayout(head)

        # ---------------- info card ----------------
        info = QFrame()
        info.setObjectName("card")
        row = QHBoxLayout(info)
        row.setContentsMargins(16, 16, 16, 16)
        row.setSpacing(18)

        self.cover = QLabel("VN")
        self.cover.setFixedSize(150, 210)
        self.cover.setAlignment(Qt.AlignCenter)
        row.addWidget(self.cover, 0, Qt.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(6)
        caps = QLabel("NOW READING")
        caps.setObjectName("caps")
        column.addWidget(caps)
        self.title_label = QLabel(tr("No game yet"))
        self.title_label.setObjectName("h2")
        self.title_label.setWordWrap(True)
        column.addWidget(self.title_label)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("sub")
        column.addWidget(self.meta_label)

        self.status_chip = QLabel("")
        self.status_chip.setObjectName("chip")
        column.addWidget(self.status_chip, 0, Qt.AlignLeft)
        self.total_label = QLabel("")
        self.total_label.setObjectName("sub")
        column.addWidget(self.total_label)
        self.session_label = QLabel("")
        self.session_label.setObjectName("sub")
        column.addWidget(self.session_label)
        self.total_chip = self.total_label
        column.addStretch(1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.cover_button = QPushButton("Change cover\u2026")
        self.cover_button.clicked.connect(self.change_cover)
        self.vndb_button = QPushButton(tr("View on VNDB"))
        self.vndb_button.clicked.connect(self.open_vndb)
        actions.addWidget(self.cover_button)
        actions.addWidget(self.vndb_button)
        actions.addStretch(1)
        column.addLayout(actions)
        row.addLayout(column, 1)
        outer.addWidget(info)

        # ---------------- discord preview ----------------
        preview_card = QFrame()
        preview_card.setObjectName("card")
        pv = QVBoxLayout(preview_card)
        pv.setContentsMargins(16, 12, 16, 16)
        pv.setSpacing(10)
        pv_head = QHBoxLayout()
        pv_caps = QLabel("DISCORD PREVIEW")
        pv_caps.setObjectName("caps")
        pv_head.addWidget(pv_caps)
        pv_head.addStretch(1)
        pv.addLayout(pv_head)

        pv_body = QHBoxLayout()
        pv_body.setSpacing(14)
        self.prev_cover = QLabel("VN")
        self.prev_cover.setFixedSize(84, 84)
        self.prev_cover.setAlignment(Qt.AlignCenter)
        pv_body.addWidget(self.prev_cover, 0, Qt.AlignTop)

        pv_text = QVBoxLayout()
        pv_text.setSpacing(3)
        self.prev_title = QLabel("")
        self.prev_title.setObjectName("h3")
        self.prev_title.setWordWrap(False)
        self.prev_title.setTextInteractionFlags(Qt.NoTextInteraction)
        self.prev_details = QLabel("")
        self.prev_details.setObjectName("sub")
        self.prev_details.setWordWrap(False)
        self.prev_state = QLabel("")
        self.prev_state.setObjectName("sub")
        self.prev_state.setWordWrap(False)
        self.prev_timer = QLabel("")
        self.prev_timer.setStyleSheet("color:#4ade80;")
        self.prev_button = QPushButton(tr("View on VNDB"))
        self.prev_button.setObjectName("fakebutton")
        self.prev_button.setFixedWidth(130)
        self.prev_button.clicked.connect(self.open_vndb)
        for widget in (self.prev_title, self.prev_details, self.prev_state,
                       self.prev_timer, self.prev_button):
            pv_text.addWidget(widget, 0, Qt.AlignLeft)
        pv_text.addStretch(1)
        pv_body.addLayout(pv_text, 1)
        pv.addLayout(pv_body)
        self._preview_card = preview_card
        outer.addWidget(preview_card)

        pin_row = QHBoxLayout()
        pin_row.setSpacing(8)
        pin_label = QLabel("Detect")
        pin_label.setObjectName("help")
        pin_row.addWidget(pin_label)
        self.pin_box = QComboBox()
        self.pin_box.setFixedWidth(260)
        self.pin_box.setToolTip(tr("Force detection to one running game"))
        self.pin_box.currentIndexChanged.connect(self._pin_changed)
        pin_row.addWidget(self.pin_box)
        pin_row.addStretch(1)
        outer.addLayout(pin_row)
        self.diag_label = QLabel("")
        self.diag_label.setObjectName("help")
        self.diag_label.setWordWrap(True)
        outer.addWidget(self.diag_label)

        self.state_value = QLabel("")
        self.state_value.setObjectName("help")
        self.state_value.setWordWrap(True)
        outer.addWidget(self.state_value)
        outer.addStretch(1)
        self._pin_stamp = 0.0

        self._image_url = ""
        self.update_from_engine()

    # ---------------------------------------------------------- actions
    def toggle_presence(self):
        self.engine.set_presence_enabled(not self.engine.presence_enabled)
        self.update_from_engine()
        try:
            self.window._refresh_tray_menu()
        except Exception:
            pass

    def open_vndb(self):
        if self.engine.game and self.engine.game.get("vndb_id"):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(
                QUrl("https://vndb.org/%s" % self.engine.game["vndb_id"]))

    def change_cover(self):
        game = self.engine.game
        if not game or not game.get("vndb_id"):
            QMessageBox.information(self, "Cover", "No game is being detected.")
            return
        dialog = CoverPickerDialog(self.window, game["vndb_id"])
        if dialog.exec() and dialog.selected is not None:
            if dialog.selected:
                game["image"] = dialog.selected
                self._image_url = ""
            store.save_games(self.engine.games)
            self.update_from_engine()

    # ---------------------------------------------------------- render
    def update_from_engine(self):
        theme = self.window.palette
        enabled = self.engine.presence_enabled
        self.presence_button.setText(tr("Presence: ON") if enabled else tr("Presence: OFF"))
        self.presence_button.setStyleSheet(
            "QPushButton{background:%s;color:#fff;border:none;border-radius:7px;"
            "padding:7px 14px;font-weight:600;}"
            % (theme["green"] if enabled else theme["red"]))
        preview = self.engine.preview or {}
        if not preview:
            self.title_label.setText(tr("No game yet"))
            self.meta_label.setText(tr("Launch a game from the library and it shows up here."))
            self.status_chip.setText("")
            self.total_label.setText("")
            self.session_label.setText("")
            self.status_chip.setVisible(False)
            self.total_label.setVisible(False)
            self.session_label.setVisible(False)
            self.prev_title.setText("")
            self.prev_details.setText("")
            self.prev_state.setText("")
            self.prev_timer.setText("")
            self.prev_cover.setPixmap(QPixmap())
            self.prev_cover.setText("VN")
            self.cover.setPixmap(QPixmap())
            self.cover.setText("VN")
            self._image_url = ""
            self._show_engine_error()
            self.window.update_status_bar(None)
            return

        game = self.engine.game or {}
        from .core import format_time
        self.title_label.setText(preview.get("title") or "")
        self.meta_label.setText("%s  \u00b7  %s"
                                % (game.get("developer") or "Unknown",
                                   Path(game.get("exe", "")).name))
        status = preview.get("status") or ""
        self.status_chip.setVisible(True)
        self.total_label.setVisible(True)
        self.session_label.setVisible(True)
        self.status_chip.setText(tr(status))
        self.status_chip.setStyleSheet(
            "QLabel#chip{background:%s;color:#fff;border-radius:7px;padding:4px 10px;"
            "font-size:8pt;}" % self.window.STATUS_COLOURS.get(status, theme["subtext"]))
        self.total_label.setText(tr("Total read  %s") % format_time(self.engine.total_seconds))
        self.session_label.setText(tr("Session  %s") % format_time(self.engine.session_seconds))

        metrics = self.prev_title.fontMetrics()
        width = self._preview_text_width()
        for label, key in ((self.prev_title, "title"),
                           (self.prev_details, "details"),
                           (self.prev_state, "state")):
            text = preview.get(key) or ""
            label.setText(metrics.elidedText(text, Qt.ElideRight, width))
        start = preview.get("start")
        if start:
            elapsed = max(0, int(time.time() - start))
            self.prev_timer.setText("\u25b6 %d:%02d" % (elapsed // 60, elapsed % 60))
        else:
            self.prev_timer.setText("")
        has_vndb = bool(game.get("vndb_id"))
        label = (self.engine.opts or {}).get("button_label") or "View on VNDB"
        if self.prev_button.text() != label:
            self.prev_button.setText(label)
        self.prev_button.setVisible(has_vndb)
        self._show_engine_error()
        if time.time() - self._pin_stamp > 6:
            self._refresh_pin_box()
        self.window.update_status_bar(preview)
        try:
            self.diag_label.setText(self.engine.debug_state())
        except Exception:
            self.diag_label.setText("")

        image = preview.get("image") or ""
        if image != self._image_url:
            self._image_url = image
            self.cover.setPixmap(QPixmap())
            self.cover.setText("VN")
            self.prev_cover.setPixmap(QPixmap())
            self.prev_cover.setText("VN")
            if image:
                self.window.request_cover(image, self._apply_cover)

    def _show_engine_error(self):
        error = (self.engine.last_error or "").strip()
        if error:
            self.state_value.setText("\u26a0  %s" % error[:200])
            self.state_value.setStyleSheet("color:#e05a4a;")
        else:
            self.state_value.setText("")
            self.state_value.setStyleSheet("")

    def _preview_text_width(self):
        """Stable width for the preview lines: the card minus the cover."""
        card = getattr(self, "_preview_card", None)
        if card is None:
            return 240
        width = card.width() - self.prev_cover.width() - 46
        return max(80, width)

    def _refresh_pin_box(self):
        self._pin_stamp = time.time()
        try:
            running = self.engine.running_games()
        except Exception:
            running = []
        self.pin_box.blockSignals(True)
        self.pin_box.clear()
        self.pin_box.addItem("Auto", "")
        for entry in running:
            try:
                game, exe_name = entry
            except Exception:
                game, exe_name = entry, ""
            title = game.get("original") or game.get("title") or game.get("exe")
            label = "%s (%s)" % (title[:40], exe_name or Path(game.get("exe", "")).name)
            self.pin_box.addItem(label, game.get("exe", ""))
        pinned = self.engine.pinned_exe or ""
        index = self.pin_box.findData(pinned)
        self.pin_box.setCurrentIndex(index if index >= 0 else 0)
        self.pin_box.blockSignals(False)

    def _pin_changed(self, _index):
        self.engine.set_pin(self.pin_box.currentData() or "")
        self.update_from_engine()

    def _apply_cover(self, url, image):
        if image is None:
            return
        from PySide6.QtGui import QPixmap
        big = QPixmap.fromImage(image).scaled(150, 210, Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation)
        self.cover.setPixmap(big)
        small = QPixmap.fromImage(image).scaled(84, 84, Qt.KeepAspectRatioByExpanding,
                                                Qt.SmoothTransformation)
        self.prev_cover.setPixmap(small)


def _short_time(seconds):
    seconds = int(round(seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%dh %02dm" % (hours, minutes)
    if minutes:
        return "%dm %02ds" % (minutes, secs)
    return "%ds" % secs


EDGE = 16

CARD_QSS = ("QFrame#shotcard{background:%(surface)s;border-radius:8px;border:%(border)s;}"
            "QFrame#shotcard:hover{background:%(surface2)s;}")

MENU_QSS = ("QMenu{background:%(surface)s;color:%(text)s;border:1px solid %(border)s;}"
            "QMenu::item:selected{background:%(accent)s;color:#ffffff;}"
            "QMenu::item:disabled{background:transparent;color:%(subtext)s;}"
            "QMenu::item:disabled:selected{background:transparent;color:%(subtext)s;}")
APP_VERSION = "2.1.0"          # one inset for the title bar, the sidebar and the status bar

CHART_COLOURS = ("#e64980", "#f0a020", "#4d5bf0", "#2fa8f0", "#7ad1c8",
                 "#c9a227", "#ef6b3a", "#e0413a", "#8f6fe8", "#3ba55d",
                 "#d9d24a", "#4aa8d8", "#f06fb5", "#9b8cff")


class BarChart(QWidget):
    """Stacked reading time per day, one colour per visual novel (ManicTime style)."""

    def __init__(self):
        super().__init__()
        self.days = []          # [(label, [(key, seconds), ...]), ...]
        self.colours = {}       # key -> hex
        self.hover = -1
        self.setMouseTracking(True)
        self.setMinimumHeight(150)
        self.setMaximumHeight(180)

    def set_data(self, days, colours):
        self.days = list(days or [])
        self.colours = dict(colours or {})
        self.hover = -1
        self.update()

    def _metrics(self):
        area = self.rect().adjusted(10, 10, -10, -20)
        count = max(1, len(self.days))
        gap = 6.0 if count < 32 else 2.0
        width = max(2.0, (area.width() - gap * (count - 1)) / count)
        return area, width, gap

    def _peak(self):
        totals = [sum(seconds for _key, seconds in parts) for _label, parts in self.days]
        return max(totals + [1]) or 1

    def mouseMoveEvent(self, event):
        from PySide6.QtWidgets import QToolTip
        from .core import format_time
        area, width, gap = self._metrics()
        x = event.position().x()
        if not self.days or x < area.left() or x > area.right():
            self.hover = -1
            QToolTip.hideText()
            self.update()
            return
        index = int((x - area.left()) // max(1.0, width + gap))
        index = max(0, min(index, len(self.days) - 1))
        self.hover = index
        label, parts = self.days[index]
        engine = getattr(self.window(), "engine", None)
        pattern = ""
        if engine is not None and getattr(engine, "opts", None):
            pattern = engine.opts.get("total_time_format") or ""
        lines = ["<b>%s</b>" % label]
        for key, seconds in sorted(parts, key=lambda item: -item[1]):
            if seconds <= 0:
                continue
            text = format_time(seconds, pattern) if pattern else format_time(seconds)
            lines.append('%s&nbsp;&nbsp;<span style="color:%s;">&#9632;</span> %s'
                         % (text, self.colours.get(key, "#5b8def"), key))
        if len(lines) == 1:
            lines.append("no reading")
        QToolTip.showText(_as_point(event.globalPosition()), "<br>".join(lines), self)
        self.update()

    def leaveEvent(self, event):
        from PySide6.QtWidgets import QToolTip
        self.hover = -1
        QToolTip.hideText()
        self.update()

    def paintEvent(self, event):
        theme = getattr(self.window(), "palette", DARK)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        area, width, gap = self._metrics()
        if area.width() <= 10 or area.height() <= 10:
            return
        if not self.days:
            painter.setPen(QColor(theme["subtext"]))
            painter.drawText(area, Qt.AlignCenter, "No data in this range")
            return
        peak = self._peak()
        base = area.bottom()
        painter.setPen(Qt.NoPen)
        for index, (_label, parts) in enumerate(self.days):
            x = area.left() + index * (width + gap)
            bottom = base
            for key, seconds in parts:
                if seconds <= 0:
                    continue
                height = max(1.0, (seconds / peak) * (area.height() - 6))
                colour = QColor(self.colours.get(key, theme["accent"]))
                if index == self.hover:
                    colour = colour.lighter(118)
                painter.setBrush(colour)
                painter.drawRect(QRectF(x, bottom - height, width, height))
                bottom -= height
        painter.setPen(QPen(QColor(theme["border"]), 1))
        painter.drawLine(area.left(), base, area.right(), base)
        painter.setPen(QColor(theme["subtext"]))
        font = painter.font()
        font.setPointSize(7)
        painter.setFont(font)
        step = max(1, len(self.days) // 9)
        for index in range(0, len(self.days), step):
            label = self.days[index][0]
            x = area.left() + index * (width + gap)
            painter.drawText(QRectF(x - 16, base + 2, width + 32, 16),
                             Qt.AlignCenter, label)


class StatsPage(Page):
    """Cards + a cover grid (one cell per VN), refreshed every second while visible."""

    RANGES = (("7d", "7 days"), ("30d", "30 days"), ("90d", "90 days"),
              ("this_week", "This week"), ("last_week", "Last week"),
              ("this_month", "This month"), ("last_month", "Last month"),
              ("this_year", "This year"), ("last_year", "Last year"))

    def __init__(self, window):
        super().__init__(window)
        from .core import format_time
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        head = QHBoxLayout()
        title = QLabel(tr("Statistics"))
        title.setObjectName("h1")
        head.addWidget(title)
        head.addStretch(1)
        self.range_key = (window.config.get("ui") or {}).get("stats_range", "30d")
        if self.range_key not in [key for key, _label in self.RANGES] \
                and self.range_key != "custom":
            self.range_key = "30d"
        self._custom_range = None
        self._selected_card = None
        self._selected_title = None
        self._cells = {}
        self._cell_titles = []
        self.range_tool = QToolButton()
        self.range_tool.setObjectName("range")
        self.range_tool.setPopupMode(QToolButton.InstantPopup)
        self.range_tool.setCursor(Qt.PointingHandCursor)
        self.all_button = QPushButton("All time")
        self.all_button.setObjectName("chip")
        self.all_button.setCheckable(True)
        self.all_button.setCursor(Qt.PointingHandCursor)
        self.all_button.clicked.connect(lambda: self._set_range("all"))
        self._refresh_range_button()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(lambda: self.refresh(flush=True))
        head.addWidget(self.refresh_button)
        self.sessions_button = QPushButton("All Sessions\u2026")
        self.sessions_button.clicked.connect(self.open_sessions)
        head.addWidget(self.sessions_button)
        self.export_button = QPushButton("Export CSV\u2026")
        self.export_button.clicked.connect(self.export_csv)
        head.addWidget(self.export_button)
        outer.addLayout(head)

        range_row = QHBoxLayout()
        range_row.setSpacing(6)
        from_label = QLabel("From")
        from_label.setObjectName("help")
        range_row.addWidget(from_label)
        self.from_button = QPushButton("")
        self.from_button.setObjectName("date")
        self.from_button.setCursor(Qt.PointingHandCursor)
        self.from_button.clicked.connect(lambda: self._open_calendar("from"))
        range_row.addWidget(self.from_button)
        to_label = QLabel("To")
        to_label.setObjectName("help")
        range_row.addWidget(to_label)
        self.to_button = QPushButton("")
        self.to_button.setObjectName("date")
        self.to_button.setCursor(Qt.PointingHandCursor)
        self.to_button.clicked.connect(lambda: self._open_calendar("to"))
        range_row.addWidget(self.to_button)
        for text, step, tooltip in (("\u2039", -1, "Previous period"),
                                    ("\u203a", 1, "Next period")):
            button = QToolButton()
            button.setObjectName("step")
            button.setText(text)
            button.setToolTip(tooltip)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _c=False, s=step: self._shift_range(s))
            range_row.addWidget(button)
        range_row.addStretch(1)
        range_row.addWidget(self.range_tool)
        range_row.addWidget(self.all_button)
        outer.addLayout(range_row)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.card_values = {}
        for key, caption in (("read", "TIME READ"), ("novels", "VISUAL NOVELS"),
                             ("sessions", "SESSIONS")):
            card = QFrame()
            card.setObjectName("card")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 12, 14, 12)
            label = QLabel(caption)
            label.setObjectName("caps")
            value = QLabel("0s")
            value.setObjectName("metric")
            layout.addWidget(label)
            layout.addWidget(value)
            cards.addWidget(card, 1)
            self.card_values[key] = value
        outer.addLayout(cards)

        chart_card = QFrame()
        chart_card.setObjectName("card")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(14, 10, 14, 6)
        chart_layout.setSpacing(2)
        self.chart_title = QLabel("PER DAY")
        self.chart_title.setObjectName("caps")
        chart_layout.addWidget(self.chart_title)
        self.chart = BarChart()
        chart_layout.addWidget(self.chart)
        self.legend = QLabel("")
        self.legend.setObjectName("help")
        self.legend.setTextFormat(Qt.RichText)
        self.legend.setWordWrap(True)
        chart_layout.addWidget(self.legend)
        outer.addWidget(chart_card)

        from PySide6.QtWidgets import QScrollArea
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self.grid = QGridLayout(host)
        self.grid.setSpacing(12)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll, 1)
        self.empty = QLabel("Nothing recorded in this range yet.")
        self.empty.setObjectName("sub")
        self.empty.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty)
        self.foot = QLabel("")
        self.foot.setObjectName("sub")
        outer.addWidget(self.foot)

        self._auto = QTimer(self)
        self._auto.setInterval(500)
        self._auto.timeout.connect(self.refresh)
        self.refresh()

    # ---------- range ----------
    def _range_label(self):
        if self.range_key == "custom" and self._custom_range:
            return "%s \u2192 %s" % (self._custom_range[0].isoformat(),
                                      self._custom_range[1].isoformat())
        for key, label in self.RANGES:
            if key == self.range_key:
                return tr(label)
        return tr("All time")

    def _refresh_range_button(self):
        from PySide6.QtWidgets import QMenu
        self.range_tool.setText("%s  \u25be" % self._range_label())
        self.all_button.setText(tr("All time"))
        self.all_button.show()
        menu = QMenu(self)
        for key, label in self.RANGES:
            action = menu.addAction(tr(label))
            action.setCheckable(True)
            action.setChecked(key == self.range_key)
            action.triggered.connect(lambda _c=False, k=key: self._set_range(k))
        menu.addSeparator()
        all_action = menu.addAction(tr("All time"))
        all_action.setCheckable(True)
        all_action.setChecked(self.range_key == "all")
        all_action.triggered.connect(lambda _c=False: self._set_range("all"))
        if self.range_key == "custom":
            entry = menu.addAction(self._range_label())
            entry.setCheckable(True)
            entry.setChecked(True)
        self._range_menu = menu
        self.range_tool.setMenu(menu)
        self.all_button.setChecked(self.range_key == "all")

    def _sync_visibility(self):
        # keep the scroll area itself visible: only the hint toggles, so the cards
        # can never blink out while a refresh is in flight
        has_cards = bool(self._cells)
        self.scroll.setVisible(True)
        self.empty.setVisible(not has_cards)
        self.empty.raise_()

    def _sync_date_buttons(self):
        start, end = self._range()
        self.from_button.setText(start.strftime("%a, %d/%m/%Y"))
        self.to_button.setText(end.strftime("%a, %d/%m/%Y"))

    def _open_calendar(self, which):
        start, end = self._range()
        current = start if which == "from" else end
        popup = CalendarPopup(self, QDate(current.year, current.month, current.day))
        popup.picked.connect(lambda value, side=which: self._set_bound(side, value))
        button = self.from_button if which == "from" else self.to_button
        popup.move(button.mapToGlobal(button.rect().bottomLeft()))
        popup.show()

    def _set_bound(self, which, value):
        start, end = self._range()
        if which == "from":
            start = value
        else:
            end = value
        if end < start:
            start, end = end, start
        self._custom_range = (start, end)
        self._set_range("custom")

    @staticmethod
    def _add_months(value, months):
        import calendar
        from datetime import date
        month = value.month - 1 + months
        year = value.year + month // 12
        month = month % 12 + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    def _shift_range(self, step):
        """Move by the unit of the current range (week / month / year / N days)."""
        from datetime import timedelta
        start, end = self._range()
        key = self.range_key
        if key in ("this_week", "last_week") or key == "7d":
            shift = timedelta(days=7 * step)
            self._custom_range = (start + shift, end + shift)
        elif key in ("this_month", "last_month"):
            self._custom_range = (self._add_months(start, step),
                                  self._add_months(end, step))
        elif key in ("this_year", "last_year"):
            self._custom_range = (self._add_months(start, 12 * step),
                                  self._add_months(end, 12 * step))
        elif key == "30d":
            shift = timedelta(days=30 * step)
            self._custom_range = (start + shift, end + shift)
        elif key == "90d":
            shift = timedelta(days=90 * step)
            self._custom_range = (start + shift, end + shift)
        else:
            span = (end - start) + timedelta(days=1)
            self._custom_range = (start + span * step, end + span * step)
        self._set_range("custom")

    def _set_range(self, key):
        self.range_key = key
        self.window.config.setdefault("ui", {})["stats_range"] = key
        self._refresh_range_button()
        self.refresh()

    def _range(self):
        from datetime import date, timedelta
        today = date.today()
        key = self.range_key
        if key == "this_week":
            return today - timedelta(days=today.weekday()), today
        if key == "last_week":
            end = today - timedelta(days=today.weekday() + 1)
            return end - timedelta(days=6), end
        if key == "this_month":
            return date(today.year, today.month, 1), today
        if key == "last_month":
            end = date(today.year, today.month, 1) - timedelta(days=1)
            return date(end.year, end.month, 1), end
        if key == "all":
            return date(2000, 1, 1), today
        if key == "custom" and self._custom_range:
            return self._custom_range
        if key == "7d":
            return today - timedelta(days=6), today
        if key == "90d":
            return today - timedelta(days=89), today
        if key == "this_year":
            return date(today.year, 1, 1), today
        if key == "last_year":
            return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        return today - timedelta(days=29), today

    # ---------- lifecycle ----------
    def showEvent(self, event):
        super().showEvent(event)
        self._auto.start(500)

    def hideEvent(self, event):
        self._auto.stop()
        super().hideEvent(event)

    # ---------- data ----------
    def refresh(self, flush=False):
        if not flush and not self.isVisible():
            return
        return self._refresh_body(flush)

    def _refresh_body(self, flush=False):
        from .core import format_time
        if flush:
            try:
                self.engine.flush_open_segment()
            except Exception:
                pass
        start, end = self._range()
        day_from, day_to = start.isoformat(), end.isoformat()
        stats = getattr(self.app, "stats", None)
        seconds, sessions = stats.total(day_from, day_to) if stats else (0, 0)
        rows = stats.by_game(day_from, day_to) if stats else []
        # the segment being read right now is not in the database yet
        live, live_game = self._live_segment(start, end)
        seconds += live
        if live and live_game is not None:
            rows = self._add_live(rows, live_game, live)
        days = max(1, (end - start).days + 1)
        self.card_values["read"].setText(format_time(seconds))
        self.card_values["novels"].setText(str(len(rows)))
        self.card_values["sessions"].setText(str(sessions))
        self.foot.setText("%s \u2192 %s \u00b7 %d days" % (day_from, day_to, days))
        self._sync_date_buttons()
        self._update_chart(stats, start, end, days, live, live_game)
        self._render(rows, seconds)

    def _update_chart(self, stats, start, end, days, live=0.0, live_game=None):
        if not stats:
            self.chart.set_data([], {})
            self.legend.setText("")
            return
        if days <= 62:
            from datetime import timedelta
            labels = [(start + timedelta(days=offset)).isoformat()
                      for offset in range(days)]
            buckets = {label: {} for label in labels}
            for row in stats.by_day_game(start.isoformat(), end.isoformat()):
                day, key, seconds = row[0], row[1], (row[2] or 0)
                buckets.setdefault(day, {})
                buckets[day][key] = buckets[day].get(key, 0) + seconds
            if live and live_game is not None:
                today_key = start.__class__.today().isoformat()
                name = live_game.get("original") or live_game.get("title") or ""
                if today_key in buckets and name:
                    buckets[today_key][name] = buckets[today_key].get(name, 0) + live
            keys = []
            for label in labels:
                for key in buckets.get(label, {}):
                    if key not in keys:
                        keys.append(key)
            colours = {key: CHART_COLOURS[index % len(CHART_COLOURS)]
                       for index, key in enumerate(keys)}
            self.chart_title.setText("PER DAY")
            self.chart.set_data(
                [(label[5:], sorted(buckets.get(label, {}).items(),
                                    key=lambda item: -item[1]))
                 for label in labels], colours)
            self._update_legend(colours)
        else:
            rows = stats.by_month(start.isoformat(), end.isoformat())
            self.chart_title.setText(tr("PER MONTH"))
            self.chart.set_data([(row[0], [("Total", row[1] or 0)]) for row in rows],
                                {"Total": CHART_COLOURS[2]})
            self.legend.setText("")

    def _update_legend(self, colours):
        parts = []
        for key, colour in list(colours.items())[:14]:
            parts.append('<span style="color:%s;">&#9632;</span>&nbsp;%s' % (colour, key))
        self.legend.setText("&nbsp;&nbsp;&nbsp;".join(parts))

    def export_csv(self):
        from PySide6.QtWidgets import QFileDialog
        import csv
        import time
        start, end = self._range()
        stats = getattr(self.app, "stats", None)
        rows = stats.sessions(start.isoformat(), end.isoformat(), limit=100000) \
            if stats else []
        if not rows:
            QMessageBox.information(self, "Export CSV",
                                    tr("Nothing recorded in this range."))
            return
        default = str(Path(store.APP_DIR) / ("hygger-stats-%s.csv" % end.isoformat()))
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default, "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "visual_novel", "seconds", "started_at"])
            for row in rows:
                day, title, seconds, started = row[1], row[2], row[3], row[4]
                writer.writerow([day, title or "",
                                 int(round(seconds or 0)),
                                 time.strftime("%Y-%m-%d %H:%M:%S",
                                               time.localtime(started)) if started else ""])
        QMessageBox.information(self, "Export CSV",
                                "Exported %d session(s) to:\n%s" % (len(rows), path))

    def _live_segment(self, start, end):
        """Pending seconds (buffer + open segment) so the total never drops."""
        engine = self.engine
        if not hasattr(engine, "pending_seconds"):
            return 0.0, None
        pending, game = engine.pending_seconds()
        if pending <= 0.0 or game is None:
            return 0.0, None
        from datetime import date
        if not (start <= date.today() <= end):
            return 0.0, None
        return pending, game

    @staticmethod
    def _add_live(rows, game, live):
        out = []
        found = False
        for row in rows:
            if isinstance(row, dict):
                entry = dict(row)
            else:
                entry = {"title": row[0], "vndb_id": row[1] if len(row) > 1 else "",
                         "seconds": row[2] if len(row) > 2 else 0,
                         "sessions": row[4] if len(row) > 4 else 0}
            if (entry.get("vndb_id") and entry.get("vndb_id") == game.get("vndb_id")) \
                    or (not entry.get("vndb_id")
                        and entry.get("title") == (game.get("original")
                                                   or game.get("title"))):
                entry["seconds"] = (entry.get("seconds") or 0) + live
                found = True
            out.append(entry)
        if not found:
            out.append({"title": game.get("original") or game.get("title") or "",
                        "vndb_id": game.get("vndb_id") or "", "seconds": live,
                        "sessions": 0})
        return out

    def _rows_as_dicts(self, rows):
        out = []
        for row in rows:
            if isinstance(row, dict):
                out.append({"vndb_id": row.get("vndb_id", ""),
                            "title": row.get("title") or "",
                            "seconds": row.get("seconds") or 0})
            elif len(row) >= 3:
                # by_game(): (title, vndb_id, seconds, last_day, session_count)
                out.append({"title": row[0] or "", "vndb_id": row[1] or "",
                            "seconds": row[2] or 0, "sessions": row[4] if len(row) > 4 else 0})
            else:
                out.append({"title": row[0] if row else "", "vndb_id": "",
                            "seconds": 0})
        return out

    def _render(self, rows, total_seconds):
        from .core import format_time
        games = self._rows_as_dicts(rows)
        titles = [game["title"] or game["vndb_id"] for game in games]
        if titles == self._cell_titles and self._cells:
            for game in games:
                entry = self._cells.get(game["title"] or game["vndb_id"])
                if entry is None:
                    continue
                _cell, read, share = entry
                read.setText(format_time(game["seconds"]))
                share.setText("%.1f%%" % (100.0 * game["seconds"] / total_seconds
                                          if total_seconds else 0.0))
            self._sync_visibility()
            return

        # build the whole grid off-screen and swap it in one go: no half-empty
        # states, no flicker, no stale widgets
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)
        for column in range(8):
            grid.setColumnStretch(column, 1 if column == 7 else 0)
        cells = {}
        for index, game in enumerate(games):
            cell = CardFrame()
            layout = QVBoxLayout(cell)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(6)
            cell.setFixedWidth(150)
            cover = QLabel("VN")
            cover.setFixedSize(90, 120)
            cover.setAlignment(Qt.AlignCenter)
            layout.addWidget(cover, 0, Qt.AlignHCenter)
            name = QLabel(game["title"] or game["vndb_id"])
            name.setWordWrap(True)
            name.setFixedHeight(34)
            layout.addWidget(name)
            read = QLabel(format_time(game["seconds"]))
            read.setObjectName("h3")
            layout.addWidget(read)
            share = QLabel("%.1f%%" % (100.0 * game["seconds"] / total_seconds
                                       if total_seconds else 0.0))
            share.setObjectName("help")
            layout.addWidget(share)
            title = game["title"] or game["vndb_id"]
            cell.setProperty("vn_title", title)
            cell.clicked.connect(lambda card=cell: self._select_card(card))
            cell.double.connect(lambda name=title: self.open_sessions_for(name))
            if self._selected_title == title:
                cell.set_selected(True)
                self._selected_card = cell
            layout.addStretch(1)
            grid.addWidget(cell, index // 6, index % 6, Qt.AlignTop)
            url = self._cover_for(game["vndb_id"])
            if url:
                self.window.request_cover(
                    url, lambda u, image, label=cover: self._apply_cover(label, image))
            cells[title] = (cell, read, share)
        self.scroll.setWidget(host)          # atomic swap (old host is deleted)
        self.grid = grid
        self._cells = cells
        self._cell_titles = titles
        self._sync_visibility()

    def _select_card(self, card):
        if self._selected_card is card:
            card.set_selected(False)
            self._selected_card = None
            self._selected_title = None
            return
        if self._selected_card is not None:
            self._selected_card.set_selected(False)
        card.set_selected(True)
        self._selected_card = card
        self._selected_title = card.property("vn_title")

    def open_sessions_for(self, title):
        start, end = self._range()
        dialog = SessionsDialog(self, start.isoformat(), end.isoformat(),
                                only_title=title)
        dialog.exec()
        self.refresh()

    def _cover_for(self, vndb_id):
        for game in self.engine.games:
            if game.get("vndb_id") == vndb_id and game.get("image"):
                return game["image"]
        return ""

    def _apply_cover(self, label, image):
        if image is None:
            return
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap.fromImage(image).scaled(90, 120, Qt.KeepAspectRatio,
                                                 Qt.SmoothTransformation)
        label.setPixmap(pixmap)

    # ---------- sessions ----------
    def open_sessions(self):
        start, end = self._range()
        dialog = SessionsDialog(self, start.isoformat(), end.isoformat())
        dialog.exec()
        self.refresh()


# ===================================================================== screenshots
class ScreenshotSettingsMixin:
    def _build_screenshot(self):
        page, layout = self._page()
        opts = self.window.config.setdefault("screenshot", {})
        layout.addWidget(QLabel(tr("Screenshot folder")))
        row = QHBoxLayout()
        self.shot_path = QLineEdit(opts.get("path") or default_pictures())
        row.addWidget(self.shot_path, 1)
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self._pick_shot_folder)
        row.addWidget(browse)
        opener = QPushButton(tr("Open folder"))
        opener.clicked.connect(self.window.open_screenshot_folder)
        row.addWidget(opener)
        layout.addLayout(row)
        self._help(layout, tr("One folder per game, named after the title."))


        layout.addWidget(QLabel(tr("Hotkey")))
        line = QHBoxLayout()
        line.addWidget(QLabel(tr("Capture the active window")))
        line.addStretch(1)
        self.shot_hotkey = QLineEdit(opts.get("hotkey") or "")
        self.shot_hotkey.setReadOnly(True)
        self.shot_hotkey.setPlaceholderText(tr("Not set"))
        self.shot_hotkey.mousePressEvent = self._bind_hotkey_click
        line.addWidget(self.shot_hotkey, 1)
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self._clear_hotkey)
        line.addWidget(clear)
        layout.addLayout(line)
        self._help(layout, tr("Click the field and press a key combination. "
                              "Escape removes it."))

        layout.addSpacing(12)
        layout.addWidget(QLabel(tr("Sound")))
        sound_row = QHBoxLayout()
        self.shot_sound = QLineEdit(opts.get("sound") or "")
        self.shot_sound.setReadOnly(True)
        self.shot_sound.setPlaceholderText(tr("System default"))
        sound_row.addWidget(self.shot_sound, 1)
        pick = QPushButton(tr("Choose…"))
        pick.clicked.connect(self._pick_sound)
        sound_row.addWidget(pick)
        test = QPushButton(tr("Test"))
        test.clicked.connect(lambda: self.window.play_sound())
        sound_row.addWidget(test)
        clear_sound = QPushButton(tr("Clear"))
        clear_sound.clicked.connect(self._clear_sound)
        sound_row.addWidget(clear_sound)
        layout.addLayout(sound_row)
        self._help(layout, tr("WAV file played after each screenshot."))
        layout.addStretch(1)
        return page

    def _pick_sound(self):
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getOpenFileName(self, tr("Choose a sound"), "",
                                               tr("Sound files (*.wav)"))
        if path:
            self.shot_sound.setText(path)
            self.window.set_sound(path)

    def _clear_sound(self):
        self.shot_sound.setText("")
        self.shot_sound.setPlaceholderText(tr("System default"))
        self.window.set_sound("")

    def _bind_hotkey_click(self, event):
        self.window.start_hotkey_capture(self.shot_hotkey)
        return QLineEdit.mousePressEvent(self.shot_hotkey, event)

    def _clear_hotkey(self):
        self.shot_hotkey.setText("")
        self.shot_hotkey.setPlaceholderText(tr("Not set"))
        self.window.set_hotkey("")

    def _pick_shot_folder(self):
        from PySide6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, tr("Screenshot folder"),
                                                  self.shot_path.text() or "")
        if folder:
            self.shot_path.setText(folder)
            self.window.set_screenshot_folder(folder)


def default_pictures():
    """Pictures/HyggerPresence - the same folder the store uses."""
    return str(shots.default_base_dir())


class ScreenshotPage(Page):
    """games -> folder -> one screenshot, all in the same page."""

    COVER = (150, 200)
    THUMB = (300, 170)

    def __init__(self, window):
        super().__init__(window)
        from PySide6.QtWidgets import QScrollArea
        self._view, self._folder, self._shot = "games", "", None
        self._limit = 60
        self._cards = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.back_button = QPushButton(tr("Back"))
        self.back_button.clicked.connect(self.go_back)
        self.back_button.setVisible(False)
        head.addWidget(self.back_button)
        self.title_label = QLabel(tr("Screenshots"))
        self.title_label.setObjectName("h1")
        head.addWidget(self.title_label)
        self.count_label = QLabel("")
        self.count_label.setObjectName("sub")
        head.addWidget(self.count_label)
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search title…"))
        self.search.textChanged.connect(self._fill)
        self.search.setFixedWidth(220)
        head.addWidget(self.search)
        self.open_folder_button = QPushButton(tr("Open folder"))
        self.open_folder_button.setFixedWidth(120)
        self.open_folder_button.clicked.connect(self._open_current_folder)
        head.addWidget(self.open_folder_button)
        outer.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)

        # single screenshot view
        self.single = QWidget()
        single_lay = QVBoxLayout(self.single)
        single_lay.setContentsMargins(0, 0, 0, 0)
        single_lay.setSpacing(10)
        self.shot_image = QLabel()
        self.shot_image.setAlignment(Qt.AlignCenter)
        single_lay.addWidget(self.shot_image, 1)
        self.shot_info = QLabel("")
        self.shot_info.setObjectName("sub")
        single_lay.addWidget(self.shot_info)
        row = QHBoxLayout()
        copy = QPushButton(tr("Copy"))
        copy.clicked.connect(self._copy_shot)
        row.addWidget(copy)
        open_it = QPushButton(tr("Open"))
        open_it.clicked.connect(self._open_shot)
        row.addWidget(open_it)
        reveal = QPushButton(tr("Show in folder"))
        reveal.clicked.connect(self._reveal_shot)
        row.addWidget(reveal)
        delete = QPushButton(tr("Delete"))
        delete.setObjectName("danger")
        delete.setStyleSheet("QPushButton{background:#b0392f;color:#ffffff;}"
                             "QPushButton:hover{background:#c9483c;}")
        delete.clicked.connect(self._delete_shot)
        row.addWidget(delete)
        row.addStretch(1)
        single_lay.addLayout(row)
        self.single.setVisible(False)
        outer.addWidget(self.single, 1)

        self.empty = QLabel(tr("No screenshots"))
        self.empty.setObjectName("sub")
        self.empty.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty)

        # Escape must work even when the focus sits on a nav button
        from PySide6.QtWidgets import QApplication

        page = self

        class _Escape(QObject):
            def eventFilter(self, obj, event):
                if event.type() != QEvent.KeyPress or not page.isVisible():
                    return False
                if event.key() == Qt.Key_Escape:
                    if page._view == "games":
                        return False
                    page.go_back()
                    return True
                if event.key() == Qt.Key_A and (event.modifiers() & Qt.ControlModifier):
                    page.select_all()
                    return True
                if event.key() == Qt.Key_Delete:
                    page.delete_selection()
                    return True
                if event.key() == Qt.Key_C and (event.modifiers() & Qt.ControlModifier):
                    page.copy_selection()
                    return True
                return False

        self._escape_filter = _Escape(self)
        QApplication.instance().installEventFilter(self._escape_filter)

        self._selection = set()
        self._rubber = None
        self._rubber_origin = None
        from PySide6.QtCore import QFileSystemWatcher
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_files_changed)
        self._watcher.directoryChanged.connect(self._on_files_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(800)
        self._refresh_timer.timeout.connect(self._fill)

        self._thumb_jobs = []
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(8)
        self._thumb_timer.timeout.connect(self._load_next_thumbs)

        self.refresh()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _thumb_cache_dir():
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(root) / "HyggerPresence" / "thumbs"

    def _cached_thumb(self, path, size):
        """Thumbnails are cached on disk, like Explorer does."""
        import hashlib
        try:
            stat = path.stat()
        except OSError:
            return QPixmap()
        key = hashlib.md5(("%s|%d|%d|%dx%d" % (path, stat.st_mtime_ns, stat.st_size,
                                               size[0], size[1])).encode()).hexdigest()
        cache = self._thumb_cache_dir() / ("%s.png" % key)
        if cache.exists():
            pixmap = QPixmap(str(cache))
            if not pixmap.isNull():
                return pixmap
        pixmap = self._fast_pixmap(path, size)
        if not pixmap.isNull():
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                pixmap.save(str(cache), "PNG")
            except Exception:
                pass
        return pixmap

    def _load_next_thumbs(self):
        """Fill placeholders a few at a time so the page never freezes."""
        if not self._thumb_jobs:
            self._thumb_timer.stop()
            return
        for _ in range(6):
            if not self._thumb_jobs:
                self._thumb_timer.stop()
                return
            label, path = self._thumb_jobs.pop(0)
            try:
                pixmap = self._cached_thumb(path, self.THUMB)
                if not pixmap.isNull() and label is not None:
                    label.setPixmap(pixmap)
            except RuntimeError:
                pass

    def _on_files_changed(self, *_args):
        self._watch_paths()
        if not self.isVisible() or getattr(self, "_capturing", False):
            self._dirty = True          # refresh when the page is shown again
            return
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _watch_paths(self):
        """Watch the root and every game folder, so counts refresh live."""
        wanted = []
        store_ = self._shot_store()
        try:
            root = store_.root
            if root.exists():
                wanted.append(str(root))
                for index, sub in enumerate(sorted(root.iterdir())):
                    if index >= 40:
                        break
                    if sub.is_dir():
                        wanted.append(str(sub))
        except Exception:
            pass
        for path in self._watcher.directories():
            if path not in wanted:
                self._watcher.removePath(path)
        for path in wanted:
            if path not in self._watcher.directories():
                self._watcher.addPath(path)

    def _shot_store(self):
        return getattr(self.window, "shot_store", None) or shots.ScreenshotStore()

    @staticmethod
    def _as_pixmap(cover):
        if cover is None:
            return None
        if isinstance(cover, QPixmap):
            return cover if not cover.isNull() else None
        if isinstance(cover, QImage):
            return QPixmap.fromImage(cover)
        try:
            return QPixmap(cover)
        except Exception:
            return None

    @staticmethod
    def _fast_pixmap(path, size):
        """Decode straight to the thumbnail size: much faster for big PNGs."""
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        source = reader.size()
        if source.isValid():
            scaled = source.scaled(QSize(size[0], size[1]), Qt.KeepAspectRatio)
            reader.setScaledSize(scaled)
        image = reader.read()
        return QPixmap.fromImage(image) if not image.isNull() else QPixmap()

    def _search_blob(self, folder):
        parts = [folder]
        for game in getattr(self.window.app, "games", []) or []:
            if shots.sanitise(game.get("original") or game.get("title") or "") != folder:
                continue
            parts.extend(str(game.get(key, "")) for key in
                         ("original", "title", "romanized", "developer", "year",
                          "vndb_id", "exe"))
            break
        return " ".join(parts).lower()

    def _title_mode(self):
        return (self.window.config.get("library_title_mode") or "original")

    def _library_title(self, folder):
        romanise = self._title_mode() == "romanized"
        for game in getattr(self.window.app, "games", []) or []:
            original = game.get("original") or game.get("title") or ""
            if shots.sanitise(original) != folder:
                continue
            return (game.get("title") or original) if romanise else (original or folder)
        return folder

    def _cover_for(self, folder):
        for game in getattr(self.window.app, "games", []) or []:
            if shots.sanitise(game.get("original") or game.get("title") or "") != folder:
                continue
            url = game.get("image") or ""
            cached = self.window.app.cover_cache.get(url) if url else None
            if cached is not None:
                return self._as_pixmap(cached)
            if url:
                self.window.request_cover(url, lambda _u, _i: self._fill())
            return None
        return None

    def _columns(self, width, size):
        return max(1, width // (size[0] + 34))

    # -------------------------------------------------------------------- views
    def show_games(self):
        self._view, self._folder, self._shot = "games", "", None
        self._fill()

    def open_folder(self, folder):
        self._view, self._folder, self._shot = "folder", folder, None
        self._limit = 60
        self._fill()

    def open_shot(self, path):
        self._view, self._shot = "shot", Path(path)
        self._fill()

    def go_back(self):
        """Escape / Back: one level up."""
        if self._view == "shot":
            self.open_folder(self._folder)
        elif self._view == "folder":
            self.show_games()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.go_back()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- selection
    def _card_pressed(self, event, path):
        from PySide6.QtWidgets import QApplication
        if event.button() == Qt.RightButton:
            if str(path) not in self._selection:
                self._selection = {str(path)}
                self._paint_selection()
            self._show_menu(position=event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        key = str(path)
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            if key in self._selection:
                self._selection.discard(key)
            else:
                self._selection.add(key)
        else:
            self._selection = {key}
        self._paint_selection()

    def _game_pressed(self, event, folder):
        if event.button() == Qt.RightButton:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            menu.setStyleSheet(MENU_QSS % self.window.palette)
            action = menu.addAction(tr("Open folder"))
            if menu.exec(event.globalPosition().toPoint()) is action:
                shots.open_folder(self._shot_store().folder_for(folder))
            return
        if event.button() != Qt.LeftButton:
            return
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            if folder in self._selection:
                self._selection.discard(folder)
            else:
                self._selection.add(folder)
        else:
            self._selection = {folder}
        self._paint_selection()

    def _paint_selection(self):
        accent = self.window.palette.get("accent", "#5b8def")
        for key, card in self._cards.items():
            if not hasattr(card, "setStyleSheet"):
                continue
            border = (("2px solid %s" % accent) if key in self._selection
                      else "2px solid transparent")
            card.setStyleSheet(CARD_QSS % dict(self.window.palette, border=border))

    def _apply_selection_style(self):
        style = self.styleSheet()
        if "card[selected=\"true\"]" in style:
            return
        self.setStyleSheet(style + """
QFrame#card[selected=\"true\"] { border:1px solid #5b8def; }
""")

    def select_all(self):
        if self._view != "folder":
            return
        self._selection = set(self._cards.keys())
        self._paint_selection()

    def _show_menu(self, event=None, position=None):
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QCursor
        menu = QMenu(self)
        menu.setStyleSheet(MENU_QSS % self.window.palette)
        count = len(self._selection)
        single = count == 1
        copy = menu.addAction(tr("Copy"))
        copy.setEnabled(count >= 1)
        open_action = menu.addAction(tr("Open"))
        open_action.setEnabled(single)
        reveal = menu.addAction(tr("Show in folder"))
        reveal.setEnabled(single)
        menu.addSeparator()
        delete = menu.addAction(tr("Delete") + (" (%d)" % count if count else ""))
        delete.setEnabled(count >= 1)
        where = position or (event.globalPosition().toPoint() if event is not None
                             else QCursor.pos())
        action = menu.exec(where)
        if action is None:
            return
        if action is delete:
            self.delete_selection()
        elif action is copy:
            self.copy_selection()
        elif single:
            path = Path(next(iter(self._selection)))
            if action is open_action:
                self._shot = path
                self._open_shot()
            elif action is reveal:
                shots.reveal_in_explorer(path)

    def copy_selection(self):
        """Copy the selected images; more than one goes to the clipboard as files."""
        paths = [Path(p) for p in self._selection if Path(p).exists()]
        if not paths:
            return
        from PySide6.QtCore import QMimeData, QUrl
        from PySide6.QtWidgets import QApplication
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
        if len(paths) == 1:
            image = QImage(str(paths[0]))
            if not image.isNull():
                mime.setImageData(image)
        QApplication.clipboard().setMimeData(mime)

    def contextMenuEvent(self, event):
        if self._view == "folder":
            self._show_menu(position=event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def delete_selection(self):
        paths = [Path(p) for p in self._selection if Path(p).exists()]
        if not paths:
            return
        if len(paths) > 1:
            from PySide6.QtWidgets import QMessageBox
            answer = QMessageBox.question(
                self, tr("Delete screenshots"),
                tr("Delete %d screenshots?") % len(paths))
            if answer != QMessageBox.Yes:
                return
        for path in paths:
            shots.ScreenshotStore.delete(path)
        self._selection = set()
        self._fill()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.go_back()
            event.accept()
            return
        if event.key() == Qt.Key_A and (event.modifiers() & Qt.ControlModifier):
            self.select_all()
            event.accept()
            return
        if event.key() == Qt.Key_Delete:
            self.delete_selection()
            event.accept()
            return
        if event.key() == Qt.Key_C and (event.modifiers() & Qt.ControlModifier):
            self.copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self._view == "folder" and event.button() == Qt.LeftButton:
            self._rubber_origin = event.position().toPoint()
            self._selection = set()
            self._paint_selection()

    def mouseMoveEvent(self, event):
        if self._rubber_origin is None:
            return
        from PySide6.QtWidgets import QRubberBand
        if self._rubber is None:
            self._rubber = QRubberBand(QRubberBand.Rectangle, self)
        rect = QRect(self._rubber_origin, event.position().toPoint()).normalized()
        self._rubber.setGeometry(rect)
        self._rubber.show()
        for key, card in self._cards.items():
            if not hasattr(card, "geometry"):
                continue
            area = QRect(card.mapTo(self, QPoint(0, 0)), card.size())
            if rect.intersects(area):
                self._selection.add(key)
        self._paint_selection()

    def mouseReleaseEvent(self, event):
        if self._rubber is not None:
            self._rubber.hide()
        self._rubber_origin = None

    def _load_more(self):
        self._limit += 120
        self._fill()

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_dirty", False):
            self._dirty = False
            QTimer.singleShot(0, self._fill)

    def refresh(self):
        self._fill()

    # --------------------------------------------------------------------- fill
    def _fill(self):
        import time as _t3
        _fill_started = _t3.time()
        store_ = self._shot_store()
        is_shot = self._view == "shot"
        self.back_button.setVisible(self._view != "games")
        self.search.setVisible(self._view == "games")
        self.scroll.setVisible(not is_shot)
        self.single.setVisible(is_shot)
        self.empty.setVisible(False)

        if is_shot:
            self._fill_single()
            return

        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(14)
        grid.setContentsMargins(0, 0, 0, 0)
        self._cards = {}
        width = max(360, self.width() - 60)

        if self._view == "games":
            self.title_label.setText(tr("Screenshots"))
            games = store_.games_with_shots()
            needle = (self.search.text() or "").strip().lower()
            if needle:
                games = [g for g in games if needle in self._search_blob(g[0])]
            self.count_label.setText(tr("%d screenshot(s)") % sum(c for _f, c in games))
            columns = self._columns(width, self.COVER)
            for index, (folder, count) in enumerate(games):
                card = self._game_card(folder, count)
                grid.addWidget(card, index // columns, index % columns)
                self._cards[folder] = card
            self.empty.setText(tr("No screenshots"))
            self.empty.setVisible(not games)
            grid.setRowStretch(len(games) // columns + 1, 1)
        else:
            self.title_label.setText(self._library_title(self._folder))
            paths = store_.shots_for(self._folder)
            self.count_label.setText(tr("%d screenshot(s)") % len(paths))
            columns = self._columns(width, self.THUMB)
            self._thumb_jobs = []
            shown = paths[:self._limit]
            for index, path in enumerate(shown):
                card, art = self._shot_card(path, deferred=True)
                grid.addWidget(card, index // columns, index % columns)
                self._cards[str(path)] = card
                self._thumb_jobs.append((art, path))
            if len(paths) > self._limit:
                more = QPushButton(tr("Load more (%d left)") % (len(paths) - self._limit))
                more.clicked.connect(self._load_more)
                grid.addWidget(more, len(shown) // columns + 1, 0, 1, min(columns, 4))
            if self._thumb_jobs:
                self._thumb_timer.start()
            else:
                self._thumb_timer.stop()
            self.empty.setText(tr("No screenshots"))
            self.empty.setVisible(not paths)
            grid.setRowStretch(len(shown) // columns + 2, 1)

        self.scroll.setWidget(host)
        self._watch_paths()
        try:
            from .core import debug_log
            debug_log("gallery %s rebuilt in %.0f ms (%d cards)"
                      % (self._view, (_t3.time() - _fill_started) * 1000.0,
                         len(self._cards)))
        except Exception:
            pass

    def _fill_single(self):
        path = self._shot
        self.title_label.setText(path.name if path else "")
        self.count_label.setText("")
        if path is None or not path.exists():
            self.empty.setVisible(True)
            self.single.setVisible(False)
            return
        from PySide6.QtGui import QImageReader
        reader = QImageReader(str(path))
        size = reader.size()
        width = max(320, self.width() - 80)
        height = max(200, self.height() - 220)
        scaled = self._fast_pixmap(path, (width, height))
        self.shot_image.setPixmap(scaled)
        self.shot_info.setText("%s   \u2022   %d x %d   \u2022   %s"
                               % (path.name, size.width(), size.height(),
                                  time.strftime("%Y-%m-%d %H:%M",
                                                time.localtime(path.stat().st_mtime))))

    # -------------------------------------------------------------------- cards
    def _game_card(self, folder, count):
        card = QFrame()
        card.setObjectName("shotcard")
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedWidth(self.COVER[0] + 30)
        card.setStyleSheet(CARD_QSS % dict(self.window.palette, border="2px solid transparent"))
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        art = QLabel()
        art.setFixedSize(*self.COVER)
        art.setAlignment(Qt.AlignCenter)
        art.setStyleSheet("QLabel{background:%s;border-radius:4px;}"
                          % self.window.palette["surface2"])
        cover = self._cover_for(folder)
        if cover is not None:
            art.setPixmap(cover.scaled(self.COVER[0], self.COVER[1], Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
        lay.addWidget(art, 0, Qt.AlignHCenter)
        name = QLabel(self._library_title(folder))
        name.setObjectName("h3")
        name.setWordWrap(True)
        name.setFixedHeight(48)
        lay.addWidget(name)
        sub = QLabel(tr("%d Screenshot(s)") % count)
        sub.setObjectName("sub")
        lay.addWidget(sub)
        card.mouseDoubleClickEvent = lambda _e, f=folder: self.open_folder(f)
        card.mousePressEvent = lambda e, f=folder: self._game_pressed(e, f)
        card.setProperty("selected", "false")
        return card

    def _shot_card(self, path, deferred=False):
        card = QFrame()
        card.setObjectName("shotcard")
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedWidth(self.THUMB[0] + 16)
        card.setStyleSheet(CARD_QSS % dict(self.window.palette, border="2px solid transparent"))
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        art = QLabel()
        art.setFixedSize(*self.THUMB)
        art.setAlignment(Qt.AlignCenter)
        art.setStyleSheet("QLabel{background:%s;border-radius:4px;}"
                          % self.window.palette["surface2"])
        if deferred:
            pass                      # _fill() queues the job after adding the card
        else:
            pixmap = self._cached_thumb(path, self.THUMB)
            if not pixmap.isNull():
                art.setPixmap(pixmap)
        lay.addWidget(art, 0, Qt.AlignHCenter)
        name = QLabel(path.name)
        name.setObjectName("sub")
        name.setWordWrap(True)
        lay.addWidget(name)
        card.mouseDoubleClickEvent = lambda _e, p=path: self.open_shot(p)
        card.mousePressEvent = lambda e, p=path: self._card_pressed(e, p)
        card.setProperty("selected", "false")
        return card, art

    # ------------------------------------------------------------------ actions
    def _open_current_folder(self):
        store_ = self._shot_store()
        if self._view == "folder" and self._folder:
            shots.open_folder(store_.folder_for(self._folder))
        else:
            try:
                store_.root.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            shots.open_folder(store_.root)

    def _copy_shot(self):
        if self._shot and self._shot.exists():
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setPixmap(QPixmap(str(self._shot)))

    def _open_shot(self):
        """Open in the program associated with PNG; explorer covers odd setups."""
        if not (self._shot and self._shot.exists()):
            return
        target = str(self._shot)
        try:
            os.startfile(target)
            return
        except Exception:
            pass
        try:
            import subprocess
            subprocess.Popen(["explorer", target])
            return
        except Exception:
            pass
        try:
            import subprocess
            subprocess.Popen(["rundll32", "shell32.dll,ShellExec_RunDLL", target])
        except Exception:
            pass

    def _reveal_shot(self):
        if self._shot and self._shot.exists():
            shots.reveal_in_explorer(self._shot)

    def _delete_shot(self):
        if not self._shot:
            return
        shots.ScreenshotStore.delete(self._shot)
        self.open_folder(self._folder)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not getattr(self, "_resize_timer", None):
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._fill)
        self._resize_timer.start(150)


class ScreenshotMixin:
    def set_screenshot_folder(self, folder):
        opts = self.config.setdefault("screenshot", {})
        opts["path"] = folder or ""
        self.shot_store = shots.ScreenshotStore(folder or None)
        store.save_config(self.config)
        if hasattr(self, "shots_page"):
            self.shots_page.refresh()

    def open_screenshot_folder(self):
        """Reveal Pictures\\HyggerPresence in Explorer."""
        store_ = getattr(self, "shot_store", None)
        folder = store_.root if store_ is not None else None
        if folder is None:
            from .screenshot import default_base_dir
            folder = default_base_dir()
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        shots.open_folder(folder)

    def current_game_title(self):
        game = self.engine.game or {}
        return (game.get("original") or game.get("title") or "").strip()

    def game_in_foreground(self):
        """True when the detected game owns the foreground window."""
        try:
            from .winapi import get_foreground_pid
            pid = get_foreground_pid()
        except Exception:
            return False
        if not pid:
            return False
        game = self.engine.game
        if not game:
            return False
        try:
            tracked = set(self.engine.pids_for_game(game) or ())
        except Exception:
            tracked = set()
        if pid in tracked:
            return True
        try:
            from .winapi import get_ancestor_pids
            return bool(tracked & set(get_ancestor_pids(pid) or ()))
        except Exception:
            return False

    def take_screenshot(self):
        if not hasattr(self, "shot_store"):
            return
        if not self.game_in_foreground():
            return

        # No delay: the window does not move away, and a delayed grab used to
        # capture whatever had the focus by then.
        self._capturing = True
        import time as _t
        _started = _t.time()
        pixmap = shots.capture_window()
        if pixmap is None:
            self._capturing = False
        else:
            try:
                from .core import debug_log
                debug_log("capture %dx%d in %.0f ms"
                          % (pixmap.width(), pixmap.height(),
                             (_t.time() - _started) * 1000.0))
            except Exception:
                pass
        if pixmap is None:
            return
        shots.beep((self.config.get("screenshot") or {}).get("sound") or "")
        title = self.current_game_title() or shots.FOLDER_FALLBACK
        store_ = self.shot_store

        def save_in_background():
            import time as _t2
            _t0 = _t2.time()
            try:
                saved = store_.save(pixmap, title)
                try:
                    from .core import debug_log
                    debug_log("saved %s in %.0f ms"
                              % (saved.name, (_t2.time() - _t0) * 1000.0))
                except Exception:
                    pass
            except Exception:
                return
            self._capturing = False
            QTimer.singleShot(0, self._after_screenshot)

        threading.Thread(target=save_in_background, daemon=True).start()

    def _after_screenshot(self):
        """Rebuild once, 1.5 s after the last shot, instead of after every one."""
        page = getattr(self, "shots_page", None)
        if page is None:
            return
        page._dirty = True
        timer = getattr(self, "_shot_refresh_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(1500)
            timer.timeout.connect(self._flush_shot_refresh)
            self._shot_refresh_timer = timer
        timer.start()

    def _flush_shot_refresh(self):
        page = getattr(self, "shots_page", None)
        if page is None or not page._dirty:
            return
        page._dirty = False
        if page.isVisible():
            page._fill()

    def _push_shot_count(self):
        return 0

    def _on_hotkey(self, _name):
        self.take_screenshot()

    def set_sound(self, path):
        opts = self.config.setdefault("screenshot", {})
        opts["sound"] = path or ""
        store.save_config(self.config)

    def play_sound(self):
        shots.beep((self.config.get("screenshot") or {}).get("sound") or "")

    def set_hotkey(self, spec):
        opts = self.config.setdefault("screenshot", {})
        opts["hotkey"] = spec
        store.save_config(self.config)
        self._register_hotkey()

    def _register_hotkey(self):
        manager = getattr(self, "hotkeys", None)
        if manager is None:
            return
        spec = ((self.config.get("screenshot") or {}).get("hotkey") or "").strip()
        parsed = hotkey_mod.parse(spec) if spec else None
        if not parsed:
            manager.release()
            self._hotkey_timer.stop()
            return
        if not manager.is_bound():
            manager.release()
            manager.bind("window", parsed[0], parsed[1])
        if not self._hotkey_timer.isActive():
            self._hotkey_timer.start()

    def _poll_hotkey(self):
        spec = ((self.config.get("screenshot") or {}).get("hotkey") or "").strip()
        parsed = hotkey_mod.parse(spec) if spec else None
        if not parsed:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            modifiers, key = parsed
            need = []
            if modifiers & 0x0002:
                need.append(0x11)
            if modifiers & 0x0001:
                need.append(0x12)
            if modifiers & 0x0004:
                need.append(0x10)
            if modifiers & 0x0008:
                need.append(0x5B)
            down = bool(user32.GetAsyncKeyState(key) & 0x8000)
            mods_ok = all(user32.GetAsyncKeyState(vk) & 0x8000 for vk in need) if need else True
        except Exception:
            return
        pressed = down and mods_ok
        if pressed and not self._hotkey_state:
            self.take_screenshot()
        self._hotkey_state = pressed

    def start_hotkey_capture(self, field):
        from PySide6.QtWidgets import QApplication

        class _Grabber(QObject):
            def __init__(self, window, target):
                super().__init__(window)
                self.window, self.target = window, target

            def eventFilter(self, obj, event):
                if event.type() != QEvent.KeyPress:
                    return False
                if event.key() == Qt.Key_Escape:
                    self.target.setText("")
                    self.target.setPlaceholderText(tr("Not set"))
                    self.window.set_hotkey("")
                    QApplication.instance().removeEventFilter(self)
                    return True
                parsed = from_qt(event.key(), event.modifiers())
                if not parsed:
                    # keep listening: a bare modifier must not end the capture
                    return True
                text = describe(parsed[0], parsed[1])
                self.target.setText(text)
                self.window.set_hotkey(text)
                QApplication.instance().removeEventFilter(self)
                return True

        grabber = _Grabber(self, field)
        QApplication.instance().installEventFilter(grabber)
        self._hotkey_grabber = grabber


class SettingsPage(ScreenshotSettingsMixin, Page):
    """Settings with the 1.0.4 shape: General / Presence (4 sub tabs) / Launchers /
    Updates. Every field has the explanation *under* it as small grey text, and each
    group has its own "Reset to default"."""

    def __init__(self, window):
        super().__init__(window)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)

        title = QLabel(tr("Settings"))
        title.setObjectName("h1")
        outer.addWidget(title)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self._build_general()
        self._build_presence()
        self._build_launchers()
        self._build_updates()

        buttons = QHBoxLayout()
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        buttons.addWidget(save)
        buttons.addStretch(1)
        self.version = QLabel("")
        self.version.setObjectName("sub")
        self.version.hide()
        outer.addLayout(buttons)

        self._reload_launchers()
        self._sync_enabled_fields()

    # ------------------------------------------------------------ helpers
    VARIABLES = (
        ("{title}", "{title} – game title (original script)"),
        ("{romanized_title}", "{romanized_title} – romanised title"),
        ("{developer}", "{developer} – developer name"),
        ("{year}", "{year} – release year"),
        ("{status}", "{status} – Reading / Paused / Idle"),
        ("{session_time}", "{session_time} – this session, formatted"),
        ("{total_time}", "{total_time} – all playtime, formatted"),
        ("{rating_average}", "{rating_average} – VNDB average rating"),
        ("{rating_weighted}", "{rating_weighted} – VNDB weighted rating"),
        ("{vndb}", "{vndb} – VNDB id (used in the button URL)"),
    )

    def _build_variables(self):
        page, layout = self._page()
        self._variable_pills = {}
        self._variable_texts = {}
        for token, description in self.VARIABLES:
            translated = tr(description)
            parts = translated.split("\u2013", 1)
            explanation = parts[1].strip() if len(parts) > 1 else translated
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            pill = QLabel(token)
            pill.setCursor(Qt.PointingHandCursor)
            pill.setToolTip(tr("Click to copy"))
            pill.setObjectName("pill")
            badge = QLabel("\u2713")
            badge.setObjectName("tick")
            badge.setFixedWidth(14)
            badge.setStyleSheet("QLabel{color:#22c55e;font-weight:700;}"
                                "QLabel{background:transparent;}")
            badge.hide()
            pill._badge = badge
            pill.mousePressEvent = lambda _e, tk=token, pl=pill: self._copy_token(tk, pl)
            line.addWidget(pill)
            line.addWidget(badge)
            text = QLabel(explanation)
            text.setWordWrap(True)
            line.addWidget(text, 1)
            layout.addWidget(row)
            self._variable_pills[token] = pill
            self._variable_texts.setdefault("_", [])
            self._variable_texts["_"].append((text, description))
        layout.addStretch(1)
        return page

    def _copy_token(self, token, pill=None):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(token)
        if pill is not None:
            badge = getattr(pill, "_badge", None)
            if badge is not None:
                badge.show()
                QTimer.singleShot(900, badge.hide)

    def refresh_variables(self):
        for label, description in getattr(self, "_variable_texts", {}).get("_", []):
            translated = tr(description)
            parts = translated.split("\u2013", 1)
            label.setText(parts[1].strip() if len(parts) > 1 else translated)
        if not hasattr(self, "_variables_label"):
            return
        from PySide6.QtWidgets import QApplication
        theme = self.window.palette
        rows = []
        for token, description in self.VARIABLES:
            translated = tr(description)
            parts = translated.split("\u2013", 1)
            explanation = parts[1].strip() if len(parts) > 1 else translated
            rows.append(
                '<div style="margin-bottom:7px;">'
                '<a href="%s" style="font-family:Consolas,\'Courier New\',monospace;'
                ' background:%s; padding:2px 6px; border-radius:4px; color:%s;'
                ' text-decoration:none;">%s</a>&nbsp;&nbsp;'
                '<span style="color:%s;">%s</span></div>'
                % (token, theme["surface2"], theme["text"], token,
                   theme["subtext"], explanation))
        self._variables_label.setText("".join(rows))

    @staticmethod
    def _help(parent, text):
        label = QLabel(text)
        label.setObjectName("help")
        label.setWordWrap(True)
        parent.addWidget(label)
        return label

    def _page(self):
        """Content inside a scroll area - the Advanced tab does not fit otherwise."""
        from PySide6.QtWidgets import QScrollArea
        content = QWidget()
        content.setObjectName("pagebody")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll, layout

    # ------------------------------------------------------------ General
    def _build_general(self):
        page, layout = self._page()
        config = self.window.config

        layout.addWidget(QLabel("Discord Application ID"))
        row = QHBoxLayout()
        self.client_id = QLineEdit(config.get("client_id", ""))
        row.addWidget(self.client_id, 1)
        how = QPushButton(tr("How to get ID?"))
        how.clicked.connect(self._how_to_get_id)
        row.addWidget(how)
        layout.addLayout(row)
        self._help(layout, "Create an application at discord.com/developers/applications, "
                           "copy its Application ID and paste it above.")

        layout.addSpacing(10)
        self.close_tray = QCheckBox("Close button hides to the tray instead of quitting")
        self.close_tray.setChecked(bool(config.get("close_to_tray", True)))
        layout.addWidget(self.close_tray)

        self.start_windows = QCheckBox("Start with Windows (minimised to the tray)")
        self.start_windows.setChecked(store.startup_enabled())
        layout.addWidget(self.start_windows)

        self.debug_box = QCheckBox(tr("Debug mode \u2013 write presence_debug.log"))
        self.debug_box.setChecked(bool(config.get("debug_log", False)))
        layout.addWidget(self.debug_box)
        self._help(layout, "Debug mode records which window was in front, which "
                           "processes were matched and why a status was chosen. "
                           "Off by default; no data leaves your PC.")

        layout.addSpacing(14)
        layout.addWidget(QLabel(tr("Language")))
        self.language_box = QComboBox()
        self.language_box.setObjectName("language")
        for code, name in LANGUAGES:
            self.language_box.addItem(name, code)
        current = config.get("language") or "en"
        index = self.language_box.findData(current)
        self.language_box.setCurrentIndex(index if index >= 0 else 0)
        self.language_box.currentIndexChanged.connect(self._language_changed)
        language_row = QHBoxLayout()
        language_row.addWidget(self.language_box)
        reload_strings = QPushButton(tr("Reload translations"))
        reload_strings.clicked.connect(self._reload_translations)
        language_row.addWidget(reload_strings)
        language_row.addStretch(1)
        layout.addLayout(language_row)
        self._help(layout, "Takes effect the next time the app starts.")

        layout.addSpacing(14)
        layout.addWidget(QLabel(tr("Library title")))
        self.title_mode = QComboBox()
        self.title_mode.addItems(["Original title", "Romanised title"])
        self.title_mode.setCurrentIndex(
            1 if (config.get("library_title_mode") or "original") == "romanized" else 0)
        self.title_mode.currentIndexChanged.connect(self._title_mode_changed)
        layout.addWidget(self.title_mode)
        self._help(layout, "Which name the Library list shows for each game.")

        layout.addSpacing(14)
        layout.addWidget(QLabel("Data files"))
        summary = store.data_summary()
        self.data_label = QLabel("")
        self.data_label.setObjectName("help")
        layout.addWidget(self.data_label)
        self._refresh_data_label()
        self._help(layout, tr("games.json, config.json and stats.db live in "
                              "%APPDATA%\\HyggerPresence. Put your old files there "
                              "and press Reload."))
        data_row = QHBoxLayout()
        reload_button = QPushButton("Reload data")
        reload_button.clicked.connect(self._reload_data)
        import_button = QPushButton("Import 1.x data\u2026")
        import_button.clicked.connect(self._import_legacy)
        folder_button = QPushButton("Open data folder")
        folder_button.clicked.connect(self._open_folder)
        for button in (reload_button, import_button, folder_button):
            data_row.addWidget(button)
        data_row.addStretch(1)
        layout.addLayout(data_row)
        layout.addStretch(1)
        self.tabs.addTab(page, tr("General"))

    def _reload_translations(self):
        from . import i18n as strings
        strings.reload_locales()
        strings.apply_language(self.window.config.get("language") or "en")
        self._retranslate_tabs()
        QMessageBox.information(self, tr("Translations"), "Reloaded from hp2/locales.")

    def _language_changed(self, _index):
        code = self.language_box.currentData() or "en"
        self.window.config["language"] = code
        try:
            store.save_config(self.window.config)
        except Exception:
            pass
        # re-translate the live window: no restart needed
        i18n.apply_language(code, root=self.window)
        if hasattr(self, "refresh_variables"):
            self.refresh_variables()
        self._retranslate_tabs()

    def _title_mode_changed(self, index):
        mode = "romanized" if index == 1 else "original"
        self.window.config["library_title_mode"] = mode
        try:
            store.save_config(self.window.config)
        except Exception:
            pass
        self.window.library_page.refresh()

    def _retranslate_tabs(self):
        for tabs, captions in ((getattr(self, "tabs", None),
                                ("General", "Presence", "Launchers", "Updates",
                                 "Screenshots")),
                               (getattr(self, "presence_tabs", None),
                                ("Reading", "Paused", "Idle", "Advanced"))):
            if tabs is None:
                continue
            for index, caption in enumerate(captions):
                if index < tabs.count():
                    tabs.setTabText(index, tr(caption))
        try:
            self._refresh_data_label()
        except Exception:
            pass
        try:
            self.window.stats_page._refresh_range_button()
        except Exception:
            pass
        try:
            self._refresh_update_notes()
        except Exception:
            pass

    def _refresh_update_notes(self):
        key = getattr(self, "_update_notes_key", None)
        if not key:
            return
        kind, value = key
        if kind == "up_to_date":
            self.update_notes.setText(tr("You are up to date (%s).") % value)
        elif kind == "text":
            self.update_notes.setText(tr(value))
        elif kind == "available":
            self.update_notes.setText(tr("Update available"))

    def _refresh_data_label(self):
        summary = store.data_summary()
        template = tr("Currently loaded: %d game(s), %d session(s)")
        self.data_label.setText(template % (summary["games"], summary["sessions"]))

    def _how_to_get_id(self):
        QMessageBox.information(
            self, tr("How to get ID?"),
            tr("1. Open https://discord.com/developers/applications\n"
               "2. Click \u201cNew Application\u201d, give it a name and create it\n"
               "3. Open \u201cGeneral Information\u201d and copy the Application ID\n"
               "4. Paste it above and press Save"))

    # ------------------------------------------------------------ Presence
    def _build_presence(self):
        self.presence_tabs = QTabWidget()
        self.presence_tabs.setObjectName("sub")
        config = self.window.config
        self.fields = {}
        self.enabled = {}
        self.template_defaults = {}
        for status in ("Reading", "Paused", "Idle"):
            page, layout = self._page()
            template = config["templates"].get(status, DEFAULT_TEMPLATES[status])
            self.fields[status] = {}
            self.enabled[status] = {}
            for key, caption, help_text in (
                    ("name", "Title", "The bold first line. {title} works."),
                    ("details", "Line 1", "Second line, e.g. {developer} | {year}"),
                    ("state", "Line 2", "Third line, e.g. {status} \u2022 Total {total_time}")):
                head = QHBoxLayout()
                head.addWidget(QLabel(caption))
                head.addStretch(1)
                if key != "name":
                    box = QCheckBox("show")
                    box.setChecked(bool(template.get(key + "_enabled", True)))
                    box.toggled.connect(self._sync_enabled_fields)
                    head.addWidget(box)
                    self.enabled[status][key + "_enabled"] = box
                layout.addLayout(head)
                edit = QLineEdit(template.get(key, ""))
                layout.addWidget(edit)
                self.fields[status][key] = edit
                self._help(layout, help_text)
                try:
                    edit.textChanged.connect(self._sync_enabled_fields)
                except Exception:
                    pass
            reset = QPushButton("Reset \u201c%s\u201d to default" % status)
            reset.clicked.connect(lambda _c=False, s=status: self._reset_status(s))
            layout.addWidget(reset)
            layout.addStretch(1)
            self.presence_tabs.addTab(page, status)

        # ---- Advanced (images / button / timer / formats) ----
        page, layout = self._page()
        opts = config["presence"]
        layout.addWidget(QLabel("Large image"))
        large_row = QHBoxLayout()
        self.large_mode = QComboBox()
        self.large_mode.addItems(["VNDB cover", "Custom"])
        self.large_mode.setCurrentIndex(0 if opts.get("large_image_mode", "vndb") == "vndb" else 1)
        large_row.addWidget(self.large_mode)
        self.custom_large = QLineEdit(opts.get("custom_large_image", ""))
        large_row.addWidget(self.custom_large, 1)
        layout.addLayout(large_row)
        self._help(layout, "Discord asset key or an https:// image URL.")
        layout.addWidget(QLabel("Large image hover text"))
        self.large_text = QLineEdit(opts.get("large_text", "{title}"))
        layout.addWidget(self.large_text)
        self._help(layout, "Shown when the pointer rests on the big image.")

        layout.addSpacing(8)
        layout.addWidget(QLabel("Small image"))
        small_row = QHBoxLayout()
        self.small_mode = QComboBox()
        self.small_mode.addItems(["None", "Custom"])
        self.small_mode.setCurrentIndex(1 if opts.get("small_image_mode") == "custom" else 0)
        small_row.addWidget(self.small_mode)
        self.custom_small = QLineEdit(opts.get("custom_small_image", ""))
        small_row.addWidget(self.custom_small, 1)
        layout.addLayout(small_row)
        layout.addWidget(QLabel("Small image hover text"))
        self.small_text = QLineEdit(opts.get("small_text", ""))
        layout.addWidget(self.small_text)
        self._help(layout, "Both fields are disabled while the small image is None.")

        layout.addSpacing(8)
        self.show_timer = QCheckBox("Show the elapsed timer while Reading")
        self.show_timer.setChecked(bool(opts.get("show_timer", True)))
        layout.addWidget(self.show_timer)
        self.button_enabled = QCheckBox("Show a button under the presence")
        self.button_enabled.setChecked(bool(opts.get("button_enabled", True)))
        layout.addWidget(self.button_enabled)
        layout.addWidget(QLabel("Button label"))
        self.button_label = QLineEdit(opts.get("button_label", "View on VNDB"))
        layout.addWidget(self.button_label)
        layout.addWidget(QLabel("Button URL"))
        self.button_url = QLineEdit(opts.get("button_url", "https://vndb.org/{vndb}"))
        layout.addWidget(self.button_url)
        self._help(layout, "Discord allows one button. {vndb} is replaced with the VN id.")

        layout.addSpacing(8)
        layout.addWidget(QLabel("Time formats"))
        self.session_fmt = QLineEdit(opts.get("session_time_format") or store.TIMEFORMAT)
        self.total_fmt = QLineEdit(opts.get("total_time_format") or store.TIMEFORMAT)
        layout.addWidget(QLabel("Session time"))
        layout.addWidget(self.session_fmt)
        layout.addWidget(QLabel("Total time"))
        layout.addWidget(self.total_fmt)
        presets = QHBoxLayout()
        for label, fmt in (("1h 23m 04s", store.TIMEFORMAT),
                           ("01:23:04", "{hh}:{mm}:{ss}"),
                           ("1:23:04 / 12:03", "{h:}{mm}:{ss}"),
                           ("1h 23m 4s", "{h}h {m}m {s}s"),
                           ("01h23m04s", "{hh}h{mm}m{ss}s")):
            chip = QPushButton(label)
            chip.clicked.connect(lambda _c=False, f=fmt: self._apply_format(f))
            presets.addWidget(chip)
        presets.addStretch(1)
        layout.addLayout(presets)
        self._help(layout,
                   "Placeholders: {h} {m} {s} \u2013 no leading zero, {hh} {mm} {ss} \u2013 "
                   "padded, {h:} {mm}:{ss} \u2013 with colons.\n"
                   "Conditional blocks: {h?}\u2026{/h} only when hours > 0, "
                   "{!h}\u2026{/!h} only when hours == 0 (same for m / s).")

        layout.addSpacing(8)
        layout.addWidget(QLabel("Variables available in every line"))
        self._help(layout,
                   "{title}  {romanized_title}  {developer}  {year}  {status}  "
                   "{session_time}  {total_time}  {rating_average}  "
                   "{rating_weighted}  {vndb}")
        reset = QPushButton("Reset presence settings to default")
        reset.clicked.connect(self._reset_presence)
        layout.addWidget(reset)
        layout.addStretch(1)
        self.presence_tabs.addTab(page, "Advanced")
        self.presence_tabs.addTab(self._build_variables(),
                                 tr("Variables"))

        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(self.presence_tabs)
        self.tabs.addTab(wrapper, tr("Presence"))

        self.large_mode.currentIndexChanged.connect(self._sync_enabled_fields)
        self.small_mode.currentIndexChanged.connect(self._sync_enabled_fields)
        self.button_enabled.toggled.connect(self._sync_enabled_fields)

    def _apply_format(self, fmt):
        self.session_fmt.setText(fmt)
        self.total_fmt.setText(fmt)

    def _sync_enabled_fields(self, *_args):
        custom_large = self.large_mode.currentIndex() == 1
        self.custom_large.setEnabled(custom_large)
        custom_small = self.small_mode.currentIndex() == 1
        self.custom_small.setEnabled(custom_small)
        self.small_text.setEnabled(custom_small)
        enabled = self.button_enabled.isChecked()
        self.button_label.setEnabled(enabled)
        self.button_url.setEnabled(enabled)
        for status, boxes in self.enabled.items():
            edits = self.fields[status]
            if "details_enabled" in boxes:
                edits["details"].setEnabled(boxes["details_enabled"].isChecked())
            if "state_enabled" in boxes:
                edits["state"].setEnabled(boxes["state_enabled"].isChecked())

    def _reset_status(self, status):
        default = DEFAULT_TEMPLATES[status]
        for key in ("name", "details", "state"):
            self.fields[status][key].setText(default.get(key, ""))
        for key in ("details_enabled", "state_enabled"):
            if key in self.enabled[status]:
                self.enabled[status][key].setChecked(bool(default.get(key, True)))
        self._sync_enabled_fields()

    def _reset_presence(self):
        opts = store.DEFAULT_PRESENCE
        self.large_mode.setCurrentIndex(0 if opts["large_image_mode"] == "vndb" else 1)
        self.custom_large.setText(opts["custom_large_image"])
        self.large_text.setText(opts["large_text"])
        self.small_mode.setCurrentIndex(1 if opts["small_image_mode"] == "custom" else 0)
        self.custom_small.setText(opts["custom_small_image"])
        self.small_text.setText(opts["small_text"])
        self.show_timer.setChecked(opts["show_timer"])
        self.button_enabled.setChecked(opts["button_enabled"])
        self.button_label.setText(opts["button_label"])
        self.button_url.setText(opts["button_url"])
        self._apply_format(store.TIMEFORMAT)
        self._sync_enabled_fields()

    # ------------------------------------------------------------ Launchers
    def _build_launchers(self):
        page = QWidget()
        launch_layout = QVBoxLayout(page)
        launch_layout.setContentsMargins(14, 14, 14, 14)
        self.launcher_list = QTableWidget(0, 1)
        self.launcher_list.setHorizontalHeaderLabels(["Launcher"])
        self.launcher_list.verticalHeader().setVisible(False)
        self.launcher_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.launcher_list.setSelectionMode(QTableWidget.SingleSelection)
        self.launcher_list.setEditTriggers(QTableWidget.NoEditTriggers)
        stored = (self.window.config.get("ui") or {}).get("launcher_columns")
        for index, width in enumerate(stored or (420,)):
            self.launcher_list.setColumnWidth(index, int(width))
        self.launcher_list.horizontalHeader().setStretchLastSection(True)
        self.launcher_list.horizontalHeader().sectionResized.connect(
            self._remember_launcher_columns)
        self.launcher_list.doubleClicked.connect(lambda _i: self._edit_launcher())
        launch_layout.addWidget(self.launcher_list, 1)
        self._help(launch_layout,
                   "Launchers appear in the Start \u25be menu. Locale Emulator profiles are "
                   "read from LEConfig.xml next to LEProc.exe; GalFC can be added once.")
        row_box = QHBoxLayout()
        add_menu = QPushButton("Add\u2026")
        from PySide6.QtWidgets import QMenu
        menu = QMenu(add_menu)
        menu.addAction(tr("Locale Emulator profiles\u2026"), self._add_le)
        menu.addAction(tr("GalFC\u2026"), self._add_galfc)
        menu.addAction(tr("Custom command\u2026"), self._add_custom)
        add_menu.setMenu(menu)
        edit = QPushButton("Edit\u2026")
        edit.clicked.connect(self._edit_launcher)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_launcher)
        row_box.addWidget(add_menu)
        row_box.addWidget(edit)
        row_box.addWidget(remove)
        row_box.addStretch(1)
        launch_layout.addLayout(row_box)
        self.tabs.addTab(page, tr("Launchers"))

    # ------------------------------------------------------------ Updates
    def _build_updates(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(QLabel("%s %s" % (tr("Current version:"), APP_VERSION)))
        self.auto_check = QCheckBox("Check for updates when the app starts")
        self.auto_check.setChecked(bool(self.window.config.get("auto_check", True)))
        layout.addWidget(self.auto_check)
        self.skip_label = QLabel("")
        self.skip_label.setObjectName("help")
        layout.addWidget(self.skip_label)
        row = QHBoxLayout()
        self.check_button = QPushButton(tr("Check now"))
        self.check_button.clicked.connect(lambda: self.check_updates())
        self.update_button = QPushButton("Update now")
        self.update_button.setToolTip(tr("Becomes available when a newer release exists"))
        self.update_button.setEnabled(False)
        self.update_button.clicked.connect(self.install_update)
        self.clear_skip_button = QPushButton("Clear skipped version")
        self.clear_skip_button.setToolTip(
            "You chose \u201cskip this version\u201d for a release. This forgets that, so "
            "you get told about it again.")
        self.clear_skip_button.clicked.connect(self.clear_skip)
        for button in (self.check_button, self.update_button, self.clear_skip_button):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.update_notes = QLabel("")
        self.update_notes.setObjectName("help")
        self.update_notes.setWordWrap(True)
        layout.addWidget(self.update_notes)
        self._help(layout, "Updating replaces this .exe in place; games.json, "
                           "config.json and stats.db are kept.")
        layout.addStretch(1)
        self.tabs.addTab(page, tr("Updates"))
        self.tabs.addTab(self._build_screenshot(), tr("Screenshots"))
        self._refresh_skip_label()

    # ------------------------------------------------------------ data actions
    def _reload_data(self):
        window = self.window
        window.config = store.load_config()
        window.engine.games = store.load_games()
        window.engine.client_id = window.config.get("client_id", "")
        window.engine.templates = window.config.get("templates") or DEFAULT_TEMPLATES
        window.engine.opts = window.config.get("presence") or {}
        window.engine.rpc = None
        self.client_id.setText(window.config.get("client_id", ""))
        try:
            if window.app.stats:
                window.app.stats.close()
            window.app.stats = StatsStore(store.STATS_FILE)
            window.engine.stats = window.app.stats
            window.stats_page.refresh()
        except Exception:
            pass
        window.library_page.refresh()
        window.library_page.refresh_menu()
        self._reload_launchers()
        window.now_page.update_from_engine()
        self._refresh_data_label()
        summary = store.data_summary()
        QMessageBox.information(
            self, tr("Reload"),
            tr("Loaded %d game(s) and %d session(s).") % (summary["games"],
                                                      summary["sessions"]))

    def _import_legacy(self):
        from . import store as store_module
        imported = store_module.import_legacy()
        if imported:
            self._reload_data()
            return
        summary = store.data_summary()
        answer = QMessageBox.question(
            self, tr("Import 1.x data"),
            tr("Nothing was copied from the folder above.\n\n"
               "This folder already has %d game(s) and %d session(s), so it is probably "
               "already imported - press \u201cReload data\u201d if you just replaced the files.\n\n"
               "Pick the files manually instead?") % (summary["games"], summary["sessions"]))
        if answer == QMessageBox.Yes:
            self._choose_import_files()

    def _choose_import_files(self):
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select 1.x data files", str(store.APP_DIR),
            "Hygger data (games.json config.json stats.db);;All files (*.*)")
        if not paths:
            return
        imported, skipped = [], []
        for path in paths:
            done = store.import_file(path)
            (imported if done else skipped).append(done or Path(path).name)
        if imported:
            self._reload_data()
        else:
            QMessageBox.warning(self, "Import",
                                "Nothing imported (those files already hold data).\n"
                                + "\n".join(skipped))

    def _open_folder(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(store.APP_DIR)))

    # ------------------------------------------------------------ updates
    def _refresh_skip_label(self):
        skipped = self.window.config.get("skip_version") or ""
        self.skip_label.setText(tr("Skipped version: %s") % (skipped or "none"))
        self.clear_skip_button.setEnabled(bool(skipped))

    def clear_skip(self):
        self.window.config["skip_version"] = ""
        store.save_config(self.window.config)
        self._refresh_skip_label()

    def check_updates(self, silent=False):
        self.check_button.setEnabled(False)
        self.check_button.setText(tr("Checking\u2026"))
        self.window.check_updates(silent=silent, from_settings=True)

    def on_update_found(self, info):
        self.check_button.setEnabled(True)
        self.check_button.setText(tr("Check now"))
        if not info:
            self._update_notes_key = ("text", "Could not check for updates.")
            self.update_notes.setText(tr("Could not check for updates."))
            return
        if not info.get("version"):
            self._update_notes_key = ("text", "No releases found yet.")
            self.update_notes.setText(tr("No releases found yet."))
            return
        if updater.is_newer(info["version"], APP_VERSION):
            self.update_button.setEnabled(True)
            self._update_notes_key = ("available", None)
            self.update_notes.setText("Version %s is available.\n%s"
                                      % (info["version"],
                                         (info.get("notes") or "")[:400]))
        else:
            self.update_button.setEnabled(False)
            self._update_notes_key = ("up_to_date", APP_VERSION)
            self.update_notes.setText((tr("You are up to date (%s).") % APP_VERSION))

    def install_update(self):
        info = getattr(self.window, "update_info", None)
        if not info:
            return
        asset = updater.pick_exe(info)
        if not asset:
            QMessageBox.warning(self, "Update", "This release has no .exe asset.")
            return
        ok, message = updater.apply_update(asset)
        QMessageBox.information(self, "Update", message)
        if ok:
            self.window._quit()

    # ------------------------------------------------------------ launchers
    def _reload_launchers(self):
        launchers = self.window.config.get("launchers") or []
        self.launcher_list.setRowCount(len(launchers))
        for row, launcher in enumerate(launchers):
            name_item = QTableWidgetItem(launcher.get("name", ""))
            detail = (launcher.get("le_path") or launcher.get("galfc_path")
                      or launcher.get("command") or "")
            name_item.setToolTip("%s\n%s\n%s" % (launcher.get("name", ""),
                                                  (launcher.get("type") or "").upper(),
                                                  detail))
            self.launcher_list.setItem(row, 0, name_item)

    def _commit_launchers(self):
        self._reload_launchers()
        self.window.library_page.refresh_menu()

    def _selected_launcher(self):
        rows = self.launcher_list.selectionModel().selectedRows()
        if not rows:
            return None, None
        index = rows[0].row()
        launchers = self.window.config.get("launchers") or []
        if 0 <= index < len(launchers):
            return index, launchers[index]
        return None, None

    def _add_le(self):
        dialog = LeProfilesDialog(self, self.window.config.get("launchers") or [])
        if not dialog.exec():
            return
        added = 0
        for name, guid, le_path in dialog.selection():
            if any(l.get("guid") == guid
                   for l in self.window.config.get("launchers") or []):
                continue
            self.window.config.setdefault("launchers", []).append(
                {"name": "LE \u2013 %s" % name, "type": "le", "le_path": le_path,
                 "guid": guid})
            added += 1
        if added:
            self._commit_launchers()
        else:
            QMessageBox.information(self, "Launchers",
                                    tr("Those profiles are already added."))

    def _add_galfc(self):
        if any(l.get("type") == "galfc" for l in self.window.config.get("launchers") or []):
            QMessageBox.information(
                self, "Launchers",
                "GalFC can only be added once. Select the existing one and use Edit\u2026")
            return
        dialog = LauncherDialog(self, None, "galfc")
        if dialog.exec():
            self.window.config.setdefault("launchers", []).append(dialog.launcher)
            self._commit_launchers()

    def _add_custom(self):
        dialog = LauncherDialog(self, None, "custom")
        if dialog.exec():
            self.window.config.setdefault("launchers", []).append(dialog.launcher)
            self._commit_launchers()

    def _edit_launcher(self):
        index, launcher = self._selected_launcher()
        if launcher is None:
            QMessageBox.information(self, "Launchers", "Select a launcher first.")
            return
        dialog = LauncherDialog(self, launcher, launcher.get("type", "custom"))
        if dialog.exec():
            self._commit_launchers()

    def _remove_launcher(self):
        index, launcher = self._selected_launcher()
        if launcher is None:
            QMessageBox.information(self, "Launchers", "Select a launcher first.")
            return
        if QMessageBox.question(
                self, tr("Remove launcher"),
                'Remove \u201c%s\u201d from the Start menu?' % launcher.get("name", "")) \
                != QMessageBox.Yes:
            return
        self.window.config["launchers"].pop(index)
        self._commit_launchers()

    def _remember_launcher_columns(self, *_args):
        ui = self.window.config.setdefault("ui", {})
        ui["launcher_columns"] = [self.launcher_list.columnWidth(i) for i in range(1)]

    def save_state(self):
        self._remember_launcher_columns()

    # ------------------------------------------------------------ save
    def save(self):
        window = self.window
        config = window.config
        config["client_id"] = self.client_id.text().strip()
        config["debug_log"] = bool(self.debug_box.isChecked())
        config["close_to_tray"] = bool(self.close_tray.isChecked())
        config["auto_check"] = bool(self.auto_check.isChecked())
        config["templates"] = {
            status: dict(
                {key: edit.text() for key, edit in self.fields[status].items()},
                **{key: bool(box.isChecked())
                   for key, box in self.enabled[status].items()})
            for status in self.fields}
        config["presence"] = {
            "large_image_mode": "vndb" if self.large_mode.currentIndex() == 0 else "custom",
            "custom_large_image": self.custom_large.text().strip(),
            "large_text": self.large_text.text(),
            "small_image_mode": "custom" if self.small_mode.currentIndex() == 1 else "none",
            "custom_small_image": self.custom_small.text().strip(),
            "small_text": self.small_text.text(),
            "show_timer": bool(self.show_timer.isChecked()),
            "button_enabled": bool(self.button_enabled.isChecked()),
            "button_label": self.button_label.text().strip() or "View on VNDB",
            "button_url": self.button_url.text().strip() or "https://vndb.org/{vndb}",
            "session_time_format": self.session_fmt.text().strip() or store.TIMEFORMAT,
            "total_time_format": self.total_fmt.text().strip() or store.TIMEFORMAT,
        }
        store.save_config(config)
        engine = window.engine
        engine.client_id = config["client_id"]
        engine.templates = config["templates"]
        engine.opts = config["presence"]
        # do NOT touch the live Discord connection here: an in-flight call that is
        # abandoned leaves an orphan socket behind and every later call times out.
        # The supervisor pushes the new templates on its next keepalive.
        engine.wake_for_new_settings()
        from .core import set_debug_enabled
        set_debug_enabled(bool(config["debug_log"]))
        if bool(self.start_windows.isChecked()) != store.startup_enabled():
            store.set_startup(bool(self.start_windows.isChecked()))
        self._refresh_data_label()
        QMessageBox.information(self, tr("Settings"), tr("Saved."))


class GameEditorDialog(QDialog):
    """One editor for everything, in five tabs (replaces the five side buttons)."""

    def __init__(self, window, game):
        super().__init__(window)
        self.window = window
        self.game = game
        self.setWindowTitle("Edit game")
        self.setMinimumWidth(560)

        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)

        # 1) title
        title_page = QWidget()
        form = QGridLayout(title_page)
        form.addWidget(QLabel("Title (original)"), 0, 0)
        self.title_edit = QLineEdit(game.get("original") or game.get("title") or "")
        form.addWidget(self.title_edit, 0, 1)
        form.addWidget(QLabel("Romanised title"), 1, 0)
        self.romanised_edit = QLineEdit(game.get("romanized") or "")
        form.addWidget(self.romanised_edit, 1, 1)
        form.setRowStretch(2, 1)
        tabs.addTab(title_page, "Title")

        # 2) executable
        exe_page = QWidget()
        exe_form = QGridLayout(exe_page)
        exe_form.addWidget(QLabel("Executable"), 0, 0)
        self.exe_edit = QLineEdit(game.get("exe") or "")
        exe_form.addWidget(self.exe_edit, 0, 1)
        browse = QPushButton("Browse\u2026")
        browse.clicked.connect(self._browse_exe)
        exe_form.addWidget(browse, 0, 2)
        exe_form.setRowStretch(1, 1)
        tabs.addTab(exe_page, "Executable")

        # 3) VNDB
        vndb_page = QWidget()
        vndb_form = QGridLayout(vndb_page)
        vndb_form.addWidget(QLabel("VNDB id / link"), 0, 0)
        self.vndb_edit = QLineEdit(game.get("vndb_id") or "")
        vndb_form.addWidget(self.vndb_edit, 0, 1)
        fetch = QPushButton("Fetch metadata")
        fetch.clicked.connect(self._fetch_vndb)
        vndb_form.addWidget(fetch, 0, 2)
        self.vndb_info = QLabel(self._describe(game))
        self.vndb_info.setObjectName("sub")
        self.vndb_info.setWordWrap(True)
        vndb_form.addWidget(self.vndb_info, 1, 0, 1, 3)
        cover_row = QHBoxLayout()
        cover_button = QPushButton("Change cover\u2026")
        cover_button.setToolTip(tr("Pick one of the VN's VNDB covers"))
        cover_button.clicked.connect(self._pick_cover)
        cover_row.addWidget(cover_button)
        cover_row.addStretch(1)
        vndb_form.addLayout(cover_row, 2, 0, 1, 3)
        vndb_form.setRowStretch(3, 1)
        tabs.addTab(vndb_page, "VNDB")

        # 4) total time
        time_page = QWidget()
        time_form = QVBoxLayout(time_page)
        from .core import format_time
        time_form.addWidget(QLabel("Total time (e.g. 3h15m, 195m, 3:15:00)"))
        self.time_edit = QLineEdit(format_time(game.get("total_seconds", 0)))
        time_form.addWidget(self.time_edit)
        time_form.addWidget(QLabel(tr("Current: %s")
                                   % format_time(game.get("total_seconds", 0))))
        time_form.addStretch(1)
        tabs.addTab(time_page, "Total time")

        # 5) process names
        proc_page = QWidget()
        proc_form = QVBoxLayout(proc_page)
        proc_form.addWidget(QLabel(
            "Extra process names (comma separated).\n"
            "Only needed when the game runs under a different .exe than the one above;\n"
            "executables in the game folder are detected automatically."))
        self.proc_edit = QLineEdit(", ".join(game.get("process_names") or []))
        proc_form.addWidget(self.proc_edit)
        proc_form.addStretch(1)
        tabs.addTab(proc_page, "Process names")

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        outer.addLayout(buttons)

    @staticmethod
    def _describe(game):
        return ("%s | %s\nAverage %s   Weighted %s"
                % (game.get("developer") or "Unknown", game.get("year") or "????",
                   game.get("rating_average") or "N/A",
                   game.get("rating_weighted") or "N/A"))

    def _browse_exe(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select executable", "",
                                              "Executable (*.exe)")
        if path:
            self.exe_edit.setText(str(Path(path).resolve()))

    def _pick_cover(self):
        vndb_id = (self.vndb_edit.text() or "").strip()
        import re
        match = re.search(r"(v\d+)", vndb_id, re.I)
        if not match:
            QMessageBox.warning(self, "Cover", "Set the VNDB id first.")
            return
        dialog = CoverPickerDialog(self.window, match.group(1).lower())
        if dialog.exec() and dialog.selected:
            self.game["image"] = dialog.selected
            store.save_games(self.window.engine.games)
            self.window.now_page.update_from_engine()

    def _fetch_vndb(self):
        import re
        match = re.search(r"(v\d+)", self.vndb_edit.text() or "", re.I)
        if not match:
            QMessageBox.warning(self, "VNDB", "Could not find a VNDB id.")
            return
        info = self.window.app.fetch_vndb(match.group(1).lower())
        if not info:
            QMessageBox.warning(self, "VNDB", "Lookup failed (network?).")
            return
        self.vndb_edit.setText(info["id"])
        self.game.update({
            "title": info.get("title") or "", "original": info.get("original") or "",
            "romanized": info.get("romanized") or "", "image": info.get("image") or "",
            "developer": info.get("developer") or "Unknown",
            "year": info.get("year") or "????",
            "rating_average": info.get("rating_average") or "N/A",
            "rating_weighted": info.get("rating_weighted") or "N/A",
        })
        if not self.title_edit.text().strip():
            self.title_edit.setText(self.game.get("original") or "")
        self.romanised_edit.setText(self.game.get("romanized") or "")
        self.vndb_info.setText(self._describe(self.game))

    def _save(self):
        from .core import parse_time_input
        self.game["original"] = self.title_edit.text().strip()
        self.game["title"] = self.game["original"]
        self.game["romanized"] = self.romanised_edit.text().strip()
        self.game["exe"] = self.exe_edit.text().strip()
        self.game["vndb_id"] = (self.vndb_edit.text() or "").strip()
        self.game["process_names"] = [name.strip() for name in
                                      (self.proc_edit.text() or "").split(",")
                                      if name.strip()]
        self.game["total_seconds"] = parse_time_input(self.time_edit.text())
        self.accept()


class SessionsDialog(QDialog):
    """The session log: delete a test launch, selected rows, or a whole range."""

    def __init__(self, page, day_from, day_to, only_title=None):
        super().__init__(page)
        self.page = page
        self.app = page.app
        self.day_from = day_from
        self.day_to = day_to
        self.only_title = only_title
        self.setWindowTitle("Sessions \u2013 %s" % only_title if only_title else "All sessions")
        self.resize(640, 460)
        outer = QVBoxLayout(self)
        head = QLabel(("Sessions of %s between %s and %s" % (only_title, day_from, day_to))
                      if only_title else
                      "Every reading session between %s and %s" % (day_from, day_to))
        head.setObjectName("sub")
        outer.addWidget(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Visual novel", "Length", "Started"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 300)
        outer.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.delete_selected = QPushButton("Delete selected")
        self.delete_selected.setObjectName("primary")
        self.delete_selected.clicked.connect(self._delete_selected)
        self.delete_range = QPushButton("Delete whole range")
        self.delete_range.clicked.connect(self._delete_range)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.delete_selected)
        buttons.addWidget(self.delete_range)
        buttons.addStretch(1)
        buttons.addWidget(close)
        outer.addLayout(buttons)
        self._reload()

    def _reload(self):
        from .core import format_time
        stats = getattr(self.app, "stats", None)
        rows = stats.sessions(self.day_from, self.day_to) if stats else []
        if self.only_title:
            # the stored title can differ slightly from the one shown on the card
            wanted = self.only_title.strip()
            rows = [row for row in rows
                    if wanted and (wanted in (row[2] or "")
                                   or (row[2] or "") in wanted)]
        self.table.setRowCount(len(rows))
        for index, (row_id, day, title, seconds, start_ts) in enumerate(rows):
            started = time.strftime("%H:%M", time.localtime(start_ts)) if start_ts else ""
            items = [QTableWidgetItem(str(day)), QTableWidgetItem(title or ""),
                     QTableWidgetItem(format_time(seconds)), QTableWidgetItem(started)]
            for column, item in enumerate(items):
                self.table.setItem(index, column, item)
            self.table.item(index, 0).setData(Qt.UserRole, row_id)

    def delete(self, ids):
        stats = getattr(self.app, "stats", None)
        if stats and ids:
            stats.delete_sessions(ids)
        self._reload()
        self.page.refresh()

    def _delete_selected(self):
        ids = []
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item is not None and item.data(Qt.UserRole) is not None:
                ids.append(item.data(Qt.UserRole))
        if not ids:
            QMessageBox.information(self, "Sessions", tr("Select at least one row first."))
            return
        if QMessageBox.question(self, tr("Delete sessions"),
                                tr("Delete %d session(s)? This cannot be undone.") % len(ids)) \
                != QMessageBox.Yes:
            return
        self.delete(ids)

    def _delete_range(self):
        who = ("\u201c%s\u201d" % self.only_title) if self.only_title else "every visual novel"
        if QMessageBox.question(
                self, tr("Delete range"),
                tr("Delete every session of %s between %s and %s?")
                % (who, self.day_from, self.day_to)) != QMessageBox.Yes:
            return
        stats = getattr(self.app, "stats", None)
        if stats:
            if self.only_title:
                stats.delete_range_for(self.day_from, self.day_to, self.only_title)
            else:
                stats.delete_range(self.day_from, self.day_to)
        self._reload()
        self.page.refresh()




class AddGameDialog(QDialog):
    """One panel for a new entry: exe + VNDB (required) + old playtime + process names."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.game = None
        self.setWindowTitle("Add game")
        self.setMinimumWidth(560)
        outer = QVBoxLayout(self)
        form = QGridLayout()
        form.setHorizontalSpacing(10)

        def help_label(text, row):
            label = QLabel(text)
            label.setObjectName("help")
            label.setWordWrap(True)
            form.addWidget(label, row, 1, 1, 2)

        form.addWidget(QLabel("Executable"))
        self.exe_edit = QLineEdit()
        form.addWidget(self.exe_edit, 0, 1)
        browse = QPushButton("Browse\u2026")
        browse.clicked.connect(self._browse)
        form.addWidget(browse, 0, 2)
        help_label("The game's .exe (the one you would double-click).", 1)

        form.addWidget(QLabel("VNDB id / link"), 2, 0)
        self.vndb_edit = QLineEdit()
        form.addWidget(self.vndb_edit, 2, 1, 1, 2)
        help_label("Required. A link like https://vndb.org/v64038 or just v64038.  "
                   "Use the \u201cHow to get ID?\u201d button in Settings if you are unsure.",
                   3)

        form.addWidget(QLabel("Previous play time"), 4, 0)
        self.time_edit = QLineEdit()
        form.addWidget(self.time_edit, 4, 1, 1, 2)
        help_label("Optional. Time you read this VN before \u2013 e.g. 3h15m, 195m, 3:15:00.",
                   5)

        form.addWidget(QLabel("Extra process names"), 6, 0)
        self.proc_edit = QLineEdit()
        form.addWidget(self.proc_edit, 6, 1, 1, 2)
        help_label("Optional, comma separated. Only needed when the game starts another "
                   ".exe than the one above; executables inside the game folder are found "
                   "automatically.", 7)

        form.setRowStretch(8, 1)
        outer.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        add = QPushButton("Add")
        add.setObjectName("primary")
        add.clicked.connect(self._add)
        buttons.addWidget(cancel)
        buttons.addWidget(add)
        outer.addLayout(buttons)

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select game executable", "",
                                              "Executable (*.exe)")
        if path:
            self.exe_edit.setText(str(Path(path).resolve()))

    def _add(self):
        import re
        from .core import parse_time_input
        exe = self.exe_edit.text().strip()
        if not exe or not Path(exe).exists():
            QMessageBox.warning(self, "Add game", tr("Pick an existing .exe first."))
            return
        match = re.search(r"(v\d+)", self.vndb_edit.text() or "", re.I)
        if not match:
            QMessageBox.warning(self, "Add game",
                                tr("A VNDB id is required (e.g. v64038)."))
            return
        vndb_id = match.group(1).lower()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            info = self.window.app.fetch_vndb(vndb_id)
        finally:
            QApplication.restoreOverrideCursor()
        if not info:
            QMessageBox.warning(self, "Add game",
                                tr("Could not fetch that VN from VNDB (network?)."))
            return
        self.game = {
            "exe": exe, "vndb_id": vndb_id,
            "title": info.get("title") or Path(exe).stem,
            "original": info.get("original") or info.get("title") or Path(exe).stem,
            "romanized": info.get("romanized") or "",
            "image": info.get("image") or "",
            "developer": info.get("developer") or "Unknown",
            "year": info.get("year") or "????",
            "rating_average": info.get("rating_average") or "N/A",
            "rating_weighted": info.get("rating_weighted") or "N/A",
            "process_names": [name.strip() for name in
                              (self.proc_edit.text() or "").split(",") if name.strip()],
            "total_seconds": parse_time_input(self.time_edit.text()),
        }
        self.accept()


class LauncherDialog(QDialog):
    """Everything about one launcher in a single window, per type.

    Locale Emulator: name, LEProc.exe, profile, generated command (read only).
    GalFC:           name, GalFC.exe, generated command (read only).
    Custom:          name, command (editable).
    """

    def __init__(self, page, launcher=None, kind="custom"):
        super().__init__(page)
        self.page = page
        self.launcher = launcher if launcher is not None else {}
        is_edit = launcher is not None
        self.setWindowTitle("Edit launcher" if is_edit else tr("Add launcher"))
        self.setMinimumWidth(560)
        outer = QVBoxLayout(self)
        self.form = QGridLayout()
        self.form.setHorizontalSpacing(10)
        self._rows = {}

        def add_row(key, caption, widget, button=None):
            row = self.form.rowCount()
            label = QLabel(caption)
            self.form.addWidget(label, row, 0)
            self.form.addWidget(widget, row, 1)
            if button is not None:
                self.form.addWidget(button, row, 2)
            self._rows[key] = (label, widget, button)
            return row

        self.name_edit = QLineEdit(self.launcher.get("name", ""))
        add_row("name", tr("Name"), self.name_edit)

        self.type_box = QComboBox()
        self.type_box.addItems(["Locale Emulator", "GalFC", "Custom command"])
        order = {"le": 0, "galfc": 1, "custom": 2}
        self.type_box.setCurrentIndex(order.get(kind, 2))
        add_row("type", "Type", self.type_box)

        self.le_edit = QLineEdit(self.launcher.get("le_path", ""))
        le_browse = QPushButton("Browse\u2026")
        le_browse.clicked.connect(self._browse_le)
        add_row("le_path", tr("LEProc.exe"), self.le_edit, le_browse)

        self.profile_box = QComboBox()
        add_row("profile", tr("LE profile"), self.profile_box)

        self.galfc_edit = QLineEdit(self.launcher.get("galfc_path", ""))
        galfc_browse = QPushButton("Browse\u2026")
        galfc_browse.clicked.connect(self._browse_galfc)
        add_row("galfc", "GalFC.exe", self.galfc_edit, galfc_browse)

        self.command_edit = QLineEdit(self.launcher.get("command", ""))
        add_row("command", tr("Command"), self.command_edit)

        outer.addLayout(self.form)
        self.command_help = QLabel("")
        self.command_help.setObjectName("help")
        self.command_help.setWordWrap(True)
        outer.addWidget(self.command_help)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        outer.addLayout(buttons)

        self.type_box.currentIndexChanged.connect(self._sync)
        self.profile_box.currentIndexChanged.connect(self._sync_command)
        self.le_edit.textChanged.connect(self._sync_command)
        self.galfc_edit.textChanged.connect(self._sync_command)
        self._load_profiles()
        self._sync()

    def _kind(self):
        return {0: "le", 1: "galfc", 2: "custom"}[self.type_box.currentIndex()]

    def _show(self, key, visible):
        label, widget, button = self._rows[key]
        for item in (label, widget, button):
            if item is not None:
                item.setVisible(visible)

    def _sync(self):
        kind = self._kind()
        self._show("type", False)          # the type is fixed by the menu entry
        self._show("le_path", kind == "le")
        self._show("profile", kind == "le")
        self._show("galfc", kind == "galfc")
        self._rows["command"][0].setText(tr("Command"))
        self.command_edit.setReadOnly(kind != "custom")
        if kind == "le" and not self.name_edit.text().strip():
            self.name_edit.setText("LE \u2013 %s" % (self.profile_box.currentText() or "profile"))
        self._sync_command()
        self.adjustSize()

    def _sync_command(self, *_args):
        kind = self._kind()
        if kind == "le":
            profile = self.profile_box.currentText()
            self.command_edit.setText('"%s" -runas %s "%%1"'
                                      % (self.le_edit.text().strip(),
                                         self.profile_box.currentData() or ""))
            self.command_help.setText("Generated from LEProc.exe and the profile (%s) \u2013 "
                                      "read only. %%1 is the game." % (profile or "none"))
        elif kind == "galfc":
            self.command_edit.setText('"%s" "%%1"' % self.galfc_edit.text().strip())
            self.command_help.setText("Generated from GalFC.exe \u2013 read only. "
                                      "%%1 is the game.")
        else:
            self.command_help.setText("Use %1 for the game path, e.g. "
                                      '\u201c"C:\\tool.exe\u201d "%1"\u201d.')

    def _profiles(self):
        path = self.le_edit.text().strip()
        if not path:
            return []
        config_path = Path(path).parent / "LEConfig.xml"
        if not config_path.exists():
            return []
        try:
            import xml.etree.ElementTree as ET
            root = ET.parse(config_path).getroot()
            return [(profile.get("Name") or "Unnamed", profile.get("Guid") or "")
                    for profile in root.findall(".//Profile") if profile.get("Guid")]
        except Exception:
            return []

    def _load_profiles(self):
        current = self.profile_box.currentData() or self.launcher.get("guid")
        self.profile_box.clear()
        for name, guid in self._profiles():
            self.profile_box.addItem(name, guid)
        if current:
            index = self.profile_box.findData(current)
            if index >= 0:
                self.profile_box.setCurrentIndex(index)

    def _browse_le(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select LEProc.exe", "",
                                              "LEProc.exe (LEProc.exe);;Executable (*.exe)")
        if path:
            self.le_edit.setText(path)
            self._load_profiles()

    def _browse_galfc(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select GalFC.exe", "",
                                              "GalFC.exe (GalFC.exe);;Executable (*.exe)")
        if path:
            self.galfc_edit.setText(path)
            self.adjustSize()

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, tr("Launcher"), tr("A name is required."))
            return
        kind = self._kind()
        launcher = {"name": name, "type": kind}
        if kind == "le":
            path = self.le_edit.text().strip()
            if not path:
                QMessageBox.warning(self, tr("Launcher"), tr("Select LEProc.exe."))
                return
            if not self.profile_box.currentData():
                QMessageBox.warning(self, tr("Launcher"), tr("Select an LE profile."))
                return
            launcher["le_path"] = path
            launcher["guid"] = self.profile_box.currentData()
        elif kind == "galfc":
            path = self.galfc_edit.text().strip()
            if not path:
                QMessageBox.warning(self, tr("Launcher"), tr("Select GalFC.exe."))
                return
            launcher["galfc_path"] = path
        else:
            command = self.command_edit.text().strip()
            if not command:
                QMessageBox.warning(self, tr("Launcher"), tr("Enter a command."))
                return
            launcher["command"] = command
        self.launcher.clear()
        self.launcher.update(launcher)
        self.accept()


class LeProfilesDialog(QDialog):
    """Pick any number of Locale Emulator profiles (checkboxes + select all)."""

    def __init__(self, page, existing):
        super().__init__(page)
        self.existing = existing
        self.setWindowTitle("Locale Emulator profiles")
        self.setMinimumWidth(460)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(tr("LEProc.exe")))
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse\u2026")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        outer.addLayout(row)

        outer.addWidget(QLabel("Profiles to add"))
        self.list = QListWidget()
        outer.addWidget(self.list, 1)

        select_row = QHBoxLayout()
        all_button = QPushButton("Select all")
        all_button.clicked.connect(lambda: self._check(True))
        none_button = QPushButton("Deselect all")
        none_button.clicked.connect(lambda: self._check(False))
        select_row.addWidget(all_button)
        select_row.addWidget(none_button)
        select_row.addStretch(1)
        outer.addLayout(select_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        add = QPushButton("Add selected")
        add.setObjectName("primary")
        add.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(add)
        outer.addLayout(buttons)

        # reuse the path remembered by an existing LE launcher
        for launcher in existing:
            if launcher.get("type") == "le" and launcher.get("le_path"):
                self.path_edit.setText(launcher["le_path"])
                break
        self._load()

    def _browse(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Select LEProc.exe", "",
                                              "LEProc.exe (LEProc.exe);;Executable (*.exe)")
        if path:
            self.path_edit.setText(path)
            self._load()

    def _profiles(self):
        path = self.path_edit.text().strip()
        if not path:
            return []
        config_path = Path(path).parent / "LEConfig.xml"
        if not config_path.exists():
            return []
        try:
            import xml.etree.ElementTree as ET
            root = ET.parse(config_path).getroot()
            return [(profile.get("Name") or "Unnamed", profile.get("Guid") or "")
                    for profile in root.findall(".//Profile") if profile.get("Guid")]
        except Exception:
            return []

    def _load(self):
        self.list.clear()
        taken = {l.get("guid") for l in self.existing if l.get("type") == "le"}
        for name, guid in self._profiles():
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, guid)
            if guid in taken:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setText(tr("%s (already added)") % name)
            self.list.addItem(item)
        if not self.list.count():
            item = QListWidgetItem("Select LEProc.exe first (LEConfig.xml next to it)")
            item.setFlags(Qt.NoItemFlags)
            self.list.addItem(item)

    def _check(self, state):
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.flags() & Qt.ItemIsEnabled:
                item.setCheckState(Qt.Checked if state else Qt.Unchecked)

    def _accept(self):
        self.accept()

    def selection(self):
        path = self.path_edit.text().strip()
        chosen = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if (item.flags() & Qt.ItemIsEnabled) and item.checkState() == Qt.Checked:
                chosen.append((item.text(), item.data(Qt.UserRole), path))
        return chosen


class CalendarPopup(QWidget):
    """Small frameless calendar used by the From / To buttons."""

    picked = Signal(object)

    def __init__(self, parent, current):
        super().__init__(parent, Qt.Popup)
        from PySide6.QtGui import QTextCharFormat
        from PySide6.QtWidgets import QCalendarWidget
        self.setObjectName("popup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.calendar.setNavigationBarVisible(True)
        theme = getattr(getattr(parent, "window", None), "palette", DARK)
        normal = QTextCharFormat()
        normal.setForeground(QColor(theme["text"]))
        for day in (Qt.Saturday, Qt.Sunday):
            self.calendar.setWeekdayTextFormat(day, normal)
        header = QTextCharFormat()
        header.setForeground(QColor(theme["subtext"]))
        self.calendar.setHeaderTextFormat(header)
        self.calendar.setSelectedDate(current)
        self.calendar.clicked.connect(self._pick)
        layout.addWidget(self.calendar)

    def _pick(self, value):
        self.picked.emit(value.toPython())
        self.close()


class CardFrame(QFrame):
    """A VN cell: click selects, double click opens its sessions."""

    clicked = Signal()
    double = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.double.emit()
        super().mouseDoubleClickEvent(event)

    def set_selected(self, flag):
        self.setProperty("selected", bool(flag))
        self.style().unpolish(self)
        self.style().polish(self)


class _CoverBridge(QObject):
    done = Signal(object)


class CoverPickerDialog(QDialog):
    """Pick one of the VN covers from vndb.org/v<id>/cv (the API only gives one)."""

    def __init__(self, window, vndb_id):
        super().__init__(window)
        self.window = window
        self.vndb_id = vndb_id
        self.selected = None
        self.setWindowTitle("Choose a cover")
        self.resize(560, 480)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(tr("Covers of https://vndb.org/%s") % vndb_id))
        self.status = QLabel("Loading\u2026")
        self.status.setObjectName("sub")
        outer.addWidget(self.status)

        from PySide6.QtWidgets import QScrollArea
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.grid = QGridLayout(inner)
        self.grid.setSpacing(10)
        self.area.setWidget(inner)
        outer.addWidget(self.area, 1)

        buttons = QHBoxLayout()
        self.use_button = QPushButton("Use selected")
        self.use_button.setObjectName("primary")
        self.use_button.setEnabled(False)
        self.use_button.clicked.connect(self.accept)
        default = QPushButton("Reset to default")
        default.clicked.connect(self._reset)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.use_button)
        buttons.addWidget(default)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        outer.addLayout(buttons)

        self.buttons = {}
        self._bridge = _CoverBridge(self)
        self._bridge.done.connect(self._on_urls)
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            from .vndb import cover_urls
            urls, error = cover_urls(self.vndb_id), None
        except Exception as exception:
            urls, error = [], str(exception)
        self._bridge.done.emit((urls, error))

    def _on_urls(self, payload):
        urls, error = payload
        if error:
            self.status.setText(tr("Could not load the cover page: %s") % error)
            return
        if not urls:
            self.status.setText(tr("No covers found for this VN."))
            return
        self.status.setText(tr("%d cover(s) \u2013 click one") % len(urls))
        self._build(urls)

    def _build(self, urls):
        for index, url in enumerate(urls):
            button = QToolButton()
            button.setObjectName("cover")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(110, 150)
            button.setToolTip(url)
            button.setProperty("cover_url", url)
            button.clicked.connect(lambda _c=False, u=url: self._select(u))
            self.grid.addWidget(button, index // 4, index % 4)
            self.buttons[url] = button
            self.window.request_cover(url, self._set_icon)

    def _set_icon(self, url, image):
        button = self.buttons.get(url)
        if button is None or image is None:
            return
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap.fromImage(image).scaled(100, 140, Qt.KeepAspectRatio,
                                                 Qt.SmoothTransformation)
        button.setIcon(QIcon(pixmap))
        button.setIconSize(pixmap.size())

    def _select(self, url):
        self.selected = url
        self.use_button.setEnabled(True)
        for other, button in self.buttons.items():
            button.setStyleSheet("border: 2px solid #5b8def;" if other == url else "")

    def _reset(self):
        self.selected = ""
        self.accept()


# --------------------------------------------------------------------------- window
class MainWindow(ScreenshotMixin, QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.engine = app.engine
        self.config = app.config
        self.palette = DARK
        self.visible_games = []
        self._cover_callbacks = {}

        self.setWindowTitle("Hygger Presence")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.resize(1100, 760)
        self.setMinimumSize(900, 620)

        shell = QWidget()
        self.setCentralWidget(shell)
        column = QVBoxLayout(shell)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.title_bar = TitleBar(self, self.toggle_theme)
        self.burger = QToolButton()
        self.burger.setObjectName("burger")
        self.burger.setIcon(paint_burger(18))
        self.burger.setIconSize(QSize(18, 18))
        self.burger.setCursor(Qt.PointingHandCursor)
        self.burger.setToolTip(tr("Show / hide the sidebar"))
        self.burger.clicked.connect(self.toggle_sidebar)
        self._burger_active = True
        self.title_bar.layout().insertWidget(0, self.burger)
        # a QFrame wrapper paints reliably (a python QWidget subclass does not
        # always honour a stylesheet background)
        self.title_frame = TitleStrip()
        self.title_frame.setObjectName("titlebar")
        frame_layout = QVBoxLayout(self.title_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)
        frame_layout.addWidget(self.title_bar)
        # a real widget line, drawn by QStyle: stylesheets/palette fills on the
        # strip itself never showed up, a frame line is painted by the style
        self.title_line = TitleLine()
        frame_layout.addWidget(self.title_line)
        column.addWidget(self.title_frame)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        column.addLayout(body, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        side_column = QVBoxLayout(sidebar)
        side_column.setContentsMargins(EDGE, 14, EDGE, 10)
        side_column.setSpacing(4)
        self.nav_buttons = []
        for index, label in enumerate((tr("Library"), tr("Detection"),
                                       tr("Statistics"), tr("Screenshots"),
                                       tr("Settings"))):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _c=False, i=index: self.go(i))
            side_column.addWidget(button)
            self.nav_buttons.append(button)
        side_column.addStretch(1)
        self.status_label = QLabel(tr("Waiting for a game…"))
        self.status_label.setObjectName("sub")
        self.status_label.setWordWrap(True)
        side_column.addWidget(self.status_label)
        self.status_label.setVisible(False)   # the bottom bar shows it now
        # quiet "update available" hint - no tray balloons / toasts at all
        self.update_hint = QLabel("")
        self.update_hint.setObjectName("sub")
        self.update_hint.setWordWrap(True)
        self.update_hint.setVisible(False)
        self.update_hint.setStyleSheet("color:#f5c451;")
        side_column.addWidget(self.update_hint)
        body.addWidget(sidebar)
        self.sidebar = sidebar

        self.stack = QStackedWidget()
        self.library_page = LibraryPage(self)
        self.now_page = NowPage(self)
        self.stats_page = StatsPage(self)
        self.shots_page = ScreenshotPage(self)
        self.settings_page = SettingsPage(self)
        for page in (self.library_page, self.now_page, self.stats_page,
                     self.shots_page, self.settings_page):
            self.stack.addWidget(page)
        body.addWidget(self.stack, 1)

        self.status_bar = QFrame()
        self.status_bar.setObjectName("statusbar")
        bar = QHBoxLayout(self.status_bar)
        bar.setContentsMargins(EDGE, 5, EDGE, 7)
        bar.setSpacing(0)
        self.status_text = QLabel("Waiting for a game\u2026")
        self.status_text.setObjectName("sub")
        self.status_text.setTextFormat(Qt.RichText)
        bar.addWidget(self.status_text, 1)
        column.addWidget(self.status_bar)

        self.grip = QSizeGrip(shell)
        self.grip.setFixedSize(16, 16)
        column.addWidget(self.grip, 0, Qt.AlignRight)
        column.addWidget(self.grip, 0, Qt.AlignRight)

        if (self.config.get("ui") or {}).get("sidebar_collapsed"):
            self.sidebar.setVisible(False)
        self.target = None
        self._snap = None
        shot_opts = (self.config.get("screenshot") or {})
        self.shot_store = shots.ScreenshotStore(shot_opts.get("path") or None)
        self.hotkeys = HotkeyManager(self)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self._hotkey_state = False
        self._hotkey_timer = QTimer(self)
        self._hotkey_timer.setInterval(50)
        self._hotkey_timer.timeout.connect(self._poll_hotkey)
        self._hotkey_retry = QTimer(self)
        self._hotkey_retry.setInterval(5000)
        self._hotkey_retry.timeout.connect(self._register_hotkey)
        self._hotkey_retry.start()
        self.native_snap = winframe.apply_native_frame(self)
        if self.native_snap:
            self._frame_filter = winframe.NativeFrameFilter(lambda: self)
            QApplication.instance().installNativeEventFilter(self._frame_filter)
        self.apply_theme()
        self._setup_icon()
        self._dark_filter = DarkDialogFilter(
            lambda: self.palette is DARK)
        QApplication.instance().installEventFilter(self._dark_filter)
        self._setup_tray()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        # the detection tick is 1 s; the clock in the UI must not be
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.refresh_clock_display)
        self.clock_timer.start(250)
        self.presence_timer = QTimer(self)
        self.presence_timer.timeout.connect(self.engine.ensure_presence)
        self.presence_timer.start(5000)
        self.cover_timer = QTimer(self)
        self.cover_timer.timeout.connect(self.drain_covers)
        self.cover_timer.start(300)
        self.tick()
        self.update_info = None
        QTimer.singleShot(2500, self.startup_update_check)

        # 1.0.4-style foreground hook: status flips in milliseconds, not seconds
        class _FocusBridge(QObject):
            fired = Signal()

        self._focus_bridge = _FocusBridge(self)
        self._focus_bridge.fired.connect(self._focus_changed)
        self._focus_timer = QTimer(self)
        self._focus_timer.setSingleShot(True)
        self._focus_timer.setInterval(120)
        self._focus_timer.timeout.connect(self.tick)
        try:
            self.engine.start_focus_hook(self._focus_bridge.fired.emit)
        except Exception as error:
            print("focus hook unavailable:", error)

    STATUS_COLOURS = {"Reading": "#3ba55d", "Paused": "#e05a4a", "Idle": "#f5c451"}

    def update_status_bar(self, preview):
        """One line with a coloured dot: status - title - session - total."""
        from .core import format_time
        if not hasattr(self, "status_text"):
            return          # the pages are built before the status bar exists
        if not preview:
            message = (tr("Detection error") if self.engine.last_error
                       else tr("Waiting for a game\u2026"))
            self.status_text.setText(
                '<span style="color:#5f6672;">\u25cf</span>&nbsp;&nbsp;%s' % message)
            return
        status = preview.get("status") or ""
        colour = self.STATUS_COLOURS.get(status, "#5f6672")
        discord = ""
        self.status_text.setText(
            '<span style="color:%s;">\u25cf</span>&nbsp;&nbsp;%s<b>:</b> %s '
            '&nbsp;\u2022&nbsp; %s %s &nbsp;\u2022&nbsp; %s %s'
            % (colour, tr(status) if status else "\u2014",
               preview.get("title") or "",
               tr("Session"), format_time(self.engine.session_seconds),
               tr("Total"), format_time(self.engine.total_seconds)))

    # ------------------------------------------------------------- updates
    def startup_update_check(self):
        if not self.config.get("auto_check", True):
            return
        self.check_updates(silent=True)

    def check_updates(self, silent=False, from_settings=False):
        class Bridge(QObject):
            done = Signal(object)

        bridge = Bridge(self)
        bridge.done.connect(lambda info: self._on_update_result(info, silent, from_settings))
        self._update_bridge = bridge

        def worker():
            try:
                info = updater.latest_release()
            except Exception as error:
                info = {"status": "error", "error": str(error)}
            bridge.done.emit(info)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_result(self, info, silent, from_settings):
        self.update_info = info
        if self.settings_page:
            self.settings_page.on_update_found(info)
        if info.get("status") != "ok":
            if not silent:
                QMessageBox.information(self, tr("Check Update"),
                                        "Could not check for updates.\n%s"
                                        % info.get("error", ""))
            return
        if not updater.is_newer(info.get("version", "0"), APP_VERSION):
            return
        skipped = (self.config.get("skip_version") or "") == info.get("version")
        if skipped and not from_settings:
            return
        if silent and not self.config.get("auto_check", True):
            return
        if silent:
            self.show_update_hint("Update %s available" % info["version"])
            return
        answer = QMessageBox.question(
            self, tr("Update available"),
            "Version %s is available.\n\n%s\n\nUpdate now?"
            % (info["version"], (info.get("notes") or "")[:400]))
        if answer == QMessageBox.Yes:
            self.settings_page.install_update()
        elif answer == QMessageBox.No and not skipped:
            if QMessageBox.question(
                    self, tr("Skip this version"),
                    tr("Stop telling me about %s?") % info["version"]) == QMessageBox.Yes:
                self.config["skip_version"] = info["version"]
                store.save_config(self.config)
                self.settings_page._refresh_skip_label()

    # ------------------------------------------------------------- native frame
    def nativeEvent(self, event_type, message):
        handled = winframe.handle_native_event(
            self, event_type, message, title_height=self.title_bar.height() + 2,
            skip_rects=self._caption_buttons())
        if handled is not None:
            return handled
        return super().nativeEvent(event_type, message)

    def _caption_buttons(self):
        rects = []
        for button in (getattr(self.title_bar, "theme_button", None),
                       getattr(self.title_bar, "minimise_button", None),
                       getattr(self.title_bar, "maximise_button", None),
                       getattr(self.title_bar, "close_button", None),
                       getattr(self, "burger", None)):
            if button is None:
                continue
            try:
                top_left = button.mapTo(self, QPoint(0, 0))
                rects.append(QRect(top_left.x() - 2, top_left.y() - 2,
                                   button.width() + 4, button.height() + 4))
            except Exception:
                continue
        # QRect.contains(x, y) is what the helper calls
        return rects

    # ------------------------------------------------------------- native frame
    def caption_button_rects(self):
        return self._caption_buttons()

    def _caption_buttons(self):
        rects = []
        for button in (getattr(self.title_bar, "theme_button", None),
                       getattr(self.title_bar, "minimise_button", None),
                       getattr(self.title_bar, "maximise_button", None),
                       getattr(self.title_bar, "close_button", None),
                       getattr(self, "burger", None)):
            if button is None:
                continue
            try:
                top_left = button.mapTo(self, QPoint(0, 0))
                rects.append(QRect(top_left.x() - 2, top_left.y() - 2,
                                   button.width() + 4, button.height() + 4))
            except Exception:
                continue
        return rects

    def showEvent(self, event):
        super().showEvent(event)
        # Qt can reset the style after the first show: re-apply the native frame
        if getattr(self, "native_snap", False):
            winframe.apply_native_frame(self)

    # ------------------------------------------------------------- snap preview
    def show_snap_preview(self, target, animate_from=None):
        if self._snap is None:
            self._snap = SnapPreview()
        self._snap.show_target(target, animate_from)

    def hide_snap_preview(self):
        if self._snap is not None:
            self._snap.hide_preview()

    def snap_preview_visible(self):
        return self._snap is not None and self._snap.isVisible()

    # ------------------------------------------------------------- resize
    RESIZE_MARGIN = 6

    def _edges_at(self, position):
        margin = self.RESIZE_MARGIN
        return (position.x() <= margin,
                position.x() >= self.width() - margin,
                position.y() <= margin,
                position.y() >= self.height() - margin)

    def mousePressEvent(self, event):
        if getattr(self, "native_snap", False):
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            edges = self._edges_at(_as_point(event.position()))
            if any(edges):
                self._resize_edges = edges
                self._resize_origin = (_as_point(event.globalPosition()),
                                       QRect(self.geometry()))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, "_resize_origin", None) and (event.buttons() & Qt.LeftButton):
            origin, geometry = self._resize_origin
            delta = _as_point(event.globalPosition()) - origin
            left, right, top, bottom = getattr(self, "_resize_edges", (False,) * 4)
            rectangle = QRect(geometry)
            if left:
                rectangle.setLeft(min(geometry.left() + delta.x(),
                                      rectangle.right() - self.minimumWidth()))
            if right:
                rectangle.setRight(max(geometry.right() + delta.x(),
                                       rectangle.left() + self.minimumWidth()))
            if top:
                rectangle.setTop(min(geometry.top() + delta.y(),
                                     rectangle.bottom() - self.minimumHeight()))
            if bottom:
                rectangle.setBottom(max(geometry.bottom() + delta.y(),
                                        rectangle.top() + self.minimumHeight()))
            self.setGeometry(rectangle)
            event.accept()
            return
        left, right, top, bottom = self._edges_at(_as_point(event.position()))
        if (left and top) or (right and bottom):
            self.setCursor(Qt.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.SizeHorCursor)
        elif top or bottom:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resize_origin = None
        super().mouseReleaseEvent(event)

    def goto_launchers(self):
        """Settings > Launchers (used by the Start menu)."""
        self.go(3)
        try:
            self.settings_page.tabs.setCurrentIndex(2)
        except Exception:
            pass

    # ------------------------------------------------------------- sidebar
    def toggle_sidebar(self):
        """Collapse the sidebar; while collapsed the burger doubles as navigation."""
        ui = self.config.setdefault("ui", {})
        if self.sidebar.isVisible():
            self.sidebar.setVisible(False)
            ui["sidebar_collapsed"] = True
        else:
            self.sidebar.setVisible(True)
            ui["sidebar_collapsed"] = False

    def _sidebar_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        for index, label in enumerate(("Library", "Now reading", "Statistics",
                                       "Screenshots", "Settings")):
            menu.addAction(label, lambda i=index: self.go(i))
        menu.addSeparator()
        menu.addAction(tr("Show sidebar"), self.toggle_sidebar)
        menu.popup(self.burger.mapToGlobal(self.burger.rect().bottomLeft()))

    # ------------------------------------------------------------- icon / tray
    def _app_icon(self):
        """icon.ico from the data folder, the bundle, or one level up.

        In a PyInstaller build icon.ico lives inside the bundle (_MEIPASS), not
        next to the exe, so the bundle has to be searched too - otherwise the
        title bar and the tray fell back to the drawn sun.
        """
        from .core import APP_DIR, BUNDLE_DIR
        folders = [Path(APP_DIR), Path(BUNDLE_DIR), Path(APP_DIR).parent,
                   Path(__file__).resolve().parent.parent]
        seen = set()
        for folder in folders:
            candidate = folder / "icon.ico"
            key = str(candidate)
            if key in seen or not candidate.exists():
                continue
            seen.add(key)
            icon = QIcon(str(candidate))
            if not icon.isNull():
                return icon
        from PySide6.QtWidgets import QStyle
        return self.style().standardIcon(QStyle.SP_ApplicationIcon)

    def _setup_icon(self):
        icon = self._app_icon()
        self.setWindowIcon(icon)
        self.title_bar.setWindowIcon(icon)
        self.title_bar.set_title_icon(icon)

    def _setup_tray(self):
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self._app_icon(), self)
        self.tray.setToolTip("Hygger Presence")
        menu = QMenu(self)
        menu.addAction(tr("Open"), self._restore_window)
        self.tray_presence = menu.addAction(tr("Presence: ON"), self._tray_toggle_presence)
        menu.addSeparator()
        menu.addAction(tr("Quit"), self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self._refresh_tray_menu()

    def show_update_hint(self, message):
        label = getattr(self, "update_hint", None)
        if label is None:
            return
        label.setText(message)
        label.setVisible(bool(message))

    def _refresh_tray_menu(self):
        if self.tray is None:
            return
        text = tr("Presence: ON") if self.engine.presence_enabled else tr("Presence: OFF")
        self.tray_presence.setText(text)
        self.tray.setToolTip("Hygger Presence\n%s" % text)

    def _tray_toggle_presence(self):
        self.engine.set_presence_enabled(not self.engine.presence_enabled)
        self.now_page.update_from_engine()
        self._refresh_tray_menu()

    def _tray_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._restore_window()

    def _restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self):
        if self.app is not None:
            self.app.shutdown()
        QApplication.quit()

    def closeEvent(self, event):
        if self.tray is not None and self.config.get("close_to_tray", True):
            self.hide()
            event.ignore()
            return
        self._quit()
        event.accept()

    # ------------------------------------------------------------- helpers
    def go(self, index):
        self.stack.setCurrentIndex(index)
        for position, button in enumerate(self.nav_buttons):
            button.setChecked(position == index)
        if index == 2:
            self.stats_page.refresh()
            self.stats_page.refresh()

    def flash_status(self, text, seconds=2.5):
        """Temporary message in the status bar."""
        try:
            self.status_text.setText(text)
            QTimer.singleShot(int(seconds * 1000), self._refresh_status)
        except Exception:
            pass

    def toggle_theme(self):
        self.palette = LIGHT if self.palette is DARK else DARK
        self.apply_theme()

    def apply_theme(self):
        self.palette_bg = self.palette["bg"]
        palette = dict(self.palette)
        palette["check"] = check_icon_path()
        palette["arrow"] = arrow_icon_path()
        self.setStyleSheet(qss(palette))
        # an id rule on the window stylesheet does not reach this widget, so give
        # the title bar its own stylesheet
        self.title_line.update()
        self.title_frame.update()
        self.title_bar.update()
        if hasattr(self, "shots_page"):
            self.shots_page._fill()
        if hasattr(self, "settings_page"):
            self.settings_page.refresh_variables()
        moon = self.palette is DARK
        self.title_bar.theme_button.setIcon(
            paint_moon(hole=self.palette["bg"]) if moon
            else paint_sun())
        self.now_page.update_from_engine()

    def request_cover(self, url, callback):
        if not url:
            return
        cached = self.app.cover_cache.get(url)
        if cached is not None:
            callback(url, cached)
            return
        self._cover_callbacks[url] = callback
        if url in self.app.cover_pending:
            return
        self.app.cover_pending.add(url)

        def worker():
            try:
                self.app.cover_bytes[url] = self.app.fetch(url)
            except Exception:
                pass
            finally:
                self.app.cover_pending.discard(url)

        threading.Thread(target=worker, daemon=True).start()

    def drain_covers(self):
        from PySide6.QtGui import QImage
        for url, data in list(self.app.cover_bytes.items()):
            if url in self.app.cover_cache:
                continue
            image = QImage()
            if image.loadFromData(data):
                self.app.cover_cache[url] = image
            else:
                self.app.cover_cache[url] = None
        for url, callback in list(self._cover_callbacks.items()):
            if url in self.app.cover_cache:
                self._cover_callbacks.pop(url, None)
                try:
                    callback(url, self.app.cover_cache[url])
                except Exception:
                    pass

    def refresh_clock_display(self):
        """Recount session/total every 250 ms without running detection."""
        engine = self.engine
        if not self.now_page.isVisible():
            return
        if engine.game is None or engine._reading_start is None:
            return
        if engine.status != "Reading":
            return
        current = max(0.0, time.time() - engine._reading_start)
        engine.session_seconds = engine._session_accumulated + current
        engine.total_seconds = engine.game.get("total_seconds", 0) + current
        self.now_page.update_from_engine()

    def _focus_changed(self):
        """Coalesce a burst of focus events into a single tick."""
        if not self._focus_timer.isActive():
            self._focus_timer.start()

    def tick(self):
        self.engine.tick()
        self.now_page.update_from_engine()
        if not self.engine.preview:
            if self.engine.last_error:
                self.status_label.setText(tr("Detection error:"))
                self.status_label.setToolTip(self.engine.last_error)
            else:
                self.status_label.setText(tr("Waiting for a game…"))
                self.status_label.setToolTip("")
        else:
            self.status_label.setText(self.engine.status or "")

    def add_game_dialog(self):
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        exe, _ = QFileDialog.getOpenFileName(self, "Select game executable",
                                             "", "Executable (*.exe)")
        if not exe:
            return
        link, ok = QInputDialog.getText(self, "VNDB",
                                        "VNDB link or ID (e.g. v64038):")
        if not ok or not link.strip():
            return
        import re
        match = re.search(r"(v\d+)", link, re.I)
        if not match:
            QMessageBox.warning(self, "VNDB", "Could not find a VNDB id.")
            return
        vndb_id = match.group(1).lower()
        info = self.app.fetch_vndb(vndb_id) or {}
        game = {
            "exe": str(Path(exe).resolve()), "vndb_id": vndb_id,
            "title": info.get("title") or Path(exe).stem,
            "original": info.get("original") or info.get("title") or Path(exe).stem,
            "romanized": info.get("romanized") or "",
            "image": info.get("image") or "",
            "developer": info.get("developer") or "Unknown",
            "year": info.get("year") or "????",
            "rating_average": info.get("rating_average") or "N/A",
            "rating_weighted": info.get("rating_weighted") or "N/A",
            "process_names": [], "total_seconds": 0,
        }
        self.engine.games = [g for g in self.engine.games
                             if g.get("exe") != game["exe"]] + [game]
        store.save_games(self.engine.games)
        self.library_page.refresh()
        self.go(0)


def run():
    app = QApplication.instance() or QApplication([])
    application = Application()
    window = MainWindow(application)
    application.window = window
    window.show()
    return app.exec()


class Application:
    """Owns the engine, the store and the cover cache (Qt-free where possible)."""

    def __init__(self):
        self.config = store.load_config()
        # the window is built in English and then translated, so switching
        # languages later can always go back to the original strings
        set_language("en")
        self.games = store.load_games()
        self.stats = StatsStore(store.STATS_FILE)
        self.cover_cache = {}
        self.cover_bytes = {}
        self.cover_pending = set()
        from .core import set_debug_enabled
        set_debug_enabled(bool(self.config.get("debug_log", False)))
        self.engine = Engine(
            client_id=self.config.get("client_id", ""),
            templates=self.config.get("templates") or DEFAULT_TEMPLATES,
            stats=self.stats,
            presence=self.config.get("presence") or {})
        self.engine.games = self.games
        self.engine.on_save = lambda: store.save_games(self.engine.games)
        self.window = None

    def fetch(self, url):
        import requests
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.content

    def fetch_vndb(self, vndb_id):
        from .vndb import fetch_vndb
        return fetch_vndb(vndb_id)

    def shutdown(self):
        for page in (getattr(self.window, "library_page", None),
                     getattr(self.window, "settings_page", None)):
            try:
                if page is not None:
                    page.save_state()
            except Exception:
                pass
        try:
            store.save_config(self.config)
        except Exception:
            pass
        try:
            self.engine.close()
        except Exception:
            pass
        try:
            # writing [] here used to create an empty games.json, which then
            # blocked the 1.x import ("file already exists")
            if self.engine.games or store.GAMES_FILE.exists():
                store.save_games(self.engine.games)
        except Exception:
            pass
        try:
            if self.stats:
                self.stats.close()
        except Exception:
            pass
