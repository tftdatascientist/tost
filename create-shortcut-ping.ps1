# Tworzy skrot na pulpicie dla TOST Ping (latency monitor)
# Uruchom raz: powershell -ExecutionPolicy Bypass -File create-shortcut-ping.ps1

$projectDir = $PSScriptRoot
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "TOST Ping.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$projectDir\ping-desktop.ps1`""
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "TOST Ping - Anthropic API Latency Monitor"
$shortcut.Save()

Write-Host "Skrot utworzony: $shortcutPath" -ForegroundColor Green
