@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo   Fetching repo stats and opening report in browser...
echo.

rem Prefer "python", fall back to "py -3" if not on PATH
where python >nul 2>&1
if %errorlevel%==0 (
  python scripts\traffic_stats.py --html
) else (
  py -3 scripts\traffic_stats.py --html
)

if errorlevel 1 (
  echo.
  echo   [ERROR] Python not found or script failed.
  echo   Install Python 3 and make sure it is on PATH.
  echo.
  pause
  exit /b 1
)

timeout /t 2 /nobreak >nul
echo.
echo   Done. The report should be open in your browser.
echo   If not, open: %~dp0stats\growth.html
echo.
pause
