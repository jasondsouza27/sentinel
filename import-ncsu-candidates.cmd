@echo off
setlocal
cd /d "%~dp0"
if "%~2"=="" (
  echo Usage: import-ncsu-candidates.cmd source.csv candidates.csv --audit-out audit.json --limit 100 --seed 42
  exit /b 2
)
set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" -m sentinel.ncsu_candidates %*
  goto done
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -m sentinel.ncsu_candidates %*
  goto done
)
where python >nul 2>&1
if not errorlevel 1 (
  python -m sentinel.ncsu_candidates %*
  goto done
)
echo Python 3.10 or newer is required. Install it, then retry.
exit /b 2
:done
exit /b %errorlevel%
