# Stop and remove WeChatAgYSidecar NSSM Service
$ServiceName = "WeChatAgYSidecar"
$NssmExe = Join-Path $PSScriptRoot "nssm.exe"

Write-Host "正在停止并卸载 $ServiceName 服务..." -ForegroundColor Yellow

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -eq "Running") {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        Write-Host "✅ 服务已停止。" -ForegroundColor Green
    }
}

if (Test-Path $NssmExe) {
    & $NssmExe remove $ServiceName confirm
    Write-Host "✅ 已从 NSSM 彻底移除服务。" -ForegroundColor Green
} else {
    $nssmCmd = Get-Command "nssm" -ErrorAction SilentlyContinue
    if ($nssmCmd) {
        & nssm remove $ServiceName confirm
        Write-Host "✅ 已从 NSSM 彻底移除服务。" -ForegroundColor Green
    } else {
        & sc.exe delete $ServiceName
        Write-Host "✅ 已通过 sc.exe 删除服务。" -ForegroundColor Green
    }
}

Write-Host "`n🎉 WeChatAgYSidecar 服务已卸载！" -ForegroundColor Cyan
Write-Host "现在你可以通过双击根目录下的 start-windows.bat 随时手动按需启动。" -ForegroundColor Cyan
