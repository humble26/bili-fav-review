#Requires -Version 5.1
# 生成发布 zip：exe + 安装/卸载脚本 + 文档，产物在 dist/BiliFavReview-v*.zip
# 前置：先运行 build_exe.bat 产出 dist\收藏夹遗忘曲线.exe
# 对方拿到 zip 解压后双击 install.bat 即可完成安装（无需 Python）
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

$verLine = Select-String -Path (Join-Path $Root "bili_fav_review\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $verLine) { throw "无法从 __init__.py 读取版本号" }
$ver = $verLine.Matches[0].Groups[1].Value

$exe = Join-Path $Root "dist\收藏夹遗忘曲线.exe"
if (-not (Test-Path $exe)) { throw "未找到 dist\收藏夹遗忘曲线.exe —— 请先运行 build_exe.bat 打包" }

$dest = Join-Path $Root "dist"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$stage = Join-Path $env:TEMP ("BiliFavRelease_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# 发布内容（解压后双击 install.bat）
Copy-Item $exe $stage
foreach ($f in @("install.bat", "install.ps1", "uninstall.bat", "uninstall.ps1",
                 "config.example.toml", "README.md", "使用指南.md", "LICENSE")) {
    $src = Join-Path $Root $f
    if (Test-Path $src) { Copy-Item $src $stage }
}

$zip = Join-Path $dest ("BiliFavReview-v" + $ver + ".zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item -Recurse -Force $stage

Write-Host " [OK] 发布包: $zip" -ForegroundColor Green
Write-Host "      解压后双击 install.bat 安装（无需 Python）"
