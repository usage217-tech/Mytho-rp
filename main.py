"""
HERMAX ROLEPLAY BOT - Optimized & Clean Architecture
Integrates: Telegram Bot + Web App + Grok AI + Pollinations Image Generation
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

# Environment Variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY")
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY")
WEBAPP_URL = "https://usage217-tech.github.io/Mytho-rp/"
MODEL = "x-ai/grok-4.1-fast"

# ============================================================================
# CHARACTER DATABASE
# ============================================================================

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

CHARACTER_REFERENCE_IMAGES = {
    # Realistic Female Characters
    "Lilith": "https://i.postimg.cc/nLPJ8WTn/image-14.jpg",
    "Hellien": "https://i.postimg.cc/Pr40sc5p/image-10.jpg",
    "Mrs. Grace": "https://i.postimg.cc/dtqSBBmz/image-15.jpg",
    "Maya": "https://i.postimg.cc/rs9ZT0cN/image-20.jpg",
    "Nika": "https://i.postimg.cc/W4J93fT3/image-8.jpg",

    # Realistic Male Characters
    "Robert": "https://i.postimg.cc/NFN8b1Qt/image-5.jpg",
    "John": "https://i.postimg.cc/JhbbSwRb/image-6.jpg",
    "Mike": "https://i.postimg.cc/pXTJr1Bj/image-7.jpg",

    # Anime Female Characters
    "Mia": "https://usage217-tech.github.io/Charecter-mp4/MIA.jpg",
    "Velora": "https://usage217-tech.github.io/Charecter-mp4/VELORA.jpg",
    "Caroline": "https://usage217-tech.github.io/Charecter-mp4/CAROLINE.jpg",
    "Laura": "https://usage217-tech.github.io/Charecter-mp4/LAURA.jpg",
    "Bella": "https://usage217-tech.github.io/Charecter-mp4/BELLA.jpg",

    # Anime Male Characters
    "Arthur": "https://usage217-tech.github.io/Charecter-mp4/ARTHUR.jpg",
    "Tim": "https://usage217-tech.github.io/Charecter-mp4/TIM.jpg",
    "Joseph": "https://usage217-tech.github.io/Charecter-mp4/JOSEPH.jpg",
    "Zenox": "https://usage217-tech.github.io/Charecter-mp4/ZENOX.jpg",
    "Anthony": "https://usage217-tech.github.io/Charecter-mp4/ANTHONY.jpg"
}

# Anime characters set for style detection
ANIME_CHARACTERS = {"Mia", "Velora", "Caroline", "Laura", "Bella", "Arthur", "Tim", "Joseph", "Zenox", "Anthony"}

# ============================================================================
# INITIALIZE SERVICES
# ============================================================================

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
app = Flask(__name__)
user_sessions = {}

# ============================================================================
# IMAGE GENERATION SYSTEM
# ============================================================================

def get_character_style(char_name):
    """
    Returns 'Anime' for anime characters, 'Realistic' for all others.
    """
    if char_name in ANIME_CHARACTERS:
        return "Anime"
    return "Realistic"


def build_image_prompt(grok_scene_description, char_name):
    """
    Wraps Grok's raw scene description into the final structured image prompt.

    Structure: "[Style] style. [Grok scene description]. Using the reference image."

    Args:
        grok_scene_description: Raw scene description from Grok (pose, setting, lighting, etc.)
        char_name: Character name to determine Anime or Realistic style

    Returns:
        str: Final structured prompt ready for Pollinations
    """
    style = get_character_style(char_name)
    final_prompt = f"{style} style. {grok_scene_description}. Using the reference image."
    logging.info(f"🖼️ Image prompt built: {final_prompt}")
    return final_prompt


def generate_scene_image(scene_description, char_name, reference_image_url=None):
    """
    Generate image using Pollinations Klein API.

    Args:
        scene_description: Raw scene description from Grok (NO character details)
        char_name: Character name (used to determine Anime/Realistic style)
        reference_image_url: Character reference image URL

    Returns:
        tuple: (image_bytes, image_url) or (None, None) on failure
    """
    try:
        # Build the structured prompt: Style + Grok description + Reference instruction
        final_prompt = build_image_prompt(scene_description, char_name)

        # Encode for URL
        encoded_prompt = quote(final_prompt)

        # Random seed for variety
        seed = random.randint(0, 999999)

        # Build Pollinations API URL
        image_url = f"https://gen.pollinations.ai/image/{encoded_prompt}"
        params = [
            "model=klein",
            "width=1024",
            "height=1024",
            f"seed={seed}",
            "enhance=true",
            f"key={POLLINATIONS_API_KEY}"
        ]

        # Add reference image using CORRECT parameter name
        if reference_image_url:
            encoded_reference = quote(reference_image_url)
            params.append(f"image={encoded_reference}")
            logging.info(f"✅ Using reference: {reference_image_url[:60]}...")

        final_url = image_url + "?" + "&".join(params)
        logging.info(f"🎨 Generating image with prompt: {final_prompt[:80]}... (seed: {seed})")

        # Download generated image
        response = requests.get(final_url, timeout=30)

        if response.status_code == 200:
            image_bytes = BytesIO(response.content)
            logging.info("✅ Image generated successfully")
            return (image_bytes, final_url)
        else:
            logging.error(f"❌ Image generation failed: HTTP {response.status_code}")
            return (None, None)

    except Exception as e:
        logging.error(f"❌ Image generation error: {e}")
        return (None, None)


async def get_scene_description_from_grok(ai_reply, char_name):
    """
    Extract image keywords from Grok's OWN RP reply (not user message).
    This runs AFTER the RP text is generated, so it has rich scene context.

    RULE 1 — Interaction scene (2 people): extract background/setting only
    RULE 2 — Character alone: extract pose + expression + background

    Returns:
        str: Keyword string like "moonlight, garden, stone wall, roses, night sky"
    """
    try:
        prompt_messages = [
            {
                "role": "user",
                "content": (
                    f"Extract image keywords from this roleplay text for a photo of {char_name} ALONE.\n\n"
                    f"ROLEPLAY TEXT:\n{ai_reply}\n\n"
                    f"RULE 1 — If the text describes TWO people interacting (touching, talking, eye contact, any interaction):\n"
                    f"→ Extract ONLY background/setting/lighting keywords. Completely ignore all actions and poses.\n"
                    f"→ Example output: moonlight, garden, stone wall, roses, night sky, silver glow\n\n"
                    f"RULE 2 — If {char_name} is alone in the text:\n"
                    f"→ Extract pose + expression + background keywords.\n"
                    f"→ Example output: blushing, shy smile, standing, library, warm golden light\n\n"
                    f"🚫 NEVER OUTPUT:\n"
                    f"- Interaction words (reaching, touching, looking at you, pinning, tracing, gazing at)\n"
                    f"- Any hint of a 2nd person existing\n"
                    f"- Sentences or full phrases\n"
                    f"- More than 10 keywords\n\n"
                    f"✅ OUTPUT FORMAT: keyword, keyword, keyword, keyword, keyword\n\n"
                    f"Output keywords only, nothing else:"
                )
            }
        ]

        response = client.chat.completions.create(
            model=MODEL,
            messages=prompt_messages,
            temperature=0.5,
            max_tokens=60
        )

        scene_desc = response.choices[0].message.content.strip()
        scene_desc = scene_desc.replace('"', '').replace("'", "")

        logging.info(f"📝 Grok image keywords (from AI reply): {scene_desc}")
        return scene_desc

    except Exception as e:
        logging.error(f"❌ Scene description error: {e}")
        return None

# ============================================================================
# IMAGE GENERATION DECISION LOGIC
# ============================================================================

def should_generate_image_now(session):
    """
    Determines if image should be generated for this message.
    Pattern: Message 3, Message 7, then random (30% chance) with cap of 6 per 20 messages.
    """
    msg_count = session["message_count"]
    images_generated = session["images_generated"]

    # Message 3: Always generate
    if msg_count == 3:
        logging.info("📸 Image trigger: Message 3 (guaranteed)")
        return True

    # Message 7: Always generate
    if msg_count == 7:
        logging.info("📸 Image trigger: Message 7 (guaranteed)")
        return True

    # After message 7: Random chance (30%) if under cap
    if msg_count > 7 and images_generated < 6:
        if random.random() < 0.3:
            logging.info(f"📸 Image trigger: Random (count: {images_generated}/6)")
            return True

    return False

# ============================================================================
# TELEGRAM UI KEYBOARDS
# ============================================================================

def get_start_keyboard():
    """Main menu keyboard"""
    keyboard = [
        [KeyboardButton("✨ Manifest Reality", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("⚜️ Help & Lore")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_utility_keyboard():
    """In-roleplay utility keyboard"""
    keyboard = [
        [KeyboardButton("🌙 Ongoing Character"), KeyboardButton("🌑 End Session")],
        [KeyboardButton("✨ Manifest New"), KeyboardButton("⚜️ Help")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ============================================================================
# FLASK SERVER (Keep-Alive)
# ============================================================================

@app.route('/')
def home():
    return "🌙 HERMAX Roleplay Engine - Online"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# ============================================================================
# BOT COMMANDS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message"""
    await update.message.reply_text(
        "✧ 🌙 **HERMAX ROLEPLAY** 🌑 ✧\n\n"
        "✨ Welcome, Traveler. The boundaries of reality are thinning. "
        "Tap the button below to design your persona and begin your journey. ⚜️",
        reply_markup=get_start_keyboard(),
        parse_mode="Markdown"
    )

# ============================================================================
# WEB APP DATA HANDLER - CHARACTER CREATION
# ============================================================================

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Receives character data from web app and initializes roleplay session.

    Web app sends:
    {
        "ai_name": "Lilith" or custom name,
        "ai_desc": "Character description",
        "ai_image": "https://..." (for pre-loaded) or "" (for custom),
        "user_name": "John",
        "user_gender": "Male" or "Female",
        "scenario": "You descended into catacombs..."
    }
    """
    try:
        # Parse web app data
        data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        # Extract character and user info
        char_name = data.get('ai_name', 'Unknown')
        char_desc = data.get('ai_desc', 'A mysterious figure')
        char_image = data.get('ai_image')
        user_name = data.get('user_name', 'Traveler')
        user_gender = data.get('user_gender', 'Male')
        scenario = data.get('scenario', 'A mysterious encounter in the shadows.')

        # Get pre-loaded character assets
        char_video = CHARACTER_VIDEOS.get(char_name)
        char_reference = CHARACTER_REFERENCE_IMAGES.get(char_name)

        # Determine final reference image
        # Priority: Pre-loaded reference > Custom uploaded image
        final_reference = char_reference or char_image

        logging.info(f"🎭 Manifesting: {char_name} for user {user_name}")
        logging.info(f"📝 Scenario: {scenario[:60]}...")
        logging.info(f"🖼️ Reference: {final_reference[:60] if final_reference else 'None'}")
        logging.info(f"🎨 Style: {get_character_style(char_name)}")

        # ========================================
        # BUILD GROK SYSTEM PROMPT
        # ========================================

        system_prompt = (
            f"You are {char_name} in an explicit adult roleplay.\n"
            f"Your personality and appearance: {char_desc}\n"
            f"You are interacting with: {user_name} (Gender: {user_gender})\n\n"
            "ROLEPLAY RULES:\n"
            "Stay fully in character at all times.\n"
            "Keep everything natural & human-like with soft sounds (umm, ahh, mmm).\n"
            "NEVER write for the user.\n"
            "Start slow & romantic. Only turn sexual if user starts it.\n"
            "Be flirty, seductive & playful.\n"
            "FORMATTING (strict - only these 3 things):\n"
            'Dialogues: "Natural human talk with little questions, soft desires, and everyday feelings." (minimum 50 words)\n'
            "Actions: descriptive actions (minimum 30 words)\n"
            "Lil narration: short plain description (minimum 30 words)\n"
            "Everything in 1-2 flowing paragraphs only.\n\n"
            "Now begin the roleplay!"
        )

        # ========================================
        # INITIALIZE SESSION
        # ========================================

        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name,
            "char_desc": char_desc,
            "scenario": scenario,
            "char_reference_image": final_reference,
            "message_count": 0,
            "images_generated": 0,
            "last_20_messages": 0
        }

        session = user_sessions[user_id]

        # ========================================
        # SEND INITIAL CONTENT
        # ========================================

        # 1. Character Video (pre-loaded only)
        if char_video:
            try:
                await update.message.reply_animation(
                    animation=char_video,
                    caption=f"✨ {char_name} materializes before you...",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"❌ Video error: {e}")

        # 2. Generate first AI response
        start_trigger = (
            f"[SCENARIO]: {scenario}\n\n"
            f"Begin the roleplay as {char_name}. Set the scene and make your first move."
        )

        session["history"].append({"role": "user", "content": start_trigger})

        # Get AI's first response
        response = client.chat.completions.create(
            model=MODEL,
            messages=session["history"],
            temperature=0.85,
            max_tokens=800
        )

        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})

        # 3. Generate initial scene image
        # Grok generates raw scene description → code wraps it → sent to Pollinations
        initial_scene_desc = f"{scenario}, cinematic scene, atmospheric"
        initial_scene_image, initial_image_url = generate_scene_image(
            scene_description=initial_scene_desc,
            char_name=char_name,
            reference_image_url=final_reference
        )

        # For custom characters, save first generated image URL as reference
        if not char_reference and initial_image_url:
            session["char_reference_image"] = initial_image_url
            logging.info("💾 Saved first generated image as reference for custom character")

        # 4. Send combined: image + AI's first message (ONLY ONE message sent)
        if initial_scene_image:
            await update.message.reply_photo(
                photo=initial_scene_image,
                caption=ai_reply,
                reply_markup=get_utility_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                ai_reply,
                reply_markup=get_utility_keyboard(),
                parse_mode="Markdown"
            )

        # Initialize message counter (this was the first message)
        session["message_count"] = 1
        session["images_generated"] = 1

    except Exception as e:
        logging.error(f"❌ Manifestation error: {e}")
        await update.message.reply_text(f"⚠️ Manifestation failed: {e}")

# ============================================================================
# CORE ROLEPLAY RESPONSE GENERATOR
# ============================================================================

async def generate_reply(update, user_id, input_text):
    """
    Generate AI response and optionally an image based on conversation state.
    """
    session = user_sessions[user_id]
    session["history"].append({"role": "user", "content": input_text})

    try:
        # ========================================
        # GENERATE TEXT RESPONSE
        # ========================================

        response = client.chat.completions.create(
            model=MODEL,
            messages=session["history"],
            temperature=0.85,
            max_tokens=800
        )

        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})

        # ========================================
        # UPDATE COUNTERS
        # ========================================

        session["message_count"] += 1
        session["last_20_messages"] += 1

        # Reset counters every 20 messages
        if session["last_20_messages"] >= 20:
            session["images_generated"] = 0
            session["last_20_messages"] = 0
            logging.info("🔄 Reset image counter for new 20-message cycle")

        # ========================================
        # IMAGE GENERATION DECISION
        # ========================================

        send_image = False
        scene_image_bytes = None

        if should_generate_image_now(session):
            logging.info(f"🎨 Message #{session['message_count']} - Generating scene image...")

            # Step 1: Extract keywords from Grok's OWN reply (not user message)
            # This is the correct order — RP text is already written above
            scene_desc = await get_scene_description_from_grok(
                ai_reply,
                session["char_name"]
            )

            if scene_desc:
                # Step 2: Wrap keywords into structured prompt → send to Pollinations
                scene_image_bytes, scene_image_url = generate_scene_image(
                    scene_description=scene_desc,
                    char_name=session["char_name"],
                    reference_image_url=session.get("char_reference_image")
                )

                if scene_image_bytes:
                    send_image = True
                    session["images_generated"] += 1
                    logging.info(f"✅ Image ready (total: {session['images_generated']}/6 in last 20)")

        # ========================================
        # SEND EXACTLY ONE RESPONSE
        # ========================================

        if send_image and scene_image_bytes:
            await update.message.reply_photo(
                photo=scene_image_bytes,
                caption=ai_reply,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(ai_reply, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"❌ Reply generation error: {e}")
        await update.message.reply_text(f"🌑 The void is silent... (Error: {e})")

# ============================================================================
# MESSAGE HANDLER - ROUTES USER INPUT
# ============================================================================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages from user"""
    user_id = update.effective_user.id
    text = update.message.text

    # ========================================
    # UTILITY BUTTONS
    # ========================================

    if text == "🌑 End Session":
        if user_id in user_sessions:
            char_name = user_sessions[user_id]['char_name']
            del user_sessions[user_id]
            await update.message.reply_text(
                f"✨ The vision of {char_name} fades into the void. Session ended. 🌑",
                reply_markup=get_start_keyboard()
            )
        else:
            await update.message.reply_text(
                "🌙 No active session found.",
                reply_markup=get_start_keyboard()
            )
        return

    elif text == "🌙 Ongoing Character":
        if user_id in user_sessions:
            char_name = user_sessions[user_id]['char_name']
            char_desc = user_sessions[user_id]['char_desc']
            msg_count = user_sessions[user_id]['message_count']
            await update.message.reply_text(
                f"⚜️ **Current Manifestation:** {char_name}\n\n"
                f"**Essence:** {char_desc}\n\n"
                f"**Messages exchanged:** {msg_count}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("🌑 No active character. Use /start to manifest one.")
        return

    elif "Help" in text:
        help_text = (
            "🌙 **HERMAX ROLEPLAY HELP** ⚜️\n\n"
            "✨ **Manifest Reality:** Create your character and scenario\n"
            "🌑 **End Session:** Clear current roleplay\n"
            "🌙 **Ongoing Character:** View current character info\n\n"
            "Just type to interact naturally with your character!"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    elif text == "✨ Manifest New":
        await update.message.reply_text(
            "✨ Opening the gateway to manifest a new reality...",
            reply_markup=get_start_keyboard()
        )
        return

    # ========================================
    # NORMAL ROLEPLAY MESSAGE
    # ========================================

    if user_id not in user_sessions:
        await update.message.reply_text(
            "🌙 Please use /start to manifest a character first!",
            reply_markup=get_start_keyboard()
        )
        return

    await generate_reply(update, user_id, text)

# ============================================================================
# MAIN BOT INITIALIZATION
# ============================================================================

def main():
    """Initialize and run the bot"""
    logging.info("🌙 Starting HERMAX Roleplay Bot...")

    # Create Telegram application
    application = Application.builder().token(TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    # Start Flask server in background
    Thread(target=run_flask, daemon=True).start()
    logging.info("🌐 Flask server started")

    # Start bot
    logging.info("✅ Bot is running!")
    application.run_polling()

if __name__ == "__main__":
    main()
