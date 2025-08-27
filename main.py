# main.py
# Minimal Discord + Flask title scheduler for A:RC
# - Discord remains source of truth (queues, assign, release, expire)
# - Web form lets non-Discord users request titles
# - Guardians get pinged in Discord; optional phone push via Pushover
# - Reminder loop warns 30/10/5 min before expiry

import os, json, asyncio, threading, logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import Flask, request, redirect, url_for, render_template_string
import requests

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ------------- CONFIG -------------
load_dotenv()

DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN")          # required
GUILD_ID        = int(os.getenv("GUILD_ID", "0"))     # optional; 0 = first guild
GUARDIAN_ROLE   = os.getenv("GUARDIAN_ROLE", "Guardians")  # role name to @mention
TITLES_CHANNEL  = os.getenv("TITLES_CHANNEL", "titles")    # channel name for pings

# Optional phone push (Pushover). Leave blank to disable.
PUSHOVER_APP_TOKEN = os.getenv("PUSHOVER_APP_TOKEN", "")
PUSHOVER_USER_KEY  = os.getenv("PUSHOVER_USER_KEY", "")

# Default policy knobs
DEFAULT_DURATION_MIN = int(os.getenv("DEFAULT_DURATION_MIN", "30"))
DEFAULT_COOLDOWN_MIN = int(os.getenv("DEFAULT_COOLDOWN_MIN", "120"))  # per title, crude
STATE_FILE = os.getenv("STATE_FILE", "state.json")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("titles")

# ------------- STATE -------------
# shape:
# state = {
#   "config": { "reminders": {"30":"30m left", "10":"10m", "5":"5m"} },
#   "titles": {
#     "Architect": {
#        "holder": {"name":"IGN","coords":"(x,y)","discord_id":123},
#        "expiry_date": "2025-08-26T18:22:00+00:00",
#        "pending_claimant": {"name":"IGN","coords":"(x,y)","duration":30,"source":"web"},
#        "queue": [ ... ],
#        "rem_30": True, "rem_10": False, "rem_5": False
#     },
#     ...
#   }
# }
state = {
    "config": {
        "reminders": {"30": "ends in ~30 minutes",
                      "10": "ends in ~10 minutes",
                      "5":  "ends in ~5 minutes"}
    },
    "titles": {}
}

_state_lock = threading.Lock()       # for Flask thread
_state_async_lock = asyncio.Lock()   # for Discord tasks

def _dt_utc_now():
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()

def load_state():
    global state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state.update(json.load(f))
            log.info("State loaded.")
        except Exception as e:
            log.error(f"Failed to load state: {e}")

def save_state():
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

async def save_state_async():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, save_state)

def push_phone(title, body):
    if not (PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY):
        return
    try:
        requests.post("https://api.pushover.net/1/messages.json", data={
            "token": PUSHOVER_APP_TOKEN,
            "user": PUSHOVER_USER_KEY,
            "title": title,
            "message": body
        }, timeout=5)
    except Exception as e:
        log.error(f"Pushover error: {e}")

# ------------- DISCORD BOT -------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

class TitleCog(commands.Cog):
    def __init__(self, bot_):
        self.bot = bot_
        self.reminder_loop.start()
        self.expire_loop.start()

    # ---------- helpers ----------
    async def guild(self):
        if GUILD_ID:
            g = self.bot.get_guild(GUILD_ID)
            if g:
                return g
        return self.bot.guilds[0] if self.bot.guilds else None

    async def titles_channel(self, g):
        if not g: return None
        ch = discord.utils.get(g.text_channels, name=TITLES_CHANNEL)
        return ch or g.system_channel

    async def guardian_mention(self, g):
        if not g: return ""
        role = discord.utils.get(g.roles, name=GUARDIAN_ROLE)
        return role.mention if role else ""

    async def announce(self, msg: str):
        g = await self.guild()
        ch = await self.titles_channel(g)
        if ch:
            await ch.send(msg)
        push_phone("ARC Titles", msg)

    async def notify_guardians_title_request(self, title, ign, coords, duration_min):
        g = await self.guild()
        mention = await self.guardian_mention(g)
        ch = await self.titles_channel(g)
        msg = (f"{mention} 👑 **Title request**: **{ign}** {coords} needs **{title}** "
               f"for {duration_min}m. Approve: `!assign {title} | {ign}`")
        if ch: await ch.send(msg)
        push_phone("Title request", f"{ign} -> {title} ({duration_min}m) {coords}")

    # ---------- lifecycle loops ----------
    @tasks.loop(minutes=5)
    async def reminder_loop(self):
        await self.bot.wait_until_ready()
        now = _dt_utc_now()
        async with _state_async_lock:
            for title, data in state.get("titles", {}).items():
                holder = data.get("holder")
                end_iso = data.get("expiry_date")
                if not (holder and end_iso): 
                    continue
                try:
                    end = datetime.fromisoformat(end_iso)
                except Exception:
                    continue
                mins_left = int((end - now).total_seconds() // 60)
                for key in ("30","10","5"):
                    if mins_left == int(key) and not data.get(f"rem_{key}"):
                        await self.announce(f"⏰ **{title}** for **{holder['name']}** "
                                            f"{state['config']['reminders'][key]}. Queue, be ready.")
                        data[f"rem_{key}"] = True
            await save_state_async()

    @tasks.loop(minutes=1)
    async def expire_loop(self):
        await self.bot.wait_until_ready()
        now = _dt_utc_now()
        async with _state_async_lock:
            changed = False
            for title, data in state.get("titles", {}).items():
                end_iso = data.get("expiry_date")
                holder = data.get("holder")
                if holder and end_iso:
                    try:
                        end = datetime.fromisoformat(end_iso)
                    except Exception:
                        continue
                    if now >= end:
                        # expire holder
                        await self.announce(f"✅ **{title}** has expired for **{holder['name']}**.")
                        data["holder"] = None
                        data["expiry_date"] = None
                        # reset reminder flags
                        for k in ("30","10","5"):
                            data.pop(f"rem_{k}", None)
                        changed = True
                        # promote next in queue if any: mark as pending and ping guardians
                        if data.get("queue"):
                            nxt = data["queue"].pop(0)
                            data["pending_claimant"] = nxt
                            await self.notify_guardians_title_request(title, nxt["name"], nxt.get("coords",""), nxt.get("duration", DEFAULT_DURATION_MIN))
                            changed = True
            if changed:
                await save_state_async()

    # ---------- commands ----------
    @commands.command(name="titles")
    async def _titles(self, ctx: commands.Context):
        """List current holders and queues."""
        async with _state_async_lock:
            if not state["titles"]:
                await ctx.send("No titles configured yet.")
                return
            lines = []
            for t, d in state["titles"].items():
                holder = d.get("holder")
                pend = d.get("pending_claimant")
                q = d.get("queue", [])
                line = f"**{t}** — holder: {holder['name']} until {d['expiry_date']}" if holder else f"**{t}** — free"
                if pend: line += f" | pending: {pend['name']}"
                if q: line += f" | queue: {', '.join(p['name'] for p in q)}"
                lines.append(line)
        await ctx.send("\n".join(lines))

    @commands.command(name="addtitle")
    @commands.has_permissions(administrator=True)
    async def _addtitle(self, ctx: commands.Context, *, title_name: str):
        """Admin: create a title bucket."""
        async with _state_async_lock:
            state["titles"].setdefault(title_name, {"holder": None, "queue": []})
            await save_state_async()
        await ctx.send(f"Added **{title_name}**.")

    @commands.command(name="assign")
    async def _assign(self, ctx: commands.Context, *, payload: str):
        """
        Assign a title to a player.
        Usage: !assign Architect | Manny | 30
               (duration minutes optional)
        If a pending claimant exists for the title, IGN may be omitted: !assign Architect
        """
        parts = [p.strip() for p in payload.split("|")]
        title = parts[0] if parts else ""
        ign   = parts[1] if len(parts) > 1 else None
        dur   = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else DEFAULT_DURATION_MIN
        if not title:
            await ctx.send("Usage: `!assign <Title> | <IGN> | <minutes>`")
            return

        async with _state_async_lock:
            t = state["titles"].setdefault(title, {"holder": None, "queue": []})
            if t.get("holder"):
                await ctx.send(f"**{title}** is already held by **{t['holder']['name']}**.")
                return

            # if IGN omitted, use pending claimant
            if not ign:
                pend = t.get("pending_claimant")
                if not pend:
                    await ctx.send("No pending claimant; provide IGN.")
                    return
                ign = pend["name"]
                dur = pend.get("duration", dur)

            end = _dt_utc_now() + timedelta(minutes=dur)
            t["holder"] = {"name": ign, "coords": "", "discord_id": getattr(ctx.author, "id", 0)}
            t["expiry_date"] = iso(end)
            # clear pending if it matches
            if t.get("pending_claimant") and t["pending_claimant"]["name"].lower() == ign.lower():
                t["pending_claimant"] = None
            # dedupe queue of this ign
            t["queue"] = [q for q in t.get("queue", []) if q.get("name","").lower() != ign.lower()]
            # reset reminders
            for k in ("30","10","5"):
                t.pop(f"rem_{k}", None)
            await save_state_async()

        await ctx.send(f"👑 Assigned **{title}** to **{ign}** for {dur}m (ends {end:%H:%M UTC}).")

    @commands.command(name="release")
    async def _release(self, ctx: commands.Context, *, title: str):
        """Release a title early."""
        async with _state_async_lock:
            t = state["titles"].get(title)
            if not t or not t.get("holder"):
                await ctx.send(f"**{title}** is not currently held.")
                return
            holder = t["holder"]["name"]
            t["holder"] = None
            t["expiry_date"] = None
            for k in ("30","10","5"):
                t.pop(f"rem_{k}", None)
            await save_state_async()
        await ctx.send(f"✅ **{title}** released from **{holder}**.")
        # auto-promote next pending
        async with _state_async_lock:
            if state["titles"].get(title, {}).get("queue"):
                nxt = state["titles"][title]["queue"].pop(0)
                state["titles"][title]["pending_claimant"] = nxt
                await save_state_async()
                await self.notify_guardians_title_request(title, nxt["name"], nxt.get("coords",""), nxt.get("duration", DEFAULT_DURATION_MIN))

    @commands.command(name="queue")
    async def _queue(self, ctx: commands.Context, *, title_and_ign: str):
        """Add yourself (or IGN) to queue. Usage: !queue Architect | Manny"""
        parts = [p.strip() for p in title_and_ign.split("|")]
        title = parts[0] if parts else ""
        ign   = parts[1] if len(parts) > 1 else ctx.author.display_name
        if not title:
            await ctx.send("Usage: `!queue <Title> | <IGN>`")
            return
        async with _state_async_lock:
            t = state["titles"].setdefault(title, {"holder": None, "queue": []})
            if any(q.get("name","").lower() == ign.lower() for q in t["queue"]):
                await ctx.send(f"**{ign}** is already in **{title}** queue.")
                return
            t["queue"].append({"name": ign, "coords": "", "duration": DEFAULT_DURATION_MIN, "source": "discord"})
            await save_state_async()
        await ctx.send(f"➕ Queued **{ign}** for **{title}**.")

bot.add_cog(TitleCog(bot))

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (guilds: {[g.name for g in bot.guilds]})")

# ------------- FLASK (web intake) -------------
app = Flask(__name__)

DASHBOARD_HTML = """
<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Title Dashboard</title>
<style>
body{font-family:system-ui,Arial,sans-serif;margin:16px}
.card{border:1px solid #ddd;border-radius:12px;padding:12px;margin:10px 0}
h2{margin:6px 0}
small{color:#666}
button{padding:6px 10px;border-radius:8px;border:1px solid #aaa;background:#f7f7f7;cursor:pointer}
.copy{margin-left:8px}
</style>
<h1>ARC Titles</h1>
<p><a href="{{ url_for('request_page') }}">Request a title</a></p>
{% if not titles %}<p><i>No titles yet. Use !addtitle in Discord.</i></p>{% endif %}
{% for name, d in titles.items() %}
<div class="card">
  <h2>{{name}}</h2>
  {% if d.holder %}
    <div><b>Holder:</b> {{d.holder.name}} <small>(until {{d.expiry_date}})</small>
      <button class="copy" onclick="copy('{{d.holder.name}}')">Copy IGN</button>
    </div>
  {% else %}
    <div><b>Holder:</b> <i>free</i></div>
  {% endif %}
  {% if d.pending_claimant %}
    <div><b>Pending:</b> {{d.pending_claimant.name}} {{d.pending_claimant.coords or ""}}
      <button class="copy" onclick="copy('{{d.pending_claimant.name}} {{d.pending_claimant.coords or ""}}')">Copy</button>
    </div>
  {% endif %}
  {% if d.queue and d.queue|length > 0 %}
    <div><b>Queue:</b> 
      {% for q in d.queue %}
        <code>{{q.name}}</code>{% if not loop.last %}, {% endif %}
      {% endfor %}
    </div>
  {% endif %}
</div>
{% endfor %}
<script>
function copy(t){ navigator.clipboard.writeText(t); }
setTimeout(()=>location.reload(), 60000); // auto-refresh every 60s
</script>
"""

REQUEST_HTML = """
<!doctype html>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Request a Title</title>
<style>
body{font-family:system-ui,Arial,sans-serif;margin:18px}
label{display:block;margin:10px 0}
input,select{padding:8px;border-radius:8px;border:1px solid #ccc;width:100%;max-width:420px}
button{margin-top:10px;padding:10px 14px;border-radius:10px;border:1px solid #aaa;background:#f5f5f5}
</style>
<h2>Request a title</h2>
<form method="post" action="{{ url_for('request_title') }}">
  <label>In-game name
    <input name="ign" required>
  </label>
  <label>Coords
    <input name="coords" placeholder="(123,456)" required>
  </label>
  <label>Title
    <select name="title_name" required>
      {% for t in titles %}<option>{{t}}</option>{% endfor %}
    </select>
  </label>
  <label>Duration (minutes)
    <input name="duration" type="number" min="5" max="180" value="{{default_duration}}">
  </label>
  <button type="submit">Submit</button>
</form>
<p><a href="{{ url_for('dashboard') }}">Back to dashboard</a></p>
"""

@app.get("/")
def dashboard():
    with _state_lock:
        # Present a simple, serializable view
        titles_view = {}
        for name, d in state.get("titles", {}).items():
            titles_view[name] = {
                "holder": d.get("holder"),
                "expiry_date": d.get("expiry_date"),
                "pending_claimant": d.get("pending_claimant"),
                "queue": d.get("queue", [])
            }
    return render_template_string(DASHBOARD_HTML, titles=titles_view)

@app.get("/request")
def request_page():
    with _state_lock:
        titles = sorted(state.get("titles", {}).keys())
    return render_template_string(REQUEST_HTML, titles=titles, default_duration=DEFAULT_DURATION_MIN)

@app.post("/request-title")
def request_title():
    title = (request.form.get("title_name") or "").strip()
    ign   = (request.form.get("ign") or "").strip()
    coords= (request.form.get("coords") or "").strip()
    try:
        dur   = int(request.form.get("duration") or DEFAULT_DURATION_MIN)
    except ValueError:
        dur = DEFAULT_DURATION_MIN
    if not (title and ign and coords):
        return "Missing fields", 400

    # hand off into the bot loop to reuse queue logic
    async def handle_web_request(title_name, ign_, coords_, duration_min):
        async with _state_async_lock:
            t = state["titles"].setdefault(title_name, {"holder": None, "queue": []})
            claimant = {"name": ign_, "coords": coords_, "duration": duration_min, "source": "web"}

            # if free and no pending → set pending + ping; else queue (dedupe)
            if not t.get("holder") and not t.get("pending_claimant"):
                t["pending_claimant"] = claimant
                await save_state_async()
                cog = bot.get_cog("TitleCog")
                if cog:
                    await cog.notify_guardians_title_request(title_name, ign_, coords_, duration_min)
            else:
                if not any(q.get("name","").lower() == ign_.lower() for q in t["queue"]):
                    t["queue"].append(claimant)
                    await save_state_async()

    def handoff():
        future = asyncio.run_coroutine_threadsafe(handle_web_request(title, ign, coords, dur), bot.loop)
        try:
            future.result(timeout=5)
        except Exception as e:
            log.error(f"handoff error: {e}")

    threading.Thread(target=handoff, daemon=True).start()
    return redirect(url_for("dashboard"))

# ------------- RUNTIME -------------
def run_flask():
    # note: set host to 0.0.0.0 if deploying
    app.run(host="127.0.0.1", port=8000, debug=False, threaded=True)

def main():
    load_state()
    # start flask in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    # run discord bot (blocking)
    if not DISCORD_TOKEN:
        log.error("Set DISCORD_TOKEN in env.")
        return
    bot.run(DISCORD_TOKEN)

if __name__ == "__main__":
    main()