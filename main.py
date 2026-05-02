import os
import sys
import random
import telebot
import ffmpeg
from dotenv import load_dotenv

# Load environment variables (local PC ke liye .env se)
load_dotenv()

# Token check karna
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Error: BOT_TOKEN environment variable set nahi hai.")
    sys.exit(1)

# Authorized user ka Chat ID
ALLOWED_CHAT_ID = os.getenv("ALLOWED_CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN)

# Folders jahan gaane aur temporary videos rahenge
SONGS_DIR = "songs"
TEMP_DIR = "temp_files"

# Folder agar nahi hain toh bana lo
os.makedirs(SONGS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Security Check Function
def is_authorized(chat_id):
    if not ALLOWED_CHAT_ID:
        return True # Agar env var set nahi hai, toh chalne do
    return str(chat_id) == str(ALLOWED_CHAT_ID)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if not is_authorized(message.chat.id):
        bot.reply_to(message, "⛔ Access Denied: Aap is bot ko use nahi kar sakte.")
        return
    bot.reply_to(message, "👋 Hello! Main ek Auto Audio Mixer Bot hu.\nMujhe koi bhi video bhejiye, aur main usme random song mix karke aapko wapas bhej dunga!")

@bot.message_handler(content_types=['video'])
def handle_video(message):
    chat_id = message.chat.id
    message_id = message.message_id
    
    if not is_authorized(chat_id):
        bot.reply_to(message, "⛔ Access Denied: Aapko video process karne ki permission nahi hai.")
        return
        
    input_video_path = ""
    output_video_path = ""
    
    # Video Size Limit Check (Telegram limits to 20MB for normal bots)
    if message.video.file_size > 20 * 1024 * 1024:
        bot.reply_to(message, "❌ Video 20MB se badi hai, Telegram bot limit isko support nahi karti.")
        return
        
    try:
        msg = bot.reply_to(message, "⏳ Video download ho rahi hai...")

        # 1. Telegram se video download karna
        file_info = bot.get_file(message.video.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        input_video_path = os.path.join(TEMP_DIR, f"input_{chat_id}_{message_id}.mp4")
        with open(input_video_path, 'wb') as new_file:
            new_file.write(downloaded_file)

        # 2. Songs folder se random song uthana
        songs = [f for f in os.listdir(SONGS_DIR) if f.endswith('.mp3')]
        if not songs:
            bot.edit_message_text("❌ Error: 'songs' folder mein koi MP3 file nahi mili! Pehle gaane upload karein.", chat_id, msg.message_id)
            return

        selected_song = random.choice(songs)
        audio_path = os.path.join(SONGS_DIR, selected_song)

        # 3. FFmpeg se processing
        bot.edit_message_text(f"🎧 Music mix ho raha hai...\n🎵 Song: {selected_song}", chat_id, msg.message_id)
        output_video_path = os.path.join(TEMP_DIR, f"output_{chat_id}_{message_id}.mp4")

        video_stream = ffmpeg.input(input_video_path)['v']
        audio_stream = ffmpeg.input(audio_path)['a']

        (
            ffmpeg
            .output(
                video_stream,
                audio_stream,
                output_video_path,
                vcodec='copy',          # Video stream copy (fast)
                acodec='aac',           # Audio to AAC (Instagram/TG compatible)
                **{'b:a': '192k'},      # Correct FFmpeg parameter for audio bitrate
                shortest=None,          # Jo chota ho wahan tak
                map_metadata=-1
            )
            .overwrite_output()
            .run(quiet=True)
        )

        # 4. Final video wapas bhejna
        bot.edit_message_text("🚀 Nayi video upload ho rahi hai...", chat_id, msg.message_id)
        with open(output_video_path, 'rb') as video_to_send:
            bot.send_video(chat_id, video_to_send, caption="✅ Ye lijiye aapki nayi video!")

        # Processing wala message delete kar do (clean UI ke liye)
        bot.delete_message(chat_id, msg.message_id)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Kuch gadbad ho gayi:\n{str(e)}")
    
    finally:
        # 5. Zaroori Kadam: Server se files DELETE karna taki space bachi rahe
        try:
            if input_video_path and os.path.exists(input_video_path):
                os.remove(input_video_path)
            if output_video_path and os.path.exists(output_video_path):
                os.remove(output_video_path)
        except Exception as e:
            print(f"Cleanup error: {e}")

if __name__ == "__main__":
    print("🤖 Bot start ho gaya hai. Waiting for messages...")
    bot.infinity_polling()
