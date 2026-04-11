# TOST Desktop Launcher
# Double-click shortcut runs this script — shows mode menu, then launches chosen mode

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Mode selection menu ──
Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   TOST — Token Optimization System   ║" -ForegroundColor Cyan
Write-Host "  ╠══════════════════════════════════════╣" -ForegroundColor Cyan
Write-Host "  ║  1) Monitor — live token dashboard   ║" -ForegroundColor White
Write-Host "  ║  2) Duel    — profile vs profile     ║" -ForegroundColor Yellow
Write-Host "  ║  3) Sim     — cost simulation        ║" -ForegroundColor Green
Write-Host "  ║  4) Train   — context trainer         ║" -ForegroundColor Magenta
Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
$choice = Read-Host "  Select mode [1-4, default=1]"
if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

switch ($choice) {
    "2" {
        # ── Duel mode — standalone, no CC needed ──
        Start-Process powershell -ArgumentList @(
            "-NoExit",
            "-Command",
            "Set-Location '$projectDir'; Write-Host '═══ TOST Duel Mode ═══' -ForegroundColor Yellow; python -m tost duel"
        ) -WindowStyle Normal
    }
    "3" {
        # ── Sim mode — standalone ──
        Start-Process powershell -ArgumentList @(
            "-NoExit",
            "-Command",
            "Set-Location '$projectDir'; Write-Host '═══ TOST Simulator ═══' -ForegroundColor Green; python -m tost sim"
        ) -WindowStyle Normal
    }
    "4" {
        # ── Trainer mode — standalone ──
        Start-Process powershell -ArgumentList @(
            "-NoExit",
            "-Command",
            "Set-Location '$projectDir'; Write-Host '═══ TOST Trainer ═══' -ForegroundColor Magenta; python -m tost train"
        ) -WindowStyle Normal
    }
    default {
        # ── Monitor mode — dashboard + CC ──
        Start-Process powershell -ArgumentList @(
            "-NoExit",
            "-Command",
            "Set-Location '$projectDir'; Write-Host '═══ TOST Dashboard ═══' -ForegroundColor Cyan; python -m tost"
        ) -WindowStyle Normal

        Start-Sleep -Seconds 2

        Start-Process powershell -ArgumentList @(
            "-NoExit",
            "-Command",
            "Set-Location '$projectDir'; Write-Host '═══ Claude Code + TOST ═══' -ForegroundColor Green; Write-Host 'OTEL -> localhost:4318 (via settings.json)' -ForegroundColor DarkGray; claude --dangerously-skip-permissions"
        ) -WindowStyle Normal
    }
}
