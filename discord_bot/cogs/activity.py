import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
import logging

log = logging.getLogger("cogs.activity")

VOICE_CHECK_INTERVAL = 5  # minutes


class ActivityCog(commands.Cog, name="Activiteit"):
    """Houdt berichtenactiviteit en voice-tijd bij voor staff en andere rangen."""

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db
        self._voice_join: dict[tuple, datetime] = {}  # (guild_id, user_id) -> join time
        self.voice_tracker.start()
        self.weekly_check.start()

    def cog_unload(self):
        self.voice_tracker.cancel()
        self.weekly_check.cancel()

    # ── Event: bericht tellen ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        self.db.add_message(message.guild.id, message.author.id)

    # ── Event: voice bijhouden ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        key = (member.guild.id, member.id)
        if before.channel is None and after.channel is not None:
            self._voice_join[key] = datetime.now(timezone.utc)
        elif before.channel is not None and after.channel is None:
            join_time = self._voice_join.pop(key, None)
            if join_time:
                minutes = int((datetime.now(timezone.utc) - join_time).total_seconds() / 60)
                if minutes > 0:
                    self.db.add_voice_minutes(member.guild.id, member.id, minutes)

    # ── Taak: voice sessies bijhouden per interval ────────────────────────────

    @tasks.loop(minutes=VOICE_CHECK_INTERVAL)
    async def voice_tracker(self):
        now = datetime.now(timezone.utc)
        for (guild_id, user_id), join_time in list(self._voice_join.items()):
            minutes = int((now - join_time).total_seconds() / 60)
            if minutes >= VOICE_CHECK_INTERVAL:
                self.db.add_voice_minutes(guild_id, user_id, VOICE_CHECK_INTERVAL)
                self._voice_join[(guild_id, user_id)] = now

    @voice_tracker.before_loop
    async def before_voice_tracker(self):
        await self.bot.wait_until_ready()

    # ── Taak: wekelijkse check ────────────────────────────────────────────────

    @tasks.loop(hours=168)  # elke week
    async def weekly_check(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self._run_staff_check(guild, automated=True)
            self.db.reset_weekly(guild.id)
            log.info(f"Wekelijkse check uitgevoerd voor guild {guild.id}")

    @weekly_check.before_loop
    async def before_weekly_check(self):
        await self.bot.wait_until_ready()
        # Wacht tot volgende maandag 09:00 UTC
        now = datetime.now(timezone.utc)
        days_until_monday = (7 - now.weekday()) % 7 or 7
        next_monday = (now + timedelta(days=days_until_monday)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        wait_secs = (next_monday - now).total_seconds()
        log.info(f"Wekelijkse check start over {wait_secs/3600:.1f} uur")
        await discord.utils.sleep_until(next_monday)

    # ── Hulpfunctie: staffcheck uitvoeren ─────────────────────────────────────

    async def _run_staff_check(self, guild: discord.Guild, automated: bool = False):
        settings = self.db.get_settings(guild.id)
        if not settings:
            return

        staff_role_rows = self.db.get_staff_roles(guild.id)
        tracked_role_rows = self.db.get_tracked_roles(guild.id)
        all_tracked_role_ids = {r["role_id"] for r in staff_role_rows} | {r["role_id"] for r in tracked_role_rows}

        if not all_tracked_role_ids:
            return

        min_msg = settings["min_messages"]
        min_voice = settings["min_voice_minutes"]
        log_ch_id = settings["log_channel"]
        do_warn = bool(settings["warn_at_inactive"])

        log_channel = guild.get_channel(log_ch_id) if log_ch_id else None

        inactive_members = []
        active_count = 0
        total_count = 0
        warn_count = 0

        for member in guild.members:
            if member.bot:
                continue
            member_role_ids = {r.id for r in member.roles}
            if not member_role_ids & all_tracked_role_ids:
                continue

            total_count += 1
            activity = self.db.get_activity(guild.id, member.id)
            msgs = activity["week_messages"] if activity else 0
            voice = activity["week_voice_min"] if activity else 0

            if msgs >= min_msg or voice >= min_voice:
                active_count += 1
            else:
                inactive_members.append((member, msgs, voice))
                if do_warn:
                    reason = (
                        f"Inactiviteit — {msgs}/{min_msg} berichten, "
                        f"{voice}/{min_voice} voice-minuten deze week"
                    )
                    warn_id = self.db.add_warning(guild.id, member.id, self.bot.user.id, reason)
                    warn_count += 1
                    try:
                        await member.send(
                            f"⚠️ Je hebt een automatische waarschuwing ontvangen op **{guild.name}**.\n"
                            f"**Reden:** {reason}\n"
                            f"Warn ID: `#{warn_id}`"
                        )
                    except discord.Forbidden:
                        pass

        self.db.log_activity_check(guild.id, total_count, active_count, warn_count)

        if not log_channel:
            return

        label = "🤖 Automatische" if automated else "🔍 Handmatige"
        embed = discord.Embed(
            title=f"{label} Wekelijkse Activiteitscheck",
            color=discord.Color.orange() if inactive_members else discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(
            name="📊 Overzicht",
            value=(
                f"**Totaal bijgehouden leden:** {total_count}\n"
                f"**Actief:** {active_count} ✅\n"
                f"**Inactief:** {len(inactive_members)} ❌\n"
                f"**Uitgedeelde warns:** {warn_count}"
            ),
            inline=False
        )
        embed.add_field(
            name="📏 Drempelwaarden",
            value=f"Berichten: **{min_msg}** | Voice: **{min_voice} min**",
            inline=False
        )

        if inactive_members:
            lines = []
            for member, msgs, voice in inactive_members[:15]:
                lines.append(f"• {member.mention} — {msgs} berichten, {voice} min voice")
            if len(inactive_members) > 15:
                lines.append(f"*...en {len(inactive_members) - 15} meer*")
            embed.add_field(name="❌ Inactieve leden", value="\n".join(lines), inline=False)

        await log_channel.send(embed=embed)

    # ── Commando's ─────────────────────────────────────────────────────────────

    @commands.command(name="activiteit", aliases=["activity", "stats"])
    async def activity_cmd(self, ctx, member: discord.Member = None):
        """Bekijk de activiteitsstats van een lid."""
        member = member or ctx.author
        data = self.db.get_activity(ctx.guild.id, member.id)
        level_data = self.db.get_user_level(ctx.guild.id, member.id)
        settings = self.db.get_settings(ctx.guild.id)

        min_msg = settings["min_messages"] if settings else 20
        min_voice = settings["min_voice_minutes"] if settings else 0

        msgs = data["week_messages"] if data else 0
        voice = data["week_voice_min"] if data else 0
        total_msgs = data["total_messages"] if data else 0
        total_voice = data["total_voice_min"] if data else 0
        level = level_data["level"] if level_data else 0
        xp = level_data["xp"] if level_data else 0

        is_active = msgs >= min_msg or voice >= min_voice
        status = "✅ Actief" if is_active else "❌ Inactief"
        color = discord.Color.green() if is_active else discord.Color.red()

        embed = discord.Embed(
            title=f"📊 Activiteit — {member.display_name}",
            color=color
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Deze week",
            value=(
                f"💬 Berichten: **{msgs}** / {min_msg}\n"
                f"🎙️ Voice: **{voice}** min / {min_voice} min\n"
                f"Status: {status}"
            ),
            inline=True
        )
        embed.add_field(
            name="Totaal",
            value=(
                f"💬 Berichten: **{total_msgs}**\n"
                f"🎙️ Voice: **{total_voice}** min\n"
                f"⭐ Level: **{level}** ({xp} XP)"
            ),
            inline=True
        )

        warn_count = self.db.count_warnings(ctx.guild.id, member.id)
        embed.add_field(name="⚠️ Actieve warns", value=str(warn_count), inline=True)

        if data and data["last_message"]:
            try:
                last = datetime.fromisoformat(data["last_message"])
                embed.set_footer(text=f"Laatste bericht: {last.strftime('%d-%m-%Y %H:%M')} UTC")
            except ValueError:
                pass

        await ctx.send(embed=embed)

    @commands.command(name="staffcheck")
    @commands.has_permissions(manage_guild=True)
    async def staffcheck_cmd(self, ctx):
        """Voer een handmatige staffcontrole uit."""
        msg = await ctx.send("🔍 Staffcheck wordt uitgevoerd...")
        await self._run_staff_check(ctx.guild, automated=False)
        await msg.edit(content="✅ Staffcheck voltooid. Bekijk het log kanaal voor details.")

    @commands.command(name="weekrapport", aliases=["weekreport"])
    @commands.has_permissions(manage_guild=True)
    async def weekrapport_cmd(self, ctx):
        """Stuur direct een weekrapport."""
        await self.staffcheck_cmd(ctx)

    @commands.command(name="staffrol", aliases=["staffrole"])
    @commands.has_permissions(manage_guild=True)
    async def staffrol_cmd(self, ctx, rol: discord.Role):
        """Voeg een staffrol toe aan activiteitstracking."""
        self.db.ensure_settings(ctx.guild.id)
        self.db.add_staff_role(ctx.guild.id, rol.id, rol.name)
        await ctx.send(f"✅ **{rol.name}** wordt nu bijgehouden als staffrol.")

    @commands.command(name="trackrol", aliases=["trackrole"])
    @commands.has_permissions(manage_guild=True)
    async def trackrol_cmd(self, ctx, rol: discord.Role):
        """Voeg een algemene rol toe aan activiteitstracking."""
        self.db.ensure_settings(ctx.guild.id)
        self.db.add_tracked_role(ctx.guild.id, rol.id, rol.name)
        await ctx.send(f"✅ **{rol.name}** wordt nu bijgehouden.")

    @commands.command(name="minimumberichten", aliases=["minberichten", "minmessages"])
    @commands.has_permissions(manage_guild=True)
    async def min_berichten_cmd(self, ctx, aantal: int):
        """Stel het minimum aantal berichten per week in."""
        if aantal < 0:
            return await ctx.send("❌ Aantal moet positief zijn.")
        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "min_messages", aantal)
        await ctx.send(f"✅ Minimum berichten per week ingesteld op **{aantal}**.")

    @commands.command(name="minimumvoice", aliases=["minvoice"])
    @commands.has_permissions(manage_guild=True)
    async def min_voice_cmd(self, ctx, minuten: int):
        """Stel het minimum aantal voice-minuten per week in."""
        if minuten < 0:
            return await ctx.send("❌ Minuten moet positief zijn.")
        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "min_voice_minutes", minuten)
        await ctx.send(f"✅ Minimum voice-minuten per week ingesteld op **{minuten}**.")

    @commands.command(name="setactief", aliases=["setlogkanaal", "logchannel"])
    @commands.has_permissions(manage_guild=True)
    async def set_log_channel_cmd(self, ctx, kanaal: discord.TextChannel):
        """Stel het log kanaal in voor activiteitsrapporten."""
        self.db.ensure_settings(ctx.guild.id)
        self.db.update_setting(ctx.guild.id, "log_channel", kanaal.id)
        await ctx.send(f"✅ Log kanaal ingesteld op {kanaal.mention}.")

    @commands.command(name="resetweek")
    @commands.has_permissions(administrator=True)
    async def reset_week_cmd(self, ctx):
        """Reset de wekelijkse activiteitstellers."""
        self.db.reset_weekly(ctx.guild.id)
        await ctx.send("✅ Wekelijkse activiteitstellers gereset.")


async def setup(bot):
    await bot.add_cog(ActivityCog(bot))
