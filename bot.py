# bot.py
import os
import asyncio
import logging
from threading import Thread
import discord
from discord.ext import commands
from dotenv import load_dotenv

from waitress import serve
from webapp import app  # Import the Flask app
from cogs.titles import TitleCog
from core import db
import config

# --- Setup ---
load_dotenv()  # Load environment variables from .env file
os.makedirs(config.DATA_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Bot Initialization ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.loop.create_task(db.init_db()) # Initialize the database

# --- Web Server ---
def run_flask():
    """Runs the Flask web server using Waitress."""
    # Pass the bot's event loop to the Flask app so routes can interact with it
    app.config['BOT_LOOP'] = bot.loop
    serve(app, host='0.0.0.0', port=8080)

# --- Bot Events ---
@bot.event
async def on_ready():
    """Called when the bot is ready and connected."""
    logger.info(f'{bot.user.name} has connected to Discord!')
    
    # Add the command cog
    await bot.add_cog(TitleCog(bot))
    
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