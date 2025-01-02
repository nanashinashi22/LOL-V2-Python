import os
import discord
from discord import app_commands
from discord.ext import commands
import requests
from datetime import datetime, timezone
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

# 環境変数からAPIキーを取得
RIOT_API_KEY = os.environ.get("RIOT_API_KEY")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# 最初にHTTPサーバーを起動する関数
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'OK')

def run_health_check_server():
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    httpd.serve_forever()

# HTTPサーバーを別スレッドで起動
server_thread = Thread(target=run_health_check_server)
server_thread.daemon = True
server_thread.start()

# Discordボットのコード
intents = discord.Intents.default()
intents.message_content = True  # メッセージコンテンツインテントを有効化

bot = commands.Bot(command_prefix="!", intents=intents)

registered_riot_info = {}

def get_summoner_info(region: str, summoner_name: str):
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner_name}"
    headers = {"X-Riot-Token": RIOT_API_KEY}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        return None

def get_last_match_timestamp(region: str, puuid: str):
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=1"
    headers = {"X-Riot-Token": RIOT_API_KEY}
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None
    match_ids = resp.json()
    if not match_ids:
        return None
    match_id = match_ids[0]
    url_detail = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    resp_detail = requests.get(url_detail, headers=headers)
    if resp_detail.status_code != 200:
        return None
    match_data = resp_detail.json()
    game_start_timestamp_ms = match_data["info"]["gameStartTimestamp"]
    return game_start_timestamp_ms

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)

@bot.tree.command(name="login", description="Botを起動し、挨拶メッセージを送信します。")
async def login_command(interaction: discord.Interaction):
    await interaction.response.send_message("ピピーッ❗️🔔⚡️LOL脱走兵監視botです❗️👊👮❗️")

@bot.tree.command(name="logout", description="Botをオフラインにします。")
async def logout_command(interaction: discord.Interaction):
    await interaction.response.send_message("Botをオフラインにします。")
    await bot.close()

@bot.tree.command(name="rules", description="BOTの機能を解説します。")
async def rules_command(interaction: discord.Interaction):
    text = (
        "```\n"
        "このBotは、RiotAPIを利用してLoLの最新プレイ時間をチェックできるDiscord Botです。\n"
        "主なコマンド:\n"
        "/register @ユーザー サモナーネーム #タグ: DiscordユーザーとRiotIDを紐づけ\n"
        "/check @ユーザー: 最後にLoLをプレイしてから何時間経過しているかチェック\n"
        "/login: Botの挨拶メッセージ送信 & ログイン\n"
        "/logout: Botをオフラインにする\n"
        "/rules: この説明を表示\n"
        "```"
    )
    await interaction.response.send_message(text)

@bot.tree.command(name="register", description="DiscordユーザーとRiotアカウントを紐づけます。")
@app_commands.describe(
    user="登録したいユーザーを@メンションで指定",
    summoner_name="サモナーネーム",
    tag="RiotIDの#タグ部分"
)
async def register_command(interaction: discord.Interaction, user: discord.User, summoner_name: str, tag: str):
    full_summoner_name = f"{summoner_name}"
    region = "asia"
    summoner_info = get_summoner_info(region, full_summoner_name)
    if not summoner_info:
        await interaction.response.send_message("サモナー情報が取得できませんでした。名前やタグを再確認してください。", ephemeral=True)
        return
    registered_riot_info[user.id] = {
        "name": summoner_name,
        "tag": tag,
        "puuid": summoner_info["puuid"],
        "region": region
    }
    await interaction.response.send_message(
        f"{user.mention} を登録しました！\n"
        f"サモナーネーム: {summoner_name} #{tag}\n"
        f"puuid: {summoner_info['puuid']}"
    )

@bot.tree.command(name="check", description="ユーザーが最後にLoLをプレイしてからの経過時間を表示します。")
@app_commands.describe(user="対象のユーザーを@メンションで指定")
async def check_command(interaction: discord.Interaction, user: discord.User):
    if user.id not in registered_riot_info:
        await interaction.response.send_message("まだ登録されていません。 /register コマンドで登録してください。", ephemeral=True)
        return
    riot_data = registered_riot_info[user.id]
    puuid = riot_data["puuid"]
    region = riot_data["region"]
    last_match_timestamp_ms = get_last_match_timestamp(region, puuid)
    if not last_match_timestamp_ms:
        await interaction.response.send_message(f"{user.mention} の試合履歴が見つかりません。", ephemeral=True)
        return
    last_match_timestamp_s = last_match_timestamp_ms / 1000.0
    last_play_dt = datetime.fromtimestamp(last_match_timestamp_s, tz=timezone.utc)
    now_dt = datetime.now(tz=timezone.utc)
    diff = now_dt - last_play_dt
    hours = diff.total_seconds() / 3600.0
    await interaction.response.send_message(
        f"{user.mention} が最後にLoLをプレイしてから **{hours:.1f}時間** 経過しました。"
    )

def main():
    if not RIOT_API_KEY or not DISCORD_BOT_TOKEN:
        print("環境変数が設定されていません。")
        exit(1)
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"Botの起動中にエラーが発生しました: {e}")
        exit(1)

if __name__ == "__main__":
    main()
