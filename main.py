import os
import sys
import random
import telebot
import subprocess
from dotenv import load_dotenv
import time
from flask import Flask, request, jsonify
import requests as http_requests
import uuid

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

        command = [
            'ffmpeg',
            '-i', input_video_path,
            '-i', audio_path,
            '-map', '0:v:0',           # Pehle input se video
            '-map', '1:a:0',           # Dusre input se audio
            '-c:v', 'copy',            # Video copy (fast)
            '-c:a', 'aac',             # Audio AAC
            '-b:a', '192k',            # Audio bitrate
            '-shortest',               # Video aur audio mein jo chota ho wahan tak katna
            '-map_metadata', '-1',     # Metadata hatana
            '-y',                      # Overwrite file agar exist karti ho
            output_video_path
        ]
        subprocess.run(command, check=True, capture_output=True)

        # 4. Final video wapas bhejna
        bot.edit_message_text("🚀 Nayi video upload ho rahi hai...", chat_id, msg.message_id)
        with open(output_video_path, 'rb') as video_to_send:
            bot.send_video(chat_id, video_to_send, caption="✅ Ye lijiye aapki nayi video!", timeout=120)

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

# ==========================================
# Flask Webhook Server
# ==========================================
app = Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    return "🤖 Telegram Audio Bot is running via Webhook!"

@app.route('/telegram', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        # Webhook ko turant 200 OK return karne ke liye processing alag thread mein
        import threading
        threading.Thread(target=bot.process_new_updates, args=([update],)).start()
        return '', 200
    else:
        return 'error', 403

@app.route('/process-video', methods=['POST'])
def process_video():
    """
    n8n se video URL lo, audio change karo, tmpfiles pe upload karo,
    processed video URL return karo.
    
    Input JSON: { "video_url": "https://..." }
    Output JSON: { "success": true, "output_url": "https://..." }
    """
    data = request.get_json()
    if not data or 'video_url' not in data:
        return jsonify({"success": False, "error": "video_url missing"}), 400

    video_url = data['video_url']
    unique_id = str(uuid.uuid4())[:8]
    input_path = os.path.join(TEMP_DIR, f"input_{unique_id}.mp4")
    output_path = os.path.join(TEMP_DIR, f"output_{unique_id}.mp4")

    try:
        # 1. Video URL se download karo
        r = http_requests.get(video_url, timeout=120, stream=True)
        r.raise_for_status()
        with open(input_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        # 2. Random song uthao (same logic jo pehle se hai)
        songs = [f for f in os.listdir(SONGS_DIR) if f.endswith('.mp3')]
        if not songs:
            return jsonify({"success": False, "error": "Songs folder empty hai"}), 500

        selected_song = random.choice(songs)
        audio_path = os.path.join(SONGS_DIR, selected_song)

        # 3. FFmpeg se audio replace karo (same command jo pehle se hai)
        command = [
            'ffmpeg',
            '-i', input_path,
            '-i', audio_path,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '192k',
            '-shortest',
            '-map_metadata', '-1',
            '-y',
            output_path
        ]
        subprocess.run(command, check=True, capture_output=True)

        # 4. tmpfiles.org pe upload karo
        with open(output_path, 'rb') as f:
            upload = http_requests.post(
                'https://tmpfiles.org/api/v1/upload',
                files={'file': f},
                timeout=120
            )
        upload.raise_for_status()
        upload_data = upload.json()

        if not upload_data.get('data', {}).get('url'):
            return jsonify({"success": False, "error": "tmpfiles upload fail"}), 500

        # URL fix karo (dl/ add karo)
        raw_url = upload_data['data']['url']
        output_url = raw_url.replace('tmpfiles.org/', 'tmpfiles.org/dl/').replace('http://', 'https://')

        return jsonify({
            "success": True,
            "output_url": output_url,
            "song_used": selected_song
        })

    except subprocess.CalledProcessError as e:
        return jsonify({"success": False, "error": f"FFmpeg error: {e.stderr.decode()[:300]}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        # Cleanup
        for path in [input_path, output_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except:
                pass

@app.route('/setup-webhook', methods=['GET'])
def setup_webhook():
    base_url = request.args.get('url', '').strip().rstrip('/')
    if not base_url:
        return jsonify({"success": False, "error": "url parameter missing"}), 400
    
    webhook_url = f"{base_url}/telegram"
    bot.remove_webhook()
    time.sleep(1)
    result = bot.set_webhook(url=webhook_url)
    if result:
        return jsonify({"success": True, "message": "Webhook set successfully", "url": webhook_url})
    else:
        return jsonify({"success": False, "error": "Failed to set webhook"}), 500

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    
    # Auto-set webhook if on Render
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip('/')
    if RENDER_URL:
        webhook_url = f"{RENDER_URL}/telegram"
        result = bot.set_webhook(url=webhook_url)
        if result:
            print(f"✅ Webhook auto-set successfully: {webhook_url}")
        else:
            print("❌ Failed to auto-set webhook!")
    else:
        print("⚠️ RENDER_EXTERNAL_URL not found. Please set webhook manually via /setup-webhook")

    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
