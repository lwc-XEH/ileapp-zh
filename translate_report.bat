@echo off
rem ---------------------------------------------------------------
rem  iLEAPP report Chinese localiser - drag and drop launcher
rem  Usage: drag an iLEAPP report folder onto this file.
rem  (Kept ASCII-only on purpose: cmd.exe reads .bat using the
rem   console codepage, so non-ASCII content can be garbled.)
rem ---------------------------------------------------------------
setlocal
chcp 65001 >nul

if "%~1"=="" (
    echo.
    echo   Usage: drag an iLEAPP report folder onto this .bat file.
    echo.
    echo   Or run from a terminal:
    echo     python "%~dp0ileapp_zh.py" "D:\path\to\iLEAPP_Output_..."
    echo.
    pause
    exit /b 1
)

set PY=
where python >nul 2>nul && set PY=python
if "%PY%"=="" (where py >nul 2>nul && set PY=py)
if "%PY%"=="" (
    echo   Python not found on PATH. Install Python 3.10+ first.
    pause
    exit /b 1
)

%PY% "%~dp0ileapp_zh.py" "%~1" --report
echo.
echo   Done. The translated report is in the folder ending with _zh
pause
