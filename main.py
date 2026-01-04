import os
import time
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
from flask import Flask, request

TOKEN = os.getenv("TOKEN", "ВАШ_ТОКЕН")
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
user_states = {}

# ================== UTILS ==================

def mb(size):
    if not size:
        return "≈ ? МБ"
    try:
        return f"{size / 1024 / 1024:.1f} МБ"
    except Exception:
        return "≈ ? МБ"

def get_formats(url):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "format_sort": ["res:720", "res:480", "res:360", "res:240"],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("formats", []), info.get("title", "video")

# ================== BOT HANDLERS ==================

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Привет! Пришли ссылку на видео (YouTube, Pinterest, Facebook), и я дам варианты скачивания.")

@bot.message_handler(func=lambda m: True)
def handle_link(message):
    url = message.text.strip()
    user_id = message.chat.id

    try:
        formats, title = get_formats(url)
    except Exception as e:
        bot.reply_to(message, f"Ошибка при получении информации о видео:\n{e}")
        return

    user_states[user_id] = {"url": url, "formats": formats, "title": title}

    keyboard = InlineKeyboardMarkup()
    qualities = {}

    for f in formats:
        if f.get("vcodec") != "none" and f.get("height"):
            h = f["height"]
            size = f.get("filesize") or f.get("filesize_approx")
            if h not in qualities or (size and size > qualities[h][1]):
                qualities[h] = (f["format_id"], size)

    for h in sorted(qualities.keys()):
        fmt_id, size = qualities[h]
        keyboard.add(InlineKeyboardButton(f"{h}p ({mb(size)})", callback_data=f"v:{fmt_id}"))

    keyboard.add(InlineKeyboardButton("Лучшее качество", callback_data="best"))
    bot.reply_to(message, "Выбери качество:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda c: True)
def handle_quality(call):
    user_id = call.message.chat.id
    data = call.data
    state = user_states.get(user_id)

    if not state:
        bot.answer_callback_query(call.id, "Ссылка устарела, пришли новую")
        return

    url = state["url"]
    bot.answer_callback_query(call.id, "Скачиваю...")

    if data == "best":
        fmt = "bestvideo+bestaudio/best"
    else:
        fmt = f"{data[2:]}+bestaudio/best"

    ydl_opts = {
        "format": fmt,
        "outtmpl": "video.%(ext)s",
        "merge_output_format": "mp4",
        "retries": 15,
        "fragment_retries": 15,
        "noplaylist": True,
        "nocheckcertificate": True,
        "socket_timeout": 60,
        "http_chunk_size": 8 * 1024 * 1024,  # 8MB chunk
        "progress_hooks": [lambda d: print(d)],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Ищем скачанный файл
        for file in os.listdir("."):
            if file.startswith("video."):
                with open(file, "rb") as f:
                    bot.send_video(user_id, f)
                os.remove(file)
                break
    except Exception as e:
        bot.send_message(user_id, f"Ошибка при скачивании:\n{e}\nПопробуй другое качество или ссылку.")

# ================== WEBHOOK ==================

@app.route("/", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200

def setup_webhook():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if url:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=url)
        print(f"Webhook set to {url}")

if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
