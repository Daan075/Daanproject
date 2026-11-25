@echo off
rem Video Zoeker starten op Windows: dubbelklik op dit bestand.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Eerste keer opstarten: alles installeren. Dit kan een paar minuten duren...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist .venv\Scripts\python.exe (
    echo Python niet gevonden. Installeer Python eerst, zie README.md.
    pause
    exit /b 1
  )
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt || (
    echo Installatie mislukt. Zie de foutmelding hierboven.
    pause
    exit /b 1
  )
)
if not exist .env (
  copy .env.example .env >nul
  echo Er is een .env-bestand gemaakt. Zet daar je ANTHROPIC_API_KEY in en start opnieuw.
  notepad .env
)
.venv\Scripts\python.exe -m videozoeker
pause
