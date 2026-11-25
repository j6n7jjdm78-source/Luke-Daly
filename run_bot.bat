@echo off
rem Restarts the paper bot after a crash. Exit code 2 = halted for safety: do NOT restart.
cd /d %~dp0
:loop
py gold\paper_bot.py
if %errorlevel%==2 (
  echo Bot HALTED for safety. Read gold\alerts.log and incidents.md before restarting.
  pause
  exit /b 2
)
timeout /t 10 /nobreak >nul
goto loop
