# Creates a desktop shortcut for TOST
# Run once: powershell -ExecutionPolicy Bypass -File create-shortcut.ps1

$scriptPath = Join-Path $PSScriptRoot "tost-desktop.ps1"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "TOST.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "TOST - Token Optimization System Tool"
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath" -ForegroundColor Green
