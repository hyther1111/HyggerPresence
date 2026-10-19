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


def _claim_single_instance():
    """Only one copy of the app may run. Returns a handle that must stay alive."""
    if os.name != "nt":
        return None
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\HyggerPresence_SingleInstance")
    if not handle:
        return None
    if kernel32.GetLastError() == 183:          # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return "exists"
    return handle


def main():
    instance = _claim_single_instance()
    if instance == "exists":
        # another copy owns the mutex: bring it to the front and quit quietly
        if os.name == "nt":
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "Hygger Presence")
            if hwnd:
                user32.ShowWindow(hwnd, 9)      # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        return 0
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
    global _INSTANCE
    _INSTANCE = instance
    code = app.exec()
    # a stuck Discord call must never keep the process alive
    os._exit(code if isinstance(code, int) else 0)


if __name__ == "__main__":
    sys.exit(main())
