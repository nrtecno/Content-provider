import os
import time
import threading
import requests
import json
from flask import Flask, request, Response, send_from_directory, jsonify, abort
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL = int(os.getenv("DEST_CHANNEL", "0"))
STORAGE_CHANNEL = int(os.getenv("STORAGE_CHANNEL", "0"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
ADMIN_KEY = os.getenv("ADMIN_KEY", "test123")
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "Wach")

BOT_USERNAME = os.getenv("BOT_USERNAME", "")
MONETAG_ZONE = os.getenv("MONETAG_ZONE", "")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/nr_hackz")
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "Super Tech Channel")
ADSGRAM_BLOCK_ID = os.getenv("ADSGRAM_BLOCK_ID", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN env variable missing")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__, static_folder="static")

media_buffer = {}
buffer_lock = threading.Lock()

# ---------- Local JSON Cache for Thumbnails ----------
DB_FILE = "data.json"
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f)

# ---------- Auto Delete Function ----------
def delete_message_after_delay(chat_id, message_id, delay_seconds):
    time.sleep(delay_seconds)
    try:
        bot.delete_message(chat_id, message_id)
        print(f"🗑️ Auto-deleted video (Message ID: {message_id}) from chat {chat_id}")
    except Exception as e:
        print(f"⚠️ Failed to delete message: {e}")

# ---------- Bot Handlers ----------
@bot.message_handler(commands=['start'])
def handle_start(message):
    args = message.text.split()
    if len(args) > 1:
        try:
            unique_id = args[1] # Yahi hamari string ID hai (Message ID)
            chat_id = message.chat.id
            
            warning_text = (
                "<blockquote>📥 <b>forward anyone & save....</b>\n\n"
                "The video will be removed from here in 10 minutes.</blockquote>"
            )
            bot.send_message(chat_id, warning_text, parse_mode="HTML")
            
            # JSON cache check karein
            video_db = load_db()
            entry = video_db.get(unique_id)
            
            if entry and "video" in entry:
                sent_video = bot.send_video(chat_id, entry["video"])
            else:
                # Agar cache delete ho gaya hai, toh Storage Channel se direct copy karein
                sent_video = bot.copy_message(
                    chat_id=chat_id, 
                    from_chat_id=STORAGE_CHANNEL, 
                    message_id=int(unique_id)
                )
            
            # 10 Minute (600 seconds) ka timer
            timer = threading.Thread(
                target=delete_message_after_delay, 
                args=(chat_id, sent_video.message_id, 600)
            )
            timer.daemon = True
            timer.start()
            
        except Exception as e:
            bot.send_message(message.chat.id, "❌ Video not found or deleted.")
            print(f"Error fetching: {e}")
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

    # Storage Channel me bhejein aur Message ID nikaalein
    try:
        vid_copy = bot.copy_message(STORAGE_CHANNEL, chat_id, video_msg.message_id)
        unique_id = str(vid_copy.message_id) # Chhoti ID (Jaise: 15)
        
        photo_copy = bot.copy_message(STORAGE_CHANNEL, chat_id, photo_msg.message_id)
        
        # Thumbnail aur Video ID ko JSON me save karein
        video_db = load_db()
        video_db[unique_id] = {
            "video": vid_copy.video.file_id,
            "thumb": photo_copy.photo[-1].file_id
        }
        save_db(video_db)
        print("✅ Saved to Storage & JSON Cache")
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ Storage Channel Error: {e}")
        return

    bot_username = bot.get_me().username
    mini_app_url = f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp={unique_id}"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("👉 Play Online Free 🍑💦", url=mini_app_url))
    caption_text = "🎬 Watch this video for FREE!\n\n▶️ Tap the button below to play instantly"

    try:
        bot.send_photo(DEST_CHANNEL, photo_copy.photo[-1].file_id, caption=caption_text, reply_markup=markup)
        bot.send_message(chat_id, f"✅ Uploaded successfully!\nYour Video ID is: `{unique_id}`", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Dest Channel Error: {e}")

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
        video_db = load_db()
        entry = video_db.get(vid_id)
        if not entry or "thumb" not in entry: abort(404)
        
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
