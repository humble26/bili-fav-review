#Requires -Version 5.1
# 收藏夹遗忘曲线 . B站版 —— Windows 一键安装（exe 版，安装后无需 Python）
#
# 用法（双击 install.bat 亦可）:
#   powershell -File install.ps1                    交互安装（询问是否建每日提醒任务）
#   powershell -File install.ps1 -NoTask            跳过计划任务
#   powershell -File install.ps1 -TaskTime 21:00    自定义提醒时间
#   powershell -File install.ps1 -Portable D:\BFR   便携安装（只放程序，不建快捷方式/任务）
param(
    [switch]$NoTask,
    [string]$TaskTime = "09:30",
    [string]$Portable = ""
)

$ErrorActionPreference = "Stop"
$Root     = $PSScriptRoot
$AppName  = "BiliFavReview"
$TaskName = "BiliFavReview"
$DataDir  = Join-Path $env:USERPROFILE ".bili_fav_review"
$ExeName  = "收藏夹遗忘曲线.exe"

if ($Portable) {
    $InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Portable)
} else {
    $InstallDir = Join-Path $env:LOCALAPPDATA $AppName
}

function Step($m)  { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)    { Write-Host " [OK] $m" -ForegroundColor Green }
function Warn2($m) { Write-Host " [!!] $m" -ForegroundColor Yellow }
function Die($m)   { Write-Host " [XX] $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "===== 收藏夹遗忘曲线 . B站版 安装程序（exe 版） =====" -ForegroundColor Magenta
Write-Host "安装目录: $InstallDir"
Write-Host ""

# ---- 1. 定位要安装的 exe（发布包：与本脚本同目录；源码树：dist\） ----
Step "定位程序文件"
$srcExe = $null
foreach ($cand in @((Join-Path $Root $ExeName), (Join-Path $Root "dist\$ExeName"))) {
    if (Test-Path $cand) { $srcExe = $cand; break }
}
if (-not $srcExe) { Die "未找到 $ExeName —— 请先运行 build_exe.bat 打包，或从发布包解压后再安装" }
Ok "找到 $srcExe"

# ---- 2. 旧版进程检查（安装目录下任何进程占用都会导致覆盖失败） ----
$busy = @()
if (Test-Path $InstallDir) {
    $busy = Get-Process -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and $_.Path.StartsWith($InstallDir, [StringComparison]::OrdinalIgnoreCase) } catch { $false }
    }
}
if ($busy) { Die "检测到程序正在运行（$((($busy | Select-Object -ExpandProperty ProcessName) -join ', '))）：请先退出「收藏夹遗忘曲线」再安装" }

# ---- 3. 复制程序文件 ----
Step "安装到 $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item $srcExe (Join-Path $InstallDir $ExeName) -Force
Ok "$ExeName 已就位"

# ---- 4. 清理旧版（0.4.1 及更早的 venv 安装） ----
$legacyVenv = Join-Path $InstallDir "venv"
$legacyBin  = Join-Path $InstallDir "bin"
if (Test-Path $legacyVenv) {
    Remove-Item -Recurse -Force $legacyVenv
    Ok "已清理旧版 Python 运行环境（venv）"
}
if (Test-Path $legacyBin) {
    Remove-Item -Recurse -Force $legacyBin
    Ok "已清理旧版命令目录（bin）"
}
if (-not $Portable) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -and (($userPath -split ";") -contains $legacyBin)) {
        $kept = ($userPath -split ";") | Where-Object { $_ -and ($_ -ne $legacyBin) }
        [Environment]::SetEnvironmentVariable("Path", ($kept -join ";"), "User")
        Ok "已从用户 PATH 移除旧命令目录"
    }
}

# ---- 5. 配置文件 ----
Step "初始化配置"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$cfg = Join-Path $DataDir "config.toml"
$cfgExample = Join-Path $Root "config.example.toml"
if (-not (Test-Path $cfg)) {
    if (Test-Path $cfgExample) {
        Copy-Item $cfgExample $cfg
        Warn2 "已生成默认配置: $cfg"
        Warn2 "请编辑该文件填入 llm.api_key（智谱/DeepSeek/本地模型均可）"
    } else {
        Warn2 "未附带配置模板，首次打开程序在「设置」页填写 AI 配置即可"
    }
} else {
    Ok "配置已存在: $cfg"
}

# ---- 6. 每日提醒计划任务（调用 exe 的 due --notify，后台静默） ----
if ($Portable) {
    Write-Host " [..] 便携模式：不创建计划任务"
} elseif ($NoTask) {
    Write-Host " [..] 跳过每日提醒任务（之后运行 install.bat 可补建）"
} else {
    $ans = Read-Host "是否创建每日提醒计划任务（每天 $TaskTime 弹出到期通知）? [Y/n]"
    if ($ans -notmatch "^[nN]") {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $tr = "`"$InstallDir\$ExeName`" due --notify"
        schtasks /Create /F /SC DAILY /ST $TaskTime /TN $TaskName /TR $tr > $null 2>&1
        $taskOk = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prevEap
        if ($taskOk) { Ok "计划任务 '$TaskName' 已创建（每天 $TaskTime）" }
        else { Warn2 "计划任务创建失败，可稍后重新运行 install.bat 重试" }
    } else {
        Write-Host " [..] 已跳过"
    }
}

# ---- 7. 桌面 / 开始菜单快捷方式（图标即 exe 内置新图标） ----
if ($Portable) {
    Write-Host " [..] 便携模式：跳过快捷方式（直接运行 $InstallDir\$ExeName）"
} else {
    Step "创建桌面 / 开始菜单快捷方式"
    try {
        $ws = New-Object -ComObject WScript.Shell
        $exePath = Join-Path $InstallDir $ExeName
        $targets = @(
            [Environment]::GetFolderPath("Desktop"),
            (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
        )
        foreach ($dir in $targets) {
            $lnkPath = Join-Path $dir "收藏夹遗忘曲线.lnk"
            # 先删后建：老快捷方式（pythonw 版）的 Arguments 等字段会被 WScript.Shell
            # 原样保留，直接覆盖会导致新 exe 收到 "-m bili_fav_review gui" 而 argparse 报错退出
            if (Test-Path $lnkPath) { Remove-Item $lnkPath -Force }
            $lnk = $ws.CreateShortcut($lnkPath)
            $lnk.TargetPath = $exePath
            $lnk.Arguments = ""
            $lnk.WorkingDirectory = $InstallDir
            $lnk.Description = "收藏夹遗忘曲线 - B站收藏复习工具"
            $lnk.Save()
        }
        Ok "桌面与开始菜单快捷方式已创建（双击图标即可打开图形界面）"
    } catch {
        Warn2 "快捷方式创建失败: $($_.Exception.Message)（可直接运行 $exePath）"
    }
}

Write-Host ""
Write-Host "===== 安装完成 =====" -ForegroundColor Magenta
Write-Host ""
Write-Host "  快速开始:"
Write-Host "    双击桌面「收藏夹遗忘曲线」图标 → 图形界面（推荐）"
Write-Host "    命令行全功能: `"$InstallDir\$ExeName`" --help"
Write-Host "  数据目录: $DataDir（数据库 / cookies / 配置）"
Write-Host "  卸载: 运行 uninstall.bat"
Write-Host ""
