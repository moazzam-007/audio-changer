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
TEMP_DIR  = "temp_files"
FONTS_DIR = "fonts"

# Folder agar nahi hain toh bana lo
os.makedirs(SONGS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Text overlay config
OVERLAY_TEXT = os.getenv("OVERLAY_TEXT", "Subscribe and comment for link")

# Security Check Function
def is_authorized(chat_id):
    if not ALLOWED_CHAT_ID:
        return True # Agar env var set nahi hai, toh chalne do
    return str(chat_id) == str(ALLOWED_CHAT_ID)


# ==========================================
# Text Overlay Helper — Animated Scroll
# ==========================================
def add_text_overlay(input_path, output_path, text, video_duration):
    """
    Video pe animated scrolling text overlay add karta hai.
    Speed video duration se calculate hoti hai — hamesha 2 loops.
    OS-aware font path: Windows aur Linux (Render) dono support.
    """
    # --- Font path: OS ke hisaab se ---
    if os.name == 'nt':  # Windows (local dev)
        font_ff = "C\\\\:/fftemp/georgiab.ttf"
        text_file = r"C:\fftemp\overlay_text.txt"
        text_file_ff = "C\\\\:/fftemp/overlay_text.txt"
    else:  # Linux — Render.com
        base = os.path.abspath(FONTS_DIR)
        font_ff = os.path.join(base, "georgiab.ttf")
        text_file = "/tmp/overlay_text.txt"
        text_file_ff = text_file

    # --- Text file banao (escaping se bachne ke liye) ---
    try:
        if os.name == 'nt':
            os.makedirs(r"C:\fftemp", exist_ok=True)
        with open(text_file, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        print(f"[overlay] Text file error: {e}")
        return False

    # --- Speed: video duration se (2 loops hamesha) ---
    # formula: (video_width + approx_text_width) * loops / duration
    n_loops  = 2
    duration = max(float(video_duration), 1)
    speed    = int((720 + 600) * n_loops / duration)

    # --- drawtext filter ---
    if os.name == 'nt':
        x_formula = f"w-mod(t*{speed}\\\\,w+text_w)"
    else:
        x_formula = f"w-mod(t*{speed}\\,w+text_w)"

    drawtext = (
        f"drawtext="
        f"fontfile={font_ff}:"
        f"textfile={text_file_ff}:"
        f"fontsize=42:"
        f"fontcolor=white:"
        f"x={x_formula}:"
        f"y=80:"
        f"box=1:"
        f"boxcolor=black@0.70:"
        f"boxborderw=12"
    )

    command = [
        "ffmpeg",
        "-i", input_path,
        "-vf", drawtext,
        "-c:v", "libx264",
        "-c:a", "copy",
        "-preset", "ultrafast",
        "-crf", "23",
        "-y",
        output_path
    ]

    result = subprocess.run(command, capture_output=True)

    # Cleanup text file
    try:
        if os.path.exists(text_file):
            os.remove(text_file)
    except Exception:
        pass

    if result.returncode != 0:
        print(f"[overlay] ffmpeg error: {result.stderr[-300:]}")
        return False
    return True

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

        # 3. FFmpeg se audio processing
        bot.edit_message_text(f"🎧 Music mix ho raha hai...\n🎵 Song: {selected_song}", chat_id, msg.message_id)
        audio_output_path  = os.path.join(TEMP_DIR, f"audio_{chat_id}_{message_id}.mp4")
        output_video_path  = os.path.join(TEMP_DIR, f"output_{chat_id}_{message_id}.mp4")

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
            audio_output_path
        ]
        subprocess.run(command, check=True, capture_output=True)

        # 4. Text overlay add karna (animated scroll)
        bot.edit_message_text("✍️ Text overlay add ho raha hai...", chat_id, msg.message_id)
        video_duration = message.video.duration  # Telegram se milta hai
        overlay_ok = add_text_overlay(audio_output_path, output_video_path, OVERLAY_TEXT, video_duration)
        if not overlay_ok:
            # Overlay fail ho toh bhi audio wali video bhej do
            output_video_path = audio_output_path

        # 5. Final video wapas bhejna
        bot.edit_message_text("🚀 Nayi video upload ho rahi hai...", chat_id, msg.message_id)
        with open(output_video_path, 'rb') as video_to_send:
            bot.send_video(chat_id, video_to_send, caption="✅ Ye lijiye aapki nayi video!", timeout=120)

        # Processing wala message delete kar do (clean UI ke liye)
        bot.delete_message(chat_id, msg.message_id)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Kuch gadbad ho gayi:\n{str(e)}")
    
    finally:
        # 6. Zaroori Kadam: Server se files DELETE karna taki space bachi rahe
        for p in [input_video_path, locals().get('audio_output_path', ''), output_video_path]:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
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

        # 3. FFmpeg se audio replace karo
        audio_out_path = output_path + "_audio.mp4"
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
            audio_out_path
        ]
        subprocess.run(command, check=True, capture_output=True)

        # 4. Text overlay add karo (animated scroll)
        # n8n endpoint mein duration URL se nahi milta, ffprobe se lete hain
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', audio_out_path],
                capture_output=True, text=True
            )
            vid_duration = float(probe.stdout.strip())
        except Exception:
            vid_duration = 30  # fallback

        overlay_ok = add_text_overlay(audio_out_path, output_path, OVERLAY_TEXT, vid_duration)
        if not overlay_ok:
            # Overlay fail ho toh audio wali file hi use karo
            import shutil
            shutil.copy2(audio_out_path, output_path)

        # 4. uguu.se pe upload karo (catbox/tmpfiles se zyada reliable API hai)
        with open(output_path, 'rb') as f:
            upload = http_requests.post(
                'https://uguu.se/upload',
                files={'files[]': ('video.mp4', f, 'video/mp4')},
                timeout=120
            )
        upload.raise_for_status()
        
        upload_data = upload.json()
        if not upload_data.get('success'):
            return jsonify({"success": False, "error": f"Uguu upload fail"}), 500
            
        output_url = upload_data['files'][0]['url']

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
