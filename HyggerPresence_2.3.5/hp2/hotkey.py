"""One global hotkey (RegisterHotKey + a Qt native event filter)."""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Qt, Signal

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 1, 2, 4, 8
MOD_NOREPEAT = 0x4000
NAMES = {}
for _i in range(12):
    NAMES[0x70 + _i] = "F%d" % (_i + 1)
for _c in range(0x30, 0x3A):
    NAMES[_c] = chr(_c)
for _c in range(0x41, 0x5B):
    NAMES[_c] = chr(_c)
NAMES.update({0x2C: "PrintScreen", 0x2D: "Insert", 0x2E: "Delete", 0x24: "Home",
              0x23: "End", 0x21: "PageUp", 0x22: "PageDown"})


def describe(modifiers, key):
    parts = [label for flag, label in ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"),
                                       (MOD_SHIFT, "Shift"), (MOD_WIN, "Win"))
             if modifiers & flag]
    parts.append(NAMES.get(key, "0x%02X" % key))
    return "+".join(parts)


def from_qt(key, modifiers):
    mapping = {}
    for index in range(12):
        attr = getattr(Qt, "Key_F%d" % (index + 1), None)
        if attr is not None:
            mapping[attr] = 0x70 + index
    for name, code in (("Print", 0x2C), ("Insert", 0x2D), ("Delete", 0x2E),
                       ("Home", 0x24), ("End", 0x23), ("PageUp", 0x21),
                       ("PageDown", 0x22)):
        attr = getattr(Qt, "Key_" + name, None)
        if attr is not None:
            mapping[attr] = code
    mods = 0
    if modifiers & Qt.ControlModifier:
        mods |= MOD_CONTROL
    if modifiers & Qt.AltModifier:
        mods |= MOD_ALT
    if modifiers & Qt.ShiftModifier:
        mods |= MOD_SHIFT
    if modifiers & Qt.MetaModifier:
        mods |= MOD_WIN
    if key in mapping:
        return mods, mapping[key]
    if Qt.Key_0 <= key <= Qt.Key_9:
        return mods, 0x30 + (key - Qt.Key_0)
    if Qt.Key_A <= key <= Qt.Key_Z:
        return mods, 0x41 + (key - Qt.Key_A)
    return None


def parse(spec):
    parts = [p.strip().lower() for p in str(spec or "").split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, None
    for part in parts:
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part in ("win", "meta"):
            mods |= MOD_WIN
        else:
            key = part
    if not key:
        return None
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        return mods, 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isalnum():
        code = ord(key.upper())
        if 0x30 <= code <= 0x39 or 0x41 <= code <= 0x5A:
            return mods, code
    named = {"printscreen": 0x2C, "insert": 0x2D, "delete": 0x2E, "home": 0x24,
             "end": 0x23, "pageup": 0x21, "pagedown": 0x22}
    return (mods, named[key]) if key in named else None


class HotkeyManager(QObject):
    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._user32 = getattr(getattr(ctypes, "windll", None), "user32", None)
        self._filter = None
        self._id = None
        self._name = ""

    def _filter_in(self):
        if self._filter is not None or self._user32 is None:
            return
        manager = self

        class _F(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                try:
                    msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                except Exception:
                    return False, 0
                if msg.message == WM_HOTKEY and manager._id == int(msg.wParam):
                    manager.triggered.emit(manager._name)
                    return True, 0
                return False, 0

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        self._filter = _F()
        app.installNativeEventFilter(self._filter)

    def bind(self, name, modifiers, key):
        self.release()
        if self._user32 is None or not key:
            return False
        self._filter_in()
        if not self._user32.RegisterHotKey(None, 1, modifiers | MOD_NOREPEAT, key):
            return False
        self._id, self._name = 1, name
        return True

    def release(self):
        if self._id is not None and self._user32 is not None:
            self._user32.UnregisterHotKey(None, self._id)
        self._id, self._name = None, ""

    def is_bound(self):
        return self._id is not None
