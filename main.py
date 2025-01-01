import os
import discord
from discord import app_commands
from discord.ext import commands
import requests
from datetime import datetime, timezone

# Koyebの環境変数から取得
RIOT_API_KEY = os.environ["RIOT_API_KEY"]
DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]

# Botの起動に必要なIntent (ユーザー情報など取得する場合は適宜調整)
intents = discord.Intents.default()
intents.members = True

# Botオブジェクトの作成
bot = commands.Bot(command_prefix="!", intents=intents)

# ユーザーID(Discord) と Riotアカウント を紐づけるための簡易データベース (メモリ管理)
# 本番運用ではDBなどを使うことが望ましい
registered_riot_info = {}  # { discord_user_id: {"name": <サモナーネーム>, "tag": <タグ>, "puuid": <PUUID>} }

# RiotAPI呼び出しヘルパー関数例
def get_summoner_info(region: str, summoner_name: str):
    """
    SummonerNameからSummoner-v4 APIを叩きサモナー情報を取得する。
    返り値の例: {
        "id": string,
        "accountId": string,
        "puuid": string,
        "name": string,
        "profileIconId": int,
        "revisionDate": long,
        "summonerLevel": long
    }
    """
    url = f"https://{region}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner_name}"
    headers = {
        "X-Riot-Token": RIOT_API_KEY
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        return None

def get_last_match_timestamp(region: str, puuid: str):
    """
    PUUIDを使って最新の試合のタイムスタンプを取得する (Match-v5 API)
    """
    # 一番新しい1試合だけ取得
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=1"
    headers = {
        "X-Riot-Token": RIOT_API_KEY
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None

    match_ids = resp.json()
    if not match_ids:
        return None

    # match detail
    match_id = match_ids[0]
    url_detail = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    resp_detail = requests.get(url_detail, headers=headers)
    if resp_detail.status_code != 200:
        return None
    
    match_data = resp_detail.json()
    # 開始時刻 (UTC) を取る例
    game_start_timestamp_ms = match_data["info"]["gameStartTimestamp"]
    return game_start_timestamp_ms

@bot.event
async def on_ready():
    # Botが起動したときに呼ばれるイベント
    print(f"Logged in as {bot.user}")

    # Slash CommandsをGuildに同期 (テスト用にGuild単位で導入)
    # グローバルに登録する場合は guild=None を指定
    for guild in bot.guilds:
        try:
            await bot.tree.sync(guild=guild)
            print(f"Synced slash commands for {guild.name}.")
        except Exception as e:
            print(e)

############################
# Slash Command 実装部分
############################

@bot.tree.command(name="login", description="Botを起動し、挨拶メッセージを送信します。")
async def login_command(interaction: discord.Interaction):
    """
    /login -> 「ピピーッ❗️🔔⚡️LOL脱走兵監視botです❗️👊👮❗️」とチャット
    実際にはBotは既にonlineだが、「ログインしました」というメッセージを出すイメージ
    """
    await interaction.response.send_message("ピピーッ❗️🔔⚡️LOL脱走兵監視botです❗️👊👮❗️")

@bot.tree.command(name="logout", description="Botをオフラインにします。")
async def logout_command(interaction: discord.Interaction):
    """
    /logout -> ボットがオフラインになる (Botをプログラム的に終了させる)
    """
    await interaction.response.send_message("Botをオフラインにします。")
    await bot.close()

@bot.tree.command(name="rules", description="BOTの機能を解説します。")
async def rules_command(interaction: discord.Interaction):
    """
    /rules -> BOTの機能を解説
    """
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
    """
    例: /register @testuser SummonerName #JP1
    """
    # RiotIDを組み立て (SummonerName#TagLine)
    full_summoner_name = f"{summoner_name}"
    
    # Riot APIからpuuid取得
    # ※ JPサーバーなどアジア地域の場合: region="asia" を指定
    region = "asia"
    summoner_info = get_summoner_info(region, full_summoner_name)
    if not summoner_info:
        await interaction.response.send_message("サモナー情報が取得できませんでした。名前やタグを再確認してください。", ephemeral=True)
        return
    
    # メモリ上に登録 (puuidも保存)
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
    
    # タイムスタンプ(ms) → 秒
    last_match_timestamp_s = last_match_timestamp_ms / 1000.0
    last_play_dt = datetime.fromtimestamp(last_match_timestamp_s, tz=timezone.utc)
    now_dt = datetime.now(tz=timezone.utc)
    diff = now_dt - last_play_dt
    hours = diff.total_seconds() / 3600.0
    
    await interaction.response.send_message(
        f"{user.mention} が最後にLoLをプレイしてから **{hours:.1f}時間** 経過しました。"
    )

# メインエントリーポイント
def main():
    bot.run(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    main()
