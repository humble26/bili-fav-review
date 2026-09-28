#Requires -Version 5.1
# 收藏夹遗忘曲线 . B站版 —— Windows 一键安装
#
# 用法（双击 install.bat 亦可）:
#   powershell -File install.ps1                    交互安装（询问是否建每日提醒任务）
#   powershell -File install.ps1 -NoTask            跳过计划任务
#   powershell -File install.ps1 -TaskTime 21:00    自定义提醒时间
#   powershell -File install.ps1 -Portable D:\BFR   便携安装（不改 PATH、不建任务、不动注册表）
param(
    [switch]$NoTask,
    [string]$TaskTime = "09:30",
    [switch]$Force,
    [string]$Portable = ""
)

$ErrorActionPreference = "Stop"
$Root     = $PSScriptRoot
$AppName  = "BiliFavReview"
$TaskName = "BiliFavReview"
$DataDir  = Join-Path $env:USERPROFILE ".bili_fav_review"

if ($Portable) {
    $InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Portable)
} else {
    $InstallDir = Join-Path $env:LOCALAPPDATA $AppName
}
$VenvDir = Join-Path $InstallDir "venv"
$BinDir  = Join-Path $InstallDir "bin"
$Shim    = Join-Path $BinDir "bili-review.cmd"

function Step($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)    { Write-Host " [OK] $m" -ForegroundColor Green }
function Warn2($m) { Write-Host " [!!] $m" -ForegroundColor Yellow }
function Die($m)   { Write-Host " [XX] $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "===== 收藏夹遗忘曲线 . B站版 安装程序 =====" -ForegroundColor Magenta
Write-Host "安装目录: $InstallDir"
Write-Host ""

# ---- 1. 查找 Python >= 3.11 ----
Step "查找 Python (>=3.11)"
$pyCmd = $null; $pyPre = @(); $pyVer = $null
foreach ($c in @(@("py", "-3"), @("python"), @("python3"))) {
    $exe = $c[0]
    $pre = @(); if ($c.Count -gt 1) { $pre = @($c[1]) }
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $out = & $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
    try { $v = [version](($out | Select-Object -Last 1).Trim()) } catch { continue }
    if ($v -ge [version]"3.11") { $pyCmd = $exe; $pyPre = $pre; $pyVer = $v; break }
}
if (-not $pyCmd) { Die "未找到 Python 3.11+，请先安装: https://www.python.org/downloads/" }
Ok "使用 $pyCmd (Python $pyVer)"

# ---- 2. 独立虚拟环境 ----
Step "准备独立运行环境"
$venvPython = Join-Path $VenvDir "Scripts\python.exe"
if ((-not (Test-Path $venvPython)) -or $Force) {
    & $pyCmd @pyPre -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Die "虚拟环境创建失败" }
}
Ok "虚拟环境: $VenvDir"

# ---- 3. 安装程序包与依赖 ----
Step "安装程序与依赖（首次需要联网）"
& $venvPython -m pip install --quiet --disable-pip-version-check --upgrade pip
& $venvPython -m pip install --quiet --disable-pip-version-check $Root
if ($LASTEXITCODE -ne 0) { Die "依赖安装失败，请检查网络后重试" }
& $venvPython -c "import bili_fav_review; print('     bili-fav-review ' + bili_fav_review.__version__)"
Ok "程序安装完成"

# ---- 4. 命令入口 ----
Step "创建命令入口 bili-review"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$shimBody = "@echo off`r`n`"$VenvDir\Scripts\bili-review.exe`" %*`r`n"
Set-Content -Path $Shim -Value $shimBody -Encoding Default
Ok "$Shim"
$GuiShim = Join-Path $BinDir "bili-review-gui.cmd"
$guiShimBody = "@echo off`r`nstart `"`" `"$VenvDir\Scripts\pythonw.exe`" -m bili_fav_review gui`r`n"
Set-Content -Path $GuiShim -Value $guiShimBody -Encoding Default
Ok "$GuiShim"

# ---- 5. 用户 PATH ----
if ($Portable) {
    Write-Host " [..] 便携模式：不修改 PATH，请直接运行 $Shim"
} else {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not $userPath) { $userPath = "" }
    if (($userPath -split ";") -notcontains $BinDir) {
        [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $BinDir), "User")
        Ok "已加入用户 PATH（对之后新开的终端生效）"
    } else {
        Ok "用户 PATH 已包含命令目录"
    }
}

# ---- 6. 配置文件 ----
Step "初始化配置"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$cfg = Join-Path $DataDir "config.toml"
if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $Root "config.example.toml") $cfg
    Warn2 "已生成默认配置: $cfg"
    Warn2 "请编辑该文件填入 llm.api_key（智谱/DeepSeek/本地模型均可）"
} else {
    Ok "配置已存在: $cfg"
}

# ---- 7. 每日提醒计划任务 ----
if ($Portable) {
    Write-Host " [..] 便携模式：不创建计划任务"
} elseif ($NoTask) {
    Write-Host " [..] 跳过每日提醒任务（之后运行 install.bat 可补建）"
} else {
    $ans = Read-Host "是否创建每日提醒计划任务（每天 $TaskTime 弹出到期通知）? [Y/n]"
    if ($ans -notmatch "^[nN]") {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $tr = "`"$Shim`" due --notify"
        schtasks /Create /F /SC DAILY /ST $TaskTime /TN $TaskName /TR $tr > $null 2>&1
        $taskOk = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prevEap
        if ($taskOk) { Ok "计划任务 '$TaskName' 已创建（每天 $TaskTime）" }
        else { Warn2 "计划任务创建失败，可稍后重新运行 install.bat 重试" }
    } else {
        Write-Host " [..] 已跳过"
    }
}

# ---- 8. 桌面 / 开始菜单快捷方式（图形界面） ----
if ($Portable) {
    Write-Host " [..] 便携模式：跳过快捷方式（图形界面可用 $GuiShim 启动）"
} else {
    Step "创建桌面 / 开始菜单快捷方式"
    try {
        $ws = New-Object -ComObject WScript.Shell
        $pythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
        $targets = @(
            [Environment]::GetFolderPath("Desktop"),
            (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
        )
        foreach ($dir in $targets) {
            $lnkPath = Join-Path $dir "收藏夹遗忘曲线.lnk"
            $lnk = $ws.CreateShortcut($lnkPath)
            $lnk.TargetPath = $pythonw
            $lnk.Arguments = "-m bili_fav_review gui"
            $lnk.WorkingDirectory = $InstallDir
            $lnk.Description = "收藏夹遗忘曲线 - B站收藏复习工具"
            $lnk.Save()
        }
        Ok "桌面与开始菜单快捷方式已创建（双击图标即可打开图形界面）"
    } catch {
        Warn2 "快捷方式创建失败: $($_.Exception.Message)（仍可用 bili-review gui 启动）"
    }
}

Write-Host ""
Write-Host "===== 安装完成 =====" -ForegroundColor Magenta
Write-Host ""
Write-Host "  快速开始:"
Write-Host "    双击桌面「收藏夹遗忘曲线」图标 → 图形界面（推荐，小白友好）"
Write-Host "    或命令行: bili-review gui"
Write-Host ""
Write-Host "  命令行全功能:"
Write-Host "    bili-review login       # 扫码登录 B 站"
Write-Host "    bili-review sync        # 同步收藏夹并生成复习卡片"
Write-Host "    bili-review review      # 复习今天到期的卡片"
Write-Host ""
Write-Host "  配置文件: $cfg"
Write-Host "  卸载: 运行 uninstall.bat"
Write-Host ""
