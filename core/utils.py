# core/utils.py
import os
import csv
import logging
import requests
from datetime import datetime, timedelta
import config

logger = logging.getLogger(__name__)

# ========= UTC & Time Helpers =========

def now_utc() -> datetime:
    """Returns the current time, aware of the UTC timezone."""
    return datetime.now(config.UTC)

def parse_iso_utc(s: str) -> datetime:
    """Parses an ISO string and ensures it is UTC-aware."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=config.UTC)
    return dt.astimezone(config.UTC)

def iso_slot_key_naive(dt: datetime) -> str:
    """Produces the normalized naive slot key 'YYYY-MM-DDTHH:MM:00' used for scheduling."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(config.UTC)
    return dt.replace(second=0, microsecond=0, tzinfo=None).isoformat()

def in_current_slot(slot_start: datetime) -> bool:
    """Checks if the current time is within the 3-hour slot starting from slot_start."""
    slot_start_utc = slot_start.astimezone(config.UTC)
    end = slot_start_utc + timedelta(hours=config.SHIFT_HOURS)
    return slot_start_utc <= now_utc() < end

# ========= Logging & Webhooks =========

def log_to_csv(request_data: dict):
    """Appends a new request record to the CSV log file."""
    file_exists = os.path.isfile(config.CSV_LOG_FILE)
    try:
        with open(config.CSV_LOG_FILE, 'a', newline='') as csvfile:
            fieldnames = ['timestamp', 'title_name', 'in_game_name', 'coordinates', 'discord_user']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(request_data)
    except IOError as e:
        logger.error(f"Error writing to CSV: {e}")

def send_webhook_notification(webhook_url: str, data: dict, reminder: bool = False):
    """Sends a formatted notification to a Discord webhook."""
    role_tag = f"<@&{config.GUARDIAN_ROLE_ID}>"
    channel_tag = f"<#{config.TITLE_REQUESTS_CHANNEL_ID}>"

    if reminder:
        title = f"Reminder: {data.get('title_name','-')} shift starts soon!"
        content = f"{role_tag} {channel_tag} The 3-hour shift for **{data.get('title_name','-')}** by **{data.get('in_game_name','-')}** starts in 5 minutes!"
    else:
        title = "New Title Request"
        content = f"{role_tag} {channel_tag} A new request was submitted."

    payload = {
        "content": content,
        "allowed_mentions": {"parse": ["roles", "everyone"]},
        "embeds": [{
            "title": title,
            "color": 5814783,
            "fields": [
                {"name": "Title", "value": data.get('title_name','-'), "inline": True},
                {"name": "In-Game Name", "value": data.get('in_game_name','-'), "inline": True},
                {"name": "Coordinates", "value": data.get('coordinates','-'), "inline": True},
                {"name": "Submitted By", "value": data.get('discord_user','-'), "inline": False}
            ],
            "timestamp": data.get('timestamp')
        }]
    }
    try:
        # Note: In a fully async app, use httpx or aiohttp here.
        # For simplicity in this refactor, requests is kept but is blocking.
        r = requests.post(webhook_url, json=payload, timeout=8)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Webhook send failed: {e}")