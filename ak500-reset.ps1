<#
.SYNOPSIS
  Reset tool for DeepCool AK500 Digital Pro on Windows.
.DESCRIPTION
  Re-enables stuck USB ports/hubs and fixes Windows Fast Startup standby power issues.
#>

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning "Requires Administrator privileges. Relaunching as Admin..."
    Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

Write-Host "Checking USB devices for AK500 (3633:0011) or stuck Hub..." -ForegroundColor Cyan

# 1. Reset any USB devices in Error state
$errorDevices = Get-PnpDevice -Class "USB" -Status "Error" -ErrorAction SilentlyContinue
if ($errorDevices) {
    foreach ($dev in $errorDevices) {
        Write-Host "Restarting failed device: $($dev.FriendlyName) ($($dev.InstanceId))" -ForegroundColor Yellow
        Disable-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false
        Start-Sleep -Seconds 1
        Enable-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false
    }
}

# 2. Restart Genesys Logic or Generic USB Hubs
$hubs = Get-PnpDevice -Class "USB" -ErrorAction SilentlyContinue | Where-Object {
    $_.InstanceId -like "*VID_05E3*" -or $_.FriendlyName -like "*Generic USB Hub*"
}

if ($hubs) {
    foreach ($hub in $hubs) {
        Write-Host "Cycling USB Hub: $($hub.FriendlyName)" -ForegroundColor Yellow
        Disable-PnpDevice -InstanceId $hub.InstanceId -Confirm:$false
        Start-Sleep -Seconds 1
        Enable-PnpDevice -InstanceId $hub.InstanceId -Confirm:$false
    }
}

# 3. Check Windows Fast Startup
Write-Host "Verifying Windows Fast Startup (hibernation)..." -ForegroundColor Cyan
$hiberboot = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power" -Name "HiberbootEnabled" -ErrorAction SilentlyContinue).HiberbootEnabled
if ($hiberboot -eq 1) {
    Write-Warning "Fast Startup is ENABLED in Windows. This prevents ErP in BIOS from cutting standby voltage on shutdown!"
    $choice = Read-Host "Disable Fast Startup now? (Y/N)"
    if ($choice -match '^[Yy]') {
        powercfg /h off
        Write-Host "Fast Startup disabled. ErP in BIOS will now properly power off the panel upon shutdown." -ForegroundColor Green
    }
} else {
    Write-Host "Fast Startup is already disabled or not active." -ForegroundColor Green
}

Write-Host "Done. Check if the AK500 panel lights up." -ForegroundColor Green
