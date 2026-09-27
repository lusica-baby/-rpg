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

set "PY=C:\Users\lenovo\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

start "" /min "%PY%" "%~dp0tools\serve_game.py" 8321
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8321/"
