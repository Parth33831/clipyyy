$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$shortcut = Join-Path $startup "Clipyyy Background.lnk"
if (Test-Path $shortcut) {
    Remove-Item -LiteralPath $shortcut -Force
    Write-Host "Removed Clipyyy automatic startup."
} else {
    Write-Host "Clipyyy automatic startup was not installed."
}
Write-Host "The desktop dashboard shortcut is left in place."
Write-Host "This does not delete Clipyyy, its settings, runs, clips, or data."
