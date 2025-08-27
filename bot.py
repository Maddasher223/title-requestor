# bot.py
import os
import asyncio
import logging
from threading import Thread
import discord
from discord.ext import commands
from dotenv import load_dotenv

from waitress import serve
from webapp import app
from cogs.titles import TitleCog
from core import db
import config

# --- Setup ---
load_dotenv()
os.makedirs(config.DATA_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Bot Subclass (The Fix is Here) ---
class MyBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def setup_hook(self):
        """This is called after login but before connecting to the gateway."""
        # 1. Initialize the database
        await db.init_db()
        logger.info("Database initialized successfully.")

        # 2. Add the command cog
        await self.add_cog(TitleCog(self))
        logger.info("TitleCog loaded.")

# --- Bot Initialization ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
# Instantiate your new bot class
bot = MyBot(command_prefix='!', intents=intents)

# --- Web Server ---
def run_flask():
    """Runs the Flask web server using Waitress."""
    app.config['BOT_LOOP'] = bot.loop
    serve(app, host='0.0.0.0', port=8080)

# --- Bot Events ---
@bot.event
async def on_ready():
    """Called when the bot is fully connected and ready."""
    logger.info(f'{bot.user.name} has connected to Discord!')
    
    # Start the Flask app in a separate thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask web server started.")

# --- Main Execution ---
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.critical("Error: DISCORD_TOKEN environment variable not set.")
    else:
        bot.run(token)