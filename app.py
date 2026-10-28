import os
import time
import uuid
import json
import threading
import requests
from flask import Flask, request, Response, send_from_directory, jsonify, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL = int(os.getenv("DEST_CHANNEL", "0"))
STORAGE_CHANNEL = int(os.getenv("STORAGE_CHANNEL", "0")) 
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
ADMIN_KEY = os.getenv("ADMIN_KEY", "test123")
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "Watch")

# Frontend Variables (Render se aayenge)
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
MONETAG_ZONE = os.getenv("MONETAG_ZONE", "")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/telegram")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "Join Our Channel")
TADS_WIDGET_ID = os.getenv("TADS_WIDGET_ID", "")
TADS_SDK_URL = os.getenv("TADS_SDK_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env variable missing")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__, static_folder="static")

# Database File
DB_FILE = "db.json"
def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: return json.load(f)
    return {}
def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f)

video_db = load_db()
media_buffer = {}
buffer_lock = threading.Lock()

# ---------- Bot Handlers ----------
@bot.message_handler(commands=['start'])
def handle_start(message):
    args = message.text.split()
    if len(args) > 1:
        vid_id = args[1]
        entry = video_db.get(vid_id)
        if entry:
            bot.send_message(message.chat.id, "✅ Here is your requested video. Enjoy!")
            try:
                bot.send_video(message.chat.id, entry["video"])
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Error sending video: {e}")
        else:
            bot.send_message(message.chat.id, "❌ Video not found.")
    else:
        bot.send_message(message.chat.id, "👋 Welcome! Please send me a Photo and Video **together** to generate a new link.")

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

    if STORAGE_CHANNEL != 0:
        try:
            vid_copy = bot.copy_message(STORAGE_CHANNEL, chat_id, video_msg.message_id)
            bot.edit_message_caption(chat_id=STORAGE_CHANNEL, message_id=vid_copy.message_id, caption=f"🎥 Video ID: `{unique_id}`", parse_mode="Markdown")
            safe_video_id = vid_copy.video.file_id
            
            photo_copy = bot.copy_message(STORAGE_CHANNEL, chat_id, photo_msg.message_id)
            bot.edit_message_caption(chat_id=STORAGE_CHANNEL, message_id=photo_copy.message_id, caption=f"🖼 Thumbnail ID: `{unique_id}`", parse_mode="Markdown")
            safe_photo_id = photo_copy.photo[-1].file_id
        except Exception as e:
            print(f"⚠️ Cloud storage failed: {e}")

    video_db[unique_id] = {"video": safe_video_id, "thumb": safe_photo_id}
    save_db(video_db)

    bot_username = bot.get_me().username
    mini_app_url = f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp={unique_id}"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("👉 Play Online Free 🍑💦", url=mini_app_url))
    caption_text = "🎬 Watch this video for FREE!\n\n▶️ Tap the button below to play instantly"

    try:
        bot.send_photo(DEST_CHANNEL, safe_photo_id, caption=caption_text, reply_markup=markup)
        bot.send_message(chat_id, f"✅ Uploaded successfully!\nYour Video ID is: `{unique_id}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to send to channel. Error: {e}")

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
    html_content = html_content.replace("__TADS_WIDGET_ID__", TADS_WIDGET_ID)
    html_content = html_content.replace("__TADS_SDK_URL__", TADS_SDK_URL)
    
    return Response(html_content, mimetype="text/html")

@app.route("/thumb/<vid_id>")
def get_thumbnail(vid_id):
    entry = video_db.get(vid_id)
    if not entry: abort(404)
    try:
        file_info = bot.get_file(entry["thumb"])
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
