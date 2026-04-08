@echo off
echo Inicjalizacja NoxPos...

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Blad: Python nie jest zainstalowany! Pobierz go ze strony python.org.
    pause
    exit /b
)

:: Install dependencies
echo Instalowanie wymaganych bibliotek...
pip install -r requirements.txt --quiet --default-timeout=100

:: Initialize database
echo Konfiguracja bazy danych...
python init_db.py

:: Start the app
echo Start aplikacji na http://127.0.0.1:5000
start http://127.0.0.1:5000
python app.py

pause
