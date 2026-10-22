@echo off
REM Build HyggerPresence.exe (single file, no console)
REM
REM   build.bat
REM
REM Output: dist\HyggerPresence.exe
REM Your data files (games.json / config.json / stats.db) are NOT bundled - the
REM exe creates them next to itself on first run, so replacing the exe keeps
REM your library and playtime.

setlocal
cd /d "%~dp0"

REM ---- pick a Python 3 that already has the dependencies -------------------
set "PY="
set "FALLBACK="

for %%c in ("py -3.11" "python3.11" "py -3.12" "python3.12" "py -3.13" "python3.13" "py -3" "python") do (
    if not defined PY (
        %%~c -c "import sys; raise SystemExit(0 if sys.version_info[0]==3 else 1)" >nul 2>nul
        if not errorlevel 1 (
            if not defined FALLBACK set "FALLBACK=%%~c"
            %%~c -c "import PySide6, pypresence, psutil, requests, PIL" >nul 2>nul
            if not errorlevel 1 set "PY=%%~c"
        )
    )
)

if not defined PY set "PY=%FALLBACK%"
if not defined PY (
    echo No Python 3 found. Install Python 3.11+ and try again.
    exit /b 1
)

echo == using %PY% ==
%PY% --version

echo == checking dependencies ==
%PY% -c "import PySide6, pypresence, psutil, requests, PIL" 2>nul
if errorlevel 1 (
    echo Installing requirements...
    %PY% -m pip install -r "HyggerPresence_2.2.1\requirements.txt"
    if errorlevel 1 goto :failed
)

%PY% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    %PY% -m pip install pyinstaller
    if errorlevel 1 goto :failed
)

echo == cleaning previous build ==
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM ---- UPX is OFF by default -------------------------------------------
REM PyInstaller skips the Qt DLLs (they use Control Flow Guard) so UPX only
REM saves a few hundred bytes, while packed executables are a common false
REM positive for antivirus products. Set USE_UPX=1 to enable it anyway.
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
) else (
    echo == UPX disabled ^(set USE_UPX=1 to enable^) ==
)

echo == running PyInstaller ^(this takes a minute^) ==
%PY% -m PyInstaller --noconfirm --clean %UPXARG% HyggerPresence.spec
if errorlevel 1 goto :failed

if not exist "dist\HyggerPresence.exe" goto :failed

for %%f in (LICENSE README.md CHANGELOG.md) do (
    if exist "%%f" copy /y "%%f" "dist\" >nul
)

echo.
echo == done: dist\HyggerPresence.exe ==
for %%f in ("dist\HyggerPresence.exe") do echo size: %%~zf bytes
echo Copy the exe anywhere and run it; data files are created next to it.
goto :eof

:failed
echo.
echo BUILD FAILED - see the messages above.
exit /b 1
