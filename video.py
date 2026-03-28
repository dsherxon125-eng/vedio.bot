import os
import glob
import logging
import yt_dlp
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# =============================================
# TOKENLAR — o'zingiznikini yozing
# =============================================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"                    # 👈 Shu yerga Telegram Bot Tokeningizni qo'ying
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY_HERE"          # 👈 Shu yerga OpenAI API keyingizni qo'ying

# =============================================
# SOZLAMALAR
# =============================================
DOWNLOAD_PATH = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_PATH, exist_ok=True)

# OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Suhbat tarixi (har user uchun)
conversation_history = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

user_url_cache = {}


# =============================================
# OPENAI — AI javob olish
# =============================================
def get_ai_response(chat_id: int, user_message: str) -> str:
    """OpenAI GPT orqali javob olish (suhbat tarixi bilan)"""
    if chat_id not in conversation_history:
        conversation_history[chat_id] = [
            {
                "role": "system",
                "content": (
                    "Siz aqlli va do'stona Telegram botisiz. "
                    "Foydalanuvchilarga YouTube, Instagram va Facebook videolarini "
                    "yuklab olishda yordam berasiz. "
                    "O'zbek tilida javob bering. "
                    "Qisqa, aniq va foydali javoblar bering."
                )
            }
        ]

    conversation_history[chat_id].append({"role": "user", "content": user_message})

    # Tarix 20 xabardan oshmasin
    if len(conversation_history[chat_id]) > 20:
        system_msg = conversation_history[chat_id][0]
        conversation_history[chat_id] = [system_msg] + conversation_history[chat_id][-19:]

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=conversation_history[chat_id],
            max_tokens=500,
            temperature=0.7,
        )
        assistant_reply = response.choices[0].message.content
        conversation_history[chat_id].append({"role": "assistant", "content": assistant_reply})
        return assistant_reply
    except Exception as e:
        logger.error(f"OpenAI xatosi: {e}")
        return "❌ AI javob berishda xato yuz berdi. Keyinroq urinib ko'ring."


# =============================================
# FFMPEG yo'lini topish
# =============================================
def get_ffmpeg_location():
    local = os.path.join(os.path.dirname(__file__), "ffmpeg.exe")
    if os.path.exists(local):
        return local
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    # Linux/Mac uchun standart yo'llar
    for path in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]:
        if os.path.exists(path):
            return path
    return None


# =============================================
# URL tekshirish
# =============================================
def is_supported_url(url: str) -> bool:
    supported = ["youtube.com", "youtu.be", "instagram.com", "facebook.com", "fb.watch"]
    return any(domain in url.lower() for domain in supported)


# =============================================
# VIDEO yuklash
# =============================================
def download_video(url: str, chat_id: int) -> str | None:
    output_template = os.path.join(DOWNLOAD_PATH, f"{chat_id}_video_%(title)s.%(ext)s")
    ydl_opts = {
        "outtmpl": output_template,
        "format": "best[filesize<50M]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "windowsfilenames": True,
        "merge_output_format": "mp4",
    }
    ffmpeg = get_ffmpeg_location()
    if ffmpeg:
        ydl_opts["ffmpeg_location"] = ffmpeg

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info)
            if not os.path.exists(filepath):
                base = os.path.splitext(filepath)[0]
                for ext in [".mp4", ".mkv", ".webm", ".avi"]:
                    if os.path.exists(base + ext):
                        return base + ext
                pattern = os.path.join(DOWNLOAD_PATH, f"{chat_id}_video_*")
                files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
                if files:
                    return files[0]
            return filepath
    except Exception as e:
        logger.error(f"Video yuklab olishda xato: {e}")
        return None


# =============================================
# AUDIO (MP3) yuklash
# =============================================
def download_audio(url: str, chat_id: int) -> str | None:
    for f in glob.glob(os.path.join(DOWNLOAD_PATH, f"{chat_id}_audio_*")):
        try:
            os.remove(f)
        except Exception:
            pass

    ffmpeg = get_ffmpeg_location()
    if not ffmpeg:
        logger.error("ffmpeg topilmadi!")
        return None

    output_template = os.path.join(DOWNLOAD_PATH, f"{chat_id}_audio_%(title)s.%(ext)s")
    ydl_opts = {
        "outtmpl": output_template,
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "windowsfilenames": True,
        "ffmpeg_location": ffmpeg,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        mp3_files = sorted(
            glob.glob(os.path.join(DOWNLOAD_PATH, f"{chat_id}_audio_*.mp3")),
            key=os.path.getmtime, reverse=True
        )
        if mp3_files:
            return mp3_files[0]

        any_files = sorted(
            glob.glob(os.path.join(DOWNLOAD_PATH, f"{chat_id}_audio_*")),
            key=os.path.getmtime, reverse=True
        )
        return any_files[0] if any_files else None

    except Exception as e:
        logger.error(f"Audio yuklab olishda xato: {e}")
        return None


# =============================================
# /start komandasi
# =============================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    conversation_history.pop(chat_id, None)

    await update.message.reply_text(
        "👋 Salom! Men aqlli video yuklovchi botman.\n\n"
        "📥 Quyidagi platformalardan yuklay olaman:\n"
        "  • 🎬 YouTube\n"
        "  • 📸 Instagram\n"
        "  • 📘 Facebook\n\n"
        "💬 Bundan tashqari, har qanday savollaringizga javob bera olaman!\n\n"
        "🔗 Havola yuboring → 🎬 Video yoki 🎵 Audio tanlang\n"
        "❓ Savol yozing → 🤖 AI sizga javob beradi!"
    )


# =============================================
# /help komandasi
# =============================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Qo'llanma:\n\n"
        "🎬 Video/Audio yuklash:\n"
        "1️⃣ YouTube / Instagram / Facebook havolasini yuboring\n"
        "2️⃣ 🎬 Video yoki 🎵 Audio tugmasini bosing\n"
        "3️⃣ Fayl yuklanib sizga yuboriladi\n\n"
        "🤖 AI suhbat:\n"
        "• Har qanday savol yozing, GPT javob beradi\n"
        "• /clear — suhbat tarixini tozalash\n\n"
        "⚠️ Telegram 50MB dan katta fayllarni qabul qilmaydi."
    )


# =============================================
# /clear komandasi
# =============================================
async def clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    conversation_history.pop(chat_id, None)
    await update.message.reply_text("🗑️ Suhbat tarixi tozalandi. Yangi suhbat boshlandi!")


# =============================================
# Xabar kelganda
# =============================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    if text.startswith("http://") or text.startswith("https://"):
        if not is_supported_url(text):
            await update.message.reply_text(
                "⚠️ Bu platforma qo'llab-quvvatlanmaydi.\n"
                "Faqat YouTube, Instagram, Facebook havolalarini yuboring.\n\n"
                "💬 Yoki savol yozsangiz, AI javob beradi!"
            )
            return

        user_url_cache[chat_id] = text

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎬 Video", callback_data="dl_video"),
                InlineKeyboardButton("🎵 Audio (MP3)", callback_data="dl_audio"),
            ]
        ])

        await update.message.reply_text(
            "✅ Havola qabul qilindi!\nNimani yuklashni xohlaysiz?",
            reply_markup=keyboard
        )
        return

    # AI suhbat
    thinking_msg = await update.message.reply_text("🤔 O'ylanmoqda...")
    ai_reply = get_ai_response(chat_id, text)
    await thinking_msg.edit_text(f"🤖 {ai_reply}")


# =============================================
# Tugma bosilganda
# =============================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    url = user_url_cache.get(chat_id)

    if not url:
        await query.edit_message_text("❌ Havola topilmadi. Iltimos, qaytadan yuboring.")
        return

    action = query.data

    if action == "dl_video":
        await query.edit_message_text("⏳ Video yuklanmoqda, kuting...")
        filepath = download_video(url, chat_id)

    elif action == "dl_audio":
        if not get_ffmpeg_location():
            await query.edit_message_text(
                "❌ ffmpeg topilmadi!\n\n"
                "Audio yuklash uchun ffmpeg kerak:\n"
                "1. https://www.gyan.dev/ffmpeg/builds/ saytidan yuklab oling\n"
                "2. ffmpeg.exe faylini bot.py bilan bir papkaga qo'ying\n"
                "3. Qaytadan urinib ko'ring"
            )
            return
        await query.edit_message_text("⏳ Audio yuklanmoqda, kuting...")
        filepath = download_audio(url, chat_id)

    else:
        return

    if not filepath or not os.path.exists(filepath):
        await query.edit_message_text(
            "❌ Yuklab olishda xato yuz berdi.\n\n"
            "Sabab bo'lishi mumkin:\n"
            "• Havola noto'g'ri yoki private\n"
            "• Internet muammosi\n"
            "• ffmpeg o'rnatilmagan (audio uchun)"
        )
        return

    file_size = os.path.getsize(filepath)

    if file_size > 50 * 1024 * 1024:
        os.remove(filepath)
        await query.edit_message_text(
            "⚠️ Fayl hajmi 50MB dan katta.\nTelegram bu o'lchamdagi fayllarni qabul qilmaydi."
        )
        return

    await query.edit_message_text("📤 Yuborilmoqda...")

    try:
        with open(filepath, "rb") as f:
            if action == "dl_video":
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption="✅ Video muvaffaqiyatli yuklandi! 🎬",
                    supports_streaming=True
                )
            else:
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    caption="✅ Audio muvaffaqiyatli yuklandi! 🎵"
                )
        await query.delete_message()

    except Exception as e:
        logger.error(f"Yuborishda xato: {e}")
        await query.edit_message_text("❌ Faylni yuborishda xato yuz berdi.")

    finally:
        if os.path.exists(filepath):
            os.remove(filepath)
        user_url_cache.pop(chat_id, None)


# =============================================
# Botni ishga tushirish
# =============================================
def main():
    print("🤖 Bot ishga tushmoqda...")
    print(f"📁 Downloads papkasi: {DOWNLOAD_PATH}")

    ffmpeg = get_ffmpeg_location()
    if ffmpeg:
        print(f"✅ ffmpeg topildi: {ffmpeg}")
    else:
        print("⚠️ ffmpeg topilmadi! Audio yuklash ishlamaydi.")

    if OPENAI_API_KEY and OPENAI_API_KEY != "YOUR_OPENAI_API_KEY_HERE":
        print("✅ OpenAI API key sozlangan — AI suhbat faol!")
    else:
        print("⚠️ OpenAI API key sozlanmagan!")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("✅ Bot tayyor! Xabarlar kutilmoqda...")
    app.run_polling()


if __name__ == "__main__":
    main()