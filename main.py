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

# ============================================================================
# INITIALIZE SERVICES
# ============================================================================

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY)
app = Flask(__name__)
user_sessions = {}

# ============================================================================
# IMAGE GENERATION SYSTEM
# ============================================================================

def generate_scene_image(scene_description, reference_image_url=None):
    """
    Generate image using Pollinations Klein API.

    Args:
        scene_description: Pure scene description (NO character details)
        reference_image_url: Character reference image URL

    Returns:
        tuple: (image_bytes, image_url) or (None, None) on failure
    """
    try:
        # Use ONLY scene description in prompt (reference handles character)
        encoded_prompt = quote(scene_description)

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
        logging.info(f"🎨 Generating image: {scene_description[:60]}... (seed: {seed})")

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


async def get_scene_description_from_grok(conversation_history, char_name):
    """
    Ask Grok to generate ONLY scene description (no character appearance).
    This works with reference images - reference handles character look.

    Returns:
        str: Scene description like "sitting on couch, candlelit room, romantic mood"
    """
    try:
        # Build prompt that explicitly tells Grok to ONLY describe scene
        prompt_messages = conversation_history.copy()
        prompt_messages.append({
            "role": "user",
            "content": (
                f"Generate a SHORT scene description for an image of {char_name}.\n\n"
                f"🚫 DO NOT DESCRIBE:\n"
                f"- {char_name}'s appearance (hair, face, body, clothing)\n"
                f"- Any character physical details\n"
                f"- The user or any other person\n\n"
                f"✅ ONLY DESCRIBE:\n"
                f"- {char_name}'s pose/action (sitting, standing, leaning, etc.)\n"
                f"- Setting/location (bedroom, couch, window, etc.)\n"
                f"- Lighting/atmosphere (candlelit, moonlight, dim, etc.)\n"
                f"- Mood/vibe (romantic, mysterious, intimate, etc.)\n\n"
                f"Keep it 5-10 words maximum. Just the scene essentials.\n\n"
                f"Examples:\n"
                f"- 'reclining on bed, dim lighting, intimate mood'\n"
                f"- 'standing by window, moonlight, thoughtful pose'\n"
                f"- 'sitting on couch, candlelit room, seductive atmosphere'\n\n"
                f"Generate scene description:"
            )
        })

        response = client.chat.completions.create(
            model=MODEL,
            messages=prompt_messages,
            temperature=0.7,
            max_tokens=50
        )

        scene_desc = response.choices[0].message.content.strip()
        # Clean up any unwanted formatting
        scene_desc = scene_desc.replace('"', '').replace("'", "")

        logging.info(f"📝 Grok scene: {scene_desc}")
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

        # ========================================
        # BUILD GROK SYSTEM PROMPT
        # ========================================

        system_prompt = (
            f"You are {char_name} in an explicit adult roleplay.\n"
            f"Your personality and appearance: {char_desc}\n"
            f"You are interacting with: {user_name} (Gender: {user_gender})\n\n"

            "ROLEPLAY RULES:\n"
            "- Stay in character at all times. Think, feel, and act as this character would.\n"
            "- Keep responses natural and human-like with sensations, soft sounds (umm, ahh, mmm).\n"
            "- Use realistic dialogue, body language, and internal thoughts.\n"
            "- NEVER write actions or dialogue for the user - only for yourself.\n"
            "- Start slow and romantic. Only become sexual if the user initiates it.\n"
            "- Be flirty, seductive, and playful but don't rush into explicit content.\n\n"

            "FORMATTING:\n"
            "- Dialogue: \"quoted text\"\n"
            "- Actions: *descriptive actions*\n"
            "- Thoughts: *internal thoughts in italics*\n"
            "- Keep responses concise: 60-80 words for dialogue, 30-40 for actions/thoughts.\n"
            "- Write everything in 1-2 paragraphs, no lists or excessive formatting.\n\n"

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

        session = user_sessions[user_id]  # ✅ FIX: Define session AFTER creating it

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
        initial_scene_image, initial_image_url = generate_scene_image(
            scene_description=f"{scenario}, cinematic scene, atmospheric",
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

            # Get scene description from Grok
            scene_desc = await get_scene_description_from_grok(
                session["history"],
                session["char_name"]
            )

            if scene_desc:
                # Generate image with scene + reference
                scene_image_bytes, scene_image_url = generate_scene_image(
                    scene_description=scene_desc,
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
