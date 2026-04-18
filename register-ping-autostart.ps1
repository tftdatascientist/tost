# Rejestruje TOST Ping jako zadanie Windows Task Scheduler
# Uruchamia sie automatycznie przy logowaniu uzytkownika
# Uruchom RAZ jako administrator:
#   powershell -ExecutionPolicy Bypass -File register-ping-autostart.ps1
#
# Aby usunac: Unregister-ScheduledTask -TaskName "TOST Ping Collector" -Confirm:$false

$projectDir = $PSScriptRoot
$pythonExe = (Get-Command python).Source
$taskName = "TOST Ping Collector"

# Sprawdz czy zadanie juz istnieje
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Zadanie '$taskName' juz istnieje. Usuwam i tworze ponownie..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# Skrypt wrapujacy — laduje .env i uruchamia ping-collect
$wrapperScript = @"
Set-Location '$projectDir'
`$envFile = Join-Path '$projectDir' '.env'
if (Test-Path `$envFile) {
    Get-Content `$envFile | ForEach-Object {
        `$line = `$_.Trim()
        if (`$line -and -not `$line.StartsWith('#') -and `$line.Contains('=')) {
            `$parts = `$line -split '=', 2
            [Environment]::SetEnvironmentVariable(`$parts[0].Trim(), `$parts[1].Trim())
        }
    }
}
& '$pythonExe' -m tost ping-collect -v
"@

$wrapperPath = Join-Path $projectDir "ping-autostart-wrapper.ps1"
$wrapperScript | Out-File -FilePath $wrapperPath -Encoding UTF8

# Akcja — uruchom PowerShell z wrapper skryptem (ukryte okno)
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$wrapperPath`"" `
    -WorkingDirectory $projectDir

# Trigger — przy logowaniu biezacego uzytkownika
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Ustawienia
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Rejestruj
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "TOST Ping - monitoruje latencje API Anthropic co 5 minut" `
    -RunLevel Limited

Write-Host ""
Write-Host "Zadanie '$taskName' zarejestrowane!" -ForegroundColor Green
Write-Host "  - Uruchamia sie automatycznie przy logowaniu" -ForegroundColor Cyan
Write-Host "  - Dziala w tle (ukryte okno)" -ForegroundColor Cyan
Write-Host "  - Dane w: ~/.claude/tost_ping.db" -ForegroundColor Cyan
Write-Host ""
Write-Host "Komendy zarzadzania:" -ForegroundColor DarkGray
Write-Host "  Start reczny:  Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor DarkGray
Write-Host "  Stop:          Stop-ScheduledTask -TaskName '$taskName'" -ForegroundColor DarkGray
Write-Host "  Usun:          Unregister-ScheduledTask -TaskName '$taskName'" -ForegroundColor DarkGray
Write-Host "  Status:        Get-ScheduledTask -TaskName '$taskName' | Select State" -ForegroundColor DarkGray
