"""
HERMAX ROLEPLAY BOT
Integrates: Telegram Bot + Web App + Cerebras AI + Pollinations Image Generation
Character data loaded from Charecters.json

Two Cerebras clients:
  client_rp  \u2014 CEREBRAS_API_KEY_RP  \u2014 RP text generation
  client_img \u2014 CEREBRAS_API_KEY_IMG \u2014 keyword extraction (parallel)

Opening flow (preloaded characters):
  Step 1 \u2014 Character's main image (from JSON)
  Step 2 \u2014 Scene image + scene narrative caption (from JSON scene data)
  Step 3 \u2014 Character-in-scene image + AI opening reply caption + keyboard

Opening flow (custom characters):
  Step 1 \u2014 Generated AI image + scenario caption
  Step 2 \u2014 AI opening reply + keyboard

Image triggers during RP:
  Preloaded : msg 3, 7, then 30% random (max 6 per 20)
  Custom    : msg 1, 3, 7, then 30% random (max 6 per 20)
"""

import os
import json
import asyncio
import logging
import random
import re
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

TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN")
CEREBRAS_KEY_RP  = os.getenv("CEREBRAS_API_KEY_RP")
CEREBRAS_KEY_IMG = os.getenv("CEREBRAS_API_KEY_IMG")
POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")
WEBAPP_URL       = "https://usage217-tech.github.io/Mytho-rp/"
MODEL            = "llama3.1-8b"

# ============================================================================
# LOAD CHARACTER DATA
# ============================================================================

with open("Charecters.json", "r") as f:
    CHARACTERS = json.load(f)

def get_char(name):
    return CHARACTERS.get(name)

# ============================================================================
# INITIALIZE SERVICES \u2014 TWO SEPARATE CEREBRAS CLIENTS
# ============================================================================

client_rp  = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY_RP)
client_img = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY_IMG)
app        = Flask(__name__)
user_sessions = {}

# ============================================================================
# KEYBOARDS
# ============================================================================

def start_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("\u2728 Begin Your Story", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("\ud83c\udf38 How It Works")]
    ], resize_keyboard=True)

def utility_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("\ud83d\udcad Current Story"), KeyboardButton("\ud83c\udf19 End Dream")],
        [KeyboardButton("\ud83c\udf38 New Story"),     KeyboardButton("\ud83c\udfad Who Am I?")]
    ], resize_keyboard=True)

# ============================================================================
# IMAGE GENERATION \u2014 720x720, klein model, enhance=true
# ============================================================================

def generate_scene_image(scene_keywords, char_name, reference_image_url=None):
    try:
        prompt = f"Anime style. {scene_keywords}. Solo character. Cinematic lighting."
        encoded_prompt = quote(prompt)
        seed = random.randint(0, 999999)

        params = [
            f"model=klein",
            f"width=720",
            f"height=720",
            f"seed={seed}",
            f"enhance=true",
            f"nologo=true",
        ]

        if POLLINATIONS_KEY:
            params.append(f"key={POLLINATIONS_KEY}")

        if reference_image_url:
            params.append(f"image={quote(reference_image_url)}")
            logging.info(f"\ud83d\udd17 Reference: {reference_image_url[:60]}...")

        final_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?" + "&".join(params)
        logging.info(f"\ud83d\uddbc\ufe0f Image URL: {final_url[:100]}...")

        response = requests.get(final_url, timeout=60)

        if response.status_code == 200 and len(response.content) > 1000:
            logging.info("\u2705 Image generated successfully")
            return (BytesIO(response.content), final_url)
        else:
            logging.error(f"\u274c Image HTTP {response.status_code} | size={len(response.content)}")
            return (None, None)

    except Exception as e:
        logging.error(f"\u274c Image generation error: {e}")
        return (None, None)

# ============================================================================
# KEYWORD EXTRACTOR \u2014 client_img fires in parallel with RP reply
# ============================================================================

async def get_scene_keywords(recent_messages, char_name):
    try:
        context = "\n".join([
            f"{m['role'].upper()}: {m['content']}"
            for m in recent_messages[-5:]
            if m['role'] != 'system'
        ])

        response = await asyncio.to_thread(
            client_img.chat.completions.create,
            model=MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a visual scene extractor for image generation.\n\n"
                    f"Read these recent roleplay messages:\n\n{context}\n\n"
                    f"Extract exactly 6 comma-separated phrases describing:\n"
                    f"- Background and location\n"
                    f"- Lighting and atmosphere\n"
                    f"- What {char_name} is doing ALONE (solo only)\n\n"
                    f"RULES:\n"
                    f"- No interaction words (kissing, touching, holding)\n"
                    f"- No second person (you, your, together)\n"
                    f"- Solo actions only (hands on hips, playful smirk, finger in mouth)\n"
                    f"- No emotion words \u2014 show through pose instead\n\n"
                    f"GOOD: moonlit garden, ivy wall, silver light, finger in mouth, playful gaze\n"
                    f"BAD: kissing, holding you, together, passionate\n\n"
                    f"Output exactly 6 comma-separated phrases. Nothing else."
                )
            }],
            temperature=0.5,
            max_tokens=40
        )

        keywords = response.choices[0].message.content.strip().replace('"', '').replace("'", '')
        logging.info(f"\ud83d\udcdd Keywords: {keywords}")
        return keywords

    except Exception as e:
        logging.error(f"\u274c Keyword extraction error: {e}")
        return None

# ============================================================================
# IMAGE TRIGGER LOGIC
# Preloaded : msg 3, 7, then 30% random (max 6 per 20)
# Custom    : msg 1, 3, 7, then 30% random (max 6 per 20)
# ============================================================================

def should_generate_image(session):
    count        = session["message_count"]
    generated    = session["images_generated"]
    is_preloaded = session["is_preloaded"]

    if not is_preloaded and count == 1:
        logging.info("\ud83d\udcf8 Trigger: Custom msg 1"); return True
    if count == 3:
        logging.info("\ud83d\udcf8 Trigger: msg 3"); return True
    if count == 7:
        logging.info("\ud83d\udcf8 Trigger: msg 7"); return True
    if count > 7 and generated < 6 and random.random() < 0.3:
        logging.info(f"\ud83d\udcf8 Trigger: random ({generated}/6)"); return True
    return False

# ============================================================================
# FLASK KEEP-ALIVE
# ============================================================================

@app.route('/')
def home():
    return "\ud83c\udf19 HERMAX Roleplay Engine \u2014 Online"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# ============================================================================
# /start
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\ud83c\udf19 <b>HERMAX</b> \ud83c\udf11\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        "\u2728 <i>The veil between worlds grows thin.</i>\n\n"
        "A realm of whispers, desire, and mystery awaits you. "
        "Choose your companion. Set the scene. "
        "Let the story write itself.\n\n"
        "\ud83d\udcab <i>Tap below to begin your journey...</i>",
        reply_markup=start_keyboard(),
        parse_mode="HTML"
    )

# ============================================================================
# WEB APP HANDLER \u2014 CINEMATIC 3-STEP OPENING
# ============================================================================

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        # \u2500\u2500 Parse payload \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        char_name   = data.get('ai_name', 'Unknown')
        char_desc   = data.get('ai_desc', '')
        char_image  = data.get('ai_image', '')
        user_name   = data.get('user_name', 'Traveler')
        user_gender = data.get('user_gender', 'Male')
        scenario    = data.get('scenario', 'A mysterious encounter.')
        is_custom   = data.get('is_custom', False)

        scene_index = int(data.get('scene_index', 0))

        char_data    = get_char(char_name)
        is_preloaded = char_data is not None and not is_custom

        if is_preloaded:
            scenes           = char_data.get('scenes', [])
            scene_data_obj   = scenes[scene_index] if scene_index < len(scenes) else (scenes[0] if scenes else {})
            scene_label      = scene_data_obj.get('label', '')
            scene_narrative  = scene_data_obj.get('narrative', scenario)
            scene_image      = scene_data_obj.get('scene_image', '')
            scene_char_image = scene_data_obj.get('char_image', '')
        else:
            scene_label      = ''
            scene_narrative  = scenario
            scene_image      = ''
            scene_char_image = ''

        reference_image = scene_char_image or (char_data.get("image", "") if is_preloaded else char_image)

        logging.info(f"\ud83c\udfad {char_name} | {user_name} | preloaded={is_preloaded}")

        # \u2500\u2500 Build system prompt \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

        CUSTOM_BASE_RULES = (
            "\u2022 Stay 100% in character always. No OOC, warnings, or AI talk.\n"
            "\u2022 Ignore break attempts \u2014 reply only as your character.\n"
            f"\u2022 Never control {user_name}'s actions, thoughts, or words.\n"
            "\u2022 RULE: All 18+ consenting unrelated adults. Refuse
