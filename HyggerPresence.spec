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
APP_DIR = Path(SPECPATH) / os.environ.get("HP_APP_DIR", "HyggerPresence_2.3.3")
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
    # QtNetwork is only pulled in by PySide6/__init__ for an OpenSSL folder the
    # wheels do not have; the app never uses it (HTTP goes through WinHTTP).
    "PySide6.QtNetwork", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtXml", "PySide6.QtConcurrent",
]

# Python modules nothing in the app reaches. HTTP goes through Windows' WinHTTP
# (hp2/net.py), so the requests stack and Python's OpenSSL are gone; the rest
# is only imported inside functions the app never calls (help(), tarballs,
# process pools, ...) or by setuptools, which PyInstaller picks up just because
# it is installed in the build environment.
excludes += [
    "ssl", "_ssl", "_hashlib",
    "requests", "urllib3", "certifi", "idna", "charset_normalizer", "PIL",
    "setuptools", "pkg_resources", "_distutils_hack", "distutils", "packaging",
    "multiprocessing", "pydoc", "doctest", "pdb",
    "bz2", "_bz2", "lzma", "_lzma", "tarfile",
    "decimal", "_decimal", "_pydecimal", "fractions", "statistics",
    "concurrent.futures.process", "asyncio.unix_events",
    "sqlite3.__main__", "code", "codeop", "py_compile", "getopt",
    "quopri", "stringprep", "tracemalloc",
    # NOT argparse/gettext: shiboken's embedded signature module imports
    # argparse at load time, and without it PySide6 aborts on start.
    # pure-Python fallbacks for modules built into python3xx.dll
    "_pydatetime", "_py_abc", "importlib._bootstrap",
    "importlib._bootstrap_external",
    # PyInstaller's xml hook adds xml.sax, whose saxutils imports urllib.request,
    # which drags in http, email, ftplib and mimetypes. ElementTree (the only
    # XML the app parses: LEConfig.xml) talks to pyexpat directly.
    "xml.sax", "xml.dom", "urllib.request", "http", "email", "ftplib",
    "mimetypes", "importlib.metadata",
    # only needed for non-ASCII host names (WinHTTP resolves those itself),
    # named escapes in a regex and source-line carets in tracebacks
    "unicodedata",
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
    # -OO: no docstrings or asserts in the bytecode. Nothing in the app (or in
    # PySide6, pypresence, psutil) reads a docstring back.
    optimize=2,
)

# ---- drop files the exe never loads --------------------------------------
# PySide6 ships extras that PyInstaller bundles just because they exist:
#   opengl32sw.dll                 Qt's software OpenGL renderer. A plain
#                                  widgets app paints in software anyway, so
#                                  only GPU-less VMs and bare remote desktops
#                                  ever reach it. HP_KEEP_SOFTGL=1 keeps it.
#   qdirect2d, qminimal,
#   qoffscreen                     other platform plugins; the app uses
#                                  qwindows (kept).
#   qtiff, qicns, qtga, qwbmp,
#   qsvg, qsvgicon, Qt6Svg.dll     image formats nothing here reads.
#   Qt6Network.dll, tls\,
#   networkinformation\, generic\  QtNetwork and the plugins that need it (TLS
#                                  backends, network status, TUIO touch over
#                                  UDP). HTTP goes through WinHTTP instead.
#   libcrypto-3-x64.dll,
#   libssl-3-x64.dll               Qt's copy of OpenSSL, for QtNetwork TLS.
#   translations\*.qm              Qt's own strings in ~50 languages (2 MB);
#                                  i18n.py only loads qtbase_zh_CN / _zh_TW.
# qjpeg, qwebp, qgif and qico stay on purpose: a cover can be a .jpg or .webp,
# a custom image URL a .gif, and the window/tray icon is icon.ico.
#
# The VC++ runtime comes three times: Python's VCRUNTIME140(_1).dll at the
# root, plus a copy in PySide6\ and one in shiboken6\. Windows loads a DLL name
# once per process and python312.dll pulls in the root copy first, so the
# package copies are never used. MSVCP140.dll (C++ runtime, Qt only) goes to
# the root once instead of twice; the root is searched before System32.
import ntpath

_DROP_BINARIES = {
    "qdirect2d.dll", "qminimal.dll", "qoffscreen.dll",
    "qtiff.dll", "qicns.dll", "qtga.dll", "qwbmp.dll",
    "qsvg.dll", "qsvgicon.dll", "qt6svg.dll",
    "qt6network.dll", "qopensslbackend.dll", "qschannelbackend.dll",
    "qcertonlybackend.dll", "qnetworklistmanager.dll", "qtuiotouchplugin.dll",
    "libcrypto-3-x64.dll", "libssl-3-x64.dll",
}
if os.environ.get("HP_KEEP_SOFTGL") != "1":
    _DROP_BINARIES.add("opengl32sw.dll")
_KEEP_TRANSLATIONS = {"qtbase_zh_cn.qm", "qtbase_zh_tw.qm"}
_VC_RUNTIME = {"vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"}


def _trim(entries):
    root = {ntpath.basename(e[0]).lower() for e in entries if not ntpath.dirname(e[0])}
    kept = []
    for entry in entries:
        dest = entry[0]
        name = ntpath.basename(dest).lower()
        folder = ntpath.dirname(dest).lower()
        if name in _DROP_BINARIES:
            print("spec: dropped", dest)
            continue
        if name.endswith(".qm") and name not in _KEEP_TRANSLATIONS:
            continue                    # ~100 of them, dropped quietly
        if folder in ("pyside6", "shiboken6") and name in _VC_RUNTIME:
            if name in root:
                print("spec: dropped", dest, "(same DLL at the root)")
                continue
            root.add(name)
            print("spec: moved", dest, "to the root")
            entry = (ntpath.basename(dest),) + tuple(entry[1:])
        kept.append(entry)
    return kept


a.binaries = _trim(a.binaries)
a.datas = _trim(a.datas)

# The PYZ (all the bytecode) is compressed at zlib level 6 by default, the rest
# of the exe at 9. Level 9 for the PYZ too; PYINSTALLER_ZLIB_COMPRESSION_LEVEL
# still overrides both.
if "PYINSTALLER_ZLIB_COMPRESSION_LEVEL" not in os.environ:
    from PyInstaller.archive.writers import ZlibArchiveWriter
    ZlibArchiveWriter._COMPRESSION_LEVEL = 9

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    # run the interpreter with -OO as well, matching optimize=2 above
    [("O", None, "OPTION"), ("O", None, "OPTION")],
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
