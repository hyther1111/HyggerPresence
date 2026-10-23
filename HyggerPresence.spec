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
APP_DIR = Path(SPECPATH) / os.environ.get("HP_APP_DIR", "HyggerPresence_2.3.0")
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=ICON,
    version=None,
)
