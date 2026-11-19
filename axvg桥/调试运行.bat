@echo off
chcp 65001 >nul
rem 前台调试：能直接看到报错。先运行「停用反向桥.bat」再跑本文件，避免双实例。
set "PY="
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
"%PY%" "%~dp0axure_to_figcraft_bridge.py"
pause >nul
