import discord
from discord.ext import commands
from datetime import datetime, timezone
import logging

log = logging.getLogger("cogs.warnings")


class WarningsCog(commands.Cog, name="Waarschuwingen"):
    """Waarschuwingssysteem met automatische acties bij meerdere warns."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db

    def _warn_embed(self, color=discord.Color.yellow()) -> discord.Embed:
        return discord.Embed(color=color, timestamp=datetime.now(timezone.utc))

    async def _check_auto_action(self, ctx, member: discord.Member, warn_count: int):
        settings = self.db.get_settings(ctx.guild.id)
        if not settings:
            return

        kick_at = settings["kick_at_warns"]
        ban_at = settings["ban_at_warns"]

        if warn_count >= ban_at:
            try:
                await member.send(
                    f"🔨 Je bent verbannen van **{ctx.guild.name}** na {warn_count} waarschuwingen."
                )
            except discord.Forbidden:
                pass
            await member.ban(reason=f"Automatisch verbannen na {warn_count} warns")
            await ctx.send(f"🔨 **{member.display_name}** is automatisch verbannen ({warn_count} warns).")
        elif warn_count >= kick_at:
            try:
                await member.send(
                    f"👢 Je bent gekicked van **{ctx.guild.name}** na {warn_count} waarschuwingen."
                )
            except discord.Forbidden:
                pass
            await member.kick(reason=f"Automatisch gekicked na {warn_count} warns")
            await ctx.send(f"👢 **{member.display_name}** is automatisch gekicked ({warn_count} warns).")

    # ── Commando's ─────────────────────────────────────────────────────────────

    @commands.command(name="warn")
    @commands.has_permissions(kick_members=True)
    async def warn_cmd(self, ctx, member: discord.Member, *, reden: str = "Geen reden opgegeven"):
        """Geef een waarschuwing aan een lid."""
        if member == ctx.author:
            return await ctx.send("❌ Je kunt jezelf geen waarschuwing geven.")
        if member.bot:
            return await ctx.send("❌ Je kunt een bot geen waarschuwing geven.")
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send("❌ Je kunt geen waarschuwing geven aan iemand met een gelijke of hogere rol.")

        self.db.ensure_settings(ctx.guild.id)
        warn_id = self.db.add_warning(ctx.guild.id, member.id, ctx.author.id, reden)
        warn_count = self.db.count_warnings(ctx.guild.id, member.id)

        embed = self._warn_embed(discord.Color.yellow())
        embed.title = "⚠️ Waarschuwing uitgedeeld"
        embed.add_field(name="Lid", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Warn #", value=f"`#{warn_id}`", inline=True)
        embed.add_field(name="Reden", value=reden, inline=False)
        embed.add_field(name="Totaal warns", value=f"**{warn_count}**", inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

        try:
            dm_embed = discord.Embed(
                title=f"⚠️ Waarschuwing ontvangen op {ctx.guild.name}",
                color=discord.Color.yellow(),
                timestamp=datetime.now(timezone.utc)
            )
            dm_embed.add_field(name="Reden", value=reden, inline=False)
            dm_embed.add_field(name="Moderator", value=str(ctx.author), inline=True)
            dm_embed.add_field(name="Warn ID", value=f"`#{warn_id}`", inline=True)
            dm_embed.add_field(name="Totaal warns", value=str(warn_count), inline=True)
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        log_ch_id = self.db.get_settings(ctx.guild.id)["warn_channel"] if self.db.get_settings(ctx.guild.id) else None
        if log_ch_id:
            log_channel = ctx.guild.get_channel(log_ch_id)
            if log_channel:
                await log_channel.send(embed=embed)

        await self._check_auto_action(ctx, member, warn_count)

    @commands.command(name="warns", aliases=["warnings", "waarschuwingen"])
    @commands.has_permissions(kick_members=True)
    async def warns_cmd(self, ctx, member: discord.Member):
        """Bekijk de actieve waarschuwingen van een lid."""
        warns = self.db.get_warnings(ctx.guild.id, member.id)

        embed = discord.Embed(
            title=f"⚠️ Waarschuwingen — {member.display_name}",
            color=discord.Color.orange() if warns else discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.description = f"Totaal actieve warns: **{len(warns)}**"

        if not warns:
            embed.description = "✅ Geen actieve waarschuwingen."
        else:
            for w in warns[:10]:
                mod = ctx.guild.get_member(w["mod_id"])
                mod_str = str(mod) if mod else f"<@{w['mod_id']}>"
                try:
                    ts = datetime.fromisoformat(w["created_at"]).strftime("%d-%m-%Y %H:%M")
                except ValueError:
                    ts = w["created_at"]
                embed.add_field(
                    name=f"#{w['id']} — {ts}",
                    value=f"**Reden:** {w['reason']}\n**Mod:** {mod_str}",
                    inline=False
                )
            if len(warns) > 10:
                embed.set_footer(text=f"... en {len(warns) - 10} meer warns")

        await ctx.send(embed=embed)

    @commands.command(name="clearwarn", aliases=["removewarn", "delwarn"])
    @commands.has_permissions(kick_members=True)
    async def clearwarn_cmd(self, ctx, member: discord.Member, warn_id: int):
        """Verwijder een specifieke waarschuwing op ID."""
        warn = self.db.get_warning_by_id(warn_id)
        if not warn or warn["guild_id"] != ctx.guild.id or warn["user_id"] != member.id:
            return await ctx.send(f"❌ Warn `#{warn_id}` niet gevonden voor dit lid.")
        if not warn["active"]:
            return await ctx.send(f"❌ Warn `#{warn_id}` is al verwijderd.")

        self.db.remove_warning(warn_id)
        remaining = self.db.count_warnings(ctx.guild.id, member.id)

        embed = discord.Embed(
            title="✅ Waarschuwing verwijderd",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Lid", value=member.mention, inline=True)
        embed.add_field(name="Warn ID", value=f"`#{warn_id}`", inline=True)
        embed.add_field(name="Verwijderd door", value=ctx.author.mention, inline=True)
        embed.add_field(name="Resterende warns", value=str(remaining), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="clearallwarns", aliases=["clearwarns", "wipewarns"])
    @commands.has_permissions(administrator=True)
    async def clearallwarns_cmd(self, ctx, member: discord.Member):
        """Verwijder alle waarschuwingen van een lid."""
        count = self.db.count_warnings(ctx.guild.id, member.id)
        self.db.clear_all_warnings(ctx.guild.id, member.id)

        embed = discord.Embed(
            title="✅ Alle waarschuwingen gewist",
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Lid", value=member.mention, inline=True)
        embed.add_field(name="Verwijderd", value=f"{count} warns", inline=True)
        embed.add_field(name="Gedaan door", value=ctx.author.mention, inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="warninfo")
    @commands.has_permissions(kick_members=True)
    async def warninfo_cmd(self, ctx, warn_id: int):
        """Bekijk details van een specifieke waarschuwing."""
        warn = self.db.get_warning_by_id(warn_id)
        if not warn or warn["guild_id"] != ctx.guild.id:
            return await ctx.send(f"❌ Warn `#{warn_id}` niet gevonden.")

        member = ctx.guild.get_member(warn["user_id"])
        mod = ctx.guild.get_member(warn["mod_id"])

        try:
            ts = datetime.fromisoformat(warn["created_at"]).strftime("%d-%m-%Y %H:%M UTC")
        except ValueError:
            ts = warn["created_at"]

        embed = discord.Embed(
            title=f"⚠️ Warn info — #{warn_id}",
            color=discord.Color.yellow() if warn["active"] else discord.Color.dark_gray(),
            timestamp=datetime.now(timezone.utc)
        )
        user_id = warn["user_id"]
        mod_id = warn["mod_id"]
        embed.add_field(name="Lid", value=member.mention if member else f"<@{user_id}>", inline=True)
        embed.add_field(name="Moderator", value=mod.mention if mod else f"<@{mod_id}>", inline=True)
        embed.add_field(name="Status", value="Actief ✅" if warn["active"] else "Verwijderd ❌", inline=True)
        embed.add_field(name="Reden", value=warn["reason"], inline=False)
        embed.add_field(name="Datum", value=ts, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="setwarnkanaal", aliases=["setwarnlogchannel"])
    @commands.has_permissions(manage_guild=True)
    async def setwarnkanaal_cmd(self, ctx, kanaal: discord.TextChannel):
        """Stel het kanaal in voor warnlogs."""
        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "warn_channel", kanaal.id)
        await ctx.send(f"✅ Warn log kanaal ingesteld op {kanaal.mention}.")

    @commands.command(name="kickbijwarns", aliases=["setkickat"])
    @commands.has_permissions(administrator=True)
    async def set_kick_at_cmd(self, ctx, aantal: int):
        """Stel in bij hoeveel warns iemand automatisch gekicked wordt."""
        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "kick_at_warns", aantal)
        await ctx.send(f"✅ Automatisch kick bij **{aantal}** warns ingesteld.")

    @commands.command(name="banbijwarns", aliases=["setbanat"])
    @commands.has_permissions(administrator=True)
    async def set_ban_at_cmd(self, ctx, aantal: int):
        """Stel in bij hoeveel warns iemand automatisch verbannen wordt."""
        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "ban_at_warns", aantal)
        await ctx.send(f"✅ Automatisch ban bij **{aantal}** warns ingesteld.")


async def setup(bot):
    await bot.add_cog(WarningsCog(bot))
