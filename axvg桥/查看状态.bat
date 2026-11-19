@echo off
chcp 65001 >nul
setlocal
set "PY="
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
  echo [错误] 未找到 python.exe
  pause >nul
  exit /b 1
)
"%PY%" "%~dp0bridge_ctl.py" status
echo.
pause >nul
