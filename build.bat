@echo off
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
)

call venv\Scripts\pip install -q -r requirements-dev.txt

venv\Scripts\pyinstaller --noconfirm MediaConverter.spec

echo.
echo Built: dist\MediaConverter.exe
