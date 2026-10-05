@echo off
setlocal
cd /d "%~dp0"
set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" -m sentinel.server
  goto done
)
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m sentinel.server
  goto done
)
where python >nul 2>&1
if %errorlevel%==0 (
  python -m sentinel.server
  goto done
)
echo Python 3.10 or newer is required. Install it, then run this file again.
:done
if errorlevel 1 pause
