"""
HERMAX ROLEPLAY BOT
Integrates: Telegram Bot + Web App + Cerebras AI + Mistral AI + Pollinations Image Generation
Character data loaded from characters.json

Two AI clients:
  client_rp    — CEREBRAS_API_KEY    — RP text generation (llama3.1-8b)
  client_img   — MISTRAL_API_KEY     — keyword extraction via Mistral agent (parallel)

Image triggers:
  Preloaded characters : message 3, 7, then 30% random (max 6 per 20)
  Custom characters    : message 1, 3, 7, then 30% random (max 6 per 20)
"""

import os
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
CEREBRAS_KEY     = os.getenv("CEREBRAS_API_KEY")
MISTRAL_KEY      = os.getenv("MISTRAL_API_KEY")
POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")
WEBAPP_URL       = "https://usage217-tech.github.io/Mytho-rp/"
RP_MODEL         = "llama3.1-8b"
MISTRAL_AGENT_ID = "ag_019c85bbf8f277ffafe698fe45909ac4"

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
# INITIALIZE SERVICES — TWO SEPARATE GROK CLIENTS
# ============================================================================

client_rp  = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY)
client_img = Mistral(api_key=MISTRAL_KEY)
app        = Flask(__name__)
user_sessions = {}

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
# IMAGE GENERATION — 720x720, klein model, enhance=true
# ============================================================================

def build_image_prompt(scene_keywords, char_name):
    style  = "Anime" if is_anime(char_name) else "Realistic"
    prompt = f"{style} style. {scene_keywords}. Using the reference image."
    logging.info(f"🖼️ Image prompt: {prompt}")
    return prompt

def generate_scene_image(scene_keywords, char_name, reference_image_url=None):
    try:
        encoded_prompt = quote(build_image_prompt(scene_keywords, char_name))
        seed           = random.randint(0, 999999)

        base_url = f"https://gen.pollinations.ai/image/{encoded_prompt}"
        params   = [
            "model=klein",
            "width=720",
            "height=720",
            f"seed={seed}",
            "enhance=true",
            f"key={POLLINATIONS_KEY}"
        ]

        if reference_image_url:
            params.append(f"image={quote(reference_image_url)}")
            logging.info(f"🔗 Reference: {reference_image_url[:60]}...")

        final_url = base_url + "?" + "&".join(params)
        response  = requests.get(final_url, timeout=45)

        if response.status_code == 200:
            logging.info("✅ Image generated successfully")
            return (BytesIO(response.content), final_url)
        else:
            logging.error(f"❌ Image failed: HTTP {response.status_code}")
            return (None, None)

    except Exception as e:
        logging.error(f"❌ Image error: {e}")
        return (None, None)

# ============================================================================
# KEYWORD EXTRACTOR — client_img (separate key), last 5 messages context
# ============================================================================

async def get_scene_keywords(recent_messages, char_name):
    """
    Fires in PARALLEL with RP reply using Mistral agent.
    Reads last 5 messages for full scene context.
    Outputs exactly 6 comma-separated visual phrases.
    """
    try:
        context = "\n".join([
            f"{m['role'].upper()}: {m['content']}"
            for m in recent_messages[-5:]
            if m['role'] != 'system'
        ])

        prompt = (
            f"You are a visual scene extractor for image generation.\n\n"
            f"Read these recent roleplay messages carefully:\n\n"
            f"{context}\n\n"
            f"Extract exactly 6 comma-separated words or short phrases describing:\n"
            f"- The background and location\n"
            f"- The lighting and atmosphere\n"
            f"- What {char_name} is doing or expressing ALONE\n\n"
            f"STRICT RULES:\n"
            f"- No interaction words (kissing, touching, holding, teaching)\n"
            f"- No second person (you, your, together, each other)\n"
            f"- Character actions must be solo only (finger in mouth, hands on hips, playful smirk)\n"
            f"- No emotion words (passionate, desire) — show through pose/expression instead\n\n"
            f"GOOD: moonlit garden, ivy wall, silver light, finger in mouth, playful gaze\n"
            f"GOOD: swimming pool, bright lights, playful smirk, hands on hips\n"
            f"BAD: kissing, holding you, passionate, together, touching each other\n\n"
            f"Output exactly 6 comma-separated phrases. Nothing else."
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client_img.beta.conversations.start(
                agent_id=MISTRAL_AGENT_ID,
                inputs=[{"role": "user", "content": prompt}]
            )
        )

        # Extract text from Mistral response
        keywords = ""
        for output in response.outputs:
            if hasattr(output, 'content'):
                for block in output.content:
                    if hasattr(block, 'text'):
                        keywords = block.text.strip().replace('"', '').replace("'", '')
                        break
            if keywords:
                break

        logging.info(f"📝 Keywords: {keywords}")
        return keywords if keywords else None

    except Exception as e:
        logging.error(f"❌ Keyword error: {e}")
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
    return "🌙 HERMAX Roleplay Engine — Online"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# ============================================================================
# /start
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌙 *HERMAX* 🌑\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✨ _The veil between worlds grows thin._\n\n"
        "A realm of whispers, desire, and mystery awaits you. "
        "Choose your companion. Set the scene. "
        "Let the story write itself.\n\n"
        "💫 _Tap below to begin your journey..._",
        reply_markup=start_keyboard(),
        parse_mode="Markdown"
    )

# ============================================================================
# WEB APP HANDLER — MANIFEST
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

        char_data    = get_char(char_name)
        is_preloaded = char_data is not None

        reference_image = char_data["image"] if is_preloaded else char_image
        char_video      = char_data.get("video", "") if is_preloaded else ""

        logging.info(f"🎭 {char_name} | {user_name} | preloaded={is_preloaded}")

        # ── Build system prompt ──────────────────────────────────────
        if is_preloaded:
            system_prompt = char_data['prompt'].format(
                user_name=user_name,
                user_gender=user_gender,
                scenario=scenario
            )
        else:
            system_prompt = (
                "You are {char_name}.\n"
                "Personality and appearance: {char_desc}\n"
                "You are talking with {user_name} ({user_gender}).\n\n"
                "Write exactly like a real human — natural, casual, never robotic.\n"
                "Match the user's energy and reply length.\n"
                "Actions go inline with *asterisks*.\n"
                "Never write for the user. Never break character.\n"
                "Always end with a small hook — a question, an action, a look.\n"
                "Only escalate if user clearly leads.\n\n"
                "Scenario: {scenario}"
            ).format(
                char_name=char_name,
                char_desc=char_desc,
                user_name=user_name,
                user_gender=user_gender,
                scenario=scenario
            )

        user_sessions[user_id] = {
            "history":          [{"role": "system", "content": system_prompt}],
            "char_name":        char_name,
            "char_desc":        char_data.get("desc", "") if is_preloaded else char_desc,
            "scenario":         scenario,
            "reference_image":  reference_image,
            "is_preloaded":     is_preloaded,
            "message_count":    0,
            "images_generated": 0,
            "last_20_messages": 0
        }

        session = user_sessions[user_id]

        # ── Step 1: Intro video ──────────────────────────────────────
        if char_video:
            try:
                await update.message.reply_animation(
                    animation=char_video,
                    caption=f"✨ *{char_name}* stirs from the shadows...",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"❌ Video error: {e}")

        # ── Step 2: First AI reply ───────────────────────────────────
        session["history"].append({
            "role": "user",
            "content": f"[SCENARIO]: {scenario}\n\nBegin the roleplay as {char_name}. Set the scene and make your first move."
        })

        response = client_rp.chat.completions.create(
            model=RP_MODEL,
            messages=session["history"],
            temperature=0.85,
            max_tokens=95
        )

        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})

        # ── Step 3: Cinematic reveal card ────────────────────────────
        char_desc_short = char_data.get("desc", "") if is_preloaded else char_desc
        reveal_text = (
            f"🌑 *A presence awakens...*\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"✦ *{char_name}*\n"
            f"_{char_desc_short}_\n\n"
            f"📖 *Scene:*\n_{scenario}_\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💫 _The story begins..._"
        )

        # ── Step 4: Send reveal photo + card ────────────────────────
        if is_preloaded:
            await update.message.reply_photo(
                photo=reference_image,
                caption=reveal_text,
                parse_mode="Markdown"
            )
        else:
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
                    caption=reveal_text,
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(reveal_text, parse_mode="Markdown")

        # ── Step 5: AI opening reply with keyboard ───────────────────
        await update.message.reply_text(
            ai_reply,
            reply_markup=utility_keyboard(),
            parse_mode="Markdown"
        )

        session["message_count"]    = 1
        session["images_generated"] = 1

    except Exception as e:
        logging.error(f"❌ Manifest error: {e}")
        await update.message.reply_text(
            "🌑 _The gateway flickered... something went wrong._\n"
            "Please try again or tap *Begin Your Story*.",
            parse_mode="Markdown",
            reply_markup=start_keyboard()
        )

# ============================================================================
# CORE REPLY GENERATOR — PARALLEL GROK CALLS WHEN IMAGE TRIGGERS
# ============================================================================

async def generate_reply(update, user_id, input_text):
    session = user_sessions[user_id]
    wrapped = f"-{input_text}\n+reply 60-80 words"
    session["history"].append({"role": "user", "content": wrapped})

    try:
        system_msg = session["history"][0]
        recent     = session["history"][1:][-10:]
        trimmed    = [system_msg] + recent

        fire_image = should_generate_image(session)

        if fire_image:
            # ── PARALLEL: both Groks fire simultaneously ─────────────
            logging.info("⚡ Parallel: RP reply + keywords firing together")

            async def get_rp_reply():
                resp = client_rp.chat.completions.create(
                    model=RP_MODEL,
                    messages=trimmed,
                    temperature=0.85,
                    max_tokens=95
                )
                return resp.choices[0].message.content

            async def get_keywords():
                return await get_scene_keywords(recent, session["char_name"])

            ai_reply, keywords = await asyncio.gather(
                get_rp_reply(),
                get_keywords()
            )

            # Update session
            session["history"].append({"role": "assistant", "content": ai_reply})
            session["message_count"]    += 1
            session["last_20_messages"] += 1

            if session["last_20_messages"] >= 20:
                session["images_generated"] = 0
                session["last_20_messages"] = 0
                logging.info("🔄 Image counter reset")

            # Generate image from keywords
            image_bytes = None
            if keywords:
                image_bytes, _ = generate_scene_image(
                    scene_keywords=keywords,
                    char_name=session["char_name"],
                    reference_image_url=session.get("reference_image")
                )
                if image_bytes:
                    session["images_generated"] += 1
                    logging.info(f"✅ Image sent ({session['images_generated']}/6)")

            # Send response
            if image_bytes:
                await update.message.reply_photo(
                    photo=image_bytes,
                    caption=ai_reply,
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(ai_reply, parse_mode="Markdown")

        else:
            # ── SEQUENTIAL: RP only, no image ────────────────────────
            response = client_rp.chat.completions.create(
                model=RP_MODEL,
                messages=trimmed,
                temperature=0.85,
                max_tokens=95
            )
            ai_reply = response.choices[0].message.content
            session["history"].append({"role": "assistant", "content": ai_reply})
            session["message_count"]    += 1
            session["last_20_messages"] += 1

            if session["last_20_messages"] >= 20:
                session["images_generated"] = 0
                session["last_20_messages"] = 0
                logging.info("🔄 Image counter reset")

            await update.message.reply_text(ai_reply, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"❌ Reply error: {e}")
        await update.message.reply_text(
            "🌑 _The void stirs but stays silent..._\n_Try again in a moment._",
            parse_mode="Markdown"
        )

# ============================================================================
# MESSAGE ROUTER
# ============================================================================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text

    # ── End Dream ────────────────────────────────────────────────────
    if text == "🌙 End Dream":
        if user_id in user_sessions:
            char_name = user_sessions[user_id]['char_name']
            count     = user_sessions[user_id]['message_count']
            del user_sessions[user_id]
            await update.message.reply_text(
                f"🌙 *The dream fades...*\n\n"
                f"Your story with *{char_name}* drifts into memory.\n"
                f"_{count} moments shared between you._\n\n"
                f"✨ _Until the next dream begins..._",
                reply_markup=start_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "🌸 _No dream is active right now._\n_Tap below to begin one._",
                reply_markup=start_keyboard(),
                parse_mode="Markdown"
            )
        return

    # ── Current Story ────────────────────────────────────────────────
    elif text == "💭 Current Story":
        if user_id in user_sessions:
            s = user_sessions[user_id]
            await update.message.reply_text(
                f"💭 *Your Current Dream*\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"✦ *Character:* {s['char_name']}\n"
                f"_{s['char_desc']}_\n\n"
                f"📖 *Scene:* _{s['scenario']}_\n\n"
                f"💬 *Moments shared:* {s['message_count']}\n"
                f"━━━━━━━━━━━━━━━━━━",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "🌸 _No dream is active yet._\nTap *Begin Your Story* to start. ✨",
                reply_markup=start_keyboard(),
                parse_mode="Markdown"
            )
        return

    # ── Who Am I ─────────────────────────────────────────────────────
    elif text == "🎭 Who Am I?":
        await update.message.reply_text(
            "🎭 *HERMAX Roleplay*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✦ _An immersive AI roleplay experience_\n\n"
            "✨ *Begin Your Story* — Open the character portal\n"
            "💭 *Current Story* — View your active dream\n"
            "🌙 *End Dream* — Close the current session\n"
            "🌸 *New Story* — Start a fresh adventure\n\n"
            "💫 _Just type naturally to talk with your character._\n"
            "━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )
        return

    # ── How It Works ─────────────────────────────────────────────────
    elif text == "🌸 How It Works":
        await update.message.reply_text(
            "🌸 *How HERMAX Works*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Tap *Begin Your Story*\n"
            "_Choose your character, set the scene_\n\n"
            "2️⃣ _The story awakens_\n"
            "_Your character appears, the dream begins_\n\n"
            "3️⃣ _Just... talk_\n"
            "_Type naturally. The character responds._\n\n"
            "✨ _Images appear as your story deepens._\n"
            "━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )
        return

    # ── New Story ────────────────────────────────────────────────────
    elif text == "🌸 New Story":
        if user_id in user_sessions:
            del user_sessions[user_id]
        await update.message.reply_text(
            "✨ _Opening the gateway to a new dream..._",
            reply_markup=start_keyboard(),
            parse_mode="Markdown"
        )
        return

    # ── No active session ────────────────────────────────────────────
    if user_id not in user_sessions:
        await update.message.reply_text(
            "🌙 _No dream is active yet._\n\n"
            "Tap *Begin Your Story* to choose your character and begin. ✨",
            reply_markup=start_keyboard(),
            parse_mode="Markdown"
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
