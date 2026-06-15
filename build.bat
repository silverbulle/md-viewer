@echo off
echo Building MD Browser...
echo.

pyinstaller ^
  --onefile ^
  --console ^
  --name md-browser ^
  --add-data "index.html;." ^
  --clean ^
  server.py

echo.
if exist dist\md-browser.exe (
    echo Build successful!
    echo Output: dist\md-browser.exe
    echo.
    echo Usage: md-browser.exe [directory]
    echo   Double-click to start, then enter path in browser UI.
) else (
    echo Build failed!
)
pause
