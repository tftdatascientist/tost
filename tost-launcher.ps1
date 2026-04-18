# TOST Launcher — unified flat menu (wszystkie moduly, wszystkie tryby, 1 ekran)
# -*- coding: utf-8-bom -*-

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

# Konsola UTF-8 (dla blokow Matrix / histogramow)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
chcp 65001 > $null

# Zaladuj .env raz na start
$envFile = Join-Path $projectDir ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line -split "=", 2
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim())
        }
    }
}

$TaskName = "TOST Ping Collector"
$ClaudeDir = Join-Path $env:USERPROFILE ".claude"
$SonarMarker = Join-Path $ClaudeDir "tost_sonar_disabled"

function Show-MainMenu {
    Clear-Host
    Write-Host ""
    Write-Host "  +======================================================================+" -ForegroundColor Cyan
    Write-Host "  |         TOST Launcher - Token Optimization System Tool               |" -ForegroundColor Cyan
    Write-Host "  +======================================================================+" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  -- TUI / DASHBOARDY -------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host "   1) TOST Monitor        - dashboard sesji (domyslny)"                    -ForegroundColor White
    Write-Host "   2) TOST + CC           - dashboard + panel Claude Code"                 -ForegroundColor White
    Write-Host "   3) THC                 - Traffic Hours Console (Matrix)"                -ForegroundColor DarkGreen
    Write-Host "  3m) THC Mini            - 3 kropki nacisku na limity"                    -ForegroundColor DarkGreen
    Write-Host "   4) Ping Viewer         - TUI readonly (latency)"                        -ForegroundColor Green
    Write-Host "   5) Holmes TUI          - interaktywna analiza anomalii"                 -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  -- SYNC / COLLECTORS ------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host "   6) SYNC WSZYSTKO       - ping + sesje + taryfa (once)"                  -ForegroundColor Yellow
    Write-Host "   7) Notion Sync (loop)  - sesje + taryfa w petli (60s / 15min)"          -ForegroundColor White
    Write-Host "   8) Notion Sync (once)  - jeden przebieg sesje+taryfa"                   -ForegroundColor White
    Write-Host "   9) Ping Daemon         - pomiar co 5 min (+sonar)"                      -ForegroundColor White
    Write-Host "  10) Ping (once)         - jeden pomiar i wyjscie"                        -ForegroundColor White
    Write-Host ""
    Write-Host "  -- ANALIZY (no-TUI) -------------------------------------------------" -ForegroundColor DarkCyan
    Write-Host "  11) Holmes (terminal)   - wyniki w konsoli"                              -ForegroundColor Magenta
    Write-Host "  12) Holmes + zakres dat - prompt na --from / --to"                       -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  -- KONFIG / NARZEDZIA -----------------------------------------------" -ForegroundColor DarkCyan
    Write-Host "  13) Edytuj .env"                                                         -ForegroundColor Gray
    Write-Host "  14) Edytuj thc_tiers.toml"                                               -ForegroundColor Gray
    Write-Host "  15) Edytuj taryfa_thresholds.toml"                                       -ForegroundColor Gray
    Write-Host "  16) Edytuj holmes_rules.toml"                                            -ForegroundColor Gray
    Write-Host "  17) Autostart Ping - zarejestruj (Task Scheduler)"                       -ForegroundColor Gray
    Write-Host "  18) Autostart Ping - usun"                                               -ForegroundColor Gray
    Write-Host "  19) Autostart Ping - status"                                             -ForegroundColor Gray
    Write-Host "  20) Toggle sonar ON/OFF"                                                 -ForegroundColor Gray
    Write-Host "  21) Status systemu (pliki stanu, procesy)"                               -ForegroundColor Gray
    Write-Host ""
    Write-Host "  +----------------------------------------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |   0) Wyjscie                                                         |" -ForegroundColor DarkGray
    Write-Host "  +======================================================================+" -ForegroundColor Cyan
    Write-Host ""
}

function Wait-Return {
    Write-Host ""
    Write-Host "  Nacisnij Enter, aby wrocic do menu..." -ForegroundColor DarkGray
    Read-Host | Out-Null
}

function Invoke-Monitor {
    Clear-Host
    Write-Host "=== TOST Dashboard ===" -ForegroundColor Cyan
    python -m tost monitor
    Wait-Return
}

function Invoke-CC {
    Clear-Host
    Write-Host "=== TOST + CC panel ===" -ForegroundColor Cyan
    python -m tost cc
    Wait-Return
}

function Invoke-Thc {
    Clear-Host
    $pingDb = Join-Path $ClaudeDir "tost_ping.db"
    if (-not (Test-Path $pingDb)) {
        Write-Host "  Uwaga: brak tost_ping.db - uruchom najpierw Ping Daemon (9)" -ForegroundColor Yellow
        Start-Sleep -Seconds 2
    }
    Write-Host "=== THC - Traffic Hours Console ===" -ForegroundColor Green
    python -m tost thc
    Wait-Return
}

function Invoke-ThcMini {
    Clear-Host
    Write-Host "=== THC Mini - 3 kropki (q=wyjscie) ===" -ForegroundColor DarkGreen
    python -m tost thc-mini
    Wait-Return
}

function Invoke-PingViewer {
    Clear-Host
    Write-Host "=== Ping TUI ===" -ForegroundColor Green
    python -m tost ping
    Wait-Return
}

function Invoke-HolmesTui {
    Clear-Host
    Write-Host "=== Holmes TUI ===" -ForegroundColor Magenta
    python -m tost holmes
    Wait-Return
}

function Invoke-SyncAll {
    Clear-Host
    Write-Host "==========================================" -ForegroundColor Yellow
    Write-Host "  SYNC WSZYSTKO - ping + sesje + taryfa   " -ForegroundColor Yellow
    Write-Host "==========================================" -ForegroundColor Yellow
    Write-Host ""

    Write-Host "[1/2] Pomiar pingu + sync (hourly+THC jesli skonfigurowane)..." -ForegroundColor Cyan
    python -m tost ping-collect --once -v
    $pingRc = $LASTEXITCODE

    Write-Host ""
    Write-Host "[2/2] Sync sesji + taryfy do Notion..." -ForegroundColor Cyan
    python -m tost sync --once -v
    $syncRc = $LASTEXITCODE

    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Yellow
    if ($pingRc -eq 0 -and $syncRc -eq 0) {
        Write-Host "  OK - wszystko zsynchronizowane."       -ForegroundColor Green
    } else {
        Write-Host "  Zakonczono z bledami (ping=$pingRc, sync=$syncRc)" -ForegroundColor Red
    }
    Write-Host "==========================================" -ForegroundColor Yellow
    Wait-Return
}

function Invoke-SyncLoop {
    Clear-Host
    Write-Host "=== Notion Sync (loop - Ctrl+C aby zatrzymac) ===" -ForegroundColor White
    python -m tost sync -v
    Wait-Return
}

function Invoke-SyncOnce {
    Clear-Host
    Write-Host "=== Notion Sync (once) ===" -ForegroundColor White
    python -m tost sync --once -v
    Wait-Return
}

function Invoke-PingDaemon {
    Clear-Host
    Write-Host "=== Ping Daemon (Ctrl+C aby zatrzymac) ===" -ForegroundColor White
    python -m tost ping-collect -v
    Wait-Return
}

function Invoke-PingOnce {
    Clear-Host
    Write-Host "=== Ping - pojedynczy pomiar ===" -ForegroundColor White
    python -m tost ping-collect --once -v
    Wait-Return
}

function Invoke-HolmesTerminal {
    Clear-Host
    Write-Host "=== Holmes - tryb konsolowy ===" -ForegroundColor Magenta
    python -m tost holmes --no-tui
    Wait-Return
}

function Invoke-HolmesRange {
    Clear-Host
    Write-Host "=== Holmes + zakres dat ===" -ForegroundColor Magenta
    Write-Host ""
    $dateFrom = Read-Host "  Data od (YYYY-MM-DD, puste = pomin)"
    $dateTo   = Read-Host "  Data do (YYYY-MM-DD, puste = pomin)"
    $argv = @("-m", "tost", "holmes", "--no-tui")
    if ($dateFrom) { $argv += @("--from", $dateFrom) }
    if ($dateTo)   { $argv += @("--to",   $dateTo)   }
    Write-Host ""
    Write-Host "  Uruchamiam: python $($argv -join ' ')" -ForegroundColor DarkGray
    Write-Host ""
    & python @argv
    Wait-Return
}

function Edit-ConfigFile {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [string]$Label = ""
    )
    if (-not (Test-Path $Path)) {
        Write-Host ""
        Write-Host "  Plik nie istnieje: $Path" -ForegroundColor Red
        Wait-Return
        return
    }
    Write-Host ""
    Write-Host "  Otwieram w notatniku: $Path" -ForegroundColor DarkGray
    Start-Process notepad.exe -ArgumentList $Path -Wait
    if ($Label) {
        Write-Host ""
        Write-Host "  $Label - zapisane. Pamietaj o reload (Ctrl+R w TUI) jesli dotyczy." -ForegroundColor Green
    }
}

function Register-PingAutostart {
    Clear-Host
    Write-Host "=== Autostart Ping - rejestracja Task Scheduler ===" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  UWAGA: rejestracja wymaga uprawnien administratora." -ForegroundColor Yellow
    Write-Host "  Otworze nowe okno PowerShell z elevacja (UAC prompt)." -ForegroundColor Yellow
    Write-Host ""
    $script = Join-Path $projectDir "register-ping-autostart.ps1"
    if (-not (Test-Path $script)) {
        Write-Host "  Brak skryptu: $script" -ForegroundColor Red
        Wait-Return
        return
    }
    $confirm = Read-Host "  Kontynuowac? [t/N]"
    if ($confirm -match '^(t|y|tak|yes)$') {
        Start-Process powershell.exe `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $script `
            -Verb RunAs
        Write-Host ""
        Write-Host "  Uruchomiono w osobnym oknie (UAC)." -ForegroundColor Green
    } else {
        Write-Host "  Anulowano." -ForegroundColor DarkGray
    }
    Wait-Return
}

function Unregister-PingAutostart {
    Clear-Host
    Write-Host "=== Autostart Ping - wyrejestrowanie ===" -ForegroundColor Yellow
    Write-Host ""
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "  Zadanie '$TaskName' nie istnieje - nic do usuniecia." -ForegroundColor DarkGray
        Wait-Return
        return
    }
    Write-Host "  Znaleziono zadanie: $TaskName (State: $($existing.State))" -ForegroundColor White
    $confirm = Read-Host "  Usunac? [t/N]"
    if ($confirm -match '^(t|y|tak|yes)$') {
        try {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
            Write-Host "  OK - zadanie usuniete." -ForegroundColor Green
        } catch {
            Write-Host "  Blad: $_" -ForegroundColor Red
            Write-Host "  (moze wymagac uprawnien administratora)" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  Anulowano." -ForegroundColor DarkGray
    }
    Wait-Return
}

function Show-PingAutostartStatus {
    Clear-Host
    Write-Host "=== Autostart Ping - status ===" -ForegroundColor Yellow
    Write-Host ""
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "  Zadanie '$TaskName' NIE jest zarejestrowane." -ForegroundColor DarkGray
        Write-Host "  Zarejestruj przez menu 17." -ForegroundColor DarkGray
    } else {
        Write-Host "  Nazwa:  $TaskName"                       -ForegroundColor White
        Write-Host "  State:  $($existing.State)"              -ForegroundColor White
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($info) {
            Write-Host "  Last run:   $($info.LastRunTime)"    -ForegroundColor DarkGray
            Write-Host "  Last result:$($info.LastTaskResult)" -ForegroundColor DarkGray
            Write-Host "  Next run:   $($info.NextRunTime)"    -ForegroundColor DarkGray
        }
    }
    Wait-Return
}

function Toggle-Sonar {
    Clear-Host
    Write-Host "=== Toggle sonar ===" -ForegroundColor Yellow
    Write-Host ""
    if (-not (Test-Path $ClaudeDir)) {
        New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
    }
    if (Test-Path $SonarMarker) {
        Remove-Item $SonarMarker -Force
        Write-Host "  Sonar: OFF -> ON (marker usuniety)" -ForegroundColor Green
    } else {
        New-Item -ItemType File -Path $SonarMarker -Force | Out-Null
        Write-Host "  Sonar: ON -> OFF (marker utworzony: $SonarMarker)" -ForegroundColor Yellow
    }
    Wait-Return
}

function Show-SystemStatus {
    Clear-Host
    Write-Host "=== Status systemu TOST ===" -ForegroundColor Cyan
    Write-Host ""

    Write-Host "-- Pliki stanu (~/.claude/) --" -ForegroundColor DarkCyan
    $files = @(
        "tost_notion.db",
        "tost_ping.db",
        "tost_taryfa.db",
        "tost_sonar.wav",
        "tost_sonar_disabled"
    )
    foreach ($f in $files) {
        $p = Join-Path $ClaudeDir $f
        if (Test-Path $p) {
            $item = Get-Item $p
            $size = if ($item.Length -gt 1MB) { "{0:N2} MB" -f ($item.Length/1MB) }
                    elseif ($item.Length -gt 1KB) { "{0:N1} KB" -f ($item.Length/1KB) }
                    else { "$($item.Length) B" }
            Write-Host ("  [x] {0,-24} {1,10}  {2}" -f $f, $size, $item.LastWriteTime) -ForegroundColor Green
        } else {
            Write-Host ("  [ ] {0,-24} (brak)" -f $f) -ForegroundColor DarkGray
        }
    }

    Write-Host ""
    Write-Host "-- Sonar --" -ForegroundColor DarkCyan
    if (Test-Path $SonarMarker) {
        Write-Host "  Sonar: OFF (marker obecny)" -ForegroundColor Yellow
    } else {
        Write-Host "  Sonar: ON (default)" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "-- Autostart Ping (Task Scheduler) --" -ForegroundColor DarkCyan
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        Write-Host "  $TaskName -> $($task.State)" -ForegroundColor Green
        $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($info) { Write-Host "  Last run: $($info.LastRunTime)  result: $($info.LastTaskResult)" -ForegroundColor DarkGray }
    } else {
        Write-Host "  $TaskName -> niezarejestrowane" -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host "-- Biezace procesy python (tost) --" -ForegroundColor DarkCyan
    $procs = Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match "tost" }
    if ($procs) {
        foreach ($p in $procs) {
            $cmd = $p.CommandLine
            if ($cmd.Length -gt 90) { $cmd = $cmd.Substring(0, 87) + "..." }
            Write-Host ("  PID {0,6}  {1}" -f $p.ProcessId, $cmd) -ForegroundColor White
        }
    } else {
        Write-Host "  (brak aktywnych procesow tost)" -ForegroundColor DarkGray
    }

    Write-Host ""
    Write-Host "-- Zmienne Notion (.env) --" -ForegroundColor DarkCyan
    $envVars = @(
        "NOTION_TOKEN",
        "NOTION_DATABASE_ID",
        "HOLMES_SUSPECTS_DB_ID",
        "PING_NOTION_DB_ID",
        "THC_NOTION_DB_ID",
        "TARYFA_NOTION_DB_ID",
        "TARYFA_NOTION_PARENT_PAGE_ID"
    )
    foreach ($v in $envVars) {
        $val = [Environment]::GetEnvironmentVariable($v)
        if ($val) {
            $masked = if ($v -eq "NOTION_TOKEN") { $val.Substring(0, [Math]::Min(10, $val.Length)) + "..." } else { $val }
            Write-Host ("  [x] {0,-32} = {1}" -f $v, $masked) -ForegroundColor Green
        } else {
            Write-Host ("  [ ] {0,-32} (brak)" -f $v) -ForegroundColor DarkGray
        }
    }

    Wait-Return
}

# Glowna petla (flaga zamiast `break` - w PowerShellu `break` w switch moze
# niespodziewanie wyjsc z otaczajacej petli, wiec uzywamy jawnego warunku)
$exit = $false
while (-not $exit) {
    Show-MainMenu
    $choice = Read-Host "  Wybierz opcje [0-21]"
    switch ($choice) {
        "1"  { Invoke-Monitor }
        "2"  { Invoke-CC }
        "3"  { Invoke-Thc }
        "3m" { Invoke-ThcMini }
        "4"  { Invoke-PingViewer }
        "5"  { Invoke-HolmesTui }
        "6"  { Invoke-SyncAll }
        "7"  { Invoke-SyncLoop }
        "8"  { Invoke-SyncOnce }
        "9"  { Invoke-PingDaemon }
        "10" { Invoke-PingOnce }
        "11" { Invoke-HolmesTerminal }
        "12" { Invoke-HolmesRange }
        "13" { Edit-ConfigFile -Path (Join-Path $projectDir ".env") -Label ".env" }
        "14" { Edit-ConfigFile -Path (Join-Path $projectDir "tost\thc_tiers.toml") -Label "thc_tiers.toml" }
        "15" { Edit-ConfigFile -Path (Join-Path $projectDir "tost\taryfa_thresholds.toml") -Label "taryfa_thresholds.toml" }
        "16" { Edit-ConfigFile -Path (Join-Path $projectDir "tost\holmes_rules.toml") -Label "holmes_rules.toml" }
        "17" { Register-PingAutostart }
        "18" { Unregister-PingAutostart }
        "19" { Show-PingAutostartStatus }
        "20" { Toggle-Sonar }
        "21" { Show-SystemStatus }
        "0"  { $exit = $true }
        ""   { $exit = $true }
        default {
            Write-Host ""
            Write-Host "  Nieznana opcja: '$choice'" -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
