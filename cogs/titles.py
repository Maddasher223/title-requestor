# cogs/titles.py
import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import logging

from core import db, utils
import config

logger = logging.getLogger(__name__)

# A simple check to see if the user is a server admin.
def is_admin():
    async def predicate(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(predicate)

class TitleCog(commands.Cog, name="Titles"):
    def __init__(self, bot):
        self.bot = bot
        self.webhook_url = os.getenv("WEBHOOK_URL")
        self.title_check_loop.start()
        # Note: 'claim' and 'assign' commands were removed as per the shift to a scheduling system.
        # If you need them, they would require a separate queue/pending system in the database.

    async def announce(self, message: str):
        """Helper to send a message to the announcement channel if configured."""
        # This function could be expanded to fetch a channel ID from a database setting
        # For now, it's a placeholder if you wish to add announcement functionality back.
        logger.info(f"ANNOUNCEMENT: {message}")

    # ===== BACKGROUND TASK =====
    @tasks.loop(minutes=1)
    async def title_check_loop(self):
        now = utils.now_utc()

        # 1. Auto-expire titles
        all_titles = await db.get_all_titles_status()
        for title in all_titles:
            if title.get('holder_ign') and title.get('expiry_date'):
                expiry_dt = utils.parse_iso_utc(title['expiry_date'])
                if now >= expiry_dt:
                    logger.info(f"Title '{title['name']}' held by {title['holder_ign']} has expired.")
                    await db.release_title(title['name'])
                    await self.announce(f"The title **'{title['name']}'** held by **{title['holder_ign']}** has automatically expired and is now available.")

        # 2. Send T-5 reminders for upcoming shifts
        schedules = await db.get_all_schedules()
        for title_name, schedule_data in schedules.items():
            for slot_key, ign in schedule_data.items():
                if await db.was_reminder_sent(slot_key):
                    continue
                
                shift_time = datetime.fromisoformat(slot_key).replace(tzinfo=config.UTC)
                reminder_time = shift_time - timedelta(minutes=5)
                
                if reminder_time <= now < shift_time:
                    logger.info(f"Sending 5-minute reminder for {title_name} to {ign}.")
                    try:
                        notification_data = {
                            "timestamp": now.isoformat(),
                            "title_name": title_name,
                            "in_game_name": ign,
                            "coordinates": "-",
                            "discord_user": "Scheduler"
                        }
                        utils.send_webhook_notification(self.webhook_url, notification_data, reminder=True)
                        await db.mark_reminder_sent(slot_key)
                    except Exception as e:
                        logger.error(f"Could not send shift reminder for {slot_key}: {e}")

        # 3. Auto-assign reserved slots at the start of their shift
        for title_name, schedule_data in schedules.items():
            for slot_key, reserver_ign in schedule_data.items():
                slot_start = datetime.fromisoformat(slot_key).replace(tzinfo=config.UTC)
                if utils.in_current_slot(slot_start) and not await db.was_slot_activated(title_name, slot_key):
                    title_status = await db.get_title_status(title_name)
                    if not title_status or not title_status.get('holder_ign'):
                        logger.info(f"Auto-assigning '{title_name}' to {reserver_ign} for slot {slot_key}.")
                        slot_end = slot_start + timedelta(hours=config.SHIFT_HOURS)
                        await db.assign_title(
                            title_name=title_name,
                            holder_ign=reserver_ign,
                            holder_coords="-",
                            holder_discord_id=0, # Discord ID is unknown from schedule
                            claim_date_iso=slot_start.isoformat(),
                            expiry_date_iso=slot_end.isoformat()
                        )
                        await db.mark_slot_activated(title_name, slot_key)
                        await self.announce(f"Scheduled handoff: **{title_name}** is now assigned to **{reserver_ign}**.")

    @title_check_loop.before_loop
    async def before_title_check_loop(self):
        await self.bot.wait_until_ready()

    # ===== DISCORD COMMANDS =====
    @commands.command(help="List all titles and their current status.")
    async def titles(self, ctx):
        all_titles_status = await db.get_all_titles_status()
        
        embed = discord.Embed(title="📜 Title Status", color=discord.Color.blue())
        
        for title_status in all_titles_status:
            title_name = title_status['name']
            details = config.TITLES_CATALOG.get(title_name, {})
            status_text = f"*{details.get('effects', 'No effects listed.')}*\n"
            
            if title_status.get('holder_ign'):
                holder_name = f"{title_status['holder_ign']} ({title_status['holder_coords']})"
                expiry = utils.parse_iso_utc(title_status['expiry_date'])
                remaining = expiry - utils.now_utc()
                if remaining.total_seconds() > 0:
                    remaining_str = str(timedelta(seconds=int(remaining.total_seconds())))
                    status_text += f"**Held by:** {holder_name}\n*Expires in: {remaining_str}*"
                else:
                    status_text += f"**Held by:** {holder_name}\n*Status: Expired*"
            else:
                status_text += "**Status:** Available"
                
            embed.add_field(name=f"👑 {title_name}", value=status_text, inline=False)
            
        await ctx.send(embed=embed)

    @commands.command(aliases=['book'], help="Book a title slot. Usage: !schedule \"Title Name\" | IGN | YYYY-MM-DD | HH:00")
    async def schedule(self, ctx, *, args: str):
        try:
            title_name, ign, date_str, time_str = [arg.strip() for arg in args.split('|')]
        except ValueError:
            await ctx.send("Invalid format. Use `!schedule \"Title Name\" | In-Game Name | YYYY-MM-DD | HH:00`")
            return

        if title_name not in config.TITLES_CATALOG:
            await ctx.send(f"Title '{title_name}' does not exist.")
            return
            
        try:
            schedule_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=config.UTC)
            if schedule_dt.minute != 0 or schedule_dt.hour % config.SHIFT_HOURS != 0:
                raise ValueError("Time must be a clean interval of the shift duration (e.g., 00:00, 03:00, 06:00...).")
        except ValueError as e:
            await ctx.send(f"Invalid date or time format. Use YYYY-MM-DD and HH:00. {e}")
            return

        if schedule_dt < utils.now_utc():
            await ctx.send("You cannot schedule a time in the past.")
            return

        slot_key = utils.iso_slot_key(schedule_dt)

        # Check if this person already has a title booked for this slot
        conflicting_title = await db.is_ign_booked_for_slot(ign, slot_key)
        if conflicting_title:
            await ctx.send(f"Error: **{ign}** has already booked **{conflicting_title}** for this exact time slot.")
            return

        # Try to reserve the slot
        if await db.reserve_slot(title_name, slot_key, ign):
            # Log to CSV
            utils.log_to_csv({
                'timestamp': utils.now_utc().isoformat(),
                'title_name': title_name,
                'in_game_name': ign,
                'coordinates': '-',
                'discord_user': f"{ctx.author.name} ({ctx.author.id})"
            })
            await ctx.send(f"✅ Slot confirmed! **{ign}** has booked **{title_name}** for {date_str} at {time_str} UTC.")
        else:
            reserver = await db.get_reservation(title_name, slot_key)
            await ctx.send(f"Sorry, that slot is already booked by **{reserver}**.")

    @commands.command(aliases=['unbook', 'cancel'], help="Cancel a booking. Usage: !unschedule \"Title Name\" | YYYY-MM-DDTHH:MM")
    async def unschedule(self, ctx, *, args: str):
        try:
            title_name, time_str = [arg.strip() for arg in args.split('|')]
            # Quick parse to build the key
            schedule_dt = datetime.fromisoformat(time_str).replace(tzinfo=config.UTC)
            slot_key = utils.iso_slot_key(schedule_dt)
        except ValueError:
            await ctx.send("Invalid format. Use `!unschedule \"Title Name\" | YYYY-MM-DDTHH:MM`")
            return

        reserver_ign = await db.get_reservation(title_name, slot_key)
        if not reserver_ign:
            await ctx.send("No reservation found for that title at that specific time.")
            return
        
        # In a real system, you'd look up the user's IGN. For now, we compare Discord name.
        # A more robust check would involve a registered list of IGNs to Discord IDs.
        is_admin = ctx.author.guild_permissions.administrator
        if reserver_ign.lower() != ctx.author.display_name.lower() and not is_admin:
            await ctx.send(f"You can only cancel your own reservations. This slot was booked by **{reserver_ign}**.")
            return
            
        await db.cancel_reservation(title_name, slot_key)
        await ctx.send(f"🗑️ Reservation for **{title_name}** at {slot_key} (booked by {reserver_ign}) has been cancelled.")