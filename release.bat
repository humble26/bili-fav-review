@echo off
rem 打包发布 zip 到 dist\（双击即可）
setlocal
chcp 65001 >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make_release.ps1" %*
set "EC=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %EC%
