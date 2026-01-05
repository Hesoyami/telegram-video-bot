import os
import threading
import telebot
import yt_dlp
from flask import Flask, request

TOKEN = "TOKEN"
WEBHOOK_URL = "WEBHOOK_URL"
PORT = int(os.environ.get("PORT", 8080))

bot = telebot.TeleBot(TOKEN, threaded=True)
app = Flask(__name__)

user_links = {}

# -------------------- utils --------------------

def safe_mb(size):
    try:
        return f"{int(size) / 1024 / 1024:.1f} MB"
    except:
        return "?"

def is_youtube_block(e: Exception) -> bool:
    msg = str(e).lower()
    return "sign in to confirm" in msg or "cookies" in msg

def download_video(url, quality):
    filename = "video.%(ext)s"

    ydl_opts = {
        "outtmpl": filename,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 30,
        "http_chunk_size": 10 * 1024 * 1024,
        "noplaylist": True,
        "concurrent_fragment_downloads": 4,
        "format_sort": ["res", "codec:h264", "br", "size"],
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
                "skip": ["dash", "hls"]
            }
        }
    }

    if quality == "best":
        ydl_opts["format"] = "best"
    else:
        ydl_opts["format"] = f"bestvideo[height<={quality}]+bestaudio/best"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)

    return filename

def send_file(chat_id, path):
    size_mb = os.path.getsize(path) / 1024 / 1024

    try:
        if size_mb <= 50:
            with open(path, "rb") as f:
                bot.send_video(chat_id, f)
        else:
            with open(path, "rb") as f:
                bot.send_document(chat_id, f)
    except:
        with open(path, "rb") as f:
            bot.send_document(chat_id, f)

# -------------------- bot handlers --------------------

@bot.message_handler(commands=["start"])
def start(msg):
    bot.send_message(
        msg.chat.id,
        "Пришли ссылку на видео (YouTube, TikTok, Pinterest, Instagram).\nЯ предложу качество и скачаю файл."
    )

@bot.message_handler(func=lambda m: m.text and m.text.startswith("http"))
def handle_link(msg):
    user_links[msg.chat.id] = msg.text

    kb = telebot.types.InlineKeyboardMarkup()
    for q in ["480", "720", "1080"]:
        kb.add(telebot.types.InlineKeyboardButton(f"{q}p", callback_data=q))
    kb.add(telebot.types.InlineKeyboardButton("Лучшее", callback_data="best"))

    bot.send_message(msg.chat.id, "Выбери качество:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def handle_quality(call):
    url = user_links.get(call.message.chat.id)
    quality = call.data

    if not url:
        bot.answer_callback_query(call.id, "Ссылка не найдена")
        return

    bot.answer_callback_query(call.id, "Скачиваю…")

    def worker():
        try:
            path = download_video(url, quality)
            send_file(call.message.chat.id, path)
            os.remove(path)
        except Exception as e:
            if is_youtube_block(e):
                bot.send_message(
                    call.message.chat.id,
                    "YouTube запросил подтверждение, что вы не бот.\n"
                    "❗ Это ограничение YouTube.\n"
                    "Попробуй другое видео или платформу."
                )
            else:
                bot.send_message(
                    call.message.chat.id,
                    f"Ошибка загрузки:\n{str(e)}"
                )

    threading.Thread(target=worker).start()

# -------------------- webhook --------------------

@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
    bot.process_new_updates([update])
    return "OK", 200

if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    app.run(host="0.0.0.0", port=PORT)

