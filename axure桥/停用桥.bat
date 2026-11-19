@echo off
chcp 65001 >nul
title 停用转换桥
set "PY="
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY (
    for /f "delims=" %%p in ('where python 2^>nul') do if not defined PY set "PY=%%p"
)
if not defined PY (
    echo [错误] 未找到 python.exe
    echo 请确认已安装 Python，或把 Python 目录加入 PATH
    pause >nul
    exit /b 1
)
"%PY%" "%~dp0bridge_ctl.py" stop
echo.
echo 按任意键关闭本窗口...
pause >nul
exit /b 0
