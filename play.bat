@echo off
rem ---------------------------------------------------------------
rem  Double-click to play "Cuzhi" in your default browser.
rem  Starts a tiny local web server for CuzhiDemo\ and opens it.
rem
rem  Why a server instead of just opening index.html:
rem  RPG Maker MZ loads data/*.json and images over XHR. Under the
rem  file:// scheme those requests are blocked by CORS and the game
rem  hangs on the loading screen.
rem
rem  Close the minimised "Cuzhi - local playtest" window to stop it.
rem ---------------------------------------------------------------
title Cuzhi - local playtest
cd /d "%~dp0"

rem Pick whichever Python this machine actually has, in order: PATH -> py launcher
rem -> the portable env on the machine this project was built on. Anyone who clones
rem the repo gets the first branch; the hardcoded path is only a last resort.
rem (Keep this file ASCII-only: cmd.exe reads .bat as the OEM codepage, so non-ASCII
rem  text here turns into mojibake on other people's machines.)
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY set "PY=C:\Users\lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

rem Probe by running it: a Store-alias "python" exists but only opens the Store.
"%PY%" --version >nul 2>nul || (
  echo [ERROR] No usable Python found. Install Python 3, add it to PATH, retry.
  pause
  exit /b 1
)

start "" /min "%PY%" "%~dp0tools\serve_game.py" 8321
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8321/"
