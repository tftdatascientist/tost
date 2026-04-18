# THC Desktop Launcher — Traffic Hours Console (Matrix TUI)
# -*- coding: utf-8-bom -*-

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

# Zaladuj .env (NOTION_TOKEN, THC_NOTION_DB_ID, itp.)
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

# Konsola UTF-8 (dla blok-znakow wykresu TTFB)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
chcp 65001 > $null

Write-Host ""
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host "  |   THC - Traffic Hours Console            |" -ForegroundColor Green
Write-Host "  |   Anthropic Server Load Radar            |" -ForegroundColor DarkGreen
Write-Host "  +==========================================+" -ForegroundColor Green
Write-Host ""

# Sprawdz czy ping-collect zyje (opcjonalny info)
$pingDb = Join-Path $env:USERPROFILE ".claude\tost_ping.db"
if (-not (Test-Path $pingDb)) {
    Write-Host "  Uwaga: brak tost_ping.db - uruchom 'tost ping-collect' aby zbierac dane" -ForegroundColor Yellow
    Write-Host ""
}

python -m tost thc

Write-Host ""
Write-Host "THC zakonczony. Nacisnij Enter, aby zamknac." -ForegroundColor DarkGray
Read-Host
