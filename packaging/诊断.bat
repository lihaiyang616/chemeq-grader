@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0chemeq.exe" (
  echo 找不到 chemeq.exe。
  pause
  exit /b 1
)
echo 正在检查环境，请稍候...
"%~dp0chemeq.exe" doctor --net > "%~dp0诊断结果.txt" 2>&1
type "%~dp0诊断结果.txt"
echo.
echo 诊断结果已保存到：%~dp0诊断结果.txt
pause
