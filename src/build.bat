@echo off
chcp 65001 >nul
rem ============================================================
rem  FigCraft 双向桥控制台 · 打包脚本（PyInstaller onefile）
rem  产物：..\FigCraft桥控制台.exe（绿色单文件，同目录生成 config.json / logs）
rem  用法：双击本文件，或用 py -3.13 环境执行：
rem        pyinstaller -m PyInstaller ... （见下方命令行）
rem ============================================================
setlocal
cd /d "%~dp0"

set PYEXE=C:\Python313\python.exe
if not exist "%PYEXE%" set PYEXE=python

"%PYEXE%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "FigCraftBridgeConsole" ^
  --icon "%~dp0assets\app.ico" ^
  --add-data "%~dp0assets;assets" ^
  --paths "%~dp0" ^
  --hidden-import core_f2a ^
  --hidden-import core_a2f ^
  --distpath "%~dp0.." ^
  --workpath "%~dp0..\_build\work" ^
  --specpath "%~dp0..\_build" ^
  "%~dp0app.py"

if exist "%~dp0..\FigCraftBridgeConsole.exe" ren "%~dp0..\FigCraftBridgeConsole.exe" "FigCraft桥控制台.exe"

echo.
if exist "%~dp0..\FigCraft桥控制台.exe" (
  echo [OK] 打包完成: %~dp0..\FigCraft桥控制台.exe
) else (
  echo [FAIL] 打包失败，请检查上方输出
)
endlocal
pause
