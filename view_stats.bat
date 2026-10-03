@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo   Fetching repo stats and opening report in browser...
echo.

set "PYEXE="

rem --- 1) python on PATH (standard install) ---
where python >nul 2>&1 && set "PYEXE=python"
if defined PYEXE goto run

rem --- 2) WorkBuddy bundled pythons: %USERPROFILE%\.workbuddy\binaries\python\versions\<ver>\python.exe ---
for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
  if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
)
if defined PYEXE goto run

rem --- 3) known local venv (last resort on this machine) ---
if exist "D:\DZZZ-OD\.venv\Scripts\python.exe" set "PYEXE=D:\DZZZ-OD\.venv\Scripts\python.exe"
if defined PYEXE goto run

rem --- 4) py launcher as generic fallback ---
where py >nul 2>&1 && goto run_py

echo   [ERROR] Python not found.
echo   Install Python 3 (check "Add python to PATH" during install),
echo   or edit this .bat and set PYEXE to your python.exe full path.
echo.
pause
exit /b 1

:run
"%PYEXE%" scripts\traffic_stats.py --html
if errorlevel 1 goto fail
goto done

:run_py
py -3 scripts\traffic_stats.py --html
if errorlevel 1 goto fail
goto done

:fail
echo.
echo   [ERROR] Script failed. See messages above.
echo.
pause
exit /b 1

:done
echo.
echo   Done. The report should be open in your browser.
echo   If not, open: %~dp0stats\growth.html
echo.
pause
