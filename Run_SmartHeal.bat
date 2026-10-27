@echo off
setlocal
cd /d "%~dp0"
title SmartHeal - Self-Healing Student Portal

py -3 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3 was not found. Install Python from https://www.python.org/downloads/ and select Add Python to PATH.
  pause
  exit /b 1
)

if exist requirements.txt (
  py -3 -m pip install -r requirements.txt
) else (
  py -3 -m pip install -r requirements.txt
)
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

echo Starting SmartHeal with automatic process watchdog...
py -3 watchdog.py
pause
