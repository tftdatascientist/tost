# Tworzy skrot na pulpicie dla TOST Launcher - menu z wszystkimi modulami
# Uruchom raz: powershell -ExecutionPolicy Bypass -File create-shortcut-launcher.ps1

$scriptPath   = Join-Path $PSScriptRoot "tost-launcher.ps1"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "TOST Launcher.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath       = "powershell.exe"
$shortcut.Arguments        = "-ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description      = "TOST Launcher - menu: TOST / CC / Holmes / Ping / THC"
$shortcut.Save()

Write-Host "Skrot utworzony: $shortcutPath" -ForegroundColor Green
Write-Host "Uruchom dwukliknieciem ikony 'TOST Launcher' na pulpicie." -ForegroundColor DarkGray
