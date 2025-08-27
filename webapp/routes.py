# webapp/routes.py
import asyncio
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, current_app

from . import app
from core import db, utils
import config

def run_async(coro):
    """Helper function to run an async coroutine from a sync context."""
    loop = current_app.config['BOT_LOOP']
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

@app.route("/")
def dashboard():
    # Fetch data from the database using the async helper
    titles_data_rows = run_async(db.get_all_titles_status())
    schedules = run_async(db.get_all_schedules())

    titles_data = []
    for row in titles_data_rows:
        title_name = row['name']
        holder_info = "None"
        if row.get('holder_ign'):
            holder_info = f"{row['holder_ign']} ({row['holder_coords']})"

        remaining = "N/A"
        if row.get('expiry_date'):
            expiry = utils.parse_iso_utc(row['expiry_date'])
            delta = expiry - utils.now_utc()
            remaining = str(timedelta(seconds=int(delta.total_seconds()))) if delta.total_seconds() > 0 else "Expired"
        
        titles_data.append({
            'name': title_name,
            'holder': holder_info,
            'expires_in': remaining,
            'icon': url_for('static', filename=f"icons/{config.TITLES_CATALOG[title_name]['icon_filename']}"),
            'buffs': config.TITLES_CATALOG[title_name]['effects']
        })

    today = utils.now_utc().date()
    days = [(today + timedelta(days=i)) for i in range(7)]
    hours = [f"{h:02d}:00" for h in range(0, 24, 3)]

    return render_template(
        'dashboard.html',
        titles=titles_data,
        days=days,
        hours=hours,
        schedules=schedules,
        today=today.strftime('%Y-%m-%d'),
        requestable_titles=config.REQUESTABLE_TITLES
    )

# ... other routes like /log, /book-slot, /cancel would be refactored here ...