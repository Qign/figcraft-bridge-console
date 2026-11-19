@echo off
chcp 65001 >nul
setlocal
set "PY="
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
  echo [错误] 未找到 python.exe，请先安装 Python 3 或把路径写进本文件。
  pause >nul
  exit /b 1
)
"%PY%" "%~dp0bridge_ctl.py" start
echo.
echo 按任意键关闭本窗口（桥在后台继续运行）
pause >nul
