@echo off
title TOST Launcher
echo ============================================
echo  TOST - Token Optimization System Tool
echo ============================================
echo.
echo  1) Monitor — live token dashboard
echo  2) Duel    — profile vs profile
echo  3) Sim     — cost simulation
echo  4) Train   — context trainer
echo.
set /p "CHOICE=Select mode [1-4, default=1]: "
if "%CHOICE%"=="" set CHOICE=1

if "%CHOICE%"=="2" goto duel
if "%CHOICE%"=="3" goto sim
if "%CHOICE%"=="4" goto train
goto monitor

:duel
echo.
echo Starting TOST Duel...
start "TOST Duel" cmd /k "cd /d %~dp0 && python -m tost duel"
goto end

:sim
echo.
echo Starting TOST Simulator...
start "TOST Sim" cmd /k "cd /d %~dp0 && python -m tost sim"
goto end

:train
echo.
echo Starting TOST Trainer...
start "TOST Trainer" cmd /k "cd /d %~dp0 && python -m tost train"
goto end

:monitor
echo.
echo [1/2] Starting TOST dashboard...
start "TOST Dashboard" cmd /k "cd /d %~dp0 && python -m tost"

:: Wait for collector to be ready
timeout /t 2 /nobreak >nul

:: Start Claude Code (OTEL configured via ~/.claude/settings.json)
echo [2/2] Starting Claude Code...
echo OTEL configured via settings.json
echo.
claude --dangerously-skip-permissions %*

:end
