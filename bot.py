"""
PiDash launcher voor de Discord Roleplay Activiteitsbot.
PiDash detecteert dit bestand automatisch als startpunt.
"""
import sys
import os

_root = os.path.dirname(os.path.abspath(__file__))
_bot_dir = os.path.join(_root, "discord_bot")

# Zorg dat discord_bot/ vindbaar is voor imports
sys.path.insert(0, _bot_dir)

# Wissel naar discord_bot/ zodat database + .env op de juiste plek staan
os.chdir(_bot_dir)

from bot import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
