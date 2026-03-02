"""
HERMAX ROLEPLAY BOT
Telegram Bot + Web App + Mistral AI + Cerebras + Pollinations

client_rp  — MISTRAL_API_KEY       — mistral-large-latest  — RP generation
client_img — CEREBRAS_API_KEY_IMG  — llama3.1-8b           — keyword extraction

Preloaded opening:  Step 1 char image → Step 2 scene image + narrative → Step 3 char-in-scene + reply
Custom opening:     Step 1 generated image + narrative → Step 2 reply

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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TOKEN            = os.getenv("TELEGRAM_BOT_TOKEN")
MISTRAL_KEY      = os.getenv("MISTRAL_API_KEY")
CEREBRAS_KEY_IMG = os.getenv("CEREBRAS_API_KEY_IMG")
POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")

RP_MODEL   = "mistral-small-latest"
IMG_MODEL  = "llama3.1-8b"
WEBAPP_URL = "https://usage217-tech.github.io/Mytho-rp/"

# ============================================================================
# CHARACTER DATA
# ============================================================================

with open("Charecters.json", "r") as f:
    CHARACTERS = json.load(f)

def get_char(name):
    return CHARACTERS.get(name)

# ============================================================================
# CLIENTS
# ============================================================================

client_rp  = Mistral(api_key=MISTRAL_KEY)
client_img = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY_IMG)
app        = Flask(__name__)
user_sessions = {}

# ============================================================================
# FORMAT RULE — injected at top of every system prompt
# ============================================================================

FORMAT_RULE = (
    "Reply format — two parts, always:\n"
    "Line 1: line 1 should be wrapped in asterisks. *one suitable emoji + everything in asterisks* — scene, atmosphere, and your actions(in 1st person). MAX 3 SENTENCES, ONE PARAGRAPH.\n"
    "Line 2: one suitable emoji + your spoken words only. no asterisks. no actions. just dialogue.\n\n"
    "Example:\n"
    "🌧️ *Rain on the glass. Jazz low. She leans in, lets her fingers trace the rim of his cup.*\n"
    "Too late to pretend you didn't want company. so — tell me something true.\n")

# ============================================================================
# HELPERS
# ============================================================================

def extract_reply(response):
    try:
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [b.text if hasattr(b, "text") else b for b in content if isinstance(b, str) or hasattr(b, "text")]
            return "".join(parts).strip()
        return str(content).strip()
    except Exception as e:
        logging.error(f"❌ extract_reply: {e}")
        return "..."


def clean_reply(text):
    text = text.strip()

    # Split into lines, find line1 (emoji + *env*)
    line1 = ""
    line2_parts = []
    found_line1 = False

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if not found_line1 and re.search(r'\*[^*]+\*', line) and re.search(
            r'[\U0001F300-\U0001FAFF\U0001F000-\U0001F9FF\u2600-\u27BF]', line
        ):
            line1 = line
            found_line1 = True
        else:
            line2_parts.append(line)

    # Flatten everything after line1 into one paragraph
    line2 = " ".join(line2_parts)

    # Action rules for line2:
    # 1 word   → strip asterisks, keep word
    # 2-5 words → keep as is
    # 6+ words → delete entirely
    def fix_action(m):
        inner = m.group(1).strip()
        count = len(inner.split())
        if count == 1:
            return inner
        elif count <= 5:
            return m.group(0)
        else:
            return ""

    line2 = re.sub(r'\*\*([^*]+)\*\*', fix_action, line2)
    line2 = re.sub(r'\*([^*]+)\*',     fix_action, line2)

    # Clean up spaces
    line2 = re.sub(r' +', ' ', line2).strip()

    if not line1:
        return line2

    return f"{line1}\n\n{line2}"


def is_incomplete(text):
    text = text.strip()
    if not text or len(text.split()) < 6:
        return True
    return text[-1] not in {".", "!", "?", "…", '"', "'", ")", "*"}

# ============================================================================
# KEYBOARDS
# ============================================================================

def start_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("✨ Begin Your Story", web_app=WebAppInfo(url=WEBAPP_URL))],
         [KeyboardButton("🌸 How It Works")]],
        resize_keyboard=True
    )

def utility_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("💭 Current Story"), KeyboardButton("🌙 End Dream")],
         [KeyboardButton("🌸 New Story"),     KeyboardButton("🎭 Who Am I?")]],
        resize_keyboard=True
    )

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def generate_scene_image(keywords, char_name, reference_url=None):
    try:
        prompt = f"Anime style. {keywords}. Solo character. Cinematic lighting."
        seed   = random.randint(0, 999999)

        params = [
            "model=klein", "width=720", "height=720",
            f"seed={seed}", "enhance=true", "nologo=true",
        ]
        if POLLINATIONS_KEY:
            params.append(f"key={POLLINATIONS_KEY}")
        if reference_url:
            params.append(f"image={quote(reference_url)}")
            logging.info(f"🔗 ref: {reference_url[:60]}")

        url = f"https://gen.pollinations.ai/image/{quote(prompt)}?" + "&".join(params)
        logging.info(f"🖼️ {url[:100]}")

        r = requests.get(url, timeout=60)
        if r.status_code == 200 and len(r.content) > 1000:
            logging.info("✅ image ok")
            return BytesIO(r.content), url
        logging.error(f"❌ image {r.status_code} size={len(r.content)}")
        return None, None
    except Exception as e:
        logging.error(f"❌ image error: {e}")
        return None, None

# ============================================================================
# KEYWORD EXTRACTOR  (Cerebras, parallel with RP call)
# ============================================================================

async def get_scene_keywords(recent_messages, char_name):
    try:
        context = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in recent_messages[-5:]
            if m["role"] != "system"
        )
        response = await asyncio.to_thread(
            client_img.chat.completions.create,
            model=IMG_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract 6 comma-separated visual phrases for image generation.\n"
                    f"Context:\n{context}\n\n"
                    f"Describe: location, lighting, atmosphere, what {char_name} is doing ALONE.\n"
                    f"Rules: solo only, no interaction, no second person, no emotions.\n"
                    f"Output exactly 6 phrases. Nothing else."
                )
            }],
            temperature=0.65,
            max_tokens=40
        )
        keywords = response.choices[0].message.content.strip().replace('"', "").replace("'", "")
        logging.info(f"📝 keywords: {keywords}")
        return keywords
    except Exception as e:
        logging.error(f"❌ keywords: {e}")
        return None

# ============================================================================
# IMAGE TRIGGER
# ============================================================================

def should_generate_image(session):
    count     = session["message_count"]
    generated = session["images_generated"]
    custom    = not session["is_preloaded"]

    if custom and count == 1:          logging.info("📸 custom msg1");  return True
    if count == 3:                     logging.info("📸 msg3");          return True
    if count == 7:                     logging.info("📸 msg7");          return True
    if count > 7 and generated < 6 and random.random() < 0.3:
        logging.info(f"📸 random {generated}/6");                        return True
    return False

# ============================================================================
# FLASK
# ============================================================================

@app.route("/")
def home():
    return "🌙 HERMAX Roleplay Engine - Online"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

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
# RP CALL  (Mistral, retry once if incomplete)
# ============================================================================

async def call_rp(messages, temperature=0.85):
    for attempt in range(2):
        response = await asyncio.to_thread(
            client_rp.chat.complete,
            model=RP_MODEL,
            messages=messages,
            max_tokens=150,
            temperature=temperature,
            random_seed=random.randint(1, 1_000_000)
        )
        reply = extract_reply(response)
        if not is_incomplete(reply):
            return clean_reply(reply)
        logging.info(f"⚠️ incomplete attempt {attempt + 1}, retrying")
        temperature = min(temperature + 0.05, 1.0)

    logging.warning("⚠️ both attempts incomplete — best effort")
    return clean_reply(reply)

# ============================================================================
# BUILD SYSTEM PROMPT
# ============================================================================

def build_system_prompt(char_data, scene_data_obj, is_preloaded,
                         char_name, char_desc, name_known, user_name, user_gender):

    # Format rule — always first
    parts = [FORMAT_RULE]

    # Name rule
    if name_known:
        parts.append(f"Their name is {user_name} ({user_gender}). Use it only when natural.")
    else:
        parts.append(
            f"You are speaking with a {user_gender} stranger. "
            "You don't know their name. Never use it. "
            "If they tell you, you may use it after that."
        )

    # Seduction style + hunger (preloaded only)
    if is_preloaded and char_data:
        seduction = char_data.get("seduction_style", "")
        hunger    = char_data.get("hunger_level", 0)
        if seduction:
            parts.append(f"Seduction style: {seduction}")
        if hunger:
            parts.append(f"Hunger intensity: {hunger}/10")

    # Scene prompt
    if is_preloaded:
        scene_prompt = scene_data_obj.get("prompt", "") or f"You are {char_name}. {char_data.get('desc', '')}"
    else:
        scene_prompt = f"You are {char_name}. {char_desc}"

    parts.append(scene_prompt)

    return "\n\n".join(parts)

# ============================================================================
# HANDLE MANIFEST  (web app data)
# ============================================================================

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data    = json.loads(update.effective_message.web_app_data.data)
        user_id = update.effective_user.id

        char_name   = data.get("ai_name",    "Unknown")
        char_desc   = data.get("ai_desc",    "")
        char_image  = data.get("ai_image",   "")
        user_name   = data.get("user_name",  "Traveler")
        user_gender = data.get("user_gender","Male")
        scenario    = data.get("scenario",   "A mysterious encounter.")
        is_custom   = data.get("is_custom",  False)
        scene_index = int(data.get("scene_index", -1))

        char_data    = get_char(char_name)
        is_preloaded = char_data is not None and not is_custom

        # Scene data
        if is_preloaded:
            scenes           = char_data.get("scenes", [])
            scene_data_obj   = scenes[scene_index] if 0 <= scene_index < len(scenes) else (scenes[0] if scenes else {})
            scene_label      = scene_data_obj.get("label",     "")
            scene_narrative  = scene_data_obj.get("narrative", scenario)
            scene_image      = scene_data_obj.get("scene_image",  "")
            scene_char_image = scene_data_obj.get("char_image",   "")
            name_known       = scene_data_obj.get("name_known",   True)
        else:
            scene_data_obj   = {}
            scene_label      = ""
            scene_narrative  = scenario
            scene_image      = ""
            scene_char_image = ""
            name_known       = True

        reference_image = scene_char_image or (char_data.get("image", "") if is_preloaded else char_image)

        logging.info(f"🎭 {char_name} | {user_name} | preloaded={is_preloaded} | name_known={name_known}")

        # Build system prompt
        system_prompt = build_system_prompt(
            char_data, scene_data_obj, is_preloaded,
            char_name, char_desc, name_known, user_name, user_gender
        )

        # Init session
        user_sessions[user_id] = {
            "history":          [{"role": "system", "content": system_prompt}],
            "char_name":        char_name,
            "char_desc":        char_data.get("desc", "") if is_preloaded and char_data else char_desc,
            "scenario":         scene_narrative,
            "reference_image":  reference_image,
            "is_preloaded":     is_preloaded,
            "message_count":    0,
            "images_generated": 0,
            "last_20_messages": 0,
        }
        session = user_sessions[user_id]

        # Opening trigger
        arrival = f"[Scene start. {user_name} has just arrived.]" if name_known else "[Scene start. A stranger has just arrived.]"
        session["history"].append({"role": "user", "content": arrival})

        ai_reply = await call_rp(session["history"])
        session["history"].append({"role": "assistant", "content": ai_reply})
        session["message_count"] = 1

        # ── PRELOADED — 3-step reveal ────────────────────────────────
        if is_preloaded:
            char_main_image = char_data.get("image", "")

            # Step 1 — character image
            if char_main_image:
                try:
                    await update.message.reply_photo(photo=char_main_image)
                except Exception as e:
                    logging.error(f"❌ step1: {e}")

            # Step 2 — scene image + narrative
            caption = f"✦ <b>{scene_label}</b>\n\n<i>{scene_narrative}</i>" if scene_label else f"<i>{scene_narrative}</i>"
            if scene_image:
                try:
                    await update.message.reply_photo(photo=scene_image, caption=caption, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"❌ step2: {e}")
                    await update.message.reply_text(caption, parse_mode="HTML")
            else:
                await update.message.reply_text(caption, parse_mode="HTML")

            # Step 3 — char-in-scene + ai reply
            char_scene_img = scene_char_image or char_main_image
            if char_scene_img:
                try:
                    await update.message.reply_photo(photo=char_scene_img, caption=ai_reply, reply_markup=utility_keyboard())
                except Exception as e:
                    logging.error(f"❌ step3: {e}")
                    await update.message.reply_text(ai_reply, reply_markup=utility_keyboard())
            else:
                await update.message.reply_text(ai_reply, reply_markup=utility_keyboard())

        # ── CUSTOM — 2-step ──────────────────────────────────────────
        else:
            caption = f"✦ <b>{char_name}</b>\n\n<i>{scenario}</i>"
            img, img_url = await asyncio.to_thread(
                generate_scene_image,
                f"{scenario}, cinematic, atmospheric",
                char_name,
                char_image or None
            )
            if img_url:
                session["reference_image"] = img_url

            if img:
                await update.message.reply_photo(photo=img, caption=caption, parse_mode="HTML")
            else:
                await update.message.reply_text(caption, parse_mode="HTML")

            await update.message.reply_text(ai_reply, reply_markup=utility_keyboard())

    except Exception as e:
        logging.error(f"❌ manifest: {e}")
        await update.message.reply_text(
            "🌑 The gateway flickered... something went wrong.\nPlease try again or tap Begin Your Story.",
            reply_markup=start_keyboard()
        )

# ============================================================================
# GENERATE REPLY
# ============================================================================

async def generate_reply(update: Update, user_id: int, input_text: str):
    session = user_sessions[user_id]
    session["history"].append({"role": "user", "content": input_text})

    try:
        recent      = session["history"][1:]
        system_copy = {"role": "system", "content": session["history"][0]["content"]}

        # Every 2nd message — keep format
        if session["message_count"] % 2 == 0:
            system_copy["content"] += "\n\nKeep the format: env line then dialogue."

        # Every 3rd message — push story forward
        if session["message_count"] % 3 == 0:
            system_copy["content"] += "\n\nIs the story moving? If stuck — shift something. Say the unexpected."

        rp_inputs  = [system_copy] + recent[-6:]
        fire_image = should_generate_image(session)

        if fire_image:
            logging.info("⚡ parallel: rp + keywords")
            ai_reply, keywords = await asyncio.gather(
                call_rp(rp_inputs),
                get_scene_keywords(recent, session["char_name"])
            )
        else:
            ai_reply = await call_rp(rp_inputs)
            keywords = None

        session["history"].append({"role": "assistant", "content": ai_reply})
        session["message_count"]    += 1
        session["last_20_messages"] += 1

        if session["last_20_messages"] >= 20:
            session["images_generated"] = 0
            session["last_20_messages"] = 0
            logging.info("🔄 image counter reset")

        # Send image if triggered
        if fire_image and keywords:
            img, _ = await asyncio.to_thread(
                generate_scene_image,
                keywords,
                session["char_name"],
                session.get("reference_image")
            )
            if img:
                session["images_generated"] += 1
                logging.info(f"✅ image {session['images_generated']}/6")
                await update.message.reply_photo(photo=img, caption=ai_reply)
                return

        await update.message.reply_text(ai_reply)

    except Exception as e:
        logging.error(f"❌ generate_reply: {e}")
        await update.message.reply_text("🌑 The void stirs but stays silent... Try again in a moment.")

# ============================================================================
# MESSAGE ROUTER
# ============================================================================

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text

    if text == "🌙 End Dream":
        if user_id in user_sessions:
            s = user_sessions.pop(user_id)
            await update.message.reply_text(
                f"🌙 <b>The dream fades...</b>\n\n"
                f"Your story with <b>{s['char_name']}</b> drifts into memory.\n"
                f"<i>{s['message_count']} moments shared between you.</i>\n\n"
                f"✨ <i>Until the next dream begins...</i>",
                reply_markup=start_keyboard(), parse_mode="HTML"
            )
        else:
            await update.message.reply_text("🌸 No dream is active right now. Tap below to begin one.", reply_markup=start_keyboard())
        return

    if text == "💭 Current Story":
        if user_id in user_sessions:
            s = user_sessions[user_id]
            await update.message.reply_text(
                f"💭 <b>Your Current Dream</b>\n━━━━━━━━━━━━━━━━━━\n\n"
                f"✦ <b>Character:</b> {s['char_name']}\n<i>{s['char_desc']}</i>\n\n"
                f"📖 <b>Scene:</b> <i>{s['scenario']}</i>\n\n"
                f"💬 <b>Moments shared:</b> {s['message_count']}\n━━━━━━━━━━━━━━━━━━",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("🌸 No dream is active yet. Tap Begin Your Story to start. ✨", reply_markup=start_keyboard())
        return

    if text == "🎭 Who Am I?":
        await update.message.reply_text(
            "🎭 <b>HERMAX Roleplay</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            "✦ <i>An immersive AI roleplay experience</i>\n\n"
            "✨ <b>Begin Your Story</b> — Open the character portal\n"
            "💭 <b>Current Story</b> — View your active dream\n"
            "🌙 <b>End Dream</b> — Close the current session\n"
            "🌸 <b>New Story</b> — Start a fresh adventure\n\n"
            "💫 <i>Just type naturally to talk with your character.</i>\n━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
        return

    if text == "🌸 How It Works":
        await update.message.reply_text(
            "🌸 <b>How HERMAX Works</b>\n━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ Tap <b>Begin Your Story</b>\n<i>Choose your character and scene</i>\n\n"
            "2️⃣ <i>The story awakens</i>\n<i>Your character appears, the dream begins</i>\n\n"
            "3️⃣ <i>Just... talk</i>\n<i>Type naturally. The character responds.</i>\n\n"
            "✨ <i>Images appear as your story deepens.</i>\n━━━━━━━━━━━━━━━━━━",
            parse_mode="HTML"
        )
        return

    if text == "🌸 New Story":
        user_sessions.pop(user_id, None)
        await update.message.reply_text("✨ Opening the gateway to a new dream...", reply_markup=start_keyboard())
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
    logging.info("🌙 Starting HERMAX...")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    Thread(target=run_flask, daemon=True).start()
    logging.info("🌐 Flask started | ✅ Bot running!")
    application.run_polling()

if __name__ == "__main__":
    main()
