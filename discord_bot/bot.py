import discord
from discord.ext import commands, tasks
import os
import asyncio
import logging
from dotenv import load_dotenv
from database import Database

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("bot")

COGS = ["cogs.activity", "cogs.warnings", "cogs.levels", "cogs.admin"]

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=os.getenv("PREFIX", "!"), intents=intents, help_command=None)
bot.db = Database("roleplay_bot.db")


@bot.event
async def on_ready():
    log.info(f"Ingelogd als {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="de server activiteit")
    )
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            log.info(f"Cog geladen: {cog}")
        except Exception as e:
            log.error(f"Fout bij laden {cog}: {e}")
    try:
        synced = await bot.tree.sync()
        log.info(f"{len(synced)} slash commands gesynchroniseerd")
    except Exception as e:
        log.error(f"Slash command sync mislukt: {e}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Je hebt geen toestemming voor dit commando.", delete_after=10)
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Lid niet gevonden.", delete_after=10)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missend argument: `{error.param.name}`", delete_after=10)
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        log.error(f"Onverwachte fout: {error}")


@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="📋 Bot Help — Roleplay Activiteitssysteem",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="⚔️ Activiteit",
        value=(
            "`!activiteit [@lid]` — Bekijk activiteit\n"
            "`!weekrapport` — Wekelijks staffrapport\n"
            "`!staffcheck` — Handmatige staffcontrole\n"
            "`!setactief <kanaal>` — Stel log kanaal in\n"
            "`!minimumberichten <aantal>` — Stel minimum berichten in\n"
            "`!staffrol <rol>` — Voeg staffrol toe aan tracking"
        ),
        inline=False
    )
    embed.add_field(
        name="⚠️ Waarschuwingen",
        value=(
            "`!warn @lid [reden]` — Geef een waarschuwing\n"
            "`!warns @lid` — Bekijk waarschuwingen\n"
            "`!clearwarn @lid <id>` — Verwijder waarschuwing\n"
            "`!clearallwarns @lid` — Verwijder alle warns\n"
            "`!warninfo <id>` — Bekijk warn details"
        ),
        inline=False
    )
    embed.add_field(
        name="⭐ Levels",
        value=(
            "`!rank [@lid]` — Bekijk rank/level\n"
            "`!leaderboard` — Top 10 actieve leden\n"
            "`!setxp @lid <xp>` — Stel XP in (admin)\n"
            "`!addxp @lid <xp>` — Voeg XP toe (admin)\n"
            "`!levelrollen` — Bekijk alle levelrollen\n"
            "`!maakrollen` — Maak levelrollen aan"
        ),
        inline=False
    )
    embed.add_field(
        name="🛠️ Admin",
        value=(
            "`!setup` — Server setup wizard\n"
            "`!instellingen` — Bekijk instellingen\n"
            "`!resetweek` — Reset wekelijkse tellers\n"
            "`!xpkanaal <kanaal>` — Stel XP log kanaal in"
        ),
        inline=False
    )
    embed.set_footer(text=f"Prefix: {bot.command_prefix}")
    await ctx.send(embed=embed)


async def main():
    async with bot:
        await bot.start(os.getenv("DISCORD_TOKEN"))


if __name__ == "__main__":
    asyncio.run(main())
