"""
HERMAX ROLEPLAY BOT - OPTIMIZED
Dual Cerebras: client_rp (roleplay) + client_img (keyword extraction)
Removed: Mistral dependency, code bloat, redundant logic
"""

import os
import json
import asyncio
import logging
import random
import requests
from io import BytesIO
from urllib.parse import quote
from flask import Flask
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
from dotenv import load_dotenv

# ============================================================================
# CONFIG
# ============================================================================

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN")
CEREBRAS_KEY_RP   = os.getenv("CEREBRAS_API_KEY_RP")      # For roleplay text
CEREBRAS_KEY_IMG  = os.getenv("CEREBRAS_API_KEY_IMG")     # For image keywords
POLL_KEY     = os.getenv("POLLINATIONS_API_KEY")
WEBAPP_URL   = "https://usage217-tech.github.io/Mytho-rp/"
RP_MODEL     = "llama3.1-8b"

# ============================================================================
# DATA
# ============================================================================

with open("characters.json", "r") as f:
    CHARACTERS = json.load(f)

def get_char(name):
    return CHARACTERS.get(name)

def is_anime(name):
    char = get_char(name)
    return char and char.get("style", "Realistic") == "Anime"

# ============================================================================
# DUAL CEREBRAS CLIENTS (Two separate API keys)
# ============================================================================

client_rp  = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY_RP)   # Roleplay
client_img = OpenAI(base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY_IMG)  # Image keywords

app = Flask(__name__)
sessions = {}

# ============================================================================
# KEYBOARDS
# ============================================================================

def start_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("✨ Begin", web_app=WebAppInfo(url=WEBAPP_URL))],
        [KeyboardButton("❓ Help")]
    ], resize_keyboard=True)

def chat_kb():
    return ReplyKeyboardMarkup([
        [KeyboardButton("💭 Story"), KeyboardButton("🌙 End")],
        [KeyboardButton("🎭 New"), KeyboardButton("ℹ️ Info")]
    ], resize_keyboard=True)

# ============================================================================
# UTILS
# ============================================================================

def fix_md(text):
    """Escape unpaired markdown chars."""
    for char in ['*', '_', '`']:
        if text.count(char) % 2:
            text = text.replace(char, f'\\{char}')
    return text.strip()

async def safe_send(update, text, reply_markup=None, photo=None):
    """Send with markdown fallback."""
    kwargs = {"reply_markup": reply_markup} if reply_markup else {}
    
    for parse_mode in ["Markdown", None]:
        try:
            content = fix_md(text) if parse_mode else text
            if photo:
                await update.message.reply_photo(photo=photo, caption=content, parse_mode=parse_mode, **kwargs)
            else:
                await update.message.reply_text(content, parse_mode=parse_mode, **kwargs)
            return
        except Exception:
            continue
    
    # Plain fallback
    if photo:
        await update.message.reply_photo(photo=photo, caption=text, **kwargs)
    else:
        await update.message.reply_text(text, **kwargs)

# ============================================================================
# IMAGE GENERATION
# ============================================================================

def gen_image(keywords, char_name, ref_url=None):
    """Generate image via Pollinations."""
    try:
        style = "Anime" if is_anime(char_name) else "Realistic"
        prompt = f"{style} style. {keywords}."
        
        url = f"https://gen.pollinations.ai/image/{quote(prompt)}?model=klein&width=720&height=720&seed={random.randint(0,999999)}&enhance=true&key={POLL_KEY}"
        if ref_url:
            url += f"&image={quote(ref_url)}"
        
        r = requests.get(url, timeout=45)
        return (BytesIO(r.content), url) if r.status_code == 200 else (None, None)
    except Exception as e:
        logging.error(f"Image error: {e}")
        return (None, None)

# ============================================================================
# CEREBRAS KEYWORD EXTRACTION (Uses separate client_img with CEREBRAS_KEY_IMG)
# ============================================================================

async def get_keywords(messages, char_name):
    """Extract visual keywords using Cerebras client_img."""
    try:
        context = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-5:] if m['role'] != 'system'])
        
        prompt = f"""Extract 6 visual keywords from this roleplay for image generation.

Context:
{context}

Rules:
- Describe: location, lighting, {char_name}'s solo action/pose
- NO interaction words (kissing, touching, holding)
- NO second person (you, together)
- Show emotion through pose, not words

Output: 6 comma-separated phrases only."""

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: client_img.chat.completions.create(
                model=RP_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=60
            )
        )
        
        keywords = resp.choices[0].message.content.strip().replace('"', '').replace("'", '')
        logging.info(f"Keywords: {keywords}")
        return keywords
    except Exception as e:
        logging.error(f"Keyword error: {e}")
        return None

# ============================================================================
# IMAGE TRIGGER LOGIC
# ============================================================================

def should_image(session):
    """Check if we should generate image."""
    count = session["msg_count"]
    gen = session["img_count"]
    is_pre = session["is_pre"]
    
    if not is_pre and count == 1:
        return True
    if count in [3, 7]:
        return True
    if count > 7 and gen < 6 and random.random() < 0.3:
        return True
    return False

# ============================================================================
# HANDLERS
# ============================================================================

@app.route('/')
def home():
    return "HERMAX Online"

def run_flask():
    import threading
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080))), daemon=True).start()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌙 *HERMAX*\n"
        "An immersive AI roleplay experience.\n\n"
        "Tap *Begin* to start your journey...",
        reply_markup=start_kb(), parse_mode="Markdown"
    )

async def handle_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle character selection from WebApp."""
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        uid = update.effective_user.id
        
        char = data.get('ai_name', 'Unknown')
        desc = data.get('ai_desc', '')
        img = data.get('ai_image', '')
        user = data.get('user_name', 'Traveler')
        gender = data.get('user_gender', 'Male')
        scene = data.get('scenario', 'A mysterious encounter.')
        
        char_data = get_char(char)
        is_pre = char_data is not None
        ref_img = char_data["image"] if is_pre else img
        video = char_data.get("video", "") if is_pre else ""
        
        # Build system prompt
        if is_pre:
            sys_prompt = char_data['prompt'].format(user_name=user, user_gender=gender, scenario=scene)
        else:
            sys_prompt = f"""You are {char}.
Personality: {desc}
Talking with {user} ({gender}).
Write naturally, casually. Actions in *asterisks*.
Never write for user. End with a hook.
Scene: {scene}"""
        
        sessions[uid] = {
            "history": [{"role": "system", "content": sys_prompt}],
            "char": char,
            "desc": char_data.get("desc", "") if is_pre else desc,
            "scene": scene,
            "ref_img": ref_img,
            "is_pre": is_pre,
            "msg_count": 0,
            "img_count": 0,
            "cycle": 0
        }
        
        sess = sessions[uid]
        
        # Send video if exists
        if video:
            try:
                await update.message.reply_animation(video, caption=f"✨ *{char}* awakens...", parse_mode="Markdown")
            except:
                pass
        
        # Generate opening
        sess["history"].append({"role": "user", "content": f"[SCENE]: {scene}\nBegin as {char}. Set the scene."})
        
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: client_rp.chat.completions.create(
                model=RP_MODEL, messages=sess["history"], temperature=0.85, max_tokens=95
            )
        )
        
        reply = resp.choices[0].message.content
        sess["history"].append({"role": "assistant", "content": reply})
        
        # Reveal card
        reveal = f"""🌑 *{char}*
_{sess['desc']}_

📖 *Scene:* _{scene}_

💫 *The story begins...*"""
        
        if is_pre:
            await update.message.reply_photo(photo=ref_img, caption=reveal, parse_mode="Markdown")
        else:
            img_bytes, img_url = gen_image(f"{scene}, cinematic", char, ref_img)
            if img_url:
                sess["ref_img"] = img_url
            if img_bytes:
                await update.message.reply_photo(photo=img_bytes, caption=reveal, parse_mode="Markdown")
            else:
                await update.message.reply_text(reveal, parse_mode="Markdown")
        
        await safe_send(update, reply, reply_markup=chat_kb())
        sess["msg_count"] = 1
        sess["img_count"] = 1 if not is_pre else 0
        
    except Exception as e:
        logging.error(f"Webapp error: {e}")
        await update.message.reply_text("🌑 Error starting dream. Try again.", reply_markup=start_kb())

async def generate_reply(update, uid, text):
    """Generate RP reply with optional image."""
    sess = sessions[uid]
    sess["history"].append({"role": "user", "content": f"-{text}\n+reply 60-80 words"})
    
    try:
        # Trim history (keep system + last 10)
        sys_msg = sess["history"][0]
        recent = sess["history"][1:][-10:]
        trimmed = [sys_msg] + recent
        
        fire_img = should_image(sess)
        
        if fire_img:
            # Parallel: RP + Keywords (each uses their own client)
            async def get_rp():
                loop = asyncio.get_event_loop()
                r = await loop.run_in_executor(
                    None,
                    lambda: client_rp.chat.completions.create(
                        model=RP_MODEL, messages=trimmed, temperature=0.85, max_tokens=95
                    )
                )
                return r.choices[0].message.content
            
            async def get_kw():
                return await get_keywords(recent, sess["char"])
            
            reply, keywords = await asyncio.gather(get_rp(), get_kw())
            
            sess["history"].append({"role": "assistant", "content": reply})
            sess["msg_count"] += 1
            sess["cycle"] += 1
            
            if sess["cycle"] >= 20:
                sess["img_count"] = 0
                sess["cycle"] = 0
            
            # Gen image
            img_bytes = None
            if keywords:
                img_bytes, _ = gen_image(keywords, sess["char"], sess.get("ref_img"))
                if img_bytes:
                    sess["img_count"] += 1
            
            await safe_send(update, reply, photo=img_bytes)
        else:
            # RP only
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(
                None,
                lambda: client_rp.chat.completions.create(
                    model=RP_MODEL, messages=trimmed, temperature=0.85, max_tokens=95
                )
            )
            reply = resp.choices[0].message.content
            sess["history"].append({"role": "assistant", "content": reply})
            sess["msg_count"] += 1
            sess["cycle"] += 1
            
            if sess["cycle"] >= 20:
                sess["img_count"] = 0
                sess["cycle"] = 0
            
            await safe_send(update, reply)
            
    except Exception as e:
        logging.error(f"Reply error: {e}")
        await update.message.reply_text("🌑 The void is silent... Try again.")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route messages."""
    uid = update.effective_user.id
    text = update.message.text
    
    # Commands
    if text == "🌙 End":
        if uid in sessions:
            char = sessions[uid]['char']
            count = sessions[uid]['msg_count']
            del sessions[uid]
            await update.message.reply_text(
                f"🌙 Dream with *{char}* ends.\n_{count} moments shared._",
                reply_markup=start_kb(), parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("No active dream.", reply_markup=start_kb())
        return
    
    if text == "💭 Story":
        if uid in sessions:
            s = sessions[uid]
            await update.message.reply_text(
                f"💭 *{s['char']}*\n_{s['desc']}_\n\nScene: _{s['scene']}_\nMessages: {s['msg_count']}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("No active dream.", reply_markup=start_kb())
        return
    
    if text in ["🎭 New", "✨ Begin"]:
        if uid in sessions:
            del sessions[uid]
        await update.message.reply_text("✨ New dream begins...", reply_markup=start_kb())
        return
    
    if text in ["ℹ️ Info", "❓ Help"]:
        await update.message.reply_text(
            "🎭 *HERMAX*\n\n"
            "1. Tap *Begin* to choose character\n"
            "2. Chat naturally with your character\n"
            "3. Images appear as story deepens\n\n"
            "Buttons: Story (status), End (finish), New (restart)",
            reply_markup=start_kb() if uid not in sessions else chat_kb(),
            parse_mode="Markdown"
        )
        return
    
    if uid not in sessions:
        await update.message.reply_text("Tap *Begin* to start.", reply_markup=start_kb(), parse_mode="Markdown")
        return
    
    await generate_reply(update, uid, text)

# ============================================================================
# MAIN
# ============================================================================

def main():
    logging.info("🌙 HERMAX starting...")
    app_tg = Application.builder().token(TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp))
    app_tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    run_flask()
    logging.info("✅ Bot running!")
    app_tg.run_polling()

if __name__ == "__main__":
    main()
