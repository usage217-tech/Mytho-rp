"""
HERMAX ROLEPLAY BOT
Integrates: Telegram Bot + Web App + Grok AI + Pollinations Image Generation
Character data loaded from characters.json
"""

import os
import json
import logging
import random
import requests
from io import BytesIO
from threading import Thread
from urllib.parse import quote
from flask import Flask
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY")
WEBAPP_URL = "https://usage217-tech.github.io/Mytho-rp/"
MODEL = "x-ai/grok-4.1-fast"

# ============================================================================
# LOAD CHARACTER DATA
# ============================================================================

with open("characters.json", "r") as f:
    CHARACTERS = json.load(f)

def get_char(name):
    return CHARACTERS.get(name)

def is_anime(name):
    char = get_char(name)
    return char and char.get("style", "Realistic") == "Anime"

# ============================================================================
# INITIALIZE SERVICES
# ============================================================================

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
app = Flask(__name__)
user_sessions = {}

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def build_image_prompt(scene_keywords, char_name):
    style = "Anime" if is_anime(char_name) else "Realistic"
    prompt = f"{style} style. {scene_keywords}. Using the reference image."
    logging.info(f"🖼️ Image prompt: {prompt}")
    return prompt

def generate_scene_image(scene_keywords, char_name, reference_image_url=None):
    try:
        final_prompt = build_image_prompt(scene_keywords, char_name)
        encoded_prompt = quote(final_prompt)
        seed = random.randint(0, 999999)

        image_url = f"https://gen.pollinations.ai/image/{encoded_prompt}"
        params = [
            "model=klein",
            "width=1024",
            "height=1024",
            f"seed={seed}",
            "enhance=true",
            f"key={POLLINATIONS_API_KEY}"
        ]

        if reference_image_url:
            params.append(f"image={quote(reference_image_url)}")
            logging.info(f"✅ Reference: {reference_image_url[:60]}...")

        final_url = image_url + "?" + "&".join(params)
        response = requests.get(final_url, timeout=30)

        if response.status_code == 200:
            logging.info("✅ Image generated successfully")
            return (BytesIO(response.content), final_url)
        else:
            logging.error(f"❌ Image failed: HTTP {response.status_code}")
            return (None, None)

    except Exception as e:
        logging.error(f"❌ Image error: {e}")
        return (None, None)

async def get_scene_keywords(ai_reply, char_name):
    """
    Extracts image keywords from Grok's OWN RP reply.
    Only called when image trigger fires — never on every message.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract image keywords from this roleplay text for a solo photo of {char_name}.\n\n"
                    f"TEXT:\n{ai_reply}\n\n"
                    f"RULE 1 — Two people interacting (touching, talking, eye contact):\n"
                    f"→ Extract ONLY background/setting/lighting. Ignore all actions.\n"
                    f"→ Example: moonlight, garden, stone wall, roses, silver glow\n\n"
                    f"RULE 2 — {char_name} is alone:\n"
                    f"→ Extract pose + expression + background.\n"
                    f"→ Example: blushing, shy smile, standing, library, warm light\n\n"
                    f"NEVER: interaction words, 2nd person hints, sentences, more than 10 keywords.\n"
                    f"Output format: keyword, keyword, keyword\n"
                    f"Output keywords only:"
                )
            }],
            temperature=0.5,
            max_tokens=30
        )

        keywords = response.choices[0].message.content.strip()
        keywords = keywords.replace('"', '').replace("'", "")
        logging.info(f"📝 Scene keywords: {keywords}")
        return keywords

    except Exception as e:
        logging.error(f"❌ Keyword error: {e}")
        return None

# ============================================================================
# IMAGE TRIGGER LOGIC
# ============================================================================

def should_generate_image(session):
    count = session["message_count"]
    generated = session["images_generated"]

    if count == 3:
        logging.info("📸 Trigger: Message 3")
        return True
    if count == 7:
        logging.info("📸 Trigger: Message 7")
        return True
    if count > 7 and generated < 6:
        if random.random() < 0.3:
            logging.info(f"📸 Trigger: Random ({generated}/6)")
            return True
    return False

# ============================================================================
# KEYBOARDS
# ============================================================================

def start_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("✨ Manifest Reality", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("⚜️ Help & Lore")]
    ], resize_keyboard=True)

def utility_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🌙 Ongoing Character"), KeyboardButton("🌑 End Session")],
        [KeyboardButton("✨ Manifest New"), KeyboardButton("⚜️ Help")]
    ], resize_keyboard=True)

# ============================================================================
# FLASK (Keep-Alive)
# ============================================================================

@app.route('/')
def home():
    return "🌙 HERMAX Roleplay Engine - Online"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# ============================================================================
# /start COMMAND
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✧ 🌙 **HERMAX ROLEPLAY** 🌑 ✧\n\n"
        "✨ Welcome, Traveler. The boundaries of reality are thinning. "
        "Tap the button below to design your persona and begin your journey. ⚜️",
        reply_markup=start_keyboard(),
        parse_mode="Markdown"
    )

# ============================================================================
# WEB APP HANDLER
# ============================================================================

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Preloaded characters → prompt from characters.json
    Custom characters → generic prompt with ai_desc from web app
    """
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        char_name   = data.get('ai_name', 'Unknown')
        char_desc   = data.get('ai_desc', '')
        char_image  = data.get('ai_image', '')
        user_name   = data.get('user_name', 'Traveler')
        user_gender = data.get('user_gender', 'Male')
        scenario    = data.get('scenario', 'A mysterious encounter.')

        char_data    = get_char(char_name)
        is_preloaded = char_data is not None

        reference_image = char_data["image"] if is_preloaded else char_image
        char_video = char_data.get("video", "") if is_preloaded else ""

        logging.info(f"🎭 {char_name} | {user_name} | Preloaded: {is_preloaded}")

        # Build system prompt
        if is_preloaded:
            # Preloaded: just fill placeholders from JSON prompt
            system_prompt = char_data['prompt'].format(
                user_name=user_name,
                user_gender=user_gender,
                scenario=scenario
            )
        else:
            # Custom: generic prompt with placeholders inline
            system_prompt = (
                "You are {char_name}.\n"
                "Personality and appearance: {char_desc}\n"
                "You are talking with {user_name} ({user_gender}).\n\n"
                "Write exactly like a real human texting — natural, casual, never robotic.\n"
                "Match the user's energy and reply length.\n"
                "Actions go inline with *asterisks*.\n"
                "Never write for the user. Never break character.\n"
                "Always end with a small hook — a question, an action, a look.\n"
                "Start warm and friendly. Only escalate if user clearly leads.\n\n"
                "Scenario: {scenario}"
            ).format(
                char_name=char_name,
                char_desc=char_desc,
                user_name=user_name,
                user_gender=user_gender,
                scenario=scenario
            )

        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name,
            "char_desc": char_data.get("desc", "") if is_preloaded else char_desc,
            "scenario": scenario,
            "reference_image": reference_image,
            "is_preloaded": is_preloaded,
            "message_count": 0,
            "images_generated": 0,
            "last_20_messages": 0
        }

        session = user_sessions[user_id]

        # Intro video (preloaded only)
        if char_video:
            try:
                await update.message.reply_animation(
                    animation=char_video,
                    caption=f"✨ {char_name} materializes before you...",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"❌ Video error: {e}")

        # First AI reply
        session["history"].append({
            "role": "user",
            "content": f"[SCENARIO]: {scenario}\n\nBegin the roleplay as {char_name}. Set the scene and make your first move."
        })

        response = client.chat.completions.create(
            model=MODEL,
            messages=session["history"],
            temperature=0.85,
            min_tokens=85,
            max_tokens=95
        )

        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})

        # Opening image
        if is_preloaded:
            # Preloaded → reference image directly, no API call
            await update.message.reply_photo(
                photo=reference_image,
                caption=ai_reply,
                reply_markup=utility_keyboard(),
                parse_mode="Markdown"
            )
        else:
            # Custom → generate AI image
            opening_image, opening_url = generate_scene_image(
                scene_keywords=f"{scenario}, cinematic, atmospheric",
                char_name=char_name,
                reference_image_url=reference_image
            )
            if opening_url:
                session["reference_image"] = opening_url

            if opening_image:
                await update.message.reply_photo(
                    photo=opening_image,
                    caption=ai_reply,
                    reply_markup=utility_keyboard(),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    ai_reply,
                    reply_markup=utility_keyboard(),
                    parse_mode="Markdown"
                )

        session["message_count"] = 1
        session["images_generated"] = 1

    except Exception as e:
        logging.error(f"❌ Manifest error: {e}")
        await update.message.reply_text(f"⚠️ Manifestation failed: {e}")

# ============================================================================
# CORE REPLY GENERATOR
# ============================================================================

async def generate_reply(update, user_id, input_text):
    session = user_sessions[user_id]
    session["history"].append({"role": "user", "content": input_text})

    try:
        # Trimmed history — system prompt + last 10 messages
        system_msg = session["history"][0]
        recent = session["history"][1:][-10:]
        trimmed = [system_msg] + recent

        response = client.chat.completions.create(
            model=MODEL,
            messages=trimmed,
            temperature=0.85,
            min_tokens=85,
            max_tokens=95
        )

        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})

        # Update counters
        session["message_count"] += 1
        session["last_20_messages"] += 1

        if session["last_20_messages"] >= 20:
            session["images_generated"] = 0
            session["last_20_messages"] = 0
            logging.info("🔄 Image counter reset")

        # Image — only when triggered, keywords from AI reply not user message
        send_image = False
        image_bytes = None

        if should_generate_image(session):
            keywords = await get_scene_keywords(ai_reply, session["char_name"])
            if keywords:
                image_bytes, _ = generate_scene_image(
                    scene_keywords=keywords,
                    char_name=session["char_name"],
                    reference_image_url=session.get("reference_image")
                )
                if image_bytes:
                    send_image = True
                    session["images_generated"] += 1
                    logging.info(f"✅ Image ready ({session['images_generated']}/6)")

        # Send exactly one response
        if send_image and image_bytes:
            await update.message.reply_photo(
                photo=image_bytes,
                caption=ai_reply,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(ai_reply, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"❌ Reply error: {e}")
        await update.message.reply_text(f"🌑 The void is silent... (Error: {e})")

# ============================================================================
# MESSAGE ROUTER
# ============================================================================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text == "🌑 End Session":
        if user_id in user_sessions:
            char_name = user_sessions[user_id]['char_name']
            del user_sessions[user_id]
            await update.message.reply_text(
                f"✨ The vision of {char_name} fades into the void. Session ended. 🌑",
                reply_markup=start_keyboard()
            )
        else:
            await update.message.reply_text("🌙 No active session.", reply_markup=start_keyboard())
        return

    elif text == "🌙 Ongoing Character":
        if user_id in user_sessions:
            s = user_sessions[user_id]
            await update.message.reply_text(
                f"⚜️ **Current Manifestation:** {s['char_name']}\n\n"
                f"**Essence:** {s['char_desc']}\n\n"
                f"**Messages exchanged:** {s['message_count']}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("🌑 No active character. Use /start to manifest one.")
        return

    elif "Help" in text:
        await update.message.reply_text(
            "🌙 **HERMAX ROLEPLAY HELP** ⚜️\n\n"
            "✨ **Manifest Reality:** Create your character and scenario\n"
            "🌑 **End Session:** Clear current roleplay\n"
            "🌙 **Ongoing Character:** View current character info\n\n"
            "Just type to interact naturally with your character!",
            parse_mode="Markdown"
        )
        return

    elif text == "✨ Manifest New":
        await update.message.reply_text("✨ Opening the gateway...", reply_markup=start_keyboard())
        return

    if user_id not in user_sessions:
        await update.message.reply_text(
            "🌙 Please use /start to manifest a character first!",
            reply_markup=start_keyboard()
        )
        return

    await generate_reply(update, user_id, text)

# ============================================================================
# MAIN
# ============================================================================

def main():
    logging.info("🌙 Starting HERMAX Roleplay Bot...")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    Thread(target=run_flask, daemon=True).start()
    logging.info("🌐 Flask started | ✅ Bot running!")
    application.run_polling()

if __name__ == "__main__":
    main()
