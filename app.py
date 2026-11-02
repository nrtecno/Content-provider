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

# Admin ID 
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) 

# Frontend Variables
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
broadcast_mode = False
admin_waiting_for_sender_id = False # Naya variable

# ---------- File Management Helpers ----------
USERS_FILE = "users.json"
SENDERS_FILE = "senders.json"
DB_FILE = "data.json"

def load_json(filename, default):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f: return json.load(f)
        except: return default
    return default

def save_json(filename, data):
    with open(filename, "w") as f: json.dump(data, f)

def load_users(): return load_json(USERS_FILE, [])
def save_user(user_id):
    users = load_users()
    if user_id not in users:
        users.append(user_id)
        save_json(USERS_FILE, users)

def load_senders(): return load_json(SENDERS_FILE, [])
def add_sender(user_id):
    senders = load_senders()
    if user_id not in senders:
        senders.append(user_id)
        save_json(SENDERS_FILE, senders)
def remove_sender(user_id):
    senders = load_senders()
    if user_id in senders:
        senders.remove(user_id)
        save_json(SENDERS_FILE, senders)

def load_db(): return load_json(DB_FILE, {})
def save_db(data): save_json(DB_FILE, data)

# ---------- Auto Delete Function ----------
def delete_message_after_delay(chat_id, message_id, delay_seconds):
    time.sleep(delay_seconds)
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        print(f"⚠️ Failed to delete message: {e}")

# ==========================================
# 🚨 COMMANDS
# ==========================================

@bot.message_handler(commands=['start'])
def handle_start(message):
    save_user(message.chat.id)
    
    args = message.text.split()
    if len(args) > 1:
        try:
            unique_id = args[1] 
            chat_id = message.chat.id
            
            warning_text = (
                "<blockquote>📥 <b>forward anyone & save....</b>\n\n"
                "The video will be removed from here in 10 minutes.</blockquote>"
            )
            bot.send_message(chat_id, warning_text, parse_mode="HTML")
            
            video_db = load_db()
            entry = video_db.get(unique_id)
            
            if entry and "video" in entry:
                sent_video = bot.send_video(chat_id, entry["video"])
            else:
                sent_video = bot.copy_message(
                    chat_id=chat_id, 
                    from_chat_id=STORAGE_CHANNEL, 
                    message_id=int(unique_id)
                )
            
            timer = threading.Thread(
                target=delete_message_after_delay, 
                args=(chat_id, sent_video.message_id, 600)
            )
            timer.daemon = True
            timer.start()
            
        except Exception as e:
            bot.send_message(message.chat.id, "❌ Video not found or deleted.")
    else:
        if message.from_user.id == ADMIN_ID:
            bot.send_message(message.chat.id, "ready hu boss... Thumbnail ke sath video bhejo")
        elif message.from_user.id in load_senders():
            bot.send_message(message.chat.id, "✅ Aap approved sender hain. Thumbnail ke sath video bhejo.")
        else:
            bot.send_message(message.chat.id, "you are not admin or sender...")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if message.from_user.id != ADMIN_ID: 
        bot.reply_to(message, "you are not admin..")
        return
    
    markup = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🟢 ON (Start Broadcast)", callback_data="bc_on"),
        InlineKeyboardButton("🔴 OFF (Stop Broadcast)", callback_data="bc_off")
    )
    bot.send_message(message.chat.id, "📢 **Broadcast Control Panel**\n\nYahan se broadcast ON/OFF karein:", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['sender'])
def cmd_sender(message):
    global admin_waiting_for_sender_id
    if message.from_user.id != ADMIN_ID: 
        bot.reply_to(message, "you are not admin..")
        return
    
    admin_waiting_for_sender_id = True
    bot.send_message(message.chat.id, "👤 Kripya us user ki **Telegram Numerical ID** bhejein jise aap Sender banana chahte hain.")

@bot.message_handler(commands=['senders'])
def cmd_senders(message):
    if message.from_user.id != ADMIN_ID: 
        bot.reply_to(message, "you are not admin..")
        return
    
    senders = load_senders()
    if not senders:
        bot.send_message(message.chat.id, "📭 Koi approved sender nahi hai abhi.")
        return
    
    bot.send_message(message.chat.id, "👥 **Approved Senders List:**\nNeeche diye gaye button se kisi bhi sender ko remove kar sakte hain.")
    for uid in senders:
        markup = InlineKeyboardMarkup().add(
            InlineKeyboardButton(f"🗑️ Remove Sender ({uid})", callback_data=f"rem_{uid}")
        )
        bot.send_message(message.chat.id, f"User ID: `{uid}`", reply_markup=markup, parse_mode="Markdown")

# ==========================================
# CALLBACKS (BUTTONS)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data in ["bc_on", "bc_off"])
def callback_broadcast(call):
    global broadcast_mode
    if call.from_user.id != ADMIN_ID: return
    
    if call.data == "bc_on":
        broadcast_mode = True
        users = load_users()
        bot.edit_message_text(f"✅ **Broadcast Mode: ON**\n\nTotal Users: {len(users)}\nAb aap koi bhi Message, Photo ya Video bhejenge, toh wo sabhi users ko chala jayega.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    else:
        broadcast_mode = False
        bot.edit_message_text("❌ **Broadcast Mode: OFF**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('rem_'))
def handle_remove_sender(call):
    if call.from_user.id != ADMIN_ID: return
    uid = int(call.data.split('_')[1])
    remove_sender(uid)
    bot.edit_message_text(f"🗑️ User `{uid}` removed from Sender list.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")
    bot.send_message(uid, "⚠️ Aapko video upload karne ki permission se hata diya gaya hai.")

# ==========================================
# MAIN HANDLER
# ==========================================
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'audio'])
def handle_all_messages(message):
    global broadcast_mode, admin_waiting_for_sender_id
    
    # 1. ADMIN ID CAPTURE
    if admin_waiting_for_sender_id and message.from_user.id == ADMIN_ID:
        try:
            new_sender_id = int(message.text.strip())
            add_sender(new_sender_id)
            bot.reply_to(message, f"✅ User `{new_sender_id}` ko Sender bana diya gaya hai.")
            bot.send_message(new_sender_id, "Congratulations 🎉.. you are sender...")
        except ValueError:
            bot.reply_to(message, "❌ Galat ID! Kripya sahi numerical ID bhejein.")
        
        admin_waiting_for_sender_id = False
        return

    # 2. BROADCAST CHECK
    if broadcast_mode and message.from_user.id == ADMIN_ID:
        users = load_users()
        if not users:
            bot.reply_to(message, "❌ Koi user nahi mila database me.")
            return
        
        bot.reply_to(message, f"🚀 Broadcasting to {len(users)} users... Please wait.")
        success = 0
        for uid in users:
            try:
                bot.copy_message(uid, message.chat.id, message.message_id)
                success += 1
                time.sleep(0.05)
            except Exception:
                pass
        
        bot.send_message(message.chat.id, f"✅ **Broadcast Complete!**\nSent to {success} users.")
        broadcast_mode = False
        return

    # 3. UPLOAD PERMISSION CHECK
    senders = load_senders()
    if message.from_user.id != ADMIN_ID and message.from_user.id not in senders:
        if message.content_type in ['photo', 'video']:
            bot.reply_to(message, "❌ Access Denied!\nAap is bot par video upload nahi kar sakte.")
        return

    if message.content_type not in ['photo', 'video']:
        return

    if not message.media_group_id:
        bot.reply_to(message, "⚠️ Please send the Photo and Video **together** as an album.")
        return
        
    mgid = message.media_group_id
    with buffer_lock:
        media_buffer.setdefault(mgid, []).append(message)
    threading.Timer(3.0, process_upload, args=[mgid, message.chat.id]).start()

# ---------- Upload Processing ----------
def process_upload(mgid, chat_id):
    with buffer_lock:
        msgs = media_buffer.pop(mgid, [])
    if not msgs: return

    photo_msg = next((m for m in msgs if m.content_type == "photo"), None)
    video_msg = next((m for m in msgs if m.content_type == "video"), None)

    if not photo_msg or not video_msg:
        bot.send_message(chat_id, "❌ Error: Please send exactly 1 Photo and 1 Video together.")
        return

    original_video_id = video_msg.video.file_id
    original_photo_id = photo_msg.photo[-1].file_id
    unique_id = str(int(time.time())) 

    if STORAGE_CHANNEL != 0:
        try:
            vid_copy = bot.copy_message(STORAGE_CHANNEL, chat_id, video_msg.message_id)
            unique_id = str(vid_copy.message_id) 
            bot.copy_message(STORAGE_CHANNEL, chat_id, photo_msg.message_id)
        except Exception as e:
            print(f"⚠️ Storage Channel Error: {e}")

    try:
        video_db = load_db()
        video_db[unique_id] = {
            "video": original_video_id,
            "thumb": original_photo_id
        }
        save_db(video_db)
    except Exception as e:
        print(f"⚠️ JSON Warning: {e}")

    bot_username = bot.get_me().username
    mini_app_url = f"https://t.me/{bot_username}/{APP_SHORT_NAME}?startapp={unique_id}"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("👉 Play Online Free 🍑💦", url=mini_app_url))
    caption_text = "🎬 Watch this video for FREE!\n\n▶️ Tap the button below to play instantly"

    try:
        bot.send_photo(DEST_CHANNEL, original_photo_id, caption=caption_text, reply_markup=markup)
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
        abort(404)

@app.route("/admin/set-webhook")
def admin_set_webhook():
    if request.args.get("key") != ADMIN_KEY: abort(403)
    bot.remove_webhook()
    time.sleep(1)
    ok = bot.set_webhook(url=f"{PUBLIC_URL}/{BOT_TOKEN}")
    return jsonify({"ok": ok})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
