"""2.1.0 screenshots, compact: hotkey module, store merge, page, settings tab."""
from pathlib import Path

APP = Path("HyggerPresence_2.1.0/hp2")
ui_p, store_p, hot_p = APP / "ui.py", APP / "store.py", APP / "hotkey.py"
ui, store = ui_p.read_text(encoding="utf-8"), store_p.read_text(encoding="utf-8")
fails = []


def rep(text, old, new, tag):
    if text.count(old) != 1:
        fails.append("%s: %d matches" % (tag, text.count(old)))
        return text
    return text.replace(old, new, 1)


# ---- store: deep merge + screenshot defaults ------------------------------
if "_deep_merge" not in store:
    store = rep(store, "def _write_json(path, payload):", '''def _deep_merge(base, overlay):
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay if overlay is not None else base
    result = dict(base)
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_json(path):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {}


def _write_json(path, payload):''', "store/write_json")
    store = rep(store, """def save_config(config):
    _write_json(CONFIG_FILE, config)""", '''def save_config(config):
    existing = _read_json(CONFIG_FILE)
    if isinstance(existing, dict) and isinstance(config, dict):
        config = _deep_merge(existing, config)
    _write_json(CONFIG_FILE, config)''', "store/save_config")
if '"screenshot"' not in store:
    store = rep(store, '''    "launchers": [],
    "close_to_tray": True,
}''', '''    "launchers": [],
    "close_to_tray": True,
    "screenshot": {"path": "", "hotkey": ""},
}''', "store/defaults")

# ---- ui wiring ------------------------------------------------------------
if not hasattr(__builtins__, "_x"):
    pass
ui = rep(ui, '''        for index, label in enumerate((tr("Library"), tr("Detection"),
                                       tr("Statistics"), tr("Settings"))):''',
         '''        for index, label in enumerate((tr("Library"), tr("Detection"),
                                       tr("Statistics"), tr("Screenshots"),
                                       tr("Settings"))):''', "ui/nav")
ui = rep(ui, '''        self.stats_page = StatsPage(self)
        self.settings_page = SettingsPage(self)''',
         '''        self.stats_page = StatsPage(self)
        self.shots_page = ScreenshotPage(self)
        self.settings_page = SettingsPage(self)''', "ui/pages")
ui = rep(ui, '''        for page in (self.library_page, self.now_page, self.stats_page,
                     self.settings_page):''',
         '''        for page in (self.library_page, self.now_page, self.stats_page,
                     self.shots_page, self.settings_page):''', "ui/page-list")
ui = rep(ui, '''        for index, label in enumerate(("Library", "Now reading", "Statistics",
                                       "Settings")):''',
         '''        for index, label in enumerate(("Library", "Now reading", "Statistics",
                                       "Screenshots", "Settings")):''', "ui/menu")
ui = rep(ui, "        self._snap = None", '''        self._snap = None
        shot_opts = (self.config.get("screenshot") or {})
        self.shot_store = shots.ScreenshotStore(shot_opts.get("path") or None)
        self.hotkeys = HotkeyManager(self)
        self.hotkeys.triggered.connect(self._on_hotkey)''', "ui/init")
ui = rep(ui, '        self.tabs.addTab(page, tr("Updates"))',
         '''        self.tabs.addTab(page, tr("Updates"))
        self.tabs.addTab(self._build_screenshot(), tr("Screenshots"))''', "ui/tab")
ui = rep(ui, '''("General", "Presence", "Launchers", "Updates")),''',
         '''("General", "Presence", "Launchers", "Updates",
                                 "Screenshots")),''', "ui/captions")
ui = rep(ui, "class SettingsPage(Page):", "class SettingsPage(ScreenshotSettingsMixin, Page):",
         "ui/settings-base")
ui = rep(ui, "class MainWindow(QMainWindow):", "class MainWindow(ScreenshotMixin, QMainWindow):",
         "ui/main-base")

if fails:
    print("FAILED")
    for f in fails:
        print(" -", f)
    raise SystemExit(1)

hot_p.write_text('''"""One global hotkey (RegisterHotKey + a Qt native event filter)."""

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
''', encoding="utf-8")

BLOCK = '''

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

        layout.addSpacing(12)
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
        buttons = QHBoxLayout()
        take = QPushButton(tr("Capture the active window now"))
        take.clicked.connect(self.window.take_screenshot)
        buttons.addWidget(take)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

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
    from PySide6.QtCore import QStandardPaths
    return QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())


class ScreenshotPage(Page):
    COVER = (78, 104)
    THUMB = (188, 106)

    def __init__(self, window):
        super().__init__(window)
        from PySide6.QtWidgets import QScrollArea
        self._view, self._folder, self._cards = "games", "", {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.back_button = QPushButton(tr("Back"))
        self.back_button.clicked.connect(self.show_games)
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
        outer.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll, 1)
        self.empty = QLabel(tr("No screenshots"))
        self.empty.setObjectName("sub")
        self.empty.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty)
        self.refresh()

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

    def _library_title(self, folder):
        romanise = (self.window.config.get("library_title_mode") or "original") == "romanized"
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

    def show_games(self):
        self._view, self._folder = "games", ""
        self.back_button.setVisible(False)
        self.search.setVisible(True)
        self.title_label.setText(tr("Screenshots"))
        self.refresh()

    def open_folder(self, folder):
        self._view, self._folder = "folder", folder
        self.back_button.setVisible(True)
        self.search.setVisible(False)
        self.title_label.setText(self._library_title(folder))
        self.refresh()

    def refresh(self):
        self._fill()

    def _fill(self):
        store_ = self._shot_store()
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(14)
        grid.setContentsMargins(0, 0, 0, 0)
        self._cards = {}
        width = max(360, self.width() - 60)
        if self._view == "games":
            games = store_.games_with_shots()
            needle = (self.search.text() or "").strip().lower()
            if needle:
                games = [g for g in games if needle in g[0].lower()
                         or needle in self._library_title(g[0]).lower()]
            self.count_label.setText(tr("%d screenshot(s)") % sum(c for _f, c in games))
            columns = self._columns(width, self.COVER)
            for index, (folder, count) in enumerate(games):
                grid.addWidget(self._game_card(folder, count),
                               index // columns, index % columns)
                self._cards[folder] = True
            self.empty.setVisible(not games)
            grid.setRowStretch(len(games) // columns + 1, 1)
        else:
            paths = store_.shots_for(self._folder)
            self.count_label.setText(tr("%d screenshot(s)") % len(paths))
            columns = self._columns(width, self.THUMB)
            for index, path in enumerate(paths):
                grid.addWidget(self._shot_card(path), index // columns, index % columns)
                self._cards[str(path)] = True
            self.empty.setVisible(not paths)
            grid.setRowStretch(len(paths) // columns + 1, 1)
        self.scroll.setWidget(host)

    def _game_card(self, folder, count):
        card = QFrame()
        card.setObjectName("card")
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedWidth(self.COVER[0] + 28)
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
        name.setFixedHeight(38)
        lay.addWidget(name)
        sub = QLabel(tr("%d Screenshot(s)") % count)
        sub.setObjectName("sub")
        lay.addWidget(sub)
        card.mouseDoubleClickEvent = lambda _e, f=folder: self.open_folder(f)
        return card

    def _shot_card(self, path):
        card = QFrame()
        card.setObjectName("card")
        card.setCursor(Qt.PointingHandCursor)
        card.setFixedWidth(self.THUMB[0] + 16)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        art = QLabel()
        art.setFixedSize(*self.THUMB)
        art.setAlignment(Qt.AlignCenter)
        art.setStyleSheet("QLabel{background:%s;border-radius:4px;}"
                          % self.window.palette["surface2"])
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            art.setPixmap(pixmap.scaled(self.THUMB[0], self.THUMB[1], Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))
        lay.addWidget(art, 0, Qt.AlignHCenter)
        name = QLabel(path.name)
        name.setObjectName("sub")
        name.setWordWrap(True)
        lay.addWidget(name)
        card.mouseDoubleClickEvent = lambda _e, p=path: self._open(p)
        return card

    def _open(self, path):
        try:
            os.startfile(str(path))
        except Exception:
            pass

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
        store_ = getattr(self, "shot_store", None)
        if store_ is None:
            return
        try:
            store_.root.mkdir(parents=True, exist_ok=True)
            os.startfile(str(store_.root))
        except Exception:
            pass

    def current_game_title(self):
        game = self.engine.game or {}
        return (game.get("original") or game.get("title") or "").strip()

    def take_screenshot(self):
        if not hasattr(self, "shot_store"):
            return
        self.hide()

        def grab():
            self.show()
            pixmap = shots.capture_window()
            if pixmap is None:
                return
            try:
                self.shot_store.save(pixmap, self.current_game_title()
                                     or shots.FOLDER_FALLBACK)
            except Exception:
                return
            if hasattr(self, "shots_page"):
                self.shots_page.refresh()

        QTimer.singleShot(180, grab)

    def _on_hotkey(self, _name):
        self.take_screenshot()

    def set_hotkey(self, spec):
        opts = self.config.setdefault("screenshot", {})
        opts["hotkey"] = spec
        store.save_config(self.config)
        self._register_hotkey()

    def _register_hotkey(self):
        manager = getattr(self, "hotkeys", None)
        if manager is None:
            return
        manager.release()
        spec = ((self.config.get("screenshot") or {}).get("hotkey") or "").strip()
        parsed = hotkey_mod.parse(spec) if spec else None
        if parsed:
            manager.bind("window", parsed[0], parsed[1])

    def start_hotkey_capture(self, field):
        from PySide6.QtWidgets import QApplication

        class _Grabber(QObject):
            def __init__(self, window, target):
                super().__init__(window)
                self.window, self.target = window, target

            def eventFilter(self, obj, event):
                if event.type() != QEvent.KeyPress:
                    return False
                QApplication.instance().removeEventFilter(self)
                if event.key() == Qt.Key_Escape:
                    self.target.setText("")
                    self.target.setPlaceholderText(tr("Not set"))
                    self.window.set_hotkey("")
                    return True
                parsed = from_qt(event.key(), event.modifiers())
                if not parsed:
                    return True
                text = describe(parsed[0], parsed[1])
                self.target.setText(text)
                self.window.set_hotkey(text)
                return True

        grabber = _Grabber(self, field)
        QApplication.instance().installEventFilter(grabber)
        self._hotkey_grabber = grabber
'''

ui = ui.replace("class SettingsPage(ScreenshotSettingsMixin, Page):",
                BLOCK.strip() + "\n\n\nclass SettingsPage(ScreenshotSettingsMixin, Page):", 1)
ui = ui.replace("from .hotkey import HotkeyManager, describe, from_qt",
                "from .hotkey import HotkeyManager, describe, from_qt\nfrom . import hotkey as hotkey_mod", 1)
ui_p.write_text(ui, encoding="utf-8")
store_p.write_text(store, encoding="utf-8")
print("2.1.0 screenshot wiring written")
