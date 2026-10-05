#Requires -Version 5.1
# 打包独立 exe：dist\收藏夹遗忘曲线.exe（PyInstaller onefile + windowed）
# 双击无参数 → 图形界面；带子命令（如 due --notify）→ CLI（计划任务继续可用）
# 安装分发请运行 install.bat；文件名与版本号资源写在 assets/build_version_file.py
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

# ---- 版本号（单一来源 bili_fav_review/__init__.py） ----
$verLine = Select-String -Path (Join-Path $Root "bili_fav_review\__init__.py") -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $verLine) { throw "无法从 __init__.py 读取版本号" }
$ver = $verLine.Matches[0].Groups[1].Value
Write-Host "==> 打包 收藏夹遗忘曲线 v$ver" -ForegroundColor Cyan

# ---- 虚拟环境与 PyInstaller ----
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "未找到 .venv\Scripts\python.exe；请先创建虚拟环境并安装依赖" }
& $py -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host " [..] 首次打包：安装 PyInstaller ..."
    & $py -m pip install --quiet --disable-pip-version-check pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 安装失败（检查网络/镜像后重试）" }
}

# ---- 版本资源文件 ----
$buildDir = Join-Path $Root "build\exe"
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$versionFile = Join-Path $buildDir "version_info.txt"
& $py (Join-Path $Root "assets\build_version_file.py") $ver $versionFile
if ($LASTEXITCODE -ne 0) { throw "生成版本资源文件失败" }

# ---- PyInstaller 构建（全部绝对路径，避免依赖工作目录） ----
Write-Host " [..] PyInstaller 构建中（首次较慢，约 1-3 分钟）..."
$pyArgs = @(
    '-m', 'PyInstaller', '--noconfirm', '--clean',
    '--onefile', '--windowed',
    '--name', '收藏夹遗忘曲线',
    '--icon', (Join-Path $Root 'bili_fav_review\webui\static\app.ico'),
    '--add-data', ((Join-Path $Root 'bili_fav_review\webui\static') + ';bili_fav_review\webui\static'),
    '--version-file', $versionFile,
    '--distpath', (Join-Path $Root 'dist'),
    '--workpath', (Join-Path $Root 'build\exe\work'),
    '--specpath', (Join-Path $Root 'build\exe'),
    (Join-Path $Root 'exe_entry.py')
)
& $py @pyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败，退出码 $LASTEXITCODE" }

$exe = Join-Path $Root "dist\收藏夹遗忘曲线.exe"
if (-not (Test-Path $exe)) { throw "未找到产物: $exe" }
$size = [math]::Round((Get-Item $exe).Length / 1MB, 2)
$fileVer = (Get-Item $exe).VersionInfo.FileVersion

Write-Host ""
Write-Host " [OK] 产物: $exe（$size MB，FileVersion=$fileVer）" -ForegroundColor Green
Write-Host "      双击 = 图形界面；带子命令 = CLI（如: `"收藏夹遗忘曲线.exe`" sync）"
Write-Host "      安装到本机请双击 install.bat（建快捷方式 / 每日提醒 / 卸载入口）"
