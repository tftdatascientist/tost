# Holmes Desktop Launcher
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
Write-Host "  +==========================================+" -ForegroundColor Magenta
Write-Host "  |   Holmes - Token Anomaly Detector        |" -ForegroundColor Magenta
Write-Host "  +==========================================+" -ForegroundColor Magenta
Write-Host "  |  1) TUI      - interaktywna analiza      |" -ForegroundColor White
Write-Host "  |  2) Terminal - wyniki w konsoli          |" -ForegroundColor Yellow
Write-Host "  +==========================================+" -ForegroundColor Magenta
Write-Host ""
$choice = Read-Host "  Wybierz tryb [1-2, domyslnie=1]"
if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

switch ($choice) {
    "2" {
        Write-Host ""
        Write-Host "=== Holmes - tryb konsolowy ===" -ForegroundColor Yellow
        python -m tost holmes --no-tui
        Write-Host ""
        Write-Host "Nacisnij Enter, aby zamknac..." -ForegroundColor DarkGray
        Read-Host
    }
    default {
        Write-Host ""
        Write-Host "=== Holmes TUI ===" -ForegroundColor Magenta
        python -m tost holmes
        Write-Host ""
        Write-Host "Holmes zakonczony. Nacisnij Enter, aby zamknac." -ForegroundColor DarkGray
        Read-Host
    }
}
