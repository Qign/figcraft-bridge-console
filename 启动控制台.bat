@echo off
rem =====================================================================
rem  FigCraft 双向桥控制台 —— 开发/脚本版启动器（P1~P4 阶段使用）
rem  正式发布版将替换为免安装的单文件 exe，此处仅供开发调试与先行使用。
rem =====================================================================
setlocal
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 pythonw.exe，请先安装 Python 3.9+ 并加入 PATH。
    pause
    exit /b 1
)

start "" pythonw.exe "%~dp0src\app.py"
exit /b 0
