import os
import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
from datetime import datetime, timezone, timedelta
import asyncio
from aiohttp import web

# 環境変数からボットのトークンと出力チャンネルIDを取得
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
OUTPUT_CHANNEL_ID = os.environ.get("OUTPUT_CHANNEL_ID")  # メッセージ送信先のチャンネルID

if not DISCORD_BOT_TOKEN:
    print("環境変数 DISCORD_BOT_TOKEN が設定されていません。")
    exit(1)

if not OUTPUT_CHANNEL_ID:
    print("環境変数 OUTPUT_CHANNEL_ID が設定されていません。")
    exit(1)

# Intentsの設定
intents = discord.Intents.default()
intents.message_content = True       # メッセージコンテンツのインテントを有効化
intents.presences = True             # Presence（アクティビティ）インテントを有効化
intents.members = True               # メンバー情報のインテントを有効化

# ボットの初期化
bot = commands.Bot(command_prefix="!", intents=intents)

# データ保存用のファイル
DATA_FILE = 'users_activity.json'

# データをロードする関数
def load_user_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# データを保存する関数
def save_user_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 初期データのロード
registered_users = load_user_data()

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
    if user_id not in registered_users:
        return  # 登録されていないユーザーは無視

    was_playing = is_playing_lol(before.activity)
    is_playing = is_playing_lol(after.activity)

    if not was_playing and is_playing:
        # プレイを開始した場合、タイムスタンプを記録し、通知フラグをリセット
        registered_users[user_id]['last_play'] = datetime.now(timezone.utc).isoformat()
        registered_users[user_id]['notified'] = False
        save_user_data(registered_users)

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

# バックグラウンドタスク: 1時間ごとにチェック
@tasks.loop(hours=1)
async def check_last_play():
    now = datetime.now(timezone.utc)
    threshold = timedelta(hours=24)
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))

    if not output_channel:
        print("指定されたチャンネルが見つかりません。")
        return

    for user_id, data in registered_users.items():
        last_play_str = data.get('last_play')
        notified = data.get('notified', False)

        if not last_play_str:
            continue  # プレイ履歴がない場合はスキップ

        last_play = datetime.fromisoformat(last_play_str)
        time_diff = now - last_play

        if time_diff >= threshold and not notified:
            user = bot.get_user(int(user_id))
            if user:
                try:
                    await output_channel.send(f"{user.mention} LOLから逃げるな。お前を見ている")
                    # 通知フラグを更新
                    registered_users[user_id]['notified'] = True
                except Exception as e:
                    print(f"ユーザー {user_id} にメッセージを送信できませんでした: {e}")
            else:
                print(f"ユーザー {user_id} が見つかりません。")
    
    save_user_data(registered_users)

# エラーハンドリング
@bot.event
async def on_command_error(interaction: discord.Interaction, error):
    print(f"Error: {error}")
    await interaction.response.send_message("エラーが発生しました。管理者に報告してください。", ephemeral=True)

# /register コマンドの実装
@bot.tree.command(name="register", description="Discordユーザーを監視対象に登録します。")
@app_commands.describe(
    user="登録したいユーザーを@メンションで指定"
)
async def register_command(interaction: discord.Interaction, user: discord.User):
    if user.id in registered_users:
        await interaction.response.send_message(f"{user.mention} は既に登録されています。", ephemeral=True)
        return
    registered_users[user.id] = {
        "last_play": None,  # 初期値はNone
        "notified": False
    }
    save_user_data(registered_users)
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send(f"{user.mention} を監視対象に登録しました！")
    else:
        await interaction.response.send_message("指定されたチャンネルが見つかりません。", ephemeral=True)

# /check コマンドの実装
@bot.tree.command(name="check", description="ユーザーが最後にLoLをプレイしてからの経過時間を表示します。")
@app_commands.describe(user="対象のユーザーを@メンションで指定")
async def check_command(interaction: discord.Interaction, user: discord.User):
    if user.id not in registered_users:
        await interaction.response.send_message("まだ登録されていません。 `/register` コマンドで登録してください。", ephemeral=True)
        return
    last_play = registered_users[user.id].get('last_play')
    if not last_play:
        await interaction.response.send_message(f"{user.mention} はまだLoLをプレイしていません。", ephemeral=True)
        return
    last_play_dt = datetime.fromisoformat(last_play)
    now_dt = datetime.now(timezone.utc)
    diff = now_dt - last_play_dt
    hours = diff.total_seconds() / 3600.0
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send(
            f"{user.mention} が最後にLoLをプレイしてから **{hours:.1f}時間** 経過しました。"
        )
    else:
        await interaction.response.send_message("指定されたチャンネルが見つかりません。", ephemeral=True)

# /login コマンドの実装
@bot.tree.command(name="login", description="Botを起動し、挨拶メッセージを送信します。")
async def login_command(interaction: discord.Interaction):
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send("ピピーッ❗️🔔⚡️LOL脱走兵監視botです❗️👊👮❗️")
    else:
        await interaction.response.send_message("指定されたチャンネルが見つかりません。", ephemeral=True)

# /logout コマンドの実装
@bot.tree.command(name="logout", description="Botをオフラインにします。")
async def logout_command(interaction: discord.Interaction):
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send("Botをオフラインにします。")
    await interaction.response.send_message("Botをオフラインにします。", ephemeral=True)
    await bot.close()

# /rules コマンドの実装
@bot.tree.command(name="rules", description="BOTの機能を解説します。")
async def rules_command(interaction: discord.Interaction):
    text = (
        "```\n"
        "このBotは、Discordのアクティビティ情報を利用してLoLの最新プレイ時間をチェックできるDiscord Botです。\n"
        "主なコマンド:\n"
        "/register @ユーザー: Discordユーザーを監視対象に登録\n"
        "/check @ユーザー: 最後にLoLをプレイしてから何時間経過しているかチェック\n"
        "/login: Botの挨拶メッセージ送信 & ログイン\n"
        "/logout: Botをオフラインにする\n"
        "/rules: この説明を表示\n"
        "```"
    )
    # 指定されたチャンネルにメッセージを送信
    output_channel = bot.get_channel(int(OUTPUT_CHANNEL_ID))
    if output_channel:
        await output_channel.send(text)
    else:
        await interaction.response.send_message("指定されたチャンネルが見つかりません。", ephemeral=True)

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
    
    # 両方のタスクを並行して実行
    await asyncio.gather(bot_task)

# ボットとサーバーを起動
def main():
    try:
        asyncio.run(run_bot_and_server())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
    except Exception as e:
        print(f"Botの起動中にエラーが発生しました: {e}")

if __name__ == "__main__":
    main()
