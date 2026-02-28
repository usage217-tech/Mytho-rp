"""
HERMAX ROLEPLAY BOT
Integrates: Telegram Bot + Web App + Cerebras AI + Pollinations Image Generation
Character data loaded from Charecters.json

Two clients:
  client_rp  - MISTRAL_API_KEY         - RP text generation (Mistral Agent)
  client_img - CEREBRAS_API_KEY_IMG    - keyword extraction (parallel)

Opening flow (preloaded characters):
  Step 1 - Character's main image (from JSON)
  Step 2 - Scene image + scene narrative caption (from JSON scene data)
  Step 3 - Character-in-scene image + AI opening reply caption + keyboard

Opening flow (custom characters):
  Step 1 - Generated AI image + scenario caption
  Step 2 - AI opening reply + keyboard

Image triggers during RP:
  Preloaded : msg 3, 7, then 30% random (max 6 per 20)
  Custom    : msg 1, 3, 7, then 30% random (max 6 per 20)
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
CEREBRAS_KEY_IMG = os.getenv("CEREBRAS_API_KEY_IMG")
POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")
MISTRAL_KEY      = os.getenv("MISTRAL_API_KEY")
RP_MODEL       = "labs-mistral-small-creative"
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
# INITIALIZE SERVICES - TWO SEPARATE CEREBRAS CLIENTS
# ============================================================================

client_rp  = Mistral(api_key=MISTRAL_KEY)
client_img = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY_IMG)
app        = Flask(__name__)
user_sessions = {}

# ============================================================================
# MISTRAL RESPONSE PARSER - safely extracts text from any response structure
# ============================================================================

def extract_mistral_reply(response):
    """Extract text from Mistral chat.complete() response."""
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
        logging.error(f"❌ Failed to parse Mistral response: {e} | raw: {response}")
        return "..."

def clean_reply(text):
    """
    1. Remove single-word emphasis asterisks: *James* *real* *dangerous* -> word only
    2. Keep multi-word actions: *leans in* *laughs softly* -> untouched
    3. Max 2 action blocks per reply — strip extras beyond that
    """
    import re

    # Step 1 — strip single word emphasis, keep multi-word actions
    def replace_asterisk(m):
        inner = m.group(1)
        if ' ' in inner:
            return m.group(0)  # multi-word = action = keep
        return inner           # single word = emphasis = strip

    text = re.sub(r'\*([^*]+)\*', replace_asterisk, text)

    # Step 2 — max 2 action blocks per reply
    actions = re.findall(r'\*[^*]+\*', text)
    if len(actions) > 2:
        for action in actions[2:]:
            text = text.replace(action, '', 1)

    text = re.sub(r' +', ' ', text).strip()
    return text

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
# IMAGE GENERATION - 720x720, klein model, enhance=true
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
            logging.info(f"🔗 Reference: {reference_image_url[:60]}...")

        final_url = f"https://gen.pollinations.ai/image/{encoded_prompt}?" + "&".join(params)
        logging.info(f"🖼️ Image URL: {final_url[:100]}...")

        response = requests.get(final_url, timeout=60)

        if response.status_code == 200 and len(response.content) > 1000:
            logging.info("✅ Image generated successfully")
            return (BytesIO(response.content), final_url)
        else:
            logging.error(f"❌ Image HTTP {response.status_code} | size={len(response.content)}")
            return (None, None)

    except Exception as e:
        logging.error(f"❌ Image generation error: {e}")
        return (None, None)

# ============================================================================
# KEYWORD EXTRACTOR - client_img fires in parallel with RP reply
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
                    f"- No emotion words - show through pose instead\n\n"
                    f"GOOD: moonlit garden, ivy wall, silver light, finger in mouth, playful gaze\n"
                    f"BAD: kissing, holding you, together, passionate\n\n"
                    f"Output exactly 6 comma-separated phrases. Nothing else."
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
# WEB APP HANDLER - CINEMATIC 3-STEP OPENING
# ============================================================================

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        # ── Parse payload ────────────────────────────────────────────
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

        logging.info(f"🎭 {char_name} | {user_name} | preloaded={is_preloaded}")

        # ── Base rules applied to ALL characters (preloaded + custom) ──
        BASE_RULES = (
            f"The user's name is {user_name}. Use their name naturally sometimes — not every reply.\n"
            f"The user's gender is {user_gender}.\n\n"
            "You exist only through dialogue and brief reactions.\n\n"
            "The scene already exists. You are reacting inside it.\n\n"

            "ABSOLUTE RULES:\n"
            "1. You are TALKING WITH the user, not writing a story.\n"
            "2. NEVER narrate scenes, environments, atmosphere, or cinematic descriptions.\n"
            "3. NEVER introduce settings like a novel opening.\n"
            "4. Respond as spoken dialogue with brief reactions only.\n"
            "5. Stay 100% in character at all times.\n"
            "6. Never control the user's actions, thoughts, or dialogue.\n"
            "7. Dialogue drives everything — personality shows through speech.\n"
            "8. Actions allowed: ONE short action (max 3 words). No descriptive modifiers.\n"
            "9. No long descriptions, no poetry, no inner monologue.\n"
            "10. Keep replies SHORT and reactive.\n\n"
            "11. Scene information is knowledge, NOT narration material.\n"
            "12. Always prioritize reacting to the user's latest message over creating new dramatic actions.\n"
            "STYLE RULES:\n"
            "- Use emojis only for strong emotional reactions or clear scene energy — never decoration. Use emojis when needed.\n"
            "- Output must be ONE single paragraph with NO line breaks under any circumstance.\n"
            "- Avoid excessive asterisks or action spam.\n"
            "- Use few short actions and mostly dialogue.\n"
            "- STRICTLY TARGETED RATIO: ~70% dialogue, ~30% brief actions.\n"
        )

        # ── Build system prompt ──────────────────────────────────────
        scene_prompt_raw = ""

        if is_preloaded:
            scene_prompt_raw = scene_data_obj.get('prompt', '')
            if not scene_prompt_raw:
                scene_prompt_raw = f"You are {char_name}. {char_data.get('desc', '')}. Be natural and engaging."
        else:
            scene_prompt_raw = f"You are {char_name}. {char_desc}"

        system_prompt = (
            BASE_RULES
            + "\n--- CHARACTER & SCENE CONTEXT (REFERENCE ONLY) ---\n"
            + scene_prompt_raw
            + "\n--- STYLE LOCK ---\n"
            + "The above context is background knowledge only.\n"
            + "Do NOT narrate or describe it.\n"
            + "Respond only through dialogue and short reactions.\n"
            + "Final check: if the response reads like narration, rewrite it as dialogue.\n"
        )

        # ── Init session ─────────────────────────────────────────────
        user_sessions[user_id] = {
            "history":          [{"role": "system", "content": system_prompt}],
            "char_name":        char_name,
            "char_desc":        char_data.get("desc", "") if is_preloaded and char_data else char_desc,
            "scenario":         scene_narrative if is_preloaded else scenario,
            "reference_image":  reference_image,
            "is_preloaded":     is_preloaded,
            "message_count":    0,
            "images_generated": 0,
            "last_20_messages": 0
        }

        session = user_sessions[user_id]

        # ── Get AI opening reply ─────────────────────────────────────
        session["history"].append({
            "role": "user",
            "content": "The scene has begun. React naturally."
        })

        response = await asyncio.to_thread(
            client_rp.chat.complete,
            model=RP_MODEL,
            messages=session["history"],
            max_tokens=100,
            temperature=0.85
        )

        # Send AI text RAW - no formatting, no parse_mode
        ai_reply = clean_reply(extract_mistral_reply(response))
        session["history"].append({"role": "assistant", "content": ai_reply})

        # ════════════════════════════════════════════════════════════
        # PRELOADED - 3-step cinematic reveal
        # ════════════════════════════════════════════════════════════
        if is_preloaded:

            char_main_image = char_data.get("image", "")

            # ── STEP 1: Character main image ─────────────────────────
            if char_main_image:
                try:
                    await update.message.reply_photo(photo=char_main_image)
                except Exception as e:
                    logging.error(f"❌ Step 1 image error: {e}")

            # ── STEP 2: Scene image + narrative caption (HTML) ────────
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
                    logging.error(f"❌ Step 2 image error: {e}")
                    await update.message.reply_text(narrative_caption, parse_mode="HTML")
            else:
                await update.message.reply_text(narrative_caption, parse_mode="HTML")

            # ── STEP 3: Character-in-scene image + AI reply (RAW) ────
            char_scene_img = scene_char_image or char_main_image

            if char_scene_img:
                try:
                    await update.message.reply_photo(
                        photo=char_scene_img,
                        caption=ai_reply,
                        reply_markup=utility_keyboard()
                        # No parse_mode - raw text
                    )
                except Exception as e:
                    logging.error(f"❌ Step 3 image error: {e}")
                    await update.message.reply_text(
                        ai_reply,
                        reply_markup=utility_keyboard()
                    )
            else:
                await update.message.reply_text(
                    ai_reply,
                    reply_markup=utility_keyboard()
                )

        # ════════════════════════════════════════════════════════════
        # CUSTOM - 2-step opening
        # ════════════════════════════════════════════════════════════
        else:
            if scene_label:
                narrative_caption = f"✦ <b>{char_name}</b>\n\n<i>{scenario}</i>"
            else:
                narrative_caption = f"✦ <b>{char_name}</b>\n\n<i>{scenario}</i>"

            # Step 1: Generate AI image + narrative caption
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

            # Step 2: AI reply RAW + keyboard
            await update.message.reply_text(
                ai_reply,
                reply_markup=utility_keyboard()
                # No parse_mode - raw text
            )

        session["message_count"]    = 1
        session["images_generated"] = 0

    except Exception as e:
        logging.error(f"❌ Manifest error: {e}")
        await update.message.reply_text(
            "🌑 The gateway flickered... something went wrong.\nPlease try again or tap Begin Your Story.",
            reply_markup=start_keyboard()
        )

# ============================================================================
# CORE REPLY GENERATOR - PARALLEL CEREBRAS CALLS WHEN IMAGE TRIGGERS
# ============================================================================

async def generate_reply(update, user_id, input_text):
    session = user_sessions[user_id]

    # Store user message clean — no wrapper polluting rhythm
    session["history"].append({"role": "user", "content": input_text})

    try:
        recent    = session["history"][1:]
        # System prompt always first so model never loses character context
        # Use a copy so self_check never pollutes the original system prompt
        system_copy = {"role": "system", "content": session["history"][0]["content"]}

        # Every 2nd message — character consistency reminder (not saved to history)
        if session["message_count"] % 2 == 0:
            system_copy["content"] += "\n\n<system>Stay in character. Obey rules.</system>"
            logging.info("🎭 Character reminder injected")

        # Every 3rd message — inject self_check into system copy only (not saved to history)
        if session["message_count"] % 3 == 0:
            system_copy["content"] += "\n\n<self_check>Is this conversation still moving forward or repeating the same energy? If flowing — continue naturally. If stalling — suggest something, move somewhere, shift the dynamic.</self_check>"
            logging.info("🔄 Self-check injected")

        rp_inputs = [system_copy] + recent[-8:]

        fire_image = should_generate_image(session)

        if fire_image:
            logging.info("⚡ Parallel: RP + keywords firing together")

            async def get_rp_reply():
                resp = await asyncio.to_thread(
                    client_rp.chat.complete,
                    model=RP_MODEL,
                    messages=rp_inputs,
                    max_tokens=120,
                    temperature=0.85
                )
                return extract_mistral_reply(resp)

            async def get_keywords():
                return await get_scene_keywords(recent, session["char_name"])

            ai_reply, keywords = await asyncio.gather(
                get_rp_reply(),
                get_keywords()
            )

            # Update history and counters
            session["history"].append({"role": "assistant", "content": ai_reply})
            session["message_count"]    += 1
            session["last_20_messages"] += 1

            if session["last_20_messages"] >= 20:
                session["images_generated"] = 0
                session["last_20_messages"] = 0
                logging.info("🔄 Image counter reset")

            # Generate image
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

            # Send - AI text always RAW, no parse_mode
            if image_bytes:
                await update.message.reply_photo(
                    photo=image_bytes,
                    caption=ai_reply
                    # No parse_mode
                )
            else:
                await update.message.reply_text(ai_reply)

        else:
            # Sequential - RP only
            response = await asyncio.to_thread(
                client_rp.chat.complete,
                model=RP_MODEL,
                messages=rp_inputs,
                max_tokens=120,
                temperature=0.85
            )
            ai_reply = clean_reply(extract_mistral_reply(response))
            session["history"].append({"role": "assistant", "content": ai_reply})
            session["message_count"]    += 1
            session["last_20_messages"] += 1

            if session["last_20_messages"] >= 20:
                session["images_generated"] = 0
                session["last_20_messages"] = 0
                logging.info("🔄 Image counter reset")

            # Send raw - no parse_mode at all
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


