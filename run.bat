@echo off
cd /d "%~dp0"

if not exist venv (
    python -m venv venv
    call venv\Scripts\pip install -r requirements.txt
)

call venv\Scripts\python app.py
