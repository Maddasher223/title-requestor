# core/db.py
import asyncio
import logging
import aiosqlite
from typing import Optional, Dict, Any, List

import config

logger = logging.getLogger(__name__)

DB_FILE = config.DATABASE_FILE

async def get_conn() -> aiosqlite.Connection:
    """Gets a database connection."""
    conn = await aiosqlite.connect(DB_FILE)
    conn.row_factory = aiosqlite.Row
    return conn

async def init_db():
    """Initializes the database and creates tables if they don't exist."""
    conn = await get_conn()
    async with conn as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS titles (
                name TEXT PRIMARY KEY,
                holder_ign TEXT,
                holder_coords TEXT,
                holder_discord_id INTEGER,
                claim_date TEXT,
                expiry_date TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                title_name TEXT,
                slot_key TEXT,
                reserver_ign TEXT,
                PRIMARY KEY (title_name, slot_key)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS sent_reminders (
                slot_key TEXT PRIMARY KEY
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS activated_slots (
                title_name TEXT,
                slot_key TEXT,
                PRIMARY KEY (title_name, slot_key)
            )
        """)
        
        cursor = await db.execute("SELECT COUNT(*) FROM titles")
        if (await cursor.fetchone())[0] == 0:
            for title_name in config.TITLES_CATALOG:
                await db.execute("INSERT INTO titles (name) VALUES (?)", (title_name,))

        await db.commit()
    logger.info("Database initialized successfully.")

async def get_all_titles_status() -> List[Dict[str, Any]]:
    conn = await get_conn()
    async with conn as db:
        cursor = await db.execute(f"SELECT * FROM titles")
        rows = await cursor.fetchall()
        # Ensure order matches config.ORDERED_TITLES
        rows_dict = {dict(row)['name']: dict(row) for row in rows}
        return [rows_dict.get(name) for name in config.ORDERED_TITLES if rows_dict.get(name)]

async def get_title_status(title_name: str) -> Optional[Dict[str, Any]]:
    conn = await get_conn()
    async with conn as db:
        cursor = await db.execute("SELECT * FROM titles WHERE name = ?", (title_name,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def assign_title(title_name: str, holder_ign: str, holder_coords: str, holder_discord_id: int, claim_date_iso: str, expiry_date_iso: str):
    conn = await get_conn()
    async with conn as db:
        await db.execute(
            "UPDATE titles SET holder_ign = ?, holder_coords = ?, holder_discord_id = ?, claim_date = ?, expiry_date = ? WHERE name = ?",
            (holder_ign, holder_coords, holder_discord_id, claim_date_iso, expiry_date_iso, title_name)
        )
        await db.commit()

async def release_title(title_name: str):
    conn = await get_conn()
    async with conn as db:
        await db.execute(
            "UPDATE titles SET holder_ign = NULL, holder_coords = NULL, holder_discord_id = NULL, claim_date = NULL, expiry_date = NULL WHERE name = ?",
            (title_name,)
        )
        await db.commit()

async def get_all_schedules() -> Dict[str, Dict[str, str]]:
    schedules = {}
    conn = await get_conn()
    async with conn as db:
        cursor = await db.execute("SELECT title_name, slot_key, reserver_ign FROM schedules")
        rows = await cursor.fetchall()
        for row in rows:
            schedules.setdefault(row['title_name'], {})[row['slot_key']] = row['reserver_ign']
    return schedules

async def reserve_slot(title_name: str, slot_key: str, reserver_ign: str) -> bool:
    try:
        conn = await get_conn()
        async with conn as db:
            await db.execute("INSERT INTO schedules (title_name, slot_key, reserver_ign) VALUES (?, ?, ?)", (title_name, slot_key, reserver_ign))
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False

async def get_reservation(title_name: str, slot_key: str) -> Optional[str]:
    conn = await get_conn()
    async with conn as db:
        cursor = await db.execute("SELECT reserver_ign FROM schedules WHERE title_name = ? AND slot_key = ?", (title_name, slot_key))
        row = await cursor.fetchone()
        return row['reserver_ign'] if row else None

async def cancel_reservation(title_name: str, slot_key: str):
    conn = await get_conn()
    async with conn as db:
        await db.execute("DELETE FROM schedules WHERE title_name = ? AND slot_key = ?", (title_name, slot_key))
        await db.execute("DELETE FROM activated_slots WHERE title_name = ? AND slot_key = ?", (title_name, slot_key))
        await db.commit()

async def mark_reminder_sent(slot_key: str):
    conn = await get_conn()
    async with conn as db:
        await db.execute("INSERT OR IGNORE INTO sent_reminders (slot_key) VALUES (?)", (slot_key,))
        await db.commit()

async def was_reminder_sent(slot_key: str) -> bool:
    conn = await get_conn()
    async with conn as db:
        cursor = await db.execute("SELECT 1 FROM sent_reminders WHERE slot_key = ?", (slot_key,))
        return await cursor.fetchone() is not None

async def mark_slot_activated(title_name: str, slot_key: str):
    conn = await get_conn()
    async with conn as db:
        await db.execute("INSERT OR IGNORE INTO activated_slots (title_name, slot_key) VALUES (?, ?)", (title_name, slot_key))
        await db.commit()

async def was_slot_activated(title_name: str, slot_key: str) -> bool:
    conn = await get_conn()
    async with conn as db:
        cursor = await db.execute("SELECT 1 FROM activated_slots WHERE title_name = ? AND slot_key = ?", (title_name, slot_key))
        return await cursor.fetchone() is not None

async def is_ign_booked_for_slot(ign: str, slot_key: str) -> Optional[str]:
    """Checks if an IGN already has any title booked for a specific slot."""
    conn = await get_conn()
    async with conn as db:
        cursor = await db.execute("SELECT title_name FROM schedules WHERE reserver_ign = ? AND slot_key = ?", (ign, slot_key))
        row = await cursor.fetchone()
        return row['title_name'] if row else None