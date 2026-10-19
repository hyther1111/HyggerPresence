#!/usr/bin/env python3
"""Hygger Presence 2.0.0 - Qt UI.

    python main.py

Needs: PySide6, pypresence, psutil, requests, Pillow (the engine reuses the
detection code from the 1.x package, which lives next to this folder).
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtWidgets import QApplication          # noqa: E402

from hp2 import i18n                                # noqa: E402
from hp2.ui import Application, MainWindow          # noqa: E402


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Hygger Presence")
    application = Application()
    i18n.install(app)
    window = MainWindow(application)
    application.window = window
    i18n.apply_language(application.config.get("language") or "en", root=window)
    window.settings_page._retranslate_tabs()
    app.aboutToQuit.connect(application.shutdown)
    window.show()
    if "--tray" in sys.argv or "--minimized" in sys.argv:
        window.hide()
    code = app.exec()
    # a stuck Discord call must never keep the process alive
    import os
    os._exit(code if isinstance(code, int) else 0)


if __name__ == "__main__":
    sys.exit(main())
