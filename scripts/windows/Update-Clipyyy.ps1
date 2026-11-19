$ErrorActionPreference = "Stop"

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($GitArgs -join ' ')"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$dataRoot = "B:\CLIPSTUDIO\clipyyy-data"
$tempRoot = Join-Path $dataRoot "tmp"
$uvCache = Join-Path $dataRoot "uv-cache"
$npmCache = Join-Path $dataRoot "npm-cache"
$ffmpeg = "B:\CLIPSTUDIO\tools\ffmpeg-extract\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"
$launcher = Join-Path $repoRoot "scripts\windows\Launch-Clipyyy.vbs"
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
    throw "Clipyyy Git repository not found at $repoRoot"
}
if (-not (Test-Path $ffmpeg)) {
    throw "The configured B: drive FFmpeg executable was not found: $ffmpeg"
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not installed or is not available on PATH."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is not installed or is not available on PATH."
}

Set-Location $repoRoot
$branch = (& git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
    throw "Switch to the main branch before updating Clipyyy. Current branch: $branch"
}

$dirty = & git status --porcelain
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect the local Git working tree."
}
if ($dirty) {
    Write-Host "Preserving local code changes and untracked files in Git stash..."
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Invoke-Git stash push --include-untracked -m "Clipyyy pre-campaign update $stamp"
}

$forkUrl = "https://github.com/Parth33831/clipyyy.git"
$remotes = @(& git remote)
if ($remotes -contains "fork") {
    Invoke-Git remote set-url fork $forkUrl
} else {
    Invoke-Git remote add fork $forkUrl
}
Invoke-Git fetch fork main
Invoke-Git merge --ff-only FETCH_HEAD

New-Item -ItemType Directory -Force -Path $tempRoot, $uvCache, $npmCache | Out-Null
$env:CLIPYYY_HOME = $dataRoot
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
$env:UV_CACHE_DIR = $uvCache
$env:npm_config_cache = $npmCache
$env:CLIPYYY_FFMPEG = $ffmpeg

Write-Host "Installing Python dependencies on B:..."
uv sync --python 3.12
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency installation failed. The previous app process was left running."
}

Write-Host "Building the dashboard on B:..."
npm ci --prefix frontend
if ($LASTEXITCODE -ne 0) {
    throw "Dashboard dependency installation failed. The previous app process was left running."
}
npm run build --prefix frontend
if ($LASTEXITCODE -ne 0) {
    throw "Dashboard build failed. The previous app process was left running."
}

if (-not (Test-Path $launcher)) {
    throw "Clipyyy background launcher was not found: $launcher"
}
$processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object {
        $_.ExecutablePath -eq $python -and
        $_.CommandLine -like "*clipyyy.cli serve --host 127.0.0.1 --port 8000*"
    }
foreach ($process in $processes) {
    Stop-Process -Id $process.ProcessId -Force
}
Start-Process -FilePath "wscript.exe" -ArgumentList "`"$launcher`""
Start-Sleep -Seconds 2

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 5
    Write-Host "Clipyyy updated and dashboard health endpoint responded."
} catch {
    Write-Warning "The update and dashboard build completed, but the health endpoint did not respond yet. Open http://127.0.0.1:8000 and check the log at $dataRoot\logs\server.log"
}

$stash = (& git stash list -n 1).Trim()
if ($stash) {
    Write-Host "Your previous local changes remain safely preserved: $stash"
}
Write-Host "Clipyyy update complete. Campaign data, runs and caches remain under $dataRoot."
