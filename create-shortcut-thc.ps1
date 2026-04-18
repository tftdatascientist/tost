# Tworzy skrot na pulpicie dla THC - Traffic Hours Console
# Uruchom raz: powershell -ExecutionPolicy Bypass -File create-shortcut-thc.ps1

$scriptPath   = Join-Path $PSScriptRoot "thc-desktop.ps1"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "THC.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath       = "powershell.exe"
$shortcut.Arguments        = "-ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description      = "THC - Traffic Hours Console (Anthropic server load radar)"
$shortcut.Save()

Write-Host "Skrot utworzony: $shortcutPath" -ForegroundColor Green
