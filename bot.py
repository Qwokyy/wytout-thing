print("BOOT FILE STARTED")

import os
import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import re
import json
import random
from datetime import datetime
import pytz

# ---------------- LOAD ENV ----------------

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ROLE_ID = int(os.getenv("ROLE_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

GUILD = discord.Object(id=GUILD_ID)
TIMEZONE = pytz.timezone("America/New_York")

REMINDER_MESSAGES = [
    "🎲 RNG gods are watching...",
    "🔥 Time to roll.",
    "🍀 Luck is calling.",
    "⚡ Show your RNG.",
    "👀 Who will rise today?"
]

# ---------------- DATA ----------------

def load_json(file, default):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except:
        return default

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

def load_data():
    return load_json("data.json", {
        "xp": {},
        "streaks": {},
        "last_roll": {}
    })

def save_data(data):
    save_json("data.json", data)

def load_players():
    return load_json("players.json", {"players": []})["players"]

# ---------------- STREAK SYSTEM ----------------

def update_roll_streak(username, roll_id):
    data = load_data()
    today = str(datetime.now().date())

    if username not in data["streaks"]:
        data["streaks"][username] = {"count": 0, "last": ""}

    if data["last_roll"].get(username) == roll_id:
        return

    data["last_roll"][username] = roll_id

    if data["streaks"][username]["last"] != today:
        data["streaks"][username]["count"] += 1
        data["streaks"][username]["last"] = today

    save_data(data)

def get_streak(username):
    data = load_data()
    return data["streaks"].get(username, {}).get("count", 0)

# ---------------- SCRAPER ----------------

def get_latest_roll(username):
    url = f"https://www.rngdle.com/u/{username}"
    r = requests.get(url, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    a = soup.find("a", href=lambda x: x and "/roll/" in x)
    if not a:
        return None

    return "https://www.rngdle.com" + a["href"]

def parse_roll(url):
    r = requests.get(url, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")

    text = soup.get_text(" ")

    ep = 0
    match = re.search(r"([\d,]+)\s*EP", text)
    if match:
        ep = int(match.group(1).replace(",", ""))

    quote = None
    for p in soup.find_all("p"):
        t = p.get_text(strip=True)

        if not t:
            continue
        if "EP" in t:
            continue
        if "Earned" in t:
            continue
        if len(t) > 120:
            continue

        quote = t
        break

    roll_id = url.split("/roll/")[1].split("/")[0]

    return {
        "ep": ep,
        "quote": quote,
        "roll": roll_id,
        "url": url
    }

def get_user_data(username):
    try:
        roll_url = get_latest_roll(username)
        if not roll_url:
            return 0, None

        data = parse_roll(roll_url)
        update_roll_streak(username, data["roll"])

        return data["ep"], data

    except:
        return 0, None

# ---------------- BOT ----------------

class MyBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True

        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync(guild=GUILD)
        print("SYNC COMPLETE")

        if not daily_loop.is_running():
            daily_loop.start()
            print("Daily loop started")

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        print("ON READY FIRED")

# ✅ THIS IS THE CRITICAL FIX (BOT MUST EXIST HERE)
bot = MyBot()

# ---------------- COMMANDS ----------------

@bot.tree.command(name="ping", description="test", guild=GUILD)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"pong 🏓 ({round(bot.latency*1000)}ms)"
    )

@bot.tree.command(name="checkprofile", description="Check RNGdle profile", guild=GUILD)
async def checkprofile(interaction: discord.Interaction, username: str):
    await interaction.response.defer()

    ep, data = get_user_data(username)

    store = load_data()
    xp = store["xp"].get(username, 0)
    streak = store["streaks"].get(username, {}).get("count", 0)

    embed = discord.Embed(title=f"{username} Profile", color=0x00ffcc)

    embed.add_field(name="🎲 EP", value=str(ep), inline=True)
    embed.add_field(name="⭐ XP", value=str(xp), inline=True)
    embed.add_field(name="🔥 Streak", value=str(streak), inline=True)

    if data:
        embed.add_field(name="🔢 Roll", value=data["roll"], inline=False)
        embed.add_field(name="🔗 Link", value=data["url"], inline=False)

        if data.get("quote"):
            embed.add_field(name="💬 Quote", value=data["quote"], inline=False)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="leaderboard", description="XP leaderboard", guild=GUILD)
async def leaderboard(interaction: discord.Interaction):
    data = load_data()
    xp = data["xp"]

    if not xp:
        await interaction.response.send_message("Nobody has earned XP yet.")
        return

    sorted_users = sorted(xp.items(), key=lambda x: x[1], reverse=True)

    embed = discord.Embed(title="🏆 XP Leaderboard", color=0xffd700)

    for i, (user, value) in enumerate(sorted_users[:10], 1):
        embed.add_field(
            name=f"#{i} {user}",
            value=f"{value:,} XP",
            inline=False
        )

    await interaction.response.send_message(embed=embed)

# ---------------- DAILY POST ----------------

async def post_daily():
    guild = bot.get_guild(GUILD_ID)
    channel = guild.get_channel(CHANNEL_ID)
    role = guild.get_role(ROLE_ID)

    players = load_players()
    results = []

    store = load_data()

    for u in players:
        old_streak = get_streak(u)

        ep, data = get_user_data(u)

        new_streak = get_streak(u)

        if data:
            results.append((u, ep, data))

            if new_streak > old_streak:
                store["xp"][u] = store["xp"].get(u, 0) + 100

    save_data(store)

    results.sort(key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title="📊 Daily RNGdle Leaderboard",
        description=random.choice(REMINDER_MESSAGES),
        color=0x5865F2
    )

    for i, (u, ep, data) in enumerate(results[:10], 1):
        embed.add_field(
            name=f"#{i} {u}",
            value=(
                f"🎲 EP: {ep:,}\n"
                f"🔥 Streak: {get_streak(u)}\n"
                f"💬 {data.get('quote') or 'No quote'}\n"
                f"🔗 {data['url']}"
            ),
            inline=False
        )

    await channel.send(content=role.mention, embed=embed)

# ---------------- SCHEDULER ----------------

last_run_date = None

@tasks.loop(minutes=1)
async def daily_loop():
    global last_run_date

    try:
        now = datetime.now(TIMEZONE)
        today = now.date()

        print("Loop tick:", now)

        if now.hour == 22 and now.minute == 32:
            if last_run_date != today:
                last_run_date = today
                print("Running daily post...")
                await post_daily()

    except Exception as e:
        print("loop error:", e)

# ---------------- RUN ----------------

import traceback

print("ABOUT TO RUN BOT")

try:
    bot.run(TOKEN)
except Exception as e:
    print("BOT CRASHED:", e)
    traceback.print_exc()
