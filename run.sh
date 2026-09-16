#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d venv ]; then
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt
fi

(sleep 1 && python3 -c "import webbrowser; webbrowser.open('http://127.0.0.1:5000')") &
venv/bin/python app.py
