@echo off
setlocal

rem Resolve the repository root from scripts\windows.
for %%I in ("%~dp0..\..") do set "CLIPYYY_ROOT=%%~fI"
set "CLIPYYY_HOME=B:\CLIPSTUDIO\clipyyy-data"
set "TEMP=%CLIPYYY_HOME%\tmp"
set "TMP=%CLIPYYY_HOME%\tmp"
set "CLIPYYY_FFMPEG=B:\CLIPSTUDIO\tools\ffmpeg-extract\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"

if not exist "%CLIPYYY_HOME%\logs" mkdir "%CLIPYYY_HOME%\logs"
if not exist "%CLIPYYY_HOME%\tmp" mkdir "%CLIPYYY_HOME%\tmp"

if not exist "%CLIPYYY_ROOT%\.venv\Scripts\python.exe" (
  echo Clipyyy virtual environment not found at "%CLIPYYY_ROOT%\.venv". > "%CLIPYYY_HOME%\logs\launcher-error.log"
  exit /b 1
)

cd /d "%CLIPYYY_ROOT%"
"%CLIPYYY_ROOT%\.venv\Scripts\python.exe" -m clipyyy.cli serve --host 127.0.0.1 --port 8000 >> "%CLIPYYY_HOME%\logs\server.log" 2>&1
