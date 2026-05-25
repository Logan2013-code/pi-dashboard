#!/bin/bash
# Start script voor de Roleplay Discord Bot

cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
    echo "❌ .env bestand niet gevonden!"
    echo "   Kopieer .env.example naar .env en vul je token in:"
    echo "   cp .env.example .env"
    exit 1
fi

if [ ! -d "venv" ]; then
    echo "⏳ Virtuele omgeving aanmaken..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

echo "🤖 Bot wordt gestart..."
python bot.py
