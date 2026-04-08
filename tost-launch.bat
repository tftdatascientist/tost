@echo off
title TOST Launcher
echo ============================================
echo  TOST - Token Overhead Surveillance Tool
echo ============================================
echo.

:: Start TOST collector in a new window
echo [1/2] Starting TOST dashboard...
start "TOST Dashboard" cmd /k "cd /d %~dp0 && python -m tost"

:: Wait for collector to be ready
timeout /t 2 /nobreak >nul

:: Set OTEL env vars and launch Claude Code
echo [2/2] Starting Claude Code with OTEL...
set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
set OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
set OTEL_METRICS_EXPORTER=otlp
echo.
echo OTEL endpoint: %OTEL_EXPORTER_OTLP_ENDPOINT%
echo.
claude %*
