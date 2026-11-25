@echo off
setlocal
echo Installing Superchat for this Windows account...
where git >nul 2>&1
if errorlevel 1 (
  echo Git is required. Install Git and run this installer again.
  goto :failure
)
where uv >nul 2>&1
if errorlevel 1 (
  echo Installing uv...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 ^| iex"
  if errorlevel 1 goto :failure
  set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
uv tool install --python 3.12 --force git+https://github.com/sasindaran/Superchat
if errorlevel 1 goto :failure
for /f "delims=" %%i in ('uv tool dir --bin') do set "SUPERCHAT_BIN=%%i"
"%SUPERCHAT_BIN%\superchat.exe" setup
if errorlevel 1 goto :failure
echo.
echo If you are already signed in, press Enter to skip sign-in.
set /p "SUPERCHAT_EMAIL=Work email: "
if defined SUPERCHAT_EMAIL (
  "%SUPERCHAT_BIN%\superchat.exe" login --email "%SUPERCHAT_EMAIL%"
  if errorlevel 1 goto :failure
  echo Open the emailed sign-in link on this computer.
)
echo Restart Claude Desktop and start a new Claude Code session.
pause
exit /b 0

:failure
echo Setup did not complete. Check the error above and run the installer again.
pause
exit /b 1
