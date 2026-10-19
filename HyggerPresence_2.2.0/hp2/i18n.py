"""UI strings, translations and live language switching.

Translations live in one JSON file per language, next to this module:

    hp2/locales/zh_TW.json

The keys are the English source strings exactly as they appear in the UI; the
values are the translated text. Anything missing falls back to English, so a
partial translation is always safe. After editing a file, press
Settings -> General -> "Reload translations" (no restart needed).

Two mechanisms are used:

* ``tr("Some English text")`` for strings wrapped at construction time;
* ``apply_language(code, root=window)`` which walks an already built widget tree,
  remembers every label/button/tab/menu whose English text has a translation and
  re-applies it - that is what makes switching languages work instantly.

The window is always built in English, then translated, so switching back to
English can restore the original strings.
"""

import json
from pathlib import Path

from PySide6.QtCore import QObject

LOCALE_DIR = Path(__file__).resolve().parent / "locales"

LANGUAGES = (("en", "English"), ("zh_TW", "\u7e41\u9ad4\u4e2d\u6587"),
             ("zh_CN", "\u7b80\u4f53\u4e2d\u6587"))

_current = "en"
_tables = {}
_registry = []
_filter = None
_qt_translator = None


def _load(code):
    if code in _tables:
        return _tables[code]
    path = LOCALE_DIR / ("%s.json" % code)
    table = {}
    if path.exists():
        try:
            table = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as error:                   # a broken file must not kill the UI
            from .core import debug_log
            debug_log("locale %s failed to load: %s" % (code, error))
            table = {}
    _tables[code] = {str(key): str(value) for key, value in table.items()}
    return _tables[code]


def reload_locales():
    """Forget cached tables so edited JSON files are picked up."""
    _tables.clear()
    return len(_tables)


def set_language(code):
    global _current
    _current = code if any(code == key for key, _ in LANGUAGES) else "en"
    _load(_current)
    _install_qt_translations(_current)


def language():
    return _current


def _install_qt_translations(code):
    """Load Qt's own translations so OK / Cancel / Yes / No are localised too."""
    global _qt_translator
    try:
        from PySide6.QtCore import QLibraryInfo, QTranslator
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return False
        # drop the previous one, otherwise OK/Cancel stay in the old language
        if _qt_translator is not None:
            try:
                app.removeTranslator(_qt_translator)
            except Exception:
                pass
            _qt_translator = None
        if code == "en":
            return False
        path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
        for name in ("qtbase_%s" % code, "qt_%s" % code):
            translator = QTranslator(app)
            if translator.load(name, path) or translator.load(name):
                app.installTranslator(translator)
                _qt_translator = translator
                return True
    except Exception:
        pass
    return False


def tr(text):
    return _load(_current).get(text, text)


def _sources():
    sources = set()
    for code, _name in LANGUAGES:
        sources.update(_load(code).keys())
    return sources


def register_tree(root):
    """Remember every widget whose English text we know a translation for."""
    from PySide6.QtWidgets import QComboBox, QLineEdit, QMenu, QTabWidget, QWidget
    sources = _sources()
    record = _registry.append
    for child in root.findChildren(QWidget):
        # never touch input fields: their text is user data, not a label
        if isinstance(child, QLineEdit):
            continue
        try:
            text = child.text()
        except Exception:
            text = None
        if text and text in sources:
            record(["text", child, text])
    for tabs in root.findChildren(QTabWidget):
        for index in range(tabs.count()):
            caption = tabs.tabText(index)
            if caption in sources:
                record(["tab", tabs, index, caption])
    for combo in root.findChildren(QComboBox):
        for index in range(combo.count()):
            caption = combo.itemText(index)
            if caption in sources:
                record(["item", combo, index, caption])
    for menu in root.findChildren(QMenu):
        for action in menu.actions():
            caption = action.text()
            if caption in sources:
                record(["action", action, caption])
    for line in root.findChildren(QLineEdit):
        hint = line.placeholderText()
        if hint and hint in sources:
            record(["hint", line, hint])
    return len(_registry)


def apply_to(root):
    """Register a freshly built tree (a dialog) and translate it right away."""
    register_tree(root)
    return apply_language(_current, root=None)


class _ShowFilter(QObject):
    """Translate every dialog the moment it is shown."""

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Show and obj is not None:
            try:
                from PySide6.QtWidgets import QMessageBox
                if isinstance(obj, QMessageBox):
                    message = obj.text()
                    if message in _sources():
                        obj.setText(tr(message))
                    caption = obj.windowTitle()
                    if caption in _sources():
                        obj.setWindowTitle(tr(caption))
                    return False
                if obj.metaObject().className().endswith("Dialog"):
                    caption = obj.windowTitle()
                    if caption in _sources():
                        obj.setWindowTitle(tr(caption))
                    apply_to(obj)
            except Exception:
                pass
        return False


def install(app):
    global _filter
    try:
        _filter = _ShowFilter()
        app.installEventFilter(_filter)
        return True
    except Exception:
        return False


def apply_language(code, root=None):
    """Translate the live UI (the first call also remembers the sources)."""
    set_language(code)
    if root is not None and not _registry:
        register_tree(root)
    for entry in _registry:
        kind = entry[0]
        try:
            if kind == "text":
                from PySide6.QtWidgets import QLineEdit as _Line
                if isinstance(entry[1], _Line):
                    continue
                entry[1].setText(tr(entry[2]))
            elif kind == "tab":
                entry[1].setTabText(entry[2], tr(entry[3]))
            elif kind == "item":
                combo, index = entry[1], entry[2]
                current = combo.currentIndex()
                combo.setItemText(index, tr(entry[3]))
                combo.setCurrentIndex(current)
            elif kind == "action":
                entry[1].setText(tr(entry[2]))
            elif kind == "hint":
                entry[1].setPlaceholderText(tr(entry[2]))
        except Exception:
            continue
    return len(_registry)
