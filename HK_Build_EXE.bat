@echo off
setlocal EnableExtensions
title Build HK.exe - Control Panel
cd /d "%~dp0"

set "PYEXE="
where py.exe >nul 2>nul && set "PYEXE=py"
if not defined PYEXE where python.exe >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  echo ERROR: Python not found. Install Python 3.12 from python.org first.
  pause
  exit /b 1
)

set "ENVDIR=%~dp0HK_BuildEnv"
if not exist "%ENVDIR%\Scripts\python.exe" %PYEXE% -m venv "%ENVDIR%"

echo Installing build dependencies (OpenCV, NumPy, PyInstaller)...
"%ENVDIR%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet opencv-python numpy pyinstaller
if errorlevel 1 (
  echo ERROR: Dependency install failed. Check your internet connection.
  pause
  exit /b 2
)

echo Building standalone HK.exe package...
"%ENVDIR%\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name HK HK_App.py
if errorlevel 1 (
  echo ERROR: Build failed.
  pause
  exit /b 3
)

if not exist "HK_Portable" mkdir "HK_Portable"
if exist "dist\HK.exe" copy /y "dist\HK.exe" "HK_Portable\HK.exe" >nul
if exist "join_button.png" copy /y "join_button.png" "HK_Portable\" >nul
if exist "march_screen.png" copy /y "march_screen.png" "HK_Portable\" >nul

echo.
echo ========================================================
echo SUCCESS! Your standalone executable is ready.
echo Location: %~dp5HK_Portable\HK.exe (or inside \HK_Portable\)
echo ========================================================
pause
exit /b 0