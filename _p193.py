import os, sys, tempfile, shutil
from pathlib import Path
base = Path(tempfile.gettempdir()) / "hg222"
shutil.rmtree(base, ignore_errors=True)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["HYGGER_DATA_DIR"] = str(base / "data")
os.environ["LOCALAPPDATA"] = str(base / "local")
sys.argv = ["C:/Users/Hugo/Downloads/test/HyggerPresence_2.1.0/main.py"]
sys.path.insert(0, r"C:\Users\Hugo\Downloads\test\HyggerPresence_2.1.0")
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
import hp2.ui as ui, hp2.screenshot as shots
ok = True
def check(l, c, e=""):
    global ok
    print(("PASS " if c else "FAIL ") + l + (("   " + str(e)) if e else ""))
    if not c: ok = False
app = QApplication([])
w = ui.MainWindow(ui.Application()); w.resize(1200, 800); w.show(); app.processEvents()
store = shots.ScreenshotStore(base / "Pictures" / "HyggerPresence")
pix = QPixmap(600, 340); pix.fill(QColor("#2f4858"))
for i in range(5):
    store.save(pix, "Game A")
w.shot_store = store
p = w.shots_page
w.go(3); p.refresh(); app.processEvents()
p.open_folder("Game A"); app.processEvents()
check("cards", len(p._cards) == 5, len(p._cards))
# ctrl+click toggles
keys = list(p._cards.keys())
p._selection = set()
p._selection.add(str(keys[0]))
check("ctrl toggle add", str(keys[0]) in p._selection)
p._card_pressed(type("E", (), {"button": lambda self=0: Qt.RightButton,
                               "globalPosition": lambda self: type("P", (), {"toPoint": lambda s: __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(0,0)})()})(), keys[0])
check("right click selects", len(p._selection) == 1, p._selection)
# ctrl+a through the app filter (simulate with focus elsewhere)
w.nav_buttons[0].setFocus()
QTest.keyClick(w.nav_buttons[0], Qt.Key_A, Qt.ControlModifier); app.processEvents()
check("ctrl+a selects all", len(p._selection) == 5, len(p._selection))
QTest.keyClick(w.nav_buttons[0], Qt.Key_Delete); app.processEvents()
check("delete key removes all", len(p._cards) == 0, len(p._cards))
check("sound override supported", hasattr(shots, "sound_file"))
check("beep callable", callable(shots.beep))
w.app.shutdown(); app.quit()
shutil.rmtree(base, ignore_errors=True)
print("RESULT:", "ALL PASS" if ok else "SOME FAILURES")
