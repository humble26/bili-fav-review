@echo off
chcp 65001 >nul 2>nul
rem 打包独立 exe 到 dist\（双击即可）
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1" %*
set "EC=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %EC%
