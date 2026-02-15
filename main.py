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
MODEL = "gryphe/mythomax-l2-13b"

# Initialize Clients
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
app = Flask(__name__)
user_sessions = {}

# --- FLASK SERVER (For Render) ---
@app.route('/')
def home(): return "Mythos Engine is Awake."

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the button to open the Web App."""
    keyboard = [[KeyboardButton("✨ Manifest Reality", web_app=WebAppInfo(url=WEBAPP_URL))]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "✧ **Mythos Engine** ✧\n\nTap the button below to design your persona and begin.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives data from the Web App and starts the RP."""
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id
        
        # [span_0](start_span)Updated keys to match your HTML 'manifest' function[span_0](end_span)
        char_name = data.get('ai_name', 'Unknown')
        char_desc = data.get('ai_desc', 'A mysterious figure')
        user_name = data.get('user_name', 'Traveler')
        user_gender = data.get('user_gender', 'not specified') # New field added
        scenario = data.get('scenario', 'A meeting in the dark.')

        # -[span_1](start_span)-- SYSTEM PROMPT (Logic and Info preserved)[span_1](end_span) ---
        system_prompt = (
            f"You are playing as {char_name}.\n"
            f"Personality: {char_desc}.\n"
            [span_2](start_span)f"User: {user_name} (Gender: {user_gender}).\n" # Included gender info[span_2](end_span)
            "You are the AI character. "
            [span_3](start_span)"The scenario below describes the {{user}}'s current actions and situation.\n"[span_3](end_span)
            "POV RULES:\n"
            "- The [START] prompt describes {{user}}'s perspective and actions. "
            [span_4](start_span)"DO NOT REPEAT THEM AS YOUR OWN.\n"[span_4](end_span)
            f"- You are {char_name}, reacting to {{user}} entering your space or performing those actions.\n"
            "- Never write for {{user}}.\n"
            "Focus entirely on your own internal reactions, physical responses, and spoken dialogue.\n"
            "- Use sensory details (smell, heat, sound) from your character's perspective.\n"
            [span_5](start_span)"Strict Rules:\n"[span_5](end_span)
            "- never rush into anything unless the user go into\n"
            [span_6](start_span)"- 100% in-character voice + senses + emotion. No narrator.\n"[span_6](end_span)
            "- Real speech: um, like, …, stutters, moans, raw dirty words that fit.\n"
            "- Vivid but believable: heat, slick, pulse, taste, clench, tremble.\n"
            [span_7](start_span)"- Explicit, varied vocab. End open for reply.\n"[span_7](end_span)
            "- STRICTLY IN 30-40 words.\n\n"
            "Formatting:\n\"dialogue\"\n*actions* *quiet thoughts/murmurs in italics*"
        )

        # [span_8](start_span)Store session[span_8](end_span)
        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name
        }
        
        # [span_9](start_span)Initial Trigger[span_9](end_span)
        start_trigger = f"[SCENARIO SETUP - USER PERSPECTIVE]: {scenario}\n\n[START THE STORY NOW AS {char_name}]"
        
        await update.message.reply_text(f"🌑 **Summoning {char_name}...**", reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
        
        # [span_10](start_span)Generate First Reply[span_10](end_span)
        await generate_reply(update, user_id, start_trigger)

    except Exception as e:
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
        [span_11](start_span))
        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})
        
        await update.message.reply_text(ai_reply, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"The void is silent (Error): {e}")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        await update.message.reply_text("Please use /start to manifest a character first!")[span_11](end_span)
        return
    
    await generate_reply(update, user_id, update.message.text)

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    # Run Flask in background
    Thread(target=run_flask).start()
    
    # Run Bot
    application.run_polling()

if __name__ == "__main__":
    main()
