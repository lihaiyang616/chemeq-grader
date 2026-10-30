@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0chemeq.exe" (
  echo 找不到 chemeq.exe，请确认压缩包已完整解压。
  pause
  exit /b 1
)
echo 正在启动 ChemEq 智批...
echo 浏览器会自动打开 http://127.0.0.1:8765
echo 关闭本窗口即停止服务。
echo.
"%~dp0chemeq.exe" serve --open
pause
