@echo off
rem NOTE: keep this file pure-ASCII. cmd.exe reads batch files as GBK unless a
rem BOM is present, and "chcp 65001" does not affect already-buffered lines, so
rem any CJK text here turns into "not recognized as an internal or external
rem command" errors. The generated HTML report is UTF-8 and can hold Chinese.
cd /d "%~dp0"

echo.
echo   Fetching repo stats, then opening the report...
echo.

set "PYEXE="

rem --- 1) python on PATH ---
where python >nul 2>&1 && set "PYEXE=python"
if defined PYEXE goto run

rem --- 2) WorkBuddy bundled python (any version) ---
for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
  if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
)
if defined PYEXE goto run

rem --- 3) known local venv (last resort on this machine) ---
if exist "D:\DZZZ-OD\.venv\Scripts\python.exe" set "PYEXE=D:\DZZZ-OD\.venv\Scripts\python.exe"
if defined PYEXE goto run

rem --- 4) py launcher ---
where py >nul 2>&1 && goto run_py

echo   [ERROR] Python not found.
echo   Install Python 3 (check "Add python to PATH"), or edit this
echo   .bat and set PYEXE to your python.exe full path.
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
echo   Opening report: %~dp0stats\growth.html
echo.
rem Use Windows "start" here: Python's webbrowser.open() can report success
rem without actually raising a window on some setups.
start "" "%~dp0stats\growth.html"
echo   If nothing opened, open that file manually.
echo.
pause
