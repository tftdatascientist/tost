# Tworzy skrot na pulpicie dla Holmes — analizatora anomalii tokenow
# Uruchom raz: powershell -ExecutionPolicy Bypass -File create-shortcut-holmes.ps1

$scriptPath = Join-Path $PSScriptRoot "holmes-desktop.ps1"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Holmes.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Holmes - TOST Token Anomaly Detector"
$shortcut.Save()

Write-Host "Skrot utworzony: $shortcutPath" -ForegroundColor Green
