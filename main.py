from dotenv import load_dotenv
load_dotenv()

import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
from datetime import datetime, timezone, timedelta
import asyncio
from aiohttp import web

# グローバル変数でボットの状態を管理
is_bot_active = True

# 環境変数からボットのトークンと出力チャンネルIDを取得
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
OUTPUT_CHANNEL_ID = os.environ.get("OUTPUT_CHANNEL_ID")  # メッセージ送信先のチャンネルID

if not DISCORD_BOT_TOKEN:
    print("環境変数 DISCORD_BOT_TOKEN が設定されていません。")
    exit(1)
else:
    print("DISCORD_BOT_TOKEN が正しく取得されました。")

if not OUTPUT_CHANNEL_ID:
    print("環境変数 OUTPUT_CHANNEL_ID が設定されていません。")
    exit(1)
else:
    print(f"OUTPUT_CHANNEL_ID が {OUTPUT_CHANNEL_ID} に設定されています。")

# Intentsの設定
intents = discord.Intents.default()
intents.message_content = True       # メッセージコンテンツのインテントを有効化
intents.presences = True             # Presence（アクティビティ）インテントを有効化
intents.members = True               # メンバー情報のインテントを有効化

# ボットの初期化
bot = commands.Bot(command_prefix="!", intents=intents)

# データベースの初期化
def init_db():
    conn = sqlite3.connect('users_activity.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            last_play TEXT,
            notified INTEGER
        )
    ''')
    conn.commit()
    conn.close()

# データベースにユーザーを登録
def register_user(user_id):
    conn = sqlite3.connect('users_activity.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, last_play, notified) VALUES (?, ?, ?)', (user_id, None, 0))
    conn.commit()
    conn.close()

# データベースからユーザー情報を取得
def get_user(user_id):
    conn = sqlite3.connect('users_activity.db')
    c = conn.cursor()
    c.execute('SELECT last_play, notified FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result

# データベースのユーザー情報を更新
def update_user(user_id, last_play=None, notified=None):
    conn = sqlite3.connect('users_activity.db')
    c = conn.cursor()
    if last_play is not None and notified is not None:
        c.execute('UPDATE users SET last_play = ?, notified = ? WHERE user_id = ?', (last_play, notified, user_id))
    elif last_play is not None:
        c.execute('UPDATE users SET last_play = ? WHERE user_id = ?', (last_play, user_id))
    elif notified is not None:
        c.execute('UPDATE users SET notified = ? WHERE user_id = ?', (notified, user_id))
    conn.commit()
    conn.close()

# ユーザーがLoLをプレイしているかどうかを判定する関数
def is_playing_lol(activity):
    if activity is None:
        return False
    # アクティビティの名前が「League of Legends」または「LoL」の場合にプレイ中と判断
    return activity.name.lower() in ["league of legends", "lol"]

# プレイ開始の通知を削除し、プレイ時間の記録のみを行う
@bot.event
async def on_presence_update(before, after):
    user_id = after.id
    user_data = get_user(user_id)
    if user_data is None:
        return  # 登録されていないユーザーは無視

    was_playing = is_playing_lol(before.activity)
    is_playing = is_playing_lol(after.activity)

    if not was_playing and is_playing:
        # プレイを開始した場合、タイムスタンプを記録し、通知フラグをリセット
        update_user(user_id, last_play=datetime.now(timezone.utc).isoformat(), notified=0)

    elif was_playing and not is_playing:
        # プレイを終了した場合の処理（必要に応じて追加）
        pass

# ボットが準備完了した際のイベント
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(e)
    check_last_play.start()  # バックグラウンドタスクの開始

# バックグラウンドタスク: 10分ごとにチェック
@tasks.loop(minutes=10)
async def check_last_play():
    now = datetime.now(timezone.utc)
    threshold = timedelta(hours=24)
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))

    if not output_channel:
        print("指定されたチャンネルが見つかりません。")
        return

    conn = sqlite3.connect('users_activity.db')
    c = conn.cursor()
    c.execute('SELECT user_id, last_play, notified FROM users')
    users = c.fetchall()
    conn.close()

    for user_id, last_play_str, notified in users:
        if not last_play_str:
            continue  # プレイ履歴がない場合はスキップ

        last_play = datetime.fromisoformat(last_play_str)
        time_diff = now - last_play

        if time_diff >= threshold and not notified:
            user = bot.get_user(user_id)
            if user:
                try:
                    await output_channel.send(f"{user.mention} LOLから逃げるな。お前を見ている")
                    update_user(user_id, notified=1)
                    print(f"通知メッセージを {user.display_name} に送信しました。")
                except Exception as e:
                    print(f"ユーザー {user_id} にメッセージを送信できませんでした: {e}")
            else:
                print(f"ユーザー {user_id} が見つかりません。")

# エラーハンドリング
@bot.event
async def on_command_error(interaction: discord.Interaction, error):
    print(f"Error: {error}")
    try:
        await interaction.response.send_message("エラーが発生しました。管理者に報告してください。", ephemeral=False)
    except:
        pass  # 既に応答が送信されている場合

# /register コマンドの実装
@bot.tree.command(name="register", description="Discordユーザーを監視対象に登録します。")
@app_commands.describe(
    user="登録したいユーザーを選択してください"
)
async def register_command(interaction: discord.Interaction, user: discord.User):
    # インタラクションへの迅速な応答
    await interaction.response.defer(ephemeral=False)

    if not is_bot_active:
        await interaction.followup.send("Botは現在オフラインです。`/login` コマンドで再起動してください。")
        return

    if get_user(user.id) is not None:
        await interaction.followup.send(f"{user.mention} は既に登録されています。")
        return

    register_user(user.id)
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send(f"{user.mention} を監視対象に登録しました！")
    else:
        await interaction.followup.send("指定されたチャンネルが見つかりません。")

# /check コマンドの実装
@bot.tree.command(name="check", description="ユーザーが最後にLoLをプレイしてからの経過時間を表示します。")
@app_commands.describe(user="対象のユーザーを選択してください")
async def check_command(interaction: discord.Interaction, user: discord.User):
    # インタラクションへの迅速な応答
    await interaction.response.defer(ephemeral=False)

    if not is_bot_active:
        await interaction.followup.send("Botは現在オフラインです。`/login` コマンドで再起動してください。")
        return

    user_data = get_user(user.id)
    if user_data is None:
        await interaction.followup.send("まだ登録されていません。 `/register` コマンドで登録してください。")
        return

    last_play_str, notified = user_data
    if not last_play_str:
        await interaction.followup.send(f"{user.mention} はまだLoLをプレイしていません。")
        return

    # ユーザーの現在のアクティビティを取得
    member = interaction.guild.get_member(user.id)
    if member:
        current_activity = member.activity
        if is_playing_lol(current_activity):
            await interaction.followup.send("現在プレイ中です。")
            return

    last_play_dt = datetime.fromisoformat(last_play_str)
    now_dt = datetime.now(timezone.utc)
    diff = now_dt - last_play_dt
    total_minutes = int(diff.total_seconds() // 60)

    if total_minutes < 60:
        minutes = (total_minutes // 10) * 10
        if minutes == 0:
            minutes = 10
        await interaction.followup.send(f"{user.mention} が最後にLoLをプレイしてから **{minutes}分** 経過しました。")
    else:
        hours = total_minutes // 60
        minutes = total_minutes % 60
        await interaction.followup.send(f"{user.mention} が最後にLoLをプレイしてから **{hours}時間 {minutes}分** 経過しました。")

# /login コマンドの実装
@bot.tree.command(name="login", description="Botを起動し、挨拶メッセージを送信します。")
async def login_command(interaction: discord.Interaction):
    global is_bot_active

    # インタラクションへの迅速な応答
    await interaction.response.defer(ephemeral=False)

    if is_bot_active:
        await interaction.followup.send("すでに起動しています。")
        return

    is_bot_active = True
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send("Botを再起動しました。挨拶メッセージを送信します。")
    else:
        await interaction.followup.send("指定されたチャンネルが見つかりません。")

    await interaction.followup.send("Botが起動しました。", ephemeral=False)

# /logout コマンドの実装
@bot.tree.command(name="logout", description="Botをオフラインにします。")
async def logout_command(interaction: discord.Interaction):
    global is_bot_active

    # インタラクションへの迅速な応答
    await interaction.response.defer(ephemeral=False)

    if not is_bot_active:
        await interaction.followup.send("すでにオフです。")
        return

    is_bot_active = False
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send("Botをオフラインにします。")
    else:
        await interaction.followup.send("指定されたチャンネルが見つかりません。")

    await interaction.followup.send("Botをオフラインにしました。", ephemeral=False)
    await bot.close()

# /rules コマンドの実装
@bot.tree.command(name="rules", description="LOL脱走兵を監視します。")
async def rules_command(interaction: discord.Interaction):
    text = (
        "```\n"
        "このBotは、Discordのアクティビティ情報を利用してLoLの最新プレイ時間をチェックできるDiscord Botです。\n"
        "主なコマンド:\n"
        "/register @ユーザー: Discordユーザーを監視対象に登録\n"
        "/check @ユーザー: 最後にLoLをプレイしてから何時間経過しているかチェック\n"
        "/login: Botの挨拶メッセージ送信 & 起動\n"
        "/logout: Botをオフラインにする\n"
        "/rules: LOL脱走兵を監視します。\n"
        "```"
    )
    # インタラクションへの迅速な応答
    await interaction.response.send_message(text, ephemeral=False)

# 簡単なHTTPサーバーの実装（Koyebのヘルスチェック用）
async def handle(request):
    return web.Response(text="OK")

async def init_app():
    app = web.Application()
    app.router.add_get('/', handle)
    return app

# ボットとHTTPサーバーを同時に実行する関数
async def run_bot_and_server():
    # ボットのタスク
    bot_task = asyncio.create_task(bot.start(DISCORD_BOT_TOKEN))
    
    # HTTPサーバーのタスク
    app = await init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8000)))
    await site.start()
    print("HTTP server started for health checks.")
    
    try:
        # 両方のタスクを並行して実行
        await asyncio.gather(bot_task)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()
        await bot.close()

# ボットとサーバーを起動
def main():
    init_db()
    try:
        asyncio.run(run_bot_and_server())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
    except Exception as e:
        print(f"Botの起動中にエラーが発生しました: {e}")

if __name__ == "__main__":
    main()
