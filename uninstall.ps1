#Requires -Version 5.1
# 收藏夹遗忘曲线 . B站版 —— 卸载
#
# 用法:
#   powershell -File uninstall.ps1                交互卸载（询问是否删数据）
#   powershell -File uninstall.ps1 -KeepData      保留数据目录
#   powershell -File uninstall.ps1 -PurgeData     连数据一起删（复习记录/cookie/配置）
param(
    [switch]$PurgeData,
    [switch]$KeepData,
    [string]$Portable = ""
)

$ErrorActionPreference = "Stop"
$AppName  = "BiliFavReview"
$TaskName = "BiliFavReview"
$DataDir  = Join-Path $env:USERPROFILE ".bili_fav_review"

if ($Portable) {
    $InstallDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Portable)
} else {
    $InstallDir = Join-Path $env:LOCALAPPDATA $AppName
}
$BinDir = Join-Path $InstallDir "bin"

Write-Host ""
Write-Host "===== 收藏夹遗忘曲线 . B站版 卸载 =====" -ForegroundColor Magenta

# 1. 计划任务（任务不存在时 schtasks 会写 stderr；PS5.1 在 Stop 偏好下会中断脚本，先降级处理）
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
schtasks /Delete /TN $TaskName /F > $null 2>&1
$taskDeleted = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap
if ($taskDeleted) { Write-Host " [OK] 已删除计划任务 $TaskName" -ForegroundColor Green }

# 2. 用户 PATH
if (-not $Portable) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -and (($userPath -split ";") -contains $BinDir)) {
        $kept = ($userPath -split ";") | Where-Object { $_ -and ($_ -ne $BinDir) }
        [Environment]::SetEnvironmentVariable("Path", ($kept -join ";"), "User")
        Write-Host " [OK] 已从用户 PATH 移除 $BinDir" -ForegroundColor Green
    }
}

# 3. 程序文件
if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host " [OK] 已删除程序目录 $InstallDir" -ForegroundColor Green
} else {
    Write-Host " [..] 未发现程序目录（可能已卸载）"
}

# 3.5 桌面 / 开始菜单快捷方式
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))) {
    $lnkPath = Join-Path $dir "收藏夹遗忘曲线.lnk"
    if (Test-Path $lnkPath) {
        Remove-Item $lnkPath -Force
        Write-Host " [OK] 已删除快捷方式 $lnkPath" -ForegroundColor Green
    }
}

# 4. 数据目录
if ($PurgeData) {
    if (Test-Path $DataDir) {
        Remove-Item -Recurse -Force $DataDir
        Write-Host " [OK] 数据目录已删除: $DataDir" -ForegroundColor Green
    }
} elseif ($KeepData) {
    Write-Host " [..] 已保留数据目录: $DataDir"
} else {
    $ans = Read-Host "是否删除数据目录（复习记录/cookie/配置） $DataDir ? [y/N]"
    if ($ans -match "^[yY]") {
        if (Test-Path $DataDir) { Remove-Item -Recurse -Force $DataDir }
        Write-Host " [OK] 数据目录已删除" -ForegroundColor Green
    } else {
        Write-Host " [..] 已保留 $DataDir"
    }
}

Write-Host "卸载完成"
Write-Host ""
