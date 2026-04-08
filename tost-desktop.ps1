# TOST Desktop Launcher
# Double-click shortcut runs this script — opens TOST dashboard + CC with OTEL

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Start TOST dashboard in separate PowerShell window ──
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$projectDir'; Write-Host '═══ TOST Dashboard ═══' -ForegroundColor Cyan; python -m tost"
) -WindowStyle Normal

# ── Wait for collector to be ready ──
Start-Sleep -Seconds 2

# ── Start Claude Code with OTEL in another PowerShell window ──
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$projectDir'; `$env:OTEL_EXPORTER_OTLP_ENDPOINT='http://localhost:4318'; `$env:OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'; `$env:OTEL_METRICS_EXPORTER='otlp'; Write-Host '═══ Claude Code + OTEL ═══' -ForegroundColor Green; Write-Host 'OTEL -> localhost:4318' -ForegroundColor DarkGray; claude"
) -WindowStyle Normal
