# Creates a desktop shortcut for TOST Notion Sync
# Run once: powershell -ExecutionPolicy Bypass -File create-shortcut-notion-sync.ps1

$scriptPath = Join-Path $PSScriptRoot "notion-sync-desktop.ps1"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "TOST Notion Sync.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "TOST - Sync Claude Code sessions to Notion"
$shortcut.Save()

Write-Host "Shortcut created: $shortcutPath" -ForegroundColor Green
