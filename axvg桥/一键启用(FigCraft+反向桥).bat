@echo off
chcp 65001 >nul
setlocal
rem 一键：确保 FigCraft 带控制端口启动 + 启用反向桥
set "PY="
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
  echo [错误] 未找到 python.exe
  pause >nul
  exit /b 1
)

"%PY%" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if (s.connect_ex(('127.0.0.1',47900))==0) else 1)"
if not errorlevel 1 goto STARTBRIDGE

tasklist /fi "imagename eq figcraft.exe" 2>nul | find /i "figcraft.exe" >nul
if not errorlevel 1 (
  echo [注意] FigCraft 正在运行，但没有开控制端口 47900。
  echo        反向桥需要它带端口启动。请先保存并关闭当前 FigCraft，
  echo        再双击 D:\AI\FigCraft\axure桥\启动FigCraft(带转换桥).lnk 打开后，重新运行本文件。
  echo.
  pause >nul
  exit /b 1
)

echo 正在启动 FigCraft（带控制端口 47900）...
start "" "D:\Program Files\ArtCraft\FigCraft\figcraft.exe" --control 47900
ping -n 6 127.0.0.1 >nul

:STARTBRIDGE
"%PY%" "%~dp0bridge_ctl.py" start
echo.
echo 按任意键关闭本窗口（桥在后台继续运行）
pause >nul
