# TOST Desktop Launcher

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

Write-Host ""
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host "  |   TOST - Token Optimization System   |" -ForegroundColor Cyan
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host "  |  1) Dashboard - podglad sesji (TUI)  |" -ForegroundColor White
Write-Host "  |  2) Sync      - jednorazowy sync      |" -ForegroundColor Yellow
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host ""
$choice = Read-Host "  Wybierz tryb [1-2, domyslnie=1]"
if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

switch ($choice) {
    "2" {
        $envFile = Join-Path $projectDir ".env"
        if (Test-Path $envFile) {
            Get-Content $envFile | ForEach-Object {
                $line = $_.Trim()
                if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                    $parts = $line -split "=", 2
                    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim())
                }
            }
            Write-Host "  Zaladowano .env" -ForegroundColor DarkGray
        }
        Write-Host ""
        Write-Host "=== Notion Sync - jednorazowy przebieg ===" -ForegroundColor Yellow
        python -m tost sync --once -v
        Write-Host ""
        Write-Host "Nacisnij Enter, aby zamknac..." -ForegroundColor DarkGray
        Read-Host
    }
    default {
        Write-Host ""
        Write-Host "=== TOST Dashboard ===" -ForegroundColor Cyan
        python -m tost monitor
        Write-Host ""
        Write-Host "TOST zakonczony. Nacisnij Enter, aby zamknac." -ForegroundColor DarkGray
        Read-Host
    }
}
