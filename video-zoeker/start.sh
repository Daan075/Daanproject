#!/usr/bin/env bash
# Video Zoeker starten op macOS/Linux: ./start.sh
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Eerste keer opstarten: alles installeren. Dit kan een paar minuten duren..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Er is een .env-bestand gemaakt. Zet daar je ANTHROPIC_API_KEY in en start opnieuw."
  exit 0
fi
exec .venv/bin/python -m videozoeker "$@"
