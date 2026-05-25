import discord
from discord.ext import commands
from datetime import datetime, timezone
from database import Database
import random
import logging

log = logging.getLogger("cogs.levels")

XP_PER_MESSAGE_MIN = 15
XP_PER_MESSAGE_MAX = 25

# Standaard level-rollen met hun vereiste level
DEFAULT_LEVEL_ROLES = [
    (1,  "⭐ Level 1"),
    (5,  "⭐⭐ Level 5"),
    (10, "⭐⭐⭐ Level 10"),
    (20, "🌟 Level 20"),
    (30, "🌟🌟 Level 30"),
    (50, "💎 Level 50"),
    (75, "💎💎 Level 75"),
    (100,"👑 Level 100"),
]

# XP cooldown per user (in seconden) om spam te voorkomen
XP_COOLDOWN = 60


class LevelsCog(commands.Cog, name="Levels"):
    """XP- en levelsysteem met automatische roluitdeling."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self._xp_cooldown: dict[tuple, float] = {}  # (guild_id, user_id) -> timestamp

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        key = (message.guild.id, message.author.id)
        now = datetime.now(timezone.utc).timestamp()

        if now - self._xp_cooldown.get(key, 0) < XP_COOLDOWN:
            return

        self._xp_cooldown[key] = now
        xp_gained = random.randint(XP_PER_MESSAGE_MIN, XP_PER_MESSAGE_MAX)
        new_xp, new_level, leveled_up = self.db.add_xp(message.guild.id, message.author.id, xp_gained)

        if leveled_up:
            await self._handle_level_up(message.guild, message.author, new_level, message.channel)

    async def _handle_level_up(self, guild: discord.Guild, member: discord.Member, new_level: int, channel: discord.TextChannel):
        settings = self.db.get_settings(guild.id)
        xp_ch_id = settings["xp_channel"] if settings else None
        notify_channel = guild.get_channel(xp_ch_id) if xp_ch_id else channel

        embed = discord.Embed(
            title="🎉 Level Up!",
            description=f"{member.mention} is nu **Level {new_level}**!",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        xp_needed = Database.xp_for_next_level(new_level)
        embed.add_field(name="Volgend level", value=f"{xp_needed} XP nodig", inline=True)

        await self._assign_level_role(guild, member, new_level, embed)

        if notify_channel:
            await notify_channel.send(embed=embed)

    async def _assign_level_role(self, guild: discord.Guild, member: discord.Member, level: int, embed: discord.Embed = None):
        """Wijs de juiste levelrol toe en verwijder lagere levelrollen."""
        role_row = self.db.get_role_for_level(guild.id, level)
        all_level_roles = self.db.get_level_roles(guild.id)
        all_level_role_ids = {r["role_id"] for r in all_level_roles}

        # Verwijder alle bestaande levelrollen
        roles_to_remove = [r for r in member.roles if r.id in all_level_role_ids]
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason="Levelrol update")
            except discord.Forbidden:
                log.warning(f"Kan levelrollen niet verwijderen van {member}")

        if role_row:
            new_role = guild.get_role(role_row["role_id"])
            if new_role:
                try:
                    await member.add_roles(new_role, reason=f"Level {level} bereikt")
                    if embed:
                        embed.add_field(name="🏅 Nieuwe rol", value=new_role.mention, inline=True)
                except discord.Forbidden:
                    log.warning(f"Kan levelrol niet toewijzen aan {member}")

    # ── Commando's ─────────────────────────────────────────────────────────────

    @commands.command(name="rank", aliases=["level", "rang"])
    async def rank_cmd(self, ctx, member: discord.Member = None):
        """Bekijk jouw rank en XP."""
        member = member or ctx.author
        data = self.db.get_user_level(ctx.guild.id, member.id)

        level = data["level"] if data else 0
        xp = data["xp"] if data else 0

        # Bereken XP binnen huidig level
        xp_in_level = xp
        for lvl in range(level):
            xp_in_level -= Database.xp_for_next_level(lvl)
        xp_needed = Database.xp_for_next_level(level)

        # Ranglijst positie
        lb = self.db.get_leaderboard(ctx.guild.id, limit=500)
        position = next((i + 1 for i, r in enumerate(lb) if r["user_id"] == member.id), "?")

        bar_filled = int((xp_in_level / xp_needed) * 20)
        progress_bar = "█" * bar_filled + "░" * (20 - bar_filled)

        embed = discord.Embed(
            title=f"⭐ Rank — {member.display_name}",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="XP", value=f"**{xp_in_level}** / {xp_needed}", inline=True)
        embed.add_field(name="Positie", value=f"**#{position}**", inline=True)
        embed.add_field(
            name="Voortgang",
            value=f"`{progress_bar}` {int(xp_in_level/xp_needed*100)}%",
            inline=False
        )

        role_row = self.db.get_role_for_level(ctx.guild.id, level)
        if role_row:
            rol = ctx.guild.get_role(role_row["role_id"])
            if rol:
                embed.add_field(name="🏅 Huidige levelrol", value=rol.mention, inline=True)

        await ctx.send(embed=embed)

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def leaderboard_cmd(self, ctx):
        """Bekijk de top 10 meest actieve leden."""
        lb = self.db.get_leaderboard(ctx.guild.id, limit=10)

        embed = discord.Embed(
            title="🏆 Activiteits Leaderboard",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(lb):
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else f"Gebruiker {row['user_id']}"
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(f"{medal} **{name}** — Level {row['level']} ({row['xp']} XP)")

        embed.description = "\n".join(lines) if lines else "Nog geen data beschikbaar."
        await ctx.send(embed=embed)

    @commands.command(name="addxp")
    @commands.has_permissions(administrator=True)
    async def addxp_cmd(self, ctx, member: discord.Member, xp: int):
        """Voeg XP toe aan een lid (admin)."""
        if xp <= 0:
            return await ctx.send("❌ XP moet positief zijn.")
        new_xp, new_level, leveled_up = self.db.add_xp(ctx.guild.id, member.id, xp)
        if leveled_up:
            await self._assign_level_role(ctx.guild, member, new_level)
        await ctx.send(f"✅ **{xp} XP** toegevoegd aan {member.mention}. Totaal: **{new_xp} XP** (Level {new_level}).")

    @commands.command(name="setxp")
    @commands.has_permissions(administrator=True)
    async def setxp_cmd(self, ctx, member: discord.Member, xp: int):
        """Stel de XP van een lid in (admin)."""
        if xp < 0:
            return await ctx.send("❌ XP kan niet negatief zijn.")
        self.db.set_xp(ctx.guild.id, member.id, xp)
        level = Database._calc_level(xp)
        await self._assign_level_role(ctx.guild, member, level)
        await ctx.send(f"✅ XP van {member.mention} ingesteld op **{xp}** (Level {level}).")

    @commands.command(name="levelrollen", aliases=["levelroles", "rollen"])
    async def levelrollen_cmd(self, ctx):
        """Bekijk alle ingestelde levelrollen."""
        roles = self.db.get_level_roles(ctx.guild.id)

        embed = discord.Embed(
            title="🏅 Levelrollen",
            color=discord.Color.blurple()
        )

        if not roles:
            embed.description = "Geen levelrollen ingesteld. Gebruik `!maakrollen` om standaardrollen aan te maken."
        else:
            lines = []
            for r in roles:
                rol = ctx.guild.get_role(r["role_id"])
                rol_str = rol.mention if rol else f"~~{r['role_name']}~~ (verwijderd)"
                lines.append(f"Level **{r['level']}** → {rol_str}")
            embed.description = "\n".join(lines)

        await ctx.send(embed=embed)

    @commands.command(name="maakrollen", aliases=["createroles", "setuproles"])
    @commands.has_permissions(manage_roles=True)
    async def maakrollen_cmd(self, ctx):
        """Maak de standaard levelrollen aan op de server."""
        msg = await ctx.send("⏳ Levelrollen worden aangemaakt...")

        colors = [
            discord.Color.light_grey(),
            discord.Color.green(),
            discord.Color.blue(),
            discord.Color.purple(),
            discord.Color.gold(),
            discord.Color.teal(),
            discord.Color.orange(),
            discord.Color.red(),
        ]

        created = []
        skipped = []
        for i, (level, name) in enumerate(DEFAULT_LEVEL_ROLES):
            existing = discord.utils.get(ctx.guild.roles, name=name)
            if existing:
                self.db.set_level_role(ctx.guild.id, level, existing.id, existing.name)
                skipped.append(f"Level {level}: {existing.mention} (al aanwezig)")
            else:
                try:
                    color = colors[i % len(colors)]
                    new_role = await ctx.guild.create_role(
                        name=name,
                        color=color,
                        reason=f"Levelrol aangemaakt door {ctx.author}"
                    )
                    self.db.set_level_role(ctx.guild.id, level, new_role.id, new_role.name)
                    created.append(f"Level {level}: {new_role.mention}")
                except discord.Forbidden:
                    await msg.edit(content="❌ Ik heb geen toestemming om rollen aan te maken.")
                    return

        embed = discord.Embed(
            title="✅ Levelrollen ingesteld",
            color=discord.Color.green()
        )
        if created:
            embed.add_field(name="🆕 Aangemaakt", value="\n".join(created), inline=False)
        if skipped:
            embed.add_field(name="♻️ Al aanwezig", value="\n".join(skipped), inline=False)

        await msg.delete()
        await ctx.send(embed=embed)

    @commands.command(name="setlevelrol", aliases=["setlevelrole"])
    @commands.has_permissions(manage_roles=True)
    async def setlevelrol_cmd(self, ctx, level: int, rol: discord.Role):
        """Koppel een bestaande rol aan een level."""
        if level < 0:
            return await ctx.send("❌ Level moet positief zijn.")
        self.db.set_level_role(ctx.guild.id, level, rol.id, rol.name)
        await ctx.send(f"✅ {rol.mention} gekoppeld aan Level **{level}**.")

    @commands.command(name="xpkanaal", aliases=["xpchannel", "levelkanaal"])
    @commands.has_permissions(manage_guild=True)
    async def xp_kanaal_cmd(self, ctx, kanaal: discord.TextChannel):
        """Stel het kanaal in voor level-up meldingen."""
        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "xp_channel", kanaal.id)
        await ctx.send(f"✅ Level-up meldingen worden verstuurd naar {kanaal.mention}.")

    @commands.command(name="synclevels", aliases=["syncrollen"])
    @commands.has_permissions(administrator=True)
    async def sync_levels_cmd(self, ctx):
        """Synchroniseer levelrollen voor alle leden op de server."""
        msg = await ctx.send("⏳ Levelrollen worden gesynchroniseerd voor alle leden...")
        count = 0
        for member in ctx.guild.members:
            if member.bot:
                continue
            data = self.db.get_user_level(ctx.guild.id, member.id)
            level = data["level"] if data else 0
            await self._assign_level_role(ctx.guild, member, level)
            count += 1
        await msg.edit(content=f"✅ Levelrollen gesynchroniseerd voor **{count}** leden.")


async def setup(bot):
    await bot.add_cog(LevelsCog(bot))
