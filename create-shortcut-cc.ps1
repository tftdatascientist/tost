# Tworzy skrót na pulpicie dla TOST + CC (panel Claude Code)
# Uruchom raz: powershell -ExecutionPolicy Bypass -File create-shortcut-cc.ps1

$projectDir = $PSScriptRoot
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "TOST+CC.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-ExecutionPolicy Bypass -NoExit -Command `"cd '$projectDir'; python -m tost cc`""
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "TOST + Claude Code panel (TUI)"
$shortcut.Save()

Write-Host "Skrót utworzony: $shortcutPath" -ForegroundColor Green
