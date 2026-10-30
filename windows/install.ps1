# WeChat Antigravity Sidecar — Windows Installer (PowerShell)
# Supports: Windows 10/11, Python 3.9+
# Installs: Python venv, dependencies, NSSM service, sidecar manifest

$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$VenvDir = Join-Path $ProjectDir ".venv"
$VenvBin = Join-Path $VenvDir "Scripts"
$HomeDir = $env:USERPROFILE

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " WeChat Antigravity Sidecar — Windows Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Detect Python
Write-Host "`n[1/6] Detecting Python..." -ForegroundColor Yellow
$PythonExe = $null
foreach ($cmd in @("python", "python3", "py")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $PythonExe = $found.Source
        break
    }
}
if (-not $PythonExe) {
    Write-Host "❌ Python not found. Please install Python 3.9+ from https://python.org" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Python found: $PythonExe"

# 2. Create venv
Write-Host "`n[2/6] Creating virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path $VenvDir)) {
    & $PythonExe -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Failed to create venv" -ForegroundColor Red
        exit 1
    }
}
Write-Host "✅ Virtual environment at: $VenvDir"

# 3. Install dependencies
Write-Host "`n[3/6] Installing dependencies..." -ForegroundColor Yellow
$PipExe = Join-Path $VenvBin "pip.exe"
$SidecarExe = Join-Path $VenvBin "wechat-agy-sidecar.exe"
& $PipExe install -e $ProjectDir
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Dependencies installed"

# 4. Ensure NSSM is available
Write-Host "`n[4/6] Checking NSSM..." -ForegroundColor Yellow
$NssmExe = $null
foreach ($path in @("$env:ProgramFiles\NSSM\nssm.exe", "$env:LOCALAPPDATA\NSSM\nssm.exe")) {
    if (Test-Path $path) {
        $NssmExe = $path
        break
    }
}

if (-not $NssmExe) {
    Write-Host "⚠️ NSSM not found. Downloading..." -ForegroundColor Yellow
    $NssmZip = Join-Path $env:TEMP "nssm-x64.zip"
    $NssmExtract = Join-Path $env:TEMP "nssm-extract"
    Invoke-WebRequest -Uri "https://github.com/SERVICES-management/NSSM/releases/latest/download/nssm-x64-2.24.zip" -OutFile $NssmZip
    if (-not (Test-Path Expand-Archive)) {
        New-Item -ItemType Directory -Force -Path $NssmExtract | Out-Null
    }
    Expand-Archive -Path $NssmZip -DestinationPath $NssmExtract -Force
    $NssmExe = Get-ChildItem -Path $NssmExtract -Recurse -Filter "nssm.exe" | Select-Object -First 1 | ForEach-Object { $_.FullName }

    if (-not $NssmExe) {
        Write-Host "❌ Failed to download NSSM. Please download manually from https://nssm.cc/download" -ForegroundColor Red
        exit 1
    }

    # Install NSSM to Program Files for system-wide access
    $NssmTarget = Join-Path $env:ProgramFiles "NSSM"
    New-Item -ItemType Directory -Force -Path $NssmTarget | Out-Null
    Copy-Item (Join-Path (Split-Path $NssmExe) "nssm.exe") $NssmTarget
    Copy-Item (Join-Path (Split-Path $NssmExe) "winsw.dll") $NssmTarget -ErrorAction SilentlyContinue
    Copy-Item (Join-Path (Split-Path $NssmExe) "winsw.exe") $NssmTarget -ErrorAction SilentlyContinue
    Copy-Item (Join-Path (Split-Path $NssmExe) "nssm.exe") "$NssmTarget\nssm.exe" -Force
    $NssmExe = Join-Path $NssmTarget "nssm.exe"

    Write-Host "✅ NSSM installed to: $NssmTarget"
} else {
    Write-Host "✅ NSSM found: $NssmExe"
}

# 5. Create Windows service via NSSM
Write-Host "`n[5/6] Creating Windows service..." -ForegroundColor Yellow
$ServiceName = "WeChatAgYSidecar"

# Remove existing service if present
& $NssmExe remove $ServiceName confirm

# Install service
& $NssmExe install $ServiceName $SidecarExe
& $NssmExe set $ServiceName AppDirectory $ProjectDir
& $NssmExe set $ServiceName AppStdout "$HomeDir\AppData\Local\wechat-agy-sidecar\stdout.log"
& $NssmExe set $ServiceName AppStderr "$HomeDir\AppData\Local\wechat-agy-sidecar\stderr.log"
& $NssmExe set $ServiceName AppEnvironmentExtra "PATH=$VenvBin;$env:SystemRoot\System32;$env:SystemRoot"
& $NssmExe set $ServiceName AppEnvironmentExtra "HOME=$HomeDir"
& $NssmExe set $ServiceName AppEnvironmentExtra "WECHAT_SIDECAR_CONFIG=$HomeDir\.gemini\wechat_sidecar_config.json"
& $NssmExe set $ServiceName AppRestartDelay "3000"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START

# Create log directory
$LogDir = "$HomeDir\AppData\Local\wechat-agy-sidecar"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "✅ Service created: $ServiceName"

# 6. Start service
Write-Host "`n[6/6] Starting service..." -ForegroundColor Yellow
& $NssmExe start $ServiceName
Start-Sleep -Seconds 3

# Check status
$ServiceStatus = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($ServiceStatus) {
    Write-Host "✅ Service status: $($ServiceStatus.Status)" -ForegroundColor Green
}

# Register sidecar manifest
$SidecarConfigDir = "$HomeDir\.gemini\config\sidecars\wechat-agy-sidecar"
New-Item -ItemType Directory -Force -Path $SidecarConfigDir | Out-Null
$SidecarJson = @"
{
  "$schema": "https://antigravity.google/schemas/sidecar.json",
  "name": "wechat-agy-sidecar",
  "description": "WeChat Antigravity Bridge Sidecar Daemon (Enhanced)",
  "command": "$SidecarExe",
  "args": [],
  "cwd": "$ProjectDir",
  "restart_policy": "always",
  "env": {
    "PATH": "$VenvBin;$env:SystemRoot\System32;$env:SystemRoot",
    "HOME": "$HomeDir",
    "WECHAT_SIDECAR_CONFIG": "$HomeDir\.gemini\wechat_sidecar_config.json"
  },
  "enabled": true
}
"@
Set-Content -Path "$SidecarConfigDir\sidecar.json" -Value $SidecarJson -Encoding UTF8
Write-Host "✅ Sidecar manifest registered"

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "✅ Installation complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "`nQuick Commands:"
Write-Host "  1. Onboarding Login: $SidecarExe --login"
Write-Host "  2. Start Service:   Start-Service WeChatAgYSidecar"
Write-Host "  3. Stop Service:    Stop-Service WeChatAgYSidecar"
Write-Host "  4. Check Status:    Get-Service WeChatAgYSidecar"
Write-Host "  5. View Logs:       Get-Content $LogDir\stdout.log -Tail 50"
Write-Host "`nService starts automatically on boot."
