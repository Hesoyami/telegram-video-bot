import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import yt_dlp
import os
import threading

BOT_TOKEN = "8317431261:AAEr8LWl_c0Gr6PExEhMTJX3Qsv9F_mCjWo"
bot = telebot.TeleBot(BOT_TOKEN)

TELEGRAM_VIDEO_LIMIT = 50 * 1024 * 1024
TELEGRAM_FILE_LIMIT = 2 * 1024 * 1024 * 1024

# Список стратегий обхода
PROXIES = [
    None,  # без прокси
    # "socks5://127.0.0.1:9050",  # Tor (если есть)
    # "http://login:pass@ip:port",
    # "socks5://login:pass@ip:port",
]

user_states = {}

# ---------- UTILS ----------

def mb(size):
    return f"{size / 1024 / 1024:.1f} МБ"

def try_extract_info(url):
    last_error = None

    for proxy in PROXIES:
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 30,
                "retries": 3,
            }
            if proxy:
                opts["proxy"] = proxy

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info, proxy

        except Exception as e:
            last_error = e

    raise last_error

def extract_formats(info):
    videos = {}
    audio = None

    for f in info.get("formats", []):
        if f.get("vcodec") == "none" and f.get("acodec") != "none":
            if not audio or (f.get("filesize", 0) > audio.get("filesize", 0)):
                audio = f

        if (
            f.get("ext") == "mp4"
            and f.get("height")
            and f.get("acodec") != "none"
            and f.get("vcodec") != "none"
        ):
            size = f.get("filesize") or f.get("filesize_approx")
            if size:
                videos[f["height"]] = {
                    "format_id": f["format_id"],
                    "size": size,
                }

    return videos, audio

def pick_fallback(videos, max_h):
    for h in sorted(videos.keys(), reverse=True):
        if h <= max_h:
            return videos[h]
    return None

# ---------- HANDLERS ----------

@bot.message_handler(commands=["start"])
def start(msg):
    bot.reply_to(
        msg,
        "Пришли ссылку.\n"
        "Бот автоматически обходит блокировки и подбирает рабочее подключение."
    )

@bot.message_handler(func=lambda m: True)
def handle_link(msg):
    url = msg.text.strip()
    uid = msg.chat.id

    try:
        info, proxy_used = try_extract_info(url)
        videos, audio = extract_formats(info)
    except Exception:
        bot.reply_to(
            msg,
            "Не удалось получить видео.\n"
            "Сайт недоступен даже через обход блокировок."
        )
        return

    if not videos and not audio:
        bot.reply_to(msg, "Форматы не найдены.")
        return

    user_states[uid] = {
        "url": url,
        "info": info,
        "videos": videos,
        "audio": audio,
        "proxy": proxy_used,
    }

    kb = InlineKeyboardMarkup()

    for h in sorted(videos.keys()):
        kb.add(
            InlineKeyboardButton(
                f"{h}p ({mb(videos[h]['size'])})",
                callback_data=f"v_{h}"
            )
        )

    if audio:
        kb.add(
            InlineKeyboardButton(
                f"🎵 Аудио ({mb(audio.get('filesize', 0))})",
                callback_data="audio"
            )
        )

    bot.reply_to(msg, "Выбери формат:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def handle_choice(call):
    uid = call.message.chat.id
    state = user_states.get(uid)

    if not state:
        bot.answer_callback_query(call.id, "Ссылка устарела")
        return

    if call.data == "audio":
        fmt = state["audio"]
        send_type = "audio"
    else:
        h = int(call.data.split("_")[1])
        fmt = pick_fallback(state["videos"], h)
        send_type = "video"

    bot.answer_callback_query(call.id, "Скачиваю...")

    threading.Thread(
        target=download_and_send,
        args=(uid, state["url"], fmt, send_type, state["proxy"]),
        daemon=True
    ).start()

def download_and_send(uid, url, fmt, send_type, proxy):
    opts = {
        "format": fmt["format_id"],
        "outtmpl": "%(title)s.%(ext)s",
        "quiet": True,
        "socket_timeout": 30,
        "retries": 3,
    }
    if proxy:
        opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        size = os.path.getsize(filename)

        with open(filename, "rb") as f:
            if send_type == "audio":
                bot.send_audio(uid, f)
            else:
                if size <= TELEGRAM_VIDEO_LIMIT:
                    bot.send_video(uid, f)
                else:
                    bot.send_document(uid, f)

        os.remove(filename)

    except Exception:
        bot.send_message(
            uid,
            "Ошибка загрузки даже через обход.\n"
            "Попробуй позже или другую ссылку."
        )

bot.polling(none_stop=True)
