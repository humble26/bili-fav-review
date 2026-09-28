#Requires -Version 5.1
# 打包发布 zip：排除 .venv / dist / 缓存，产物在 dist/BiliFavReview-v*.zip
# 对方拿到 zip 解压后双击 install.bat 即可完成安装（需已装 Python 3.11+）。
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

$verLine = Select-String -Path (Join-Path $Root "bili_fav_review\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $verLine) { throw "无法从 __init__.py 读取版本号" }
$ver = $verLine.Matches[0].Groups[1].Value

$dest = Join-Path $Root "dist"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
$stage = Join-Path $env:TEMP ("BiliFavRelease_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $stage | Out-Null

robocopy $Root $stage /E /NFL /NDL /NJH /NJS /XD .venv __pycache__ dist .git .pytest_cache /XF *.pyc | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy 失败 code=$LASTEXITCODE" }

$zip = Join-Path $dest ("BiliFavReview-v" + $ver + ".zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Remove-Item -Recurse -Force $stage

Write-Host " [OK] 发布包: $zip" -ForegroundColor Green
Write-Host "      解压后运行 install.bat 即可安装（需 Python 3.11+）"
