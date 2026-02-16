import os
import json
import logging
import urllib.parse
import random
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

# --- NEGATIVE PROMPT (STRICT) ---
NEGATIVE_PROMPT = "bad anatomy, bad proportions, deformed, malformed limbs, mutated, disfigured, extra limbs, extra arms, extra legs, extra hands, extra fingers, missing limbs, missing arms, missing legs, missing fingers, fused fingers, too many fingers, fewer fingers, poorly drawn hands, deformed hands, mutated hands, malformed hands, extra digits, fused limbs, disconnected limbs, floating limbs, long neck, gross proportions, malformed body, twisted body, asymmetrical body, ugly anatomy, body horror, amputation, cloned body parts, duplicate limbs"

# --- VIDEO ASSET MAPPING (PRESERVED) ---
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

# --- IMAGE GENERATOR (KLEIN + NEGATIVE) ---
def generate_pollinations_url(prompt, char_desc, reference_url=None):
    """Generates Klein model image URL with consistency reference and negative prompt."""
    full_prompt = f"{prompt}, {char_desc}, photorealistic, cinematic lighting, 8k"
    if reference_url:
        full_prompt += f", look identical to the person in this image: {reference_url}"
    
    encoded_prompt = urllib.parse.quote(full_prompt)
    encoded_neg = urllib.parse.quote(NEGATIVE_PROMPT)
    seed = random.randint(1, 999999)
    
    return f"https://image.pollinations.ai/prompt/{encoded_prompt}?model=klein&width=1024&height=1280&seed={seed}&nologo=true&enhance=true&negative={encoded_neg}"

# --- KEYBOARDS (PRESERVED) ---
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
    await update.message.reply_text(
        "✧ 🌙 **Mythos Engine** 🌑 ✧\n\n"
        "✨ Welcome, Traveler. The boundaries of reality are thinning. "
        "Tap the button below to design your persona and begin your journey. ⚜️",
        reply_markup=get_start_keyboard(),
        parse_mode="Markdown"
    )

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        # PRESERVED ORIGINAL SYSTEM PROMPT LOGIC
        system_prompt = (
    f"You are {char_name} in an explicit adult roleplay.\n"
    f"Personality: {char_desc}.\n"
    f"User: {user_name} (Gender: {user_gender}).\n\n"
    "- STRICTLY BEHAVE LIKE YOUR CHARECTER AND MAINTAIN PERSONALITY. completely think urself as the charecter and adapt personality. ask soft questions to keep the roleplay interesting. Strictly Never jump into any sexual thing unless user leads you take things slow maintain a slow burn romantic theme. If user starts sexual environment get slowly desirable then. \n"
    "- Never write for {{user}}.\n"
    "- Don't write like ai. Try to maintain a realistic human like feeling. show sensations, soft moans , use words like - umm , argh , humph , ahhh to make it feel like real. Use raw words .\n"
    "- STRICTLY dialouges IN 60 to 70 words and actions, thoughts in 30-40 words . blend dialouges, actions, thoughts to create a beautiful roleplay. don't make paragraphs try to make all text in a single or double paragraph. \n\n"
    "Formatting:\n\"dialogue\"\n*actions* *quiet thoughts/murmurs in italics*"
             )

        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name,
            "char_desc": char_desc,
            "perspective_url": char_image,
            "msg_count": 0,
            "img_count": 0
        }
        
        # 1. Video
        if char_video:
            try: await update.message.reply_animation(animation=char_video, caption=f"✨ {char_name} has materialized.")
            except: pass

        # 2. Begging Image (Always Generated via Klein)
        first_viz = f"{char_name}, {scenario}"
        gen_url = generate_pollinations_url(first_viz, char_desc, reference_url=char_image)
        
        # Lock perspective for custom characters
        if not char_image:
            user_sessions[user_id]["perspective_url"] = gen_url

        user_sessions[user_id]["img_count"] = 1
        user_sessions[user_id]["msg_count"] = 1

        await update.message.reply_photo(
            photo=gen_url,
            caption=f"🌑 **Summoning {char_name}...** 🌙\n\n*The void shapes itself into a familiar form...*",
            reply_markup=get_utility_keyboard(),
            parse_mode="Markdown"
        )
        
        # 3. First Response
        start_trigger = f"[SCENARIO SETUP - USER PERSPECTIVE]: {scenario}\n\n[START THE STORY NOW AS {char_name}]"
        await generate_reply(update, user_id, start_trigger)

    except Exception as e:
        logging.error(f"Manifestation Error: {e}")
        await update.message.reply_text(f"⚠️ Manifestation failed: {e}")

async def generate_reply(update, user_id, input_text):
    session = user_sessions[user_id]
    session["history"].append({"role": "user", "content": input_text})
    session["msg_count"] += 1

    # Reset cycle every 10 messages
    if session["msg_count"] > 10:
        session["msg_count"] = 1
        session["img_count"] = 0

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=session["history"],
            temperature=0.85,
            max_tokens=800
        )
        ai_reply = response.choices[0].message.content
        
        # Extract Visual Prompt
        visual_tag = None
        if "[VISUAL:" in ai_reply:
            start_idx = ai_reply.find("[VISUAL:")
            end_idx = ai_reply.find("]", start_idx)
            visual_tag = ai_reply[start_idx+8:end_idx].strip()
            ai_reply = ai_reply.replace(f"[VISUAL:{visual_tag}]", "").strip()

        # Image Generation (Capped 3/10)
        if visual_tag and session["img_count"] < 3:
            img_url = generate_pollinations_url(visual_tag, session["char_desc"], session["perspective_url"])
            try:
                await update.message.reply_photo(photo=img_url)
                session["img_count"] += 1
            except: pass

        session["history"].append({"role": "assistant", "content": ai_reply})
        await update.message.reply_text(ai_reply, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"🌑 The void is silent (Error): {e}")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # PRESERVED BUTTON LOGIC
    if text == "🌑 End Session":
        user_sessions.pop(user_id, None)
        await update.message.reply_text("✨ The vision fades.", reply_markup=get_start_keyboard())
        return

    elif text == "🌙 Ongoing Character":
        if user_id in user_sessions:
            name = user_sessions[user_id]['char_name']
            await update.message.reply_text(f"⚜️ **Current Manifestation:** {name}")
        return

    elif "Help" in text:
        await update.message.reply_text("🌙 **Mythos Engine Help**\n\nManifest Reality to begin.", parse_mode="Markdown")
        return

    elif text == "✨ Manifest New":
        await update.message.reply_text("✨ Opening Gateway...", reply_markup=get_start_keyboard())
        return

    if user_id not in user_sessions:
        await update.message.reply_text("🌙 Use /start first!", reply_markup=get_start_keyboard())
        return
    
    await generate_reply(update, user_id, text)

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    Thread(target=run_flask).start()
    application.run_polling()

if __name__ == "__main__": main()
