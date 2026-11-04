import asyncio
import json
import logging
import os
import re
import urllib.request
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

# Token Telegram diambil dari Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# Membaca 4 API Keys dari Environment Variables Railway
raw_keys = [
    os.getenv("GEMINI_KEY_1", ""),
    os.getenv("GEMINI_KEY_2", ""),
    os.getenv("GEMINI_KEY_3", ""),
    os.getenv("GEMINI_KEY_4", "")
]
API_KEYS = [k for k in raw_keys if k]
current_key_index = 0

device_status = {
    "lampu": "OFF",
    "pompa": "OFF"
}

def ask_gemini_official(prompt_text: str) -> str:
    global current_key_index
    total_keys = len(API_KEYS)
    if total_keys == 0:
        return None
        
    for _ in range(total_keys):
        active_key = API_KEYS[current_key_index]
        try:
            # Menggunakan REST API langsung agar kompatibel 100% dengan Token Cloud/AI Studio
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={active_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "systemInstruction": {
                    "parts": [{"text": "Jawab dengan ramah, singkat, dan padat (maksimal 2 kalimat) untuk sistem Smart Home."}]
                }
            }
            
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"⚠️ Key index {current_key_index} error: {e}")
            # Pindah ke key berikutnya jika ada error / kuota habis
            current_key_index = (current_key_index + 1) % total_keys

    return None

telegram_app = (
    Application.builder()
    .token(TELEGRAM_TOKEN)
    .connect_timeout(60.0)
    .read_timeout(60.0)
    .write_timeout(60.0)
    .pool_timeout(60.0)
    .build()
)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"Halo {user_name}! 🤖\nServer Smart Home & AI Aktif!\n\n"
        "Perintah Sakelar:\n"
        "/status - Cek status sakelar\n"
        "/lampu_on - Nyalakan Lampu\n"
        "/lampu_off - Matikan Lampu"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🟢 Status System: ONLINE\n"
        f"💡 Status Lampu: {device_status['lampu']}\n"
        f"🚰 Status Pompa: {device_status['pompa']}"
    )
    await update.message.reply_text(msg)

async def lampu_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_status["lampu"] = "ON"
    await update.message.reply_text("💡 Lampu berhasil dinyalakan! (Relay Signal: HIGH)")

async def lampu_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_status["lampu"] = "OFF"
    await update.message.reply_text("🔌 Lampu berhasil dimatikan! (Relay Signal: LOW)")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    text_lower = user_text.lower().strip()
    print(f"📩 Pesan masuk: {user_text}")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # Pengecekan Presisi: Perintah Sakelar vs Pertanyaan Umum
    is_on = bool(re.search(r'\b(nyala|nyalakan|on|hidupkan)\b', text_lower))
    is_off = bool(re.search(r'\b(mati|matikan|off|padamkan)\b', text_lower))
    has_device = bool(re.search(r'\b(lampu|led|sakelar|relay)\b', text_lower))
    is_question = bool(re.search(r'\b(kenapa|apa|mengapa|bagaimana|jelaskan|fungsi)\b', text_lower))

    # 1. PERINTAH SAKELAR (Hanya jalan jika BUKAN pertanyaan dan ada kata perintah + nama alat)
    if not is_question and (is_on and has_device):
        device_status["lampu"] = "ON"
        await update.message.reply_text("💡 [Lokal] Lampu berhasil dinyalakan! (Relay: HIGH)")
        return
    elif not is_question and (is_off and has_device):
        device_status["lampu"] = "OFF"
        await update.message.reply_text("🔌 [Lokal] Lampu berhasil dimatikan! (Relay: LOW)")
        return
    elif text_lower in ["status", "cek status", "kondisi"]:
        msg = (
            "🟢 Status System: ONLINE\n"
            f"💡 Status Lampu: {device_status['lampu']}\n"
            f"🚰 Status Pompa: {device_status['pompa']}"
        )
        await update.message.reply_text(msg)
        return

    # 2. PERTANYAAN BEBAS -> Kirim ke Gemini AI
    ai_reply = await asyncio.to_thread(ask_gemini_official, user_text)
    
    if ai_reply:
        await update.message.reply_text(f"🤖 {ai_reply}")
    else:
        await update.message.reply_text("🤖 Maaf, sistem AI sedang tidak dapat merespons. Silakan coba lagi.")

telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(CommandHandler("status", status_command))
telegram_app.add_handler(CommandHandler("lampu_on", lampu_on_command))
telegram_app.add_handler(CommandHandler("lampu_off", lampu_off_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("⏳ Menghubungkan ke Telegram Bot...")
    try:
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(drop_pending_updates=True)
        print("🤖 Server Smart Home Berhasil Aktif!")
        yield
    except Exception as e:
        print(f"❌ Error Bot: {e}")
        yield
    finally:
        try:
            if telegram_app.updater and telegram_app.updater.running:
                await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()
        except Exception:
            pass

app = FastAPI(title="Smart Home Server", lifespan=lifespan)

@app.get("/")
def home():
    return {"status": "online", "devices": device_status}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
