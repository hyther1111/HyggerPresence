import json, os, sys, tempfile, shutil, time
from pathlib import Path

root = Path(tempfile.gettempdir()) / "hg_regress"
shutil.rmtree(root, ignore_errors=True)
appdir = root / "install"
shutil.copytree(r"C:\Users\Hugo\Downloads\test\HyggerPresence_2.0.0", appdir,
                ignore=shutil.ignore_patterns("__pycache__"))
# pretend this is a fresh install with data sitting next to the program
(appdir / "games.json").write_text(json.dumps([
    {"title": "Old Game", "original": "Old Game", "exe": r"D:\g\Old\old.exe",
     "vndb_id": "v1", "total_seconds": 3600, "process_names": []}]), encoding="utf-8")
(appdir / "config.json").write_text(json.dumps({"client_id": "", "language": "en"}), encoding="utf-8")

data = root / "appdata"
os.environ["HYGGER_DATA_DIR"] = str(data)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HYGGER_DEBUG"] = "0"
sys.argv = [str(appdir / "main.py")]
sys.path.insert(0, str(appdir))

ok = True
def check(label, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + label + (("   " + str(extra)) if extra else ""))
    if not cond: ok = False

import hp2.core as core
check("data folder is %APPDATA%-style", str(core.APP_DIR) == str(data), core.APP_DIR)
check("install folder detected", str(core.INSTALL_DIR) == str(appdir), core.INSTALL_DIR)
check("existing library migrated", "Old Game" in (data / "games.json").read_text(encoding="utf-8"))
check("config migrated", (data / "config.json").exists())
check("legacy import points at install parent",
      str(__import__("hp2.store", fromlist=["LEGACY_DIR"]).LEGACY_DIR) == str(appdir.parent))

from PySide6.QtWidgets import QApplication, QLabel
import hp2.i18n as i18n
import hp2.ui as ui
import hp2.store as store
import main as entry

app = QApplication([])
i18n.install(app)
w = ui.MainWindow(ui.Application())
w.resize(1200, 800)
w.show(); app.processEvents()

check("window built", w.isVisible())
check("library shows migrated game", w.library_page.table.rowCount() == 1,
      w.library_page.table.rowCount())
for i, name in enumerate(("Library", "Detection", "Statistics", "Settings")):
    w.go(i); app.processEvents()
    check("page %s opens" % name, w.stack.currentIndex() == i)

w.go(2); app.processEvents()
w.stats_page.refresh(flush=True); app.processEvents()
check("statistics page refreshes", w.stats_page is not None)

# session clock + stats writing
now = time.time()
w.app.stats.add("v9", "New Game", "new.exe", now - 120, now - 60, 60, min_seconds=0)
total = w.app.stats.total("1970-01-01", "2100-01-01")
check("stats add + total", total[0] >= 60, total)
w.stats_page.refresh(flush=True); app.processEvents()
check("stats page renders cards", len(w.stats_page._cells) >= 1, len(w.stats_page._cells))

# detection tick with a fake process
game = {"title": "New Game", "original": "New Game", "exe": r"D:\g\New\new.exe",
        "vndb_id": "v9", "total_seconds": 0, "process_names": []}
w.app.games.append(game)
w.engine.games = w.app.games
w.engine.scan = lambda force=False: (game, {1})
w.engine._pids_alive = lambda pids: True
w.engine._status_for = lambda g, p: "Reading"
w.engine._arm_exit_watch = lambda g, p: None
w.engine.tick(); app.processEvents()
check("detection sets Reading", w.engine.status == "Reading", w.engine.status)
check("session clock started", w.engine.session_seconds >= 0, w.engine.session_seconds)
check("preview built", bool(w.engine.preview), list(w.engine.preview)[:3])

# language switching
for code, expected in (("zh_TW", "\u79fb\u9664"), ("zh_CN", "\u79fb\u9664"), ("en", "Remove")):
    i18n.apply_language(code, root=w if code == "zh_TW" else None)
    w.settings_page._retranslate_tabs(); app.processEvents()
    check("language " + code, w.library_page.remove_button.text() == expected,
          w.library_page.remove_button.text())

# settings save writes into the new data folder
w.config["language"] = "zh_TW"
w.settings_page.save()
saved = json.loads((data / "config.json").read_text(encoding="utf-8"))
check("save writes to data folder", saved.get("language") == "zh_TW", saved.get("language"))
check("backup of config created", (data / "config.json.bak").exists())

# single instance helper
handle = entry._claim_single_instance()
check("single-instance claim", handle not in (None, "exists"), type(handle).__name__)
second = entry._claim_single_instance()
check("second instance refused", second == "exists", second)

# icon
icon = w._app_icon()
check("icon loads", not icon.isNull() and len(icon.availableSizes()) >= 5,
      len(icon.availableSizes()))

w.app.shutdown(); app.quit()
shutil.rmtree(root, ignore_errors=True)
print("RESULT:", "ALL PASS" if ok else "SOME FAILURES")
