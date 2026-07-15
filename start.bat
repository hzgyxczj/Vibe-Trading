@echo off
cd /d "%~dp0"
echo [1/2] Pulling latest changes from git...
git pull
if %errorlevel% neq 0 (
    echo [warn] Git pull failed, continuing anyway...
)
echo [2/2] Starting Vibe-Trading server...
cd agent
python api_server.py
