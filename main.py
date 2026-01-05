import os
import telebot
import yt_dlp
from flask import Flask, request
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ================= CONFIG =================

BOT_TOKEN = "8317431261:AAEr8LWl_c0Gr6PExEhMTJX3Qsv9F_mCjWo"
WEBHOOK_URL = "https://telegram-video-bot-bbmt.onrender.com"
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50 MB

if ":" not in BOT_TOKEN:
    raise RuntimeError("Некорректный токен бота")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
user_states = {}

# ================= HELPERS =================

def mb(size):
    if not size:
        return "≈ ? МБ"
    return f"{size / 1024 / 1024:.1f} МБ"

def yt_opts_base():
    return {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "force_ipv4": True,
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        "merge_output_format": "mp4",
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {
            "tiktok": {
                "api_hostname": "api16-normal-c-useast1a.tiktokv.com",
                "app_version": "34.1.2",
                "manifest_app_version": "34.1.2",
            },
            "pinterest": {
                "use_mobile_api": True,
            },
        },
    }

def get_formats(url):
    opts = yt_opts_base()
    opts["skip_download"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return info.get("formats", [])

def send_video_with_fallback(chat_id, filepath):
    size = os.path.getsize(filepath)

    with open(filepath, "rb") as f:
        if size > MAX_VIDEO_SIZE:
            bot.send_document(chat_id, f, caption="Видео отправлено файлом")
            return

        try:
            bot.send_video(chat_id, f)
        except Exception:
            f.seek(0)
            bot.send_document(chat_id, f, caption="Видео отправлено файлом")

# ================= BOT =================

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "Пришли ссылку на видео (TikTok, Pinterest, YouTube, Facebook, Instagram)."
    )

@bot.message_handler(func=lambda m: m.text and m.text.startswith("http"))
def handle_link(message):
    url = message.text.strip()
    user_id = message.chat.id

    try:
        formats = get_formats(url)
    except Exception as e:
        bot.reply_to(message, f"Не удалось получить видео:\n{e}")
        return

    user_states[user_id] = {"url": url}
    keyboard = InlineKeyboardMarkup()
    qualities = {}

    for f in formats:
        if (
            f.get("ext") == "mp4"
            and f.get("height")
            and f.get("vcodec") != "none"
        ):
            h = f["height"]
            size = f.get("filesize") or f.get("filesize_approx")
            qualities[h] = (f["format_id"], size)

    for h in sorted(qualities):
        fmt, size = qualities[h]
        keyboard.add(
            InlineKeyboardButton(
                f"{h}p ({mb(size)})",
                callback_data=f"q:{fmt}"
            )
        )

    keyboard.add(
        InlineKeyboardButton("Лучшее доступное", callback_data="q:best")
    )

    bot.reply_to(message, "Выбери качество:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda c: c.data.startswith("q:"))
def download(call):
    user_id = call.message.chat.id
    state = user_states.get(user_id)

    if not state:
        bot.answer_callback_query(call.id, "Ссылка устарела")
        return

    bot.answer_callback_query(call.id, "Скачиваю...")
    url = state["url"]
    q = call.data.split(":", 1)[1]

    opts = yt_opts_base()
    opts.update({
        "outtmpl": "video.%(ext)s",
        "noplaylist": True,
        "format": (
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]"
            if q == "best" else q
        ),
        "format_sort": [
            "res",
            "codec:h264",
            "br",
            "size",
        ],
    })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)

        filename = next(
            (f for f in os.listdir(".") if f.startswith("video.")),
            None
        )

        if not filename or os.path.getsize(filename) < 1024:
            if filename:
                os.remove(filename)
            bot.send_message(user_id, "Не удалось скачать видео.")
            return

        send_video_with_fallback(user_id, filename)
        os.remove(filename)

    except Exception as e:
        bot.send_message(user_id, f"Ошибка загрузки:\n{e}")

# ================= WEBHOOK =================

@app.route("/", methods=["POST"])
def webhook():
    update = telebot.types.Update.de_json(
        request.get_data().decode("utf-8")
    )
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "OK"

def setup_webhook():
    bot.remove_webhook()
    bot.set_webhook(url=WEBHOOK_URL)

# ================= RUN =================

if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
