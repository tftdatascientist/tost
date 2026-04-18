# Ping Desktop Launcher
# -*- coding: utf-8-bom -*-

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

# Zaladuj .env
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

Write-Host ""
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host "  |   TOST Ping - API Latency Monitor        |" -ForegroundColor Green
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host "  |  1) Daemon   - ciagly pomiar co 5 min    |" -ForegroundColor White
Write-Host "  |  2) Raz      - jeden pomiar i wyjscie    |" -ForegroundColor Yellow
Write-Host "  |  3) Podglad  - TUI z wynikami            |" -ForegroundColor Cyan
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host ""
$choice = Read-Host "  Wybierz tryb [1-3, domyslnie=1]"
if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

switch ($choice) {
    "2" {
        Write-Host ""
        Write-Host "=== Ping - pojedynczy pomiar ===" -ForegroundColor Yellow
        python -m tost ping-collect --once -v
        Write-Host ""
        Write-Host "Nacisnij Enter, aby zamknac..." -ForegroundColor DarkGray
        Read-Host
    }
    "3" {
        Write-Host ""
        Write-Host "=== Ping TUI ===" -ForegroundColor Cyan
        python -m tost ping
        Write-Host ""
        Write-Host "Ping zakonczony. Nacisnij Enter, aby zamknac." -ForegroundColor DarkGray
        Read-Host
    }
    default {
        Write-Host ""
        Write-Host "=== Ping Daemon (Ctrl+C aby zatrzymac) ===" -ForegroundColor Green
        python -m tost ping-collect -v
        Write-Host ""
        Write-Host "Ping zakonczony. Nacisnij Enter, aby zamknac." -ForegroundColor DarkGray
        Read-Host
    }
}
