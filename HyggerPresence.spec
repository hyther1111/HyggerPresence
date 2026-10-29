# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Hygger Presence.

    build.bat                 (recommended)
    pyinstaller --noconfirm HyggerPresence.spec

Produces a single dist\\HyggerPresence.exe with no console window. Qt modules
that the application never imports are excluded to keep the file small.
"""
from pathlib import Path
import os

# HP_APP_DIR lets a test build point at another copy of the sources without
# editing this file, e.g. set HP_APP_DIR=HyggerPresence_2.1.1_pretest
APP_DIR = Path(SPECPATH) / os.environ.get("HP_APP_DIR", "HyggerPresence_2.3.4")
ICON = str(APP_DIR / "icon.ico")

datas = [
    (str(APP_DIR / "hp2" / "locales"), "hp2/locales"),
    (str(APP_DIR / "icon.ico"), "."),
]

# Qt ships a lot of modules this app does not use; excluding them saves tens of
# megabytes without touching anything that is imported at runtime.
excludes = [
    "tkinter", "unittest", "pydoc_data", "test",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQml",
    "PySide6.QtQuick3D", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.Qt3DInput", "PySide6.Qt3DAnimation", "PySide6.Qt3DLogic",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtDBus",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtSensors", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtSpatialAudio", "PySide6.QtGraphs", "PySide6.QtGraphsWidgets",
    "PySide6.QtHttpServer", "PySide6.QtNetworkAuth",
]

a = Analysis(
    [str(APP_DIR / "main.py")],
    pathex=[str(APP_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=["pypresence", "psutil"],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# ---- drop files the exe never loads --------------------------------------
# PySide6 ships extras that PyInstaller bundles just because they exist:
#   opengl32sw.dll                 Qt's software OpenGL renderer. A plain
#                                  widgets app paints in software anyway, so
#                                  only GPU-less VMs and bare remote desktops
#                                  ever reach it. HP_KEEP_SOFTGL=1 keeps it.
#   qdirect2d.dll                  second Windows platform plugin; the app
#                                  uses qwindows (kept).
#   qtiff.dll                      TIFF reader; covers are jpg/png/webp.
#   libcrypto-3-x64.dll,
#   libssl-3-x64.dll               Qt's copy of OpenSSL, used only by QtNetwork
#                                  TLS. The app talks to Discord through
#                                  requests, which uses the Python copies
#                                  (libcrypto-3.dll / libssl-3.dll, kept).
# qwebp.dll and qjpeg.dll stay on purpose: a cover can be a .webp or .jpg.
import ntpath

_DROP_BINARIES = {
    "qdirect2d.dll",
    "qtiff.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
}
if os.environ.get("HP_KEEP_SOFTGL") != "1":
    _DROP_BINARIES.add("opengl32sw.dll")

_kept = []
for _entry in a.binaries:
    if ntpath.basename(_entry[0]).lower() in _DROP_BINARIES:
        print("spec: dropped", _entry[0])
    else:
        _kept.append(_entry)
a.binaries = _kept

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HyggerPresence",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=bool(os.environ.get("HP_UPX")),
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=ICON,
    version=None,
)
