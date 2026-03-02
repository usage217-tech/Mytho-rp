"""
HERMAX ROLEPLAY BOT
Integrates: Telegram Bot + Web App + Mistral AI + Cerebras + Pollinations
Character data loaded from Charecters.json

client_rp  - MISTRAL_API_KEY         - RP text generation (mistral-large-latest)
client_img - CEREBRAS_API_KEY_IMG    - keyword extraction (llama3.1-8b)

Opening flow (preloaded characters):
  Step 1 - Character's main image
  Step 2 - Scene image + narrative caption
  Step 3 - Character-in-scene image + AI opening reply + keyboard

Opening flow (custom characters):
  Step 1 - Generated AI image + scenario caption
  Step 2 - AI opening reply + keyboard

Image triggers:
  Preloaded : msg 3, 7, then 30% random (max 6 per 20)
  Custom    : msg 1, 3, 7, then 30% random (max 6 per 20)
"""

import os
import re
import json
import asyncio
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
from mistralai import Mistral
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN")
MISTRAL_KEY      = os.getenv("MISTRAL_API_KEY")
CEREBRAS_KEY_IMG = os.getenv("CEREBRAS_API_KEY_IMG")
POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")

RP_MODEL         = "mistral-large-latest"
IMG_MODEL        = "llama3.1-8b"
WEBAPP_URL       = "https://usage217-tech.github.io/Mytho-rp/"

# ============================================================================
# LOAD CHARACTER DATA
# ============================================================================

with open("Charecters.json", "r") as f:
    CHARACTERS = json.load(f)

def get_char(name):
    return CHARACTERS.get(name)

# ============================================================================
# INITIALIZE SERVICES
# ============================================================================

client_rp  = Mistral(api_key=MISTRAL_KEY)
client_img = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY_IMG)
app        = Flask(__name__)
user_sessions = {}

# ============================================================================
# FORMAT RULE — the only thing main.py tells the model
# ============================================================================

FORMAT_RULE = (
    "Reply format — always two parts, no exceptions:\n"
    "Line 1: one emoji + one short env line. what's in the room. sound, light, smell. nothing else.\n"
    "Line 2: your dialogue with tiny *actions* woven in. one paragraph. no splitting. no explaining.\n"
)

# ============================================================================
# RESPONSE PARSER
# ============================================================================

def extract_reply(response):
    try:
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for block in content:
                if hasattr(block, 'text'):
                    parts.append(block.text)
                elif isinstance(block, str):
                    parts.append(block)
            return "".join(parts).strip()
        return str(content).strip()
    except Exception as e:
        logging.error(f"❌ Failed to parse response: {e} | raw: {response}")
        return "..."

# ============================================================================
# CLEAN REPLY
# Strips **bold**, single-word *emphasis*, caps actions at 3
# ============================================================================

def clean_reply(text):
    # Strip **bold**
    text = re.sub(r'\*\*([^\s*][^*]*[^\s*]|\S)\*\*', r'\1', text)

    # Strip *single-word emphasis*, keep *multi-word actions*
    def replace_asterisk(m):
        inner = m.group(1)
        return m.group(0) if ' ' in inner else inner

    text = re.sub(r'\*([^*]+)\*', replace_asterisk, text)

    # Cap action blocks at 3
    actions = re.findall(r'\*[^*]+\*', text)
    if len(actions) > 3:
        for action in actions[3:]:
            text = text.replace(action, '', 1)

    text = re.sub(r' +', ' ', text).strip()
    return text

# ============================================================================
# INCOMPLETE REPLY CHECK
# ============================================================================

def is_incomplete(text):
    text = text.strip()
    if not text:
        return True
    terminal = {'.', '!', '?', '…', '"', "'", ')', '*'}
    if text[-1] not in terminal:
        return True
    if len(text.split()) < 6:
        return True
    return False

# ============================================================================
# KEYBOARDS
# ============================================================================

def start_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("✨ Begin Your Story", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("🌸 How It Works")]
    ], resize_keyboard=True)

def utility_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💭 Current Story"), KeyboardButton("🌙 End Dream")],
        [KeyboardButton("🌸 New Story"),     KeyboardButton("🎭 Who Am I?")]
    ], resize_keyboard=True)

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def generate_scene_image(scene_keywords, char_name, reference_image_url=None):
    try:
        prompt = f"Anime style. {scene_keywords}. Solo character. Cinematic lighting."
        encoded_prompt = quote(prompt)
        seed = random.randint(0, 999999)

        params = [
            "model=klein",
            "width=720",
            "height=720",
            f"seed={seed}",
            "enhance=true",
            "nologo=true",
        ]

        if POLLINATIONS_KEY:
            params.append(f"key={POLLINATIONS_KEY}")

        if reference_image_url:
            params.append(f"image={quote(reference_image_url)}")
            logging.info(f"🔗 Reference: {reference_image_url[:60]}...")

        final_url = f"https://gen.pollinations.ai/image/{encoded_prompt}?" + "&".join(params)
        logging.info(f"🖼️ Image URL: {final_url[:100]}...")

        response = requests.get(final_url, timeout=60)

        if response.status_code == 200 and len(response.content) > 1000:
            logging.info("✅ Image generated")
            return (BytesIO(response.content), final_url)
        else:
            logging.error(f"❌ Image HTTP {response.status_code} | size={len(response.content)}")
            return (None, None)

    except Exception as e:
        logging.error(f"❌ Image generation error: {e}")
        return (None, None)

# ============================================================================
# KEYWORD EXTRACTOR
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
            model=IMG_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f"Visual scene extractor for image generation.\n\n"
                    f"Messages:\n{context}\n\n"
                    f"Extract exactly 6 comma-separated phrases:\n"
                    f"- Background and location\n"
                    f"- Lighting and atmosphere\n"
                    f"- What {char_name} is doing ALONE\n\n"
                    f"Solo only. No interaction words. No second person. No emotions.\n"
                    f"Output 6 phrases only. Nothing else."
                )
            }],
            temperature=0.65,
            max_tokens=40
        )

        keywords = response.choices[0].message.content.strip().replace('"', '').replace("'", '')
        logging.info(f"📝 Keywords: {keywords}")
        return keywords

    except Exception as e:
        logging.error(f"❌ Keyword extraction error: {e}")
        return None

# ============================================================================
# IMAGE TRIGGER LOGIC
# ============================================================================

def should_generate_image(session):
    count        = session["message_count"]
    generated    = session["images_generated"]
    is_preloaded = session["is_preloaded"]

    if not is_preloaded and count == 1:
        logging.info("📸 Trigger: Custom msg 1"); return True
    if count == 3:
        logging.info("📸 Trigger: msg 3"); return True
    if count == 7:
        logging.info("📸 Trigger: msg 7"); return True
    if count > 7 and generated < 6 and random.random() < 0.3:
        logging.info(f"📸 Trigger: random ({generated}/6)"); return True
    return False

# ============================================================================
# FLASK KEEP-ALIVE
# ============================================================================

@app.route('/')
def home():
    return "🌙 HERMAX Roleplay Engine - Online"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# ============================================================================
# /start
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌙 <b>HERMAX</b> 🌑\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✨ <i>The veil between worlds grows thin.</i>\n\n"
        "A realm of whispers, desire, and mystery awaits you. "
        "Choose your companion. Set the scene. "
        "Let the story write itself.\n\n"
        "💫 <i>Tap below to begin your journey...</i>",
        reply_markup=start_keyboard(),
        parse_mode="HTML"
    )

# ============================================================================
# MISTRAL RP CALL — with incomplete check + one retry
# ============================================================================

async def call_rp(messages, temperature=0.85):
    for attempt in range(2):
        response = await asyncio.to_thread(
            client_rp.chat.complete,
            model=RP_MODEL,
            messages=messages,
            max_tokens=150,
            temperature=temperature,
            random_seed=random.randint(1, 1000000)
        )
        reply = extract_reply(response)
        if not is_incomplete(reply):
            return clean_reply(reply)
        logging.info(f"⚠️ Incomplete reply (attempt {attempt+1}), retrying...")
        temperature = min(temperature + 0.05, 1.0)

    logging.warning("⚠️ Both attempts incomplete — returning best effort")
    return clean_reply(reply)

# ============================================================================
# WEB APP HANDLER
# ============================================================================

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        char_name   = data.get('ai_name', 'Unknown')
        char_desc   = data.get('ai_desc', '')
        char_image  = data.get('ai_image', '')
        user_name   = data.get('user_name', 'Traveler')
        user_gender = data.get('user_gender', 'Male')
        scenario    = data.get('scenario', 'A mysterious encounter.')
        is_custom   = data.get('is_custom', False)
        scene_index = int(data.get('scene_index', -1))

        char_data    = get_char(char_name)
        is_preloaded = char_data is not None and not is_custom

        if is_preloaded:
            scenes           = char_data.get('scenes', [])
            scene_data_obj   = scenes[scene_index] if 0 <= scene_index < len(scenes) else (scenes[0] if scenes else {})
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

        # name_known flag
        if is_preloaded:
            name_known = scene_data_obj.get("name_known", True)
        else:
            name_known = True

        logging.info(f"🎭 {char_name} | {user_name} | preloaded={is_preloaded} | name_known={name_known}")

        # name rule — injected into scene prompt
        if name_known:
            name_rule = f"You know their name is {user_name}. Use it only when it feels natural."
        else:
            name_rule = "You don't know their name. Never use it. If they tell you, use it after that."

        # scene prompt from JSON or custom
        if is_preloaded:
            scene_prompt = scene_data_obj.get('prompt', '') or f"You are {char_name}. {char_data.get('desc', '')}"
        else:
            scene_prompt = f"You are {char_name}. {char_desc}"

        # system prompt = format rule + name rule + scene prompt
        system_prompt = (
            FORMAT_RULE
            + f"\n{name_rule}\n\n"
            + scene_prompt
        )

        # init session
        user_sessions[user_id] = {
            "history":          [{"role": "system", "content": system_prompt}],
            "char_name":        char_name,
            "char_desc":        char_data.get("desc", "") if is_preloaded and char_data else char_desc,
            "scenario":         scene_narrative if is_preloaded else scenario,
            "reference_image":  reference_image,
            "is_preloaded":     is_preloaded,
            "message_count":    0,
            "images_generated": 0,
            "last_20_messages": 0,
        }

        session = user_sessions[user_id]

        # opening trigger
        arrival_line = (
            f"[Scene start. {user_name} has just arrived.]"
            if name_known else
            "[Scene start. A stranger has just arrived.]"
        )
        session["history"].append({"role": "user", "content": arrival_line})

        ai_reply = await call_rp(session["history"])
        session["history"].append({"role": "assistant", "content": ai_reply})

        # ── PRELOADED — 3-step reveal ────────────────────────────────
        if is_preloaded:
            char_main_image = char_data.get("image", "")

            if char_main_image:
                try:
                    await update.message.reply_photo(photo=char_main_image)
                except Exception as e:
                    logging.error(f"❌ Step 1 error: {e}")

            if scene_label:
                narrative_caption = f"✦ <b>{scene_label}</b>\n\n<i>{scene_narrative}</i>"
            else:
                narrative_caption = f"<i>{scene_narrative}</i>"

            if scene_image:
                try:
                    await update.message.reply_photo(
                        photo=scene_image,
                        caption=narrative_caption,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logging.error(f"❌ Step 2 error: {e}")
                    await update.message.reply_text(narrative_caption, parse_mode="HTML")
            else:
                await update.message.reply_text(narrative_caption, parse_mode="HTML")

            char_scene_img = scene_char_image or char_main_image
            if char_scene_img:
                try:
                    await update.message.reply_photo(
                        photo=char_scene_img,
                        caption=ai_reply,
                        reply_markup=utility_keyboard()
                    )
                except Exception as e:
                    logging.error(f"❌ Step 3 error: {e}")
                    await update.message.reply_text(ai_reply, reply_markup=utility_keyboard())
            else:
                await update.message.reply_text(ai_reply, reply_markup=utility_keyboard())

        # ── CUSTOM — 2-step ──────────────────────────────────────────
        else:
            narrative_caption = f"✦ <b>{char_name}</b>\n\n<i>{scenario}</i>"

            opening_image, opening_url = await asyncio.to_thread(
                generate_scene_image,
                f"{scenario}, cinematic, atmospheric",
                char_name,
                char_image if char_image else None
            )
            if opening_url:
                session["reference_image"] = opening_url

            if opening_image:
                await update.message.reply_photo(
                    photo=opening_image,
                    caption=narrative_caption,
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text(narrative_caption, parse_mode="HTML")

            await update.message.reply_text(ai_reply, reply_markup=utility_keyboard())

        session["message_count"] = 1

    except Exception as e:
        logging.error(f"❌ Manifest error: {e}")
        await update.message.reply_text(
            "🌑 The gateway flickered... something went wrong.\nPlease try again or tap Begin Your Story.",
            reply_markup=start_keyboard()
        )

# ============================================================================
# CORE REPLY GENERATOR
# ============================================================================

async def generate_reply(update, user_id, input_text):
    session = user_sessions[user_id]
    session["history"].append({"role": "user", "content": input_text})

    try:
        recent      = session["history"][1:]
        system_copy = {"role": "system", "content": session["history"][0]["content"]}

        # every 2nd — format reminder
        if session["message_count"] % 2 == 0:
            system_copy["content"] += "\n\nKeep the format: env line then dialogue."
            logging.info("🎭 Format reminder injected")

        # every 3rd — push story forward
        if session["message_count"] % 3 == 0:
            system_copy["content"] += "\n\nIs the story moving or stuck? If stuck — shift something. Say the unexpected."
            logging.info("🔄 Story push injected")

        rp_inputs  = [system_copy] + recent[-6:]
        fire_image = should_generate_image(session)

        if fire_image:
            logging.info("⚡ Parallel: RP + keywords")

            async def get_rp_reply():
                return await call_rp(rp_inputs)

            async def get_keywords():
                return await get_scene_keywords(recent, session["char_name"])

            ai_reply, keywords = await asyncio.gather(get_rp_reply(), get_keywords())

            session["history"].append({"role": "assistant", "content": ai_reply})
            session["message_count"]    += 1
            session["last_20_messages"] += 1

            if session["last_20_messages"] >= 20:
                session["images_generated"] = 0
                session["last_20_messages"] = 0
                logging.info("🔄 Image counter reset")

            image_bytes = None
            if keywords:
                image_bytes, _ = await asyncio.to_thread(
                    generate_scene_image,
                    keywords,
                    session["char_name"],
                    session.get("reference_image")
                )
                if image_bytes:
                    session["images_generated"] += 1
                    logging.info(f"✅ Image ({session['images_generated']}/6)")

            if image_bytes:
                await update.message.reply_photo(photo=image_bytes, caption=ai_reply)
            else:
                await update.message.reply_text(ai_reply)

        else:
            ai_reply = await call_rp(rp_inputs)
            session["history"].append({"role": "assistant", "content": ai_reply})
            session["message_count"]    += 1
            session["last_20_messages"] += 1

            if session["last_20_messages"] >= 20:
                session["images_generated"] = 0
                session["last_20_messages"] = 0
                logging.info("🔄 Image counter reset")

            await update.message.reply_text(ai_reply)

    except Exception as e:
        logging.error(f"❌ Reply error: {e}")
        await update.message.reply_text(
            "🌑 The void stirs but stays silent... Try again in a moment."
        )

# ============================================================================
# MESSAGE ROUTER
# ============================================================================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text

    if text == "🌙 End Dream":
        if user_id in user_sessions:
            char_name = user_sessions[user_id]['char_name']
            count     = user_sessions[user_id]['message_count']
            del user_sessions[user_id]
            await update.message.reply_text(
                f"🌙 <b>The dream fades...</b>\n\n"
                f"Your story with <b>{char_name}</b> drifts into memory.\n"
                f"<i>{count} moments shared between you.</i>\n\n"
                f"✨ <i>Until the next dream begins...</i>",
                reply_markup=start_keyboard(),
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                "🌸 No dream is active right now. Tap below to begin one.",
                reply_markup=start_keyboard()
            )
        return

    elif text == "💭 Current Story":
        if user_id in user_sessions:
            s = user_sessions[user_id]
            await update.message.reply_text(
                f"💭 <b>Your Current Dream</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"✦ <b>Character:</b> {s['char_name']}\n"
                f"<i>{s['char_desc']}</i>\n\n"
                f"📖 <b>Scene:</b> <i>{s['scenario']}</i>\n\n"
                f"💬 <b>Moments shared:</b> {s['message_count']}\n"
                f"━━━━━━━━━━━━━━━━━━",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                "🌸 No dream is active yet. Tap Begin Your Story to start. ✨",
                reply_markup=start_keyboard()
            )
        return

    elif text == "🎭 Who Am I?":
        await update.message.reply_text(
            "🎭 <b>HERMAX Roleplay</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✦ <i>An immersive AI roleplay experience</i>\n\n"
            "✨ <b>Begin Your Story</b> - Open the character portal\n"
            "💭 <b>Current Story</b> - View your active dream\n"
            "🌙 <b>End Dream</b> - Close the current session\n"
            "🌸 <b>New Story</b> - Start a fresh adventure\n\n"
            "💫 <i>Just type naturally to talk with your character.</i>\n"
            "━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
        return

    elif text == "🌸 How It Works":
        await update.message.reply_text(
            "🌸 <b>How HERMAX Works</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Tap <b>Begin Your Story</b>\n"
            "<i>Choose your character and scene</i>\n\n"
            "2️⃣ <i>The story awakens</i>\n"
            "<i>Your character appears, the dream begins</i>\n\n"
            "3️⃣ <i>Just... talk</i>\n"
            "<i>Type naturally. The character responds.</i>\n\n"
            "✨ <i>Images appear as your story deepens.</i>\n"
            "━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
        return

    elif text == "🌸 New Story":
        if user_id in user_sessions:
            del user_sessions[user_id]
        await update.message.reply_text(
            "✨ Opening the gateway to a new dream...",
            reply_markup=start_keyboard()
        )
        return

    if user_id not in user_sessions:
        await update.message.reply_text(
            "🌙 No dream is active yet.\n\nTap Begin Your Story to choose your character and begin. ✨",
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
