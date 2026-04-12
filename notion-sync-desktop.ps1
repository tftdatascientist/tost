# TOST Notion Sync - desktop launcher
# Loads .env, runs notion_sync in a loop (or --once with flag)

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host "  |   TOST - Notion Sync                 |" -ForegroundColor Cyan
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host "  |  1) Continuous - sync every 60s      |" -ForegroundColor White
Write-Host "  |  2) Once      - single pass and exit |" -ForegroundColor Yellow
Write-Host "  +======================================+" -ForegroundColor Cyan
Write-Host ""
$choice = Read-Host "  Select mode [1-2, default=1]"
if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

# Load .env file
$envFile = Join-Path $projectDir ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line -split "=", 2
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim())
        }
    }
    Write-Host "  Loaded .env" -ForegroundColor DarkGray
}
else {
    Write-Host "  Warning: .env not found - ensure NOTION_TOKEN and NOTION_DATABASE_ID are set" -ForegroundColor Red
}

Set-Location $projectDir

switch ($choice) {
    "2" {
        Write-Host ""
        Write-Host "=== Notion Sync - single pass ===" -ForegroundColor Yellow
        python -m tost sync --once -v
    }
    default {
        Write-Host ""
        Write-Host "=== Notion Sync - continuous (Ctrl+C to stop) ===" -ForegroundColor Cyan
        python -m tost sync -v
    }
}
