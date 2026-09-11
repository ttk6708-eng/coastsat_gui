@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set VENV_DIR=venv
set GDAL_RELEASE=v2026.8.20
set GDAL_VERSION=3.13.3
set PYEXE=

rem --- Find a real, working Python (avoid the Microsoft Store "python.exe" alias stub) ---
python -c "print(1)" >nul 2>nul
if errorlevel 1 goto :try_py_launcher
set PYEXE=python
goto :found_python

:try_py_launcher
py -3 -c "print(1)" >nul 2>nul
if errorlevel 1 goto :try_fallback_path
set PYEXE=py -3
goto :found_python

:try_fallback_path
if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PYEXE=%LOCALAPPDATA%\Python\bin\python.exe"
if defined PYEXE goto :found_python

for /d %%d in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if exist "%%d\python.exe" set "PYEXE=%%d\python.exe"
)
if defined PYEXE goto :found_python

echo [ERROR] Could not find a working Python on this PC.
echo If you just installed Python, this may be the Microsoft Store "python.exe"
echo shortcut interfering with it - see:
echo Settings ^> Apps ^> Advanced app settings ^> App execution aliases, turn "python.exe"/"py.exe" OFF.
echo Or install Python fresh from https://www.python.org/downloads/
echo Check "Add python.exe to PATH" during install, then run this file again.
pause
exit /b 1

:found_python
echo Using Python: !PYEXE!

if exist "%VENV_DIR%\Scripts\python.exe" goto :venv_ready
echo [1/4] Creating a virtual environment. This only happens once.
!PYEXE! -m venv %VENV_DIR%
if errorlevel 1 goto :error

:venv_ready
set PY=%VENV_DIR%\Scripts\python.exe

for /f "delims=" %%v in ('%PY% -c "import sys;print(f'cp{sys.version_info[0]}{sys.version_info[1]}')"') do set PYTAG=%%v

if exist "%VENV_DIR%\Scripts\gdal_installed.flag" goto :gdal_ready
echo [2/4] Installing GDAL for Python !PYTAG! from https://github.com/cgohlke/geospatial-wheels ...
%PY% -m pip install --upgrade pip >nul
%PY% -m pip install "https://github.com/cgohlke/geospatial-wheels/releases/download/%GDAL_RELEASE%/gdal-%GDAL_VERSION%-!PYTAG!-!PYTAG!-win_amd64.whl"
if errorlevel 1 goto :gdal_failed
echo done > "%VENV_DIR%\Scripts\gdal_installed.flag"
goto :gdal_ready

:gdal_failed
echo.
echo Could not install GDAL for your Python version, !PYTAG!.
echo This script currently supports Python 3.12 / 3.13 / 3.14 / 3.15, 64-bit.
echo Please install one of those from https://www.python.org/downloads/ and try again.
echo Alternatively, see README.md for the conda-based manual setup.
goto :error

:gdal_ready
echo [3/4] Installing the remaining Python packages. This can take a few minutes the first time.
%PY% -m pip install -r requirements-local.txt
if errorlevel 1 goto :error

rem --- Skip Streamlit's first-run "enter your email" prompt (it reads stdin and would look like a freeze) ---
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    echo [general] > "%USERPROFILE%\.streamlit\credentials.toml"
    echo email = "" >> "%USERPROFILE%\.streamlit\credentials.toml"
)

echo [4/4] Starting CoastSat GUI. Your browser will open automatically in a moment.
echo Close this window or press Ctrl+C to stop the app.
echo.
%PY% -m streamlit run app.py

pause
exit /b 0

:error
echo.
echo Something went wrong. Please check the messages above.
pause
exit /b 1
