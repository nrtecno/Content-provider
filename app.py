import os
import time
import uuid
import threading
import requests
from flask import Flask, request, Response, send_from_directory, jsonify, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
import libsql_client

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL = int(os.getenv("DEST_CHANNEL", "0"))
STORAGE_CHANNEL = int(os.getenv("STORAGE_CHANNEL", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
ADMIN_KEY = os.getenv("ADMIN_KEY", "test123")
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "Wach")

# Frontend Variables
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
MONETAG_ZONE = os.getenv("MONETAG_ZONE", "")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/nr_hackz")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "Super Tech Channel")
ADSGRAM_BLOCK_ID = os.getenv("ADSGRAM_BLOCK_ID", "")

# ---------- Turso Database Connection ----------
TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env variable missing")
if not TURSO_URL or not TURSO_AUTH_TOKEN:
    raise RuntimeError("Turso DB credentials missing")

if TURSO_URL.startswith("libsql://"):
    TURSO_URL = TURSO_URL.replace("libsql://", "https://", 1)

db_client = libsql_client.create_client_sync(
    url=TURSO_URL,
    auth_token=TURSO_AUTH_TOKEN
)

# Table initialize
try:
    db_client.execute("CREATE TABLE IF NOT EXISTS videos (id TEXT PRIMARY KEY, video_id TEXT, thumb_id TEXT)")
except Exception as e:
    print(f"DB Init Error: {e}")

# ---------- Bot Setup ----------
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__, static_folder="static")

media_buffer = {}
buffer_lock = threading.Lock()

# ---------- Bot Handlers ----------
@bot.message_handler(commands=['start'])
def handle_start(message):
    args = message.text.split()
    if len(args) > 1:
        vid_id = args[1]
        try:
            result = db_client.execute("SELECT video_id FROM videos WHERE id = ?", [vid_id])
            if result.rows:
                bot.send_message(message.chat.id, "✅ Here is your requested video. Enjoy!")
                bot.send_video(message.chat.id, result.rows[0][0])
            else:
                bot.send_message(message.chat.id, "❌ Video not found.")
        except Exception as e:
            bot.send_message(message.chat.id, "❌ Database error. Please try again.")
            print(f"DB Fetch Error: {e}")
    else:
        bot.send_message(message.chat.id, "👋 Welcome! Send me a Photo and Video **together** to generate a new link.")

@bot.message_handler(content_types=["photo", "video"])
def handle_bot_upload(message):
    if not message.media_group_id:
        bot.reply_to(message, "⚠️ Please send the Photo and Video **together** as an album.")
        return
    mgid = message.media_group_id
    with buffer_lock:
        media_buffer.setdefault(mgid, []).append(message)
    threading.Timer(3.0, process_upload, args=[mgid, message.chat.id]).start()

def process_upload(mgid, chat_id):
    with buffer_lock:
        msgs = media_buffer.pop(mgid, [])
    if not msgs: return

    photo_msg = next((m for m in msgs if m.content_type == "photo"), None)
    video_msg = next((m for m in msgs if m.content_type == "video"), None)

    if not photo_msg or not video_msg:
        bot.send_message(chat_id, "❌ Error: Please send exactly 1 Photo and 1 Video together.")
        return

    unique_id = uuid.uuid4().hex[:10].upper()
    safe_video_id = video_msg.video.file_id
    safe_photo_id = photo_msg.photo[-1].file_id

    # 1. Cloud Storage (Storage Channel) me save karein
    if STORAGE_CHANNEL != 0:
        try:
            vid_copy = bot.copy_message(STORAGE_CHANNEL, chat_id, video_msg.message_id)
            bot.edit_message_caption(chat_id=STORAGE_CHANNEL, message_id=vid_copy.message_id, caption=f"🎥 Video ID: `{unique_id}`", parse_mode="Markdown")
            safe_video_id = vid_copy.video.file_id
            
            photo_copy = bot.copy_message(STORAGE_CHANNEL, chat_id, photo_msg.message_id)
            bot.edit_message_caption(chat_id=STORAGE_CHANNEL, message_id=photo_copy.message_id, caption=f"🖼 Thumbnail ID: `{unique_id}`", parse_mode="Markdown")
            safe_photo_id = photo_copy.photo[-1].file_id
            print("✅ Saved to Storage Channel")
        except Exception as e:
            print(f"⚠️ Cloud storage failed: {e}")

    # 2. Turso DB me save karein (Agar fail ho toh rukna nahi hai)
    try:
        db_client.execute(
            "INSERT OR REPLACE INTO videos (id, video_id, thumb_id) VALUES (?, ?, ?)",
            [unique_id, safe_video_id, safe_photo_id]
        )
        print("✅ Saved to Database")
    except Exception as e:
        print(f"❌ Database Error (Ignoring to send to channel): {e}")
        bot.send_message(chat_id, f"⚠️ Warning: Video saved in Storage, but DB failed.")

    # 3. Destination Channel me post karein
    bot_username = bot.get_me().username
    mini_app_url = f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp={unique_id}"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("👉 Play Online Free 🍑💦", url=mini_app_url))
    caption_text = "🎬 Watch this video for FREE!\n\n▶️ Tap the button below to play instantly"

    try:
        bot.send_photo(DEST_CHANNEL, safe_photo_id, caption=caption_text, reply_markup=markup)
        bot.send_message(chat_id, f"✅ Uploaded successfully!\nYour Video ID is: `{unique_id}`", parse_mode="Markdown")
        print("✅ Posted to Destination Channel")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to send to DEST Channel. Check if bot is Admin & Channel ID is correct. Error: {e}")
        print(f"❌ Dest Channel Error: {e}")

# ---------- Flask Routes ----------
@app.route("/health")
def health(): return "OK", 200

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.headers.get("content-type") == "application/json":
        update = Update.de_json(request.data.decode("utf-8"))
        bot.process_new_updates([update])
        return "", 200
    return "", 403

@app.route("/miniapp")
def miniapp_page():
    with open(os.path.join("static", "miniapp.html"), "r", encoding="utf-8") as f:
        html_content = f.read()
    
    html_content = html_content.replace("__BOT_USERNAME__", BOT_USERNAME)
    html_content = html_content.replace("__MONETAG_ZONE__", MONETAG_ZONE)
    html_content = html_content.replace("__CHANNEL_LINK__", CHANNEL_LINK)
    html_content = html_content.replace("__CHANNEL_NAME__", CHANNEL_NAME)
    html_content = html_content.replace("__ADSGRAM_BLOCK_ID__", ADSGRAM_BLOCK_ID)
    
    return Response(html_content, mimetype="text/html")

@app.route("/thumb/<vid_id>")
def get_thumbnail(vid_id):
    try:
        result = db_client.execute("SELECT thumb_id FROM videos WHERE id = ?", [vid_id])
        if not result.rows: abort(404)
        
        file_info = bot.get_file(result.rows[0][0])
        tg_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        req = requests.get(tg_url, stream=True)
        return Response(req.iter_content(chunk_size=1024), content_type='image/jpeg')
    except Exception:
        abort(500)

@app.route("/admin/set-webhook")
def admin_set_webhook():
    if request.args.get("key") != ADMIN_KEY: abort(403)
    bot.remove_webhook()
    time.sleep(1)
    ok = bot.set_webhook(url=f"{PUBLIC_URL}/{BOT_TOKEN}")
    return jsonify({"ok": ok})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
