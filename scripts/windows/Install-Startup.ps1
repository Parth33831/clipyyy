$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$vbs = Join-Path $PSScriptRoot "Launch-Clipyyy.vbs"
$dataRoot = "B:\CLIPSTUDIO\clipyyy-data"

if (-not (Test-Path $python)) {
    throw "Clipyyy's virtual environment is missing: $python. Install/sync the project dependencies first."
}
if (-not (Test-Path $vbs)) {
    throw "Launcher file is missing: $vbs"
}

New-Item -ItemType Directory -Force -Path (Join-Path $dataRoot "logs"), (Join-Path $dataRoot "tmp") | Out-Null

$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Clipyyy Background.lnk"
$wscript = Join-Path $env:WINDIR "System32\wscript.exe"
$ws = New-Object -ComObject WScript.Shell
$shortcut = $ws.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = '//B //Nologo "' + $vbs + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Start the local Clipyyy dashboard in the background"
$shortcut.Save()

$desktop = [Environment]::GetFolderPath("Desktop")
$urlPath = Join-Path $desktop "Clipyyy Dashboard.url"
@"
[InternetShortcut]
URL=http://127.0.0.1:8000
"@ | Set-Content -Path $urlPath -Encoding ASCII

Write-Host "Clipyyy background startup installed."
Write-Host "It will start automatically at your next Windows sign-in."
Write-Host "Dashboard: http://127.0.0.1:8000"
Write-Host "Logs: $dataRoot\logs\server.log"
Write-Host "To start it now, run scripts\windows\Launch-Clipyyy.vbs."
