@echo off
rem ---------------------------------------------------------------
rem  iLEAPP Chinese Workbench - launcher
rem
rem  Kept ASCII-only on purpose: cmd.exe reads .bat using the console
rem  codepage, so non-ASCII content would be garbled. Line endings
rem  must be CRLF for the same reason.
rem
rem  Why not simply "start pythonw workbench.py":
rem  a machine usually carries several Pythons (venv, portable,
rem  embedded, sandbox) and some of them ship without tkinter.
rem  pythonw has no console, so an ImportError there is completely
rem  silent - double-clicking the launcher just looks like nothing
rem  happened. So probe every candidate first and keep the first one
rem  that can actually "import tkinter".
rem ---------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PY="
for %%C in (pythonw python) do (
    if not defined PY (
        for /f "delims=" %%P in ('where %%C 2^>nul') do (
            if not defined PY (
                "%%P" -c "import tkinter" >nul 2>nul
                if !ERRORLEVEL! EQU 0 set "PY=%%P"
            )
        )
    )
)

if not defined PY (
    echo.
    echo   No Python with tkinter found on PATH.
    echo.
    echo   This tool needs Python 3.10+ with tkinter.  The installer from
    echo   python.org includes it; some minimal, embedded or virtual
    echo   environment builds do not.
    echo.
    echo   Tried every pythonw / python on PATH.  If you know a good one,
    echo   start the workbench with it directly:
    echo.
    echo       "C:\path\to\pythonw.exe" "%~dp0workbench.py"
    echo.
    pause
    exit /b 1
)

start "" "%PY%" "%~dp0workbench.py"
exit /b 0
