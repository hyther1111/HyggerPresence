@echo off
REM Build HyggerPresence.exe (single file, no console)
REM
REM   build.bat                      normal build -> dist\HyggerPresence.exe
REM   set HP_NO_VENV=1 ^& build.bat  build with the Python already installed
REM   set USE_UPX=1 ^& build.bat     also run UPX (smaller, but antivirus bait)
REM
REM Why buildenv: PyInstaller bundles every package it can import, used or not.
REM Building from the system Python of a dev machine (full PySide6 with Quick,
REM Qml, Pdf, 3D, WebEngine, plus cryptography and friends) adds ~13 MB to the
REM exe for nothing, so the default build installs requirements.txt into
REM buildenv\ and builds from there. That folder is disposable: delete it and
REM build.bat recreates it.
REM
REM Output: dist\HyggerPresence.exe
REM Your data files (games.json / config.json / stats.db) are NOT bundled - the
REM exe creates them next to itself on first run, so replacing the exe keeps
REM your library and playtime.

setlocal
cd /d "%~dp0"

REM Source folder to package. Bump this when the folder is renamed for a release.
set "APPSRC=HyggerPresence_2.3.2"

REM ---- find a Python 3.11 or newer -----------------------------------------
set "PY="
for %%c in ("py -3.11" "python3.11" "py -3.12" "python3.12" "py -3.13" "python3.13" "py -3" "python") do (
    if not defined PY (
        %%~c -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>nul
        if not errorlevel 1 set "PY=%%~c"
    )
)
if not defined PY (
    echo No Python 3.11 or newer found. Install it from python.org and try again.
    exit /b 1
)

echo == using %PY% ==
%PY% --version

if not exist "%APPSRC%\main.py" (
    echo Source folder "%APPSRC%" not found - edit APPSRC at the top of build.bat.
    exit /b 1
)

REM ---- build inside a clean venv so only requirements.txt gets bundled ------
if defined HP_NO_VENV (
    echo == HP_NO_VENV set: building with the system Python ^(bigger exe^) ==
    set "BUILDPY=%PY%"
) else (
    if not exist "buildenv\Scripts\python.exe" (
        echo == creating buildenv ^(first run only^) ==
        %PY% -m venv buildenv
        if errorlevel 1 goto :failed
    )
    set "BUILDPY=buildenv\Scripts\python.exe"
)

echo == installing requirements + PyInstaller into the build environment ==
echo    ^(first run downloads ~100 MB, later runs take a few seconds^)
REM Own wheel cache: pip's shared cache in %LOCALAPPDATA%\pip\cache can get into
REM a state where pip waits on it forever and the build looks frozen, so the
REM build keeps its downloads to itself.
set "PIPCACHE=%LOCALAPPDATA%\HyggerPresence-build\pip-cache"
if not exist "%PIPCACHE%" mkdir "%PIPCACHE%"
REM --timeout/--retries keep a slow mirror from looking like a frozen build, and
REM a failed attempt is retried once (the cache keeps what already downloaded).
%BUILDPY% -m pip install --disable-pip-version-check --no-input --cache-dir "%PIPCACHE%" --timeout 60 --retries 5 -r "%APPSRC%\requirements.txt" pyinstaller
if errorlevel 1 (
    echo.
    echo == pip failed - retrying once ==
    %BUILDPY% -m pip install --disable-pip-version-check --no-input --cache-dir "%PIPCACHE%" --timeout 60 --retries 5 -r "%APPSRC%\requirements.txt" pyinstaller
    if errorlevel 1 goto :failed
)

echo == cleaning previous build ==
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM ---- UPX is OFF by default -------------------------------------------
REM The Qt DLLs use Control Flow Guard, so UPX either skips them or fails on
REM them, and packed executables are a common antivirus false positive.
REM Set USE_UPX=1 to try it anyway.
set "UPXARG="
if /i "%USE_UPX%"=="1" (
    for %%u in (
        "%LOCALAPPDATA%\Microsoft\WinGet\Links\upx.exe"
        "%ProgramFiles%\upx\upx.exe"
        "%ProgramFiles(x86)%\upx\upx.exe"
        "%LOCALAPPDATA%\Programs\upx\upx.exe"
        "%USERPROFILE%\scoop\shims\upx.exe"
    ) do (
        if not defined UPXARG if exist %%~u set "UPXARG=--upx-dir %%~dpu"
    )
    if defined UPXARG (echo == UPX: %UPXARG% ==) else (echo == UPX not found ==)
    set "HP_UPX=1"
) else (
    echo == UPX disabled ^(set USE_UPX=1 to enable^) ==
)

echo == running PyInstaller ^(this takes a minute^) ==
%BUILDPY% -m PyInstaller --noconfirm --clean %UPXARG% HyggerPresence.spec
if errorlevel 1 goto :failed

if not exist "dist\HyggerPresence.exe" goto :failed

for %%f in (LICENSE README.md CHANGELOG.md) do (
    if exist "%%f" copy /y "%%f" "dist\" >nul
)

echo.
echo == done: dist\HyggerPresence.exe ==
for %%f in ("dist\HyggerPresence.exe") do (
    echo size: %%~zf bytes
    if %%~zf GTR 30000000 echo WARNING: expected about 23 MB - HP_NO_VENV or a full PySide6 build?
)
echo Copy the exe anywhere and run it; the library and settings stay in %%APPDATA%%\HyggerPresence.
goto :eof

:failed
echo.
echo BUILD FAILED - see the messages above.
exit /b 1
