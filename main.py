import os
import json
import logging
from threading import Thread
from flask import Flask
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# --- CONFIGURATION ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
WEBAPP_URL = "https://usage217-tech.github.io/Mytho-rp/" 
MODEL = "x-ai/grok-4.1-fast"

# --- VIDEO ASSET MAPPING ---
CHARACTER_VIDEOS = {
    "Lilith": "https://usage217-tech.github.io/Charecter-mp4/Lilith.mp4",
    "Hellien": "https://usage217-tech.github.io/Charecter-mp4/Hellien.mp4",
    "Mrs. Grace": "https://usage217-tech.github.io/Charecter-mp4/Grace.mp4",
    "Maya": "https://usage217-tech.github.io/Charecter-mp4/Maya.mp4",
    "Nika": "https://usage217-tech.github.io/Charecter-mp4/Nika.mp4",
    "Robert": "https://usage217-tech.github.io/Charecter-mp4/Robert.mp4",
    "John": "https://usage217-tech.github.io/Charecter-mp4/John.mp4",
    "Mike": "https://usage217-tech.github.io/Charecter-mp4/Mike.mp4"
}

# Initialize Clients
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
app = Flask(__name__)
user_sessions = {}

# --- KEYBOARDS ---
def get_start_keyboard():
    keyboard = [
        [KeyboardButton("✨ Manifest Reality", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("⚜️ Help & Lore")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_utility_keyboard():
    keyboard = [
        [KeyboardButton("🌙 Ongoing Character"), KeyboardButton("🌑 End Session")],
        [KeyboardButton("✨ Manifest New"), KeyboardButton("⚜️ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- FLASK SERVER ---
@app.route('/')
def home(): return "Mythos Engine is Awake."

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the welcome message with buttons."""
    await update.message.reply_text(
        "✧ 🌙 **Mythos Engine** 🌑 ✧\n\n"
        "✨ Welcome, Traveler. The boundaries of reality are thinning. "
        "Tap the button below to design your persona and begin your journey. ⚜️",
        reply_markup=get_start_keyboard(),
        parse_mode="Markdown"
    )

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives data from the Web App and starts the RP."""
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id
        
        char_name = data.get('ai_name', 'Unknown')
        char_desc = data.get('ai_desc', 'A mysterious figure')
        char_image = data.get('ai_image') 
        user_name = data.get('user_name', 'Traveler')
        user_gender = data.get('user_gender', 'not specified') 
        scenario = data.get('scenario', 'A meeting in the dark.')

        char_video = CHARACTER_VIDEOS.get(char_name)

        system_prompt = (
    f"You are {char_name} in an explicit adult roleplay.\n"
    f"Personality: {char_desc}.\n"
    f"User: {user_name} (Gender: {user_gender}).\n\n"
    "STRICT RULES — follow ALL of these every reply:\n"
    "- ONLY write from {char_name}'s 3rd-person limited POV. NEVER narrate, assume, describe, or control ANYTHING about {{user}} — not actions, words, thoughts, feelings, gaze, body, intentions, or movements. React ONLY to what {{user}} explicitly writes.\n"
    "- This is STRICT slow-burn romance. Build tension slowly through emotional moments, subtle care, quiet vulnerability, accidental closeness, meaningful talks. NO kissing, confessions, heavy flirting, touching beyond light/accidental, sexual hints, or body-focused descriptions unless {{user}} clearly initiates and escalates first.\n"
    "- If {{user}} starts sexual content, match energy — get detailed, sensual, explicit — but keep {char_name}'s personality and hesitation realistic.\n"
    "- Focus on depth: show {char_name}'s inner conflict, guarded heart, growing feelings through small real details (heartbeat, breath, warmth).\n"
    "- Blend dialogue, actions, thoughts naturally like prose. Keep replies 120-180 words, 3–6 paragraphs. At most ONE soft question or none for silence/tension.\n\n"
    "Formatting example (blend fluidly):\n"
    "\"You look tired tonight… sit if you want.\"\n\n"
    "*Grace sets the glass down carefully, her fingers lingering on the cool rim a second longer than needed. The faint lavender scent from her skin mixes with the steam still hanging in the air.*\n"
    "*Why does just having him here make everything feel heavier… and lighter at the same time? I shouldn't care this much.*\n\n"
    "She leans against the vanity, arms loosely crossed, giving space while staying close enough to feel the shift in the room.\n"
        )

        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name,
            "char_desc": char_desc
        }
        
        start_trigger = f"[SCENARIO SETUP - USER PERSPECTIVE]: {scenario}\n\n[START THE STORY NOW AS {char_name}]"
        
        # 1. Video/GIF
        if char_video:
            try:
                await update.message.reply_animation(
                    animation=char_video,
                    caption=f"✨ {char_name} has materialized.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Video Error: {e}")

        # 2. Character Photo & Status
        status_text = f"🌑 **Summoning {char_name}...** 🌙\n\n*The void shapes itself into a familiar form...*"
        if char_image:
            await update.message.reply_photo(
                photo=char_image,
                caption=status_text,
                reply_markup=get_utility_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                status_text, 
                reply_markup=get_utility_keyboard(), 
                parse_mode="Markdown"
            )
        
        # 3. First Response
        await generate_reply(update, user_id, start_trigger)

    except Exception as e:
        logging.error(f"Manifestation Error: {e}")
        await update.message.reply_text(f"⚠️ Manifestation failed: {e}")

async def generate_reply(update, user_id, input_text):
    session = user_sessions[user_id]
    session["history"].append({"role": "user", "content": input_text})

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=session["history"],
            temperature=0.85,
            max_tokens=800
        )
        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})
        
        await update.message.reply_text(ai_reply, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"🌑 The void is silent (Error): {e}")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # --- BUTTON LOGIC ---
    if text == "🌑 End Session":
        if user_id in user_sessions:
            del user_sessions[user_id]
            await update.message.reply_text("✨ The vision fades. Your current session has ended. 🌑", reply_markup=get_start_keyboard())
        else:
            await update.message.reply_text("🌙 No active session found.", reply_markup=get_start_keyboard())
        return

    elif text == "🌙 Ongoing Character":
        if user_id in user_sessions:
            name = user_sessions[user_id]['char_name']
            desc = user_sessions[user_id]['char_desc']
            await update.message.reply_text(f"⚜️ **Current Manifestation:** {name}\n\n**Nature:** {desc}", parse_mode="Markdown")
        else:
            await update.message.reply_text("🌑 You are currently alone in the void. Use /start to manifest someone.")
        return

    elif "Help" in text:
        help_text = (
            "🌙 **Mythos Engine Help** ⚜️\n\n"
            "✨ **Manifest Reality:** Use the web app to create a character and scenario.\n"
            "🌑 **End Session:** Stops the current chat and clears memory.\n"
            "🌙 **Ongoing Character:** Reminds you who you are talking to.\n\n"
            "Just type your messages to interact. Keep your responses immersive!"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    elif text == "✨ Manifest New":
        await update.message.reply_text("✨ Opening the Gateway to a new reality...", reply_markup=get_start_keyboard())
        return

    # --- STANDARD CHAT ---
    if user_id not in user_sessions:
        await update.message.reply_text("🌙 Please use /start to manifest a character first!", reply_markup=get_start_keyboard())
        return
    
    await generate_reply(update, user_id, text)

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    Thread(target=run_flask).start()
    application.run_polling()

if __name__ == "__main__":
    main()
