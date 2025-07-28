import discord
from discord.ext import commands
import random
import string
import os
import requests
import psycopg2
from flask import Flask
from threading import Thread

# Version för att se att rätt script körs
SCRIPT_VERSION = "v2.0 - embeds & commands"

# ===== Flask keep-alive (Replit) =====
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=3000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ===== PostgreSQL setup =====
DATABASE_URL = os.environ["DATABASE_URL"]
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cur = conn.cursor()

# Skapa tabell om den inte finns
cur.execute("""
CREATE TABLE IF NOT EXISTS keys (
    key TEXT PRIMARY KEY,
    used BOOLEAN DEFAULT FALSE
);
""")
conn.commit()

def key_exists(key):
    cur.execute("SELECT used FROM keys WHERE key = %s;", (key,))
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]

def insert_key(new_key):
    cur.execute("INSERT INTO keys (key, used) VALUES (%s, %s)", (new_key, False))
    conn.commit()

def set_key_used(key):
    cur.execute("UPDATE keys SET used = TRUE WHERE key = %s;", (key,))
    conn.commit()

def wipe_all_keys():
    cur.execute("DELETE FROM keys;")
    conn.commit()

def get_active_keys():
    cur.execute("SELECT key FROM keys WHERE used = FALSE;")
    return [row[0] for row in cur.fetchall()]

TOKEN = os.environ["TOKEN"]
ROBLOX_COOKIE = os.environ["ROBLOX_SECURITY"]
ROBLOX_GROUP_ID = os.environ["ROBLOX_GROUP_ID"]
ALLOWED_ROLE_ID = int(os.environ["ALLOWED_ROLE_ID"])
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", 0))

# ===== Discord bot setup =====
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Roblox API helper functions =====
def generate_key(length=16):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def get_user_id(username):
    url = "https://users.roblox.com/v1/usernames/users"
    resp = requests.post(url, json={"usernames": [username]})
    if resp.status_code == 200:
        data = resp.json()
        if data["data"]:
            return data["data"][0]["id"]
    return None

def roblox_request_with_xcsrf(method, url, json_data=None):
    headers = {
        "Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}",
        "Content-Type": "application/json"
    }
    resp = requests.request(method, url, headers=headers, json=json_data)
    if resp.status_code == 403 and "X-CSRF-TOKEN" in resp.headers:
        headers["X-CSRF-TOKEN"] = resp.headers["X-CSRF-TOKEN"]
        resp = requests.request(method, url, headers=headers, json=json_data)
    return resp

def accept_group_request(user_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/join-requests/users/{user_id}"
    resp = roblox_request_with_xcsrf("POST", url)
    return resp.status_code == 200

def kick_from_group(user_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}"
    resp = roblox_request_with_xcsrf("DELETE", url)
    return resp.status_code == 200

def get_group_roles():
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles"
    resp = roblox_request_with_xcsrf("GET", url)
    if resp.status_code == 200:
        return resp.json()["roles"]
    return []

def get_user_role_in_group(user_id):
    url = f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
    resp = roblox_request_with_xcsrf("GET", url)
    if resp.status_code == 200:
        for g in resp.json()["data"]:
            if str(g["group"]["id"]) == str(ROBLOX_GROUP_ID):
                return g["role"]
    return None

def set_user_role(user_id, new_role_id):
    url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}"
    resp = roblox_request_with_xcsrf("PATCH", url, json_data={"roleId": new_role_id})
    return resp.status_code == 200

def promote_in_group(user_id):
    roles = get_group_roles()
    current = get_user_role_in_group(user_id)
    if not current: return False
    sorted_roles = sorted(roles, key=lambda r: r["rank"])
    for i, r in enumerate(sorted_roles):
        if r["id"] == current["id"] and i < len(sorted_roles)-1:
            return set_user_role(user_id, sorted_roles[i+1]["id"])
    return False

def demote_in_group(user_id):
    roles = get_group_roles()
    current = get_user_role_in_group(user_id)
    if not current: return False
    sorted_roles = sorted(roles, key=lambda r: r["rank"])
    for i, r in enumerate(sorted_roles):
        if r["id"] == current["id"] and i > 0:
            return set_user_role(user_id, sorted_roles[i-1]["id"])
    return False

def check_roblox_login():
    url = "https://auth.roblox.com/v2/logout"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"}
    resp = requests.post(url, headers=headers)
    return resp.status_code in [200, 403]

# ===== Helper function =====
def has_allowed_role(ctx):
    return any(r.id == ALLOWED_ROLE_ID for r in ctx.author.roles)

# ===== Events =====
@bot.event
async def on_ready():
    print("===================================")
    print(f"🚀 Bot started! Running script version: {SCRIPT_VERSION}")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    if check_roblox_login():
        print("✅ Roblox cookie works!")
    else:
        print("❌ Roblox cookie is invalid!")
    print("===================================")

    if LOG_CHANNEL_ID:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(f"Bot restarted and is now running `{SCRIPT_VERSION}`")

# ===== Commands with embeds =====
def embed_message(title, description, color):
    return discord.Embed(title=title, description=description, color=color)

@bot.command()
async def generatekey(ctx, amount: int):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    new_keys = []
    for _ in range(amount):
        new_key = generate_key()
        while key_exists(new_key) is not None:
            new_key = generate_key()
        insert_key(new_key)
        new_keys.append(new_key)
    embed = discord.Embed(title="Generated Keys", color=discord.Color.green())
    for k in new_keys:
        embed.add_field(name="Key", value=f"```{k}```", inline=False)
    try:
        await ctx.author.send(embed=embed)
        await ctx.send(embed=embed_message("Done", "Keys have been sent to your DM!", discord.Color.green()))
    except discord.Forbidden:
        await ctx.send(embed=embed_message("Warning", "Couldn't DM you. Enable DMs!", discord.Color.red()))

@bot.command()
async def wipekeys(ctx):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    wipe_all_keys()
    await ctx.send(embed=embed_message("Success", "All keys have been wiped!", discord.Color.green()))

@bot.command()
async def activekeys(ctx):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    active = get_active_keys()
    if not active:
        await ctx.send(embed=embed_message("Active Keys", "There are no active keys.", discord.Color.blue()))
    else:
        embed = discord.Embed(title="Active Keys", color=discord.Color.blue())
        for k in active:
            embed.add_field(name="Key", value=k, inline=False)
        await ctx.send(embed=embed)

@bot.command()
async def cmds(ctx):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    commands_text = (
        "!generatekey <amount>\n"
        "!wipekeys\n!activekeys\n!kick <username>\n"
        "!promote <username>\n!demote <username>\n"
        "!key <key> <username>\n!rank <username> <rank>\n"
        "!memberinfo <username>"
    )
    await ctx.send(embed=embed_message("Commands", commands_text, discord.Color.blue()))

@bot.command()
async def key(ctx, key: str, username: str):
    key_status = key_exists(key)
    if key_status is None:
        await ctx.send(embed=embed_message("Error", "Invalid key.", discord.Color.red()))
        return
    if key_status:
        await ctx.send(embed=embed_message("Error", "This key has already been used.", discord.Color.red()))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.send(embed=embed_message("Error", "Roblox user not found.", discord.Color.red()))
        return
    if accept_group_request(user_id):
        set_key_used(key)
        await ctx.send(embed=embed_message("Success", f"{username} has been accepted into the group!", discord.Color.green()))
    else:
        await ctx.send(embed=embed_message("Error", "Failed to accept the join request.", discord.Color.red()))

@bot.command()
async def kick(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.send(embed=embed_message("Error", "User not found.", discord.Color.red()))
        return
    if kick_from_group(user_id):
        await ctx.send(embed=embed_message("Success", f"{username} has been kicked.", discord.Color.green()))
    else:
        await ctx.send(embed=embed_message("Error", "Failed to kick user.", discord.Color.red()))

@bot.command()
async def promote(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.send(embed=embed_message("Error", "User not found.", discord.Color.red()))
        return
    if promote_in_group(user_id):
        await ctx.send(embed=embed_message("Success", f"{username} has been promoted.", discord.Color.green()))
    else:
        await ctx.send(embed=embed_message("Error", "Failed to promote user.", discord.Color.red()))

@bot.command()
async def demote(ctx, username: str):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.send(embed=embed_message("Error", "User not found.", discord.Color.red()))
        return
    if demote_in_group(user_id):
        await ctx.send(embed=embed_message("Success", f"{username} has been demoted.", discord.Color.green()))
    else:
        await ctx.send(embed=embed_message("Error", "Failed to demote user.", discord.Color.red()))

@bot.command()
async def rank(ctx, username: str, rank: int):
    if not has_allowed_role(ctx):
        await ctx.send(embed=embed_message("Permission Denied", "Du har inte behörighet.", discord.Color.red()))
        return
    user_id = get_user_id(username)
    if not user_id:
        await ctx.send(embed=embed_message("Error", "User not found.", discord.Color.red()))
        return
    roles = get_group_roles()
    for r in roles:
        if r["rank"] == rank:
            if set_user_role(user_id, r["id"]):
                await ctx.send(embed=embed_message("Success", f"{username} has been set to rank {rank}.", discord.Color.green()))
                return
    await ctx.send(embed=embed_message("Error", "Rank not found.", discord.Color.red()))

@bot.command()
async def memberinfo(ctx, username: str):
    user_id = get_user_id(username)
    if not user_id:
        await ctx.send(embed=embed_message("Error", "User not found.", discord.Color.red()))
        return
    role = get_user_role_in_group(user_id)
    rank = role["rank"] if role else "N/A"
    role_name = role["name"] if role else "N/A"
    embed = discord.Embed(title=f"Info för {username}", color=discord.Color.blue())
    embed.add_field(name="Rank", value=rank, inline=True)
    embed.add_field(name="Role", value=role_name, inline=True)
    await ctx.send(embed=embed)

# ===== Main =====
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
