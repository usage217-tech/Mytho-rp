import os
import json
import logging
from threading import Thread
from flask import Flask
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from openai import OpenAI
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# --- CONFIGURATION ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
WEBAPP_URL = "https://usage217-tech.github.io/Mytho-rp/" 
MODEL = "x-ai/grok-4-fast"

# Initialize Clients
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
app = Flask(__name__)
user_sessions = {}

# --- FLASK SERVER (For Render) ---
@app.route('/')
def home(): 
    return "Mythos Engine is Awake."

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- UI HELPERS ---
def get_main_menu():
    """Persistent keyboard at the bottom of the screen."""
    keyboard = [
        [KeyboardButton("✨ Manifest Reality", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("📜 Current Character"), KeyboardButton("❓ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_stop_button():
    """Inline button that appears under AI messages."""
    keyboard = [[InlineKeyboardButton("🛑 End Session", callback_data="stop_session")]]
    return InlineKeyboardMarkup(keyboard)

# --- BOT LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Refined welcome message with main menu."""
    welcome_text = (
        "<b>✧ MYTHOS ENGINE ✧</b>\n"
        "<i>Where imagination bleeds into reality.</i>\n\n"
        "Welcome, Traveler. This engine allows you to manifest complex personas and explore limitless scenarios.\n\n"
        "<b>How to begin:</b>\n"
        "1. Tap <b>'Manifest Reality'</b> below.\n"
        "2. Design your character and scenario.\n"
        "3. Step into the void.\n\n"
        "<i>Use the menu below to manage your journey.</i>"
    )
    await update.message.reply_html(welcome_text, reply_markup=get_main_menu())

async def stop_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears user session."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if query: await query.answer()
    
    if user_id in user_sessions:
        del user_sessions[user_id]
        msg = "<b>✧ THE VOID CLOSES ✧</b>\n\nThe manifestation has faded. You are back in reality."
    else:
        msg = "No active manifestation found."

    if query:
        await query.edit_message_text(text=msg, parse_mode="HTML")
    else:
        await update.message.reply_html(msg, reply_markup=get_main_menu())

async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows current active character."""
    user_id = update.effective_user.id
    if user_id in user_sessions:
        char = user_sessions[user_id]['char_name']
        await update.message.reply_html(f"🎭 <b>Currently Manifesting:</b> {char}\n<i>You can continue chatting or start a new one.</i>")
    else:
        await update.message.reply_html("🌑 <b>No active manifestation.</b>\nTap 'Manifest Reality' to begin.")

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

        system_prompt = (
            f"You are playing in a adult Explicit roleplay. you are playing as {char_name}.\n"
            f"Personality: {char_desc}.\n"
            f"User: {user_name} (Gender: {user_gender}).\n"
            "You are the AI character. The scenario below describes the {{user}}'s current actions and situation.\n"
            "POV RULES:\n"
            "- The [START] prompt describes {{user}}'s perspective and actions. DO NOT REPEAT THEM AS YOUR OWN.\n"
            f"- You are {char_name}, reacting to {{user}} entering your space.\n"
            "- Never write for {{user}}.\n"
            "Focus entirely on your own internal reactions, physical responses, and spoken dialogue.\n"
            "- Use sensory details (smell, heat, sound) from your character's perspective.\n"
            "Strict Rules:\n"
            "- 100% in-character voice. Raw, vivid, and emotive. provide expressions like aghh,gasps,mmh etc.\n"
            "- STRICTLY IN 70-100 words.\n\n"
            "Formatting:\n\"dialogue\"\n*actions* *quiet thoughts*"
        )

        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name
        }
        
        start_trigger = f"[SCENARIO SETUP]: {scenario}\n\n[START THE STORY NOW AS {char_name}]"
        
        status_text = f"🌑 <b>Summoning {char_name}...</b>\n<i>The reality is shifting.</i>"
        
        if char_image:
            await update.message.reply_photo(photo=char_image, caption=status_text, parse_mode="HTML")
        else:
            await update.message.reply_html(status_text)
        
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
        
        # Send reply with the "Stop" button
        await update.message.reply_text(ai_reply, parse_mode="Markdown", reply_markup=get_stop_button())
        
    except Exception as e:
        await update.message.reply_text(f"The void is silent (Error): {e}")

async def handle_text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes messages from the persistent menu buttons."""
    text = update.message.text
    if text == "📜 Current Character":
        await show_status(update, context)
    elif text == "❓ Help":
        await start(update, context)
    else:
        # It's a chat message
        user_id = update.effective_user.id
        if user_id not in user_sessions:
            await update.message.reply_html("Please use <b>Manifest Reality</b> to begin a session!", reply_markup=get_main_menu())
            return
        await generate_reply(update, user_id, text)

def main():
    application = Application.builder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_session))
    application.add_handler(CallbackQueryHandler(stop_session, pattern="stop_session"))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons))

    # Run Flask in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print("Mythos Engine 2.0 is polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
