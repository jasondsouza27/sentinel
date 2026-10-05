@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: curate-sentinel.cmd init^|prepare^|finalize^|freeze^|evaluate data\curation
  pause
  exit /b 2
)
set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" -m sentinel.curation %*
  goto done
)
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m sentinel.curation %*
  goto done
)
where python >nul 2>&1
if %errorlevel%==0 (
  python -m sentinel.curation %*
  goto done
)
echo Python 3.10 or newer is required. Install it, then retry.
:done
if errorlevel 1 pause
