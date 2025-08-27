# webapp/routes.py
import asyncio
import os
import csv
from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, current_app, flash

from . import app
from core import db, utils
import config

def run_async(coro):
    """Helper function to run an async coroutine from a sync (Flask) context."""
    loop = current_app.config.get('BOT_LOOP')
    if not loop:
        # Fallback for environments where the loop isn't passed, though it should be.
        return asyncio.run(coro)
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

@app.route("/")
def dashboard():
    titles_status = run_async(db.get_all_titles_status())
    schedules = run_async(db.get_all_schedules())

    # Process title data for the template
    titles_data = []
    for title in titles_status:
        title_name = title['name']
        holder_info = "Available"
        if title.get('holder_ign'):
            holder_info = f"{title['holder_ign']} ({title['holder_coords']})"

        remaining = "N/A"
        if title.get('expiry_date'):
            try:
                expiry = utils.parse_iso_utc(title['expiry_date'])
                delta = expiry - utils.now_utc()
                remaining = str(timedelta(seconds=int(delta.total_seconds()))) if delta.total_seconds() > 0 else "Expired"
            except (ValueError, TypeError):
                remaining = "Invalid Date"

        titles_data.append({
            'name': title_name,
            'holder': holder_info,
            'expires_in': remaining,
            'icon': url_for('static', filename=f"icons/{config.TITLES_CATALOG[title_name]['icon_filename']}"),
            'buffs': config.TITLES_CATALOG[title_name]['effects']
        })

    today = utils.now_utc().date()
    days = [(today + timedelta(days=i)) for i in range(7)]
    hours = [f"{h:02d}:00" for h in range(0, 24, config.SHIFT_HOURS)]

    return render_template(
        'dashboard.html',
        titles=titles_data,
        days=days,
        hours=hours,
        schedules=schedules,
        today=today.strftime('%Y-%m-%d'),
        requestable_titles=sorted(list(config.REQUESTABLE_TITLES))
    )

@app.route("/book-slot", methods=['POST'])
def book_slot():
    title_name = request.form.get('title')
    ign = request.form.get('ign')
    date_str = request.form.get('date')
    time_str = request.form.get('time')

    if not all([title_name, ign, date_str, time_str]):
        flash("Missing form data.", "error")
        return redirect(url_for('dashboard'))

    try:
        schedule_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=config.UTC)
        slot_key = utils.iso_slot_key(schedule_dt)

        # Run database checks
        conflicting_title = run_async(db.is_ign_booked_for_slot(ign, slot_key))
        if conflicting_title:
            flash(f"Error: {ign} has already booked {conflicting_title} for this time slot.", "error")
            return redirect(url_for('dashboard'))

        success = run_async(db.reserve_slot(title_name, slot_key, ign))
        if success:
             # Log to CSV
            utils.log_to_csv({
                'timestamp': utils.now_utc().isoformat(),
                'title_name': title_name,
                'in_game_name': ign,
                'coordinates': '-', # Coords not collected in this form
                'discord_user': "Web Form"
            })
            flash(f"Slot confirmed for {ign}!", "success")
        else:
            reserver = run_async(db.get_reservation(title_name, slot_key))
            flash(f"Sorry, that slot was just booked by {reserver}.", "error")

    except ValueError:
        flash("Invalid date or time format submitted.", "error")
    
    return redirect(url_for('dashboard'))


@app.route("/log")
def view_log():
    log_data = []
    if os.path.exists(config.CSV_LOG_FILE):
        with open(config.CSV_LOG_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            log_data = list(reader)
    return render_template('log.html', logs=reversed(log_data))

# You can add a simple secret key for flash messages to work
app.secret_key = os.getenv("FLASK_SECRET_KEY", "a-default-secret-key-for-development")