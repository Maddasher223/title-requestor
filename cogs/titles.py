# cogs/titles.py

# This is a large file representing the logic from the original TitleCog.
# For brevity, only key methods are shown with the new database calls.
# The full, refactored cog would be here.

import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta

from core import db, utils
import config

class TitleCog(commands.Cog, name="Titles"):
    def __init__(self, bot):
        self.bot = bot
        self.webhook_url = os.getenv("WEBHOOK_URL")
        self.title_check_loop.start()

    # --- Main Loop (Example of refactoring) ---
    @tasks.loop(minutes=1)
    async def title_check_loop(self):
        await self.bot.wait_until_ready()
        now = utils.now_utc()

        # 1. Auto-expire titles
        all_titles = await db.get_all_titles_status()
        for title in all_titles:
            if title.get('holder_ign') and title.get('expiry_date'):
                if now >= utils.parse_iso_utc(title['expiry_date']):
                    # await self.force_release_logic(...)
                    pass # Placeholder for release logic

        # 2. Send T-5 reminders
        schedules = await db.get_all_schedules()
        for title_name, schedule_data in schedules.items():
            for iso_time, ign in schedule_data.items():
                if await db.was_reminder_sent(iso_time):
                    continue
                # ... reminder logic ...
                # await db.mark_reminder_sent(iso_time)

        # 3. Auto-assign reserved slots
        for title_name, schedule_data in schedules.items():
            for iso_time, reserver_ign in list(schedule_data.items()):
                slot_start = utils.parse_iso_utc(iso_time)
                # ... auto-assign logic ...
                # if should_assign:
                #    await db.assign_title(...)
                #    await db.mark_slot_activated(title_name, iso_time)

    # --- Commands (Example of refactoring) ---
    @commands.command(help="Book a 3-hour time slot.")
    async def schedule(self, ctx, *, full_argument: str):
        # ... (argument parsing logic remains the same) ...
        title_name, ign, date_str, time_str = [p.strip() for p in full_argument.split('|')]
        schedule_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=config.UTC)
        schedule_key = utils.iso_slot_key_naive(schedule_time)

        # Check for existing reservation using the database
        existing_reserver = await db.get_reservation(title_name, schedule_key)
        if existing_reserver:
            await ctx.send(f"This slot is already booked by **{existing_reserver}**.")
            return

        # Book it in the database
        success = await db.reserve_slot(title_name, schedule_key, ign)
        if success:
            await ctx.send(f"Booked '{title_name}' for **{ign}** on {date_str} at {time_str} UTC.")
            # ... (announcement logic) ...
        else:
            await ctx.send("Sorry, that slot was just taken.")

    # ... other commands like !assign, !titles, !unschedule would be refactored similarly ...