import discord
from discord.ext import commands
from datetime import datetime, timezone
import logging

log = logging.getLogger("cogs.admin")


class AdminCog(commands.Cog, name="Admin"):
    """Beheertaken en server setup."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    @commands.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def setup_cmd(self, ctx):
        """Interactieve setup wizard voor de bot."""
        self.db.ensure_settings(ctx.guild.id)

        embed = discord.Embed(
            title="🛠️ Bot Setup",
            description=(
                "Gebruik de volgende commando's om de bot in te stellen:\n\n"
                "**Stap 1 — Log kanalen**\n"
                "`!setactief #kanaal` — Activiteits-/staffrapporten\n"
                "`!setwarnkanaal #kanaal` — Warn logs\n"
                "`!xpkanaal #kanaal` — Level-up meldingen\n\n"
                "**Stap 2 — Rollen bijhouden**\n"
                "`!staffrol @rol` — Voeg een staffrol toe\n"
                "`!trackrol @rol` — Voeg andere rang toe\n\n"
                "**Stap 3 — Activiteitsdrempel**\n"
                "`!minimumberichten 20` — Min. berichten per week\n"
                "`!minimumvoice 0` — Min. voice-minuten per week\n\n"
                "**Stap 4 — Levelrollen**\n"
                "`!maakrollen` — Maak standaard levelrollen aan\n\n"
                "**Stap 5 — Warn acties**\n"
                "`!kickbijwarns 5` — Kick bij N warns\n"
                "`!banbijwarns 10` — Ban bij N warns"
            ),
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Gebruik !instellingen om de huidige instellingen te bekijken.")
        await ctx.send(embed=embed)

    @commands.command(name="instellingen", aliases=["settings", "config"])
    @commands.has_permissions(manage_guild=True)
    async def instellingen_cmd(self, ctx):
        """Bekijk de huidige botinstellingen."""
        self.db.ensure_settings(ctx.guild.id)
        s = self.db.get_settings(ctx.guild.id)

        def ch(id_):
            if not id_:
                return "❌ Niet ingesteld"
            ch = ctx.guild.get_channel(id_)
            return ch.mention if ch else f"❌ Verwijderd ({id_})"

        log_ch = ch(s["log_channel"])
        warn_ch = ch(s["warn_channel"])
        xp_ch = ch(s["xp_channel"])

        staff_roles = self.db.get_staff_roles(ctx.guild.id)
        tracked_roles = self.db.get_tracked_roles(ctx.guild.id)
        level_roles = self.db.get_level_roles(ctx.guild.id)

        staff_str = ", ".join(
            f"<@&{r['role_id']}>" for r in staff_roles
        ) if staff_roles else "❌ Geen ingesteld"

        tracked_str = ", ".join(
            f"<@&{r['role_id']}>" for r in tracked_roles
        ) if tracked_roles else "❌ Geen ingesteld"

        embed = discord.Embed(
            title=f"⚙️ Instellingen — {ctx.guild.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(
            name="📢 Kanalen",
            value=(
                f"Activiteitslog: {log_ch}\n"
                f"Warn log: {warn_ch}\n"
                f"Level-up: {xp_ch}"
            ),
            inline=False
        )
        embed.add_field(
            name="👥 Bijgehouden rollen",
            value=(
                f"Staff: {staff_str}\n"
                f"Overig: {tracked_str}"
            ),
            inline=False
        )
        embed.add_field(
            name="📊 Activiteitsdrempel",
            value=(
                f"Min. berichten/week: **{s['min_messages']}**\n"
                f"Min. voice min/week: **{s['min_voice_minutes']}**\n"
                f"Automatisch waarschuwen: **{'Ja' if s['warn_at_inactive'] else 'Nee'}**"
            ),
            inline=False
        )
        embed.add_field(
            name="⚠️ Warn acties",
            value=(
                f"Kick bij: **{s['kick_at_warns']} warns**\n"
                f"Ban bij: **{s['ban_at_warns']} warns**"
            ),
            inline=False
        )
        embed.add_field(
            name="⭐ Levelrollen",
            value=f"**{len(level_roles)}** levelrollen ingesteld",
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name="autoaktief", aliases=["autowarn"])
    @commands.has_permissions(manage_guild=True)
    async def auto_warn_cmd(self, ctx, aan_uit: str):
        """Schakel automatisch waarschuwen bij inactiviteit in/uit. (aan/uit)"""
        if aan_uit.lower() in ("aan", "on", "true", "1"):
            val = 1
            status = "ingeschakeld ✅"
        elif aan_uit.lower() in ("uit", "off", "false", "0"):
            val = 0
            status = "uitgeschakeld ❌"
        else:
            return await ctx.send("❌ Gebruik `aan` of `uit`.")

        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "warn_at_inactive", val)
        await ctx.send(f"✅ Automatisch waarschuwen bij inactiviteit is **{status}**.")

    @commands.command(name="serverinfo")
    @commands.has_permissions(manage_guild=True)
    async def serverinfo_cmd(self, ctx):
        """Bekijk server activiteitsstatistieken."""
        all_activity = self.db.get_all_activity(ctx.guild.id)
        settings = self.db.get_settings(ctx.guild.id)
        min_msg = settings["min_messages"] if settings else 20

        total_members = len([m for m in ctx.guild.members if not m.bot])
        tracked_members = len(all_activity)
        active_this_week = sum(1 for a in all_activity if a["week_messages"] >= min_msg)
        total_messages = sum(a["total_messages"] for a in all_activity)
        total_voice = sum(a["total_voice_min"] for a in all_activity)

        embed = discord.Embed(
            title=f"📈 Serverstatistieken — {ctx.guild.name}",
            color=discord.Color.blue(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.add_field(
            name="👥 Leden",
            value=(
                f"Totaal: **{total_members}**\n"
                f"Bijgehouden: **{tracked_members}**\n"
                f"Actief deze week: **{active_this_week}**"
            ),
            inline=True
        )
        embed.add_field(
            name="📊 Globale activiteit",
            value=(
                f"Totaal berichten: **{total_messages:,}**\n"
                f"Totaal voice-min: **{total_voice:,}**"
            ),
            inline=True
        )

        level_data = self.db.get_leaderboard(ctx.guild.id, limit=500)
        avg_level = sum(r["level"] for r in level_data) / len(level_data) if level_data else 0
        embed.add_field(
            name="⭐ Levels",
            value=f"Gemiddeld level: **{avg_level:.1f}**\nActieve levelers: **{len(level_data)}**",
            inline=True
        )
        await ctx.send(embed=embed)

    @commands.command(name="verwijderstaffrol", aliases=["removestaffrole"])
    @commands.has_permissions(manage_guild=True)
    async def verwijder_staffrol_cmd(self, ctx, rol: discord.Role):
        """Verwijder een staffrol uit de tracking."""
        self.db.remove_staff_role(ctx.guild.id, rol.id)
        await ctx.send(f"✅ **{rol.name}** verwijderd uit staffrol tracking.")


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
