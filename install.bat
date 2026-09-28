@echo off
rem 收藏夹遗忘曲线 . B站版 一键安装（双击即可）
setlocal
chcp 65001 >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "EC=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %EC%
