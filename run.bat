@echo off
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist config\config.yaml copy config\config.example.yaml config\config.yaml
python -m app.main
