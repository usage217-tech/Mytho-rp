import os
import json
import logging
from threading import Thread
from urllib.parse import quote
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
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY")
WEBAPP_URL = "https://usage217-tech.github.io/Mytho-rp/" 
MODEL = "x-ai/grok-4.1-fast"

# --- VIDEO ASSET MAPPING ---
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

# --- KEYBOARDS ---
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

# --- IMAGE GENERATION ---
def generate_scene_image(prompt_text, char_name=""):
    """Generate scene image using Pollinations Klein model with API key."""
    try:
        # Build the full prompt
        if char_name:
            full_prompt = f"{char_name}, {prompt_text}"
        else:
            full_prompt = prompt_text
        
        # Negative prompt for Klein model
        negative = "bad anatomy, bad proportions, deformed, malformed limbs, mutated, disfigured, extra limbs, extra arms, extra legs, extra hands, extra fingers, missing legs, missing fingers, fused fingers, too many fingers, fewer fingers, poorly drawn hands, deformed hands, mutated hands, malformed hands"
        
        # URL encode
        encoded_prompt = quote(full_prompt)
        encoded_negative = quote(negative)
        
        # Build Pollinations URL with API key
        image_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?model=klein"
            f"&width=1024"
            f"&height=1024"
            f"&enhance=true"
            f"&nologo=true"
            f"&negative={encoded_negative}"
            f"&key={POLLINATIONS_API_KEY}"
        )
        
        logging.info(f"Generated image URL for prompt: {full_prompt[:50]}...")
        return image_url
        
    except Exception as e:
        logging.error(f"Image generation error: {e}")
        return None

async def get_image_prompt_from_grok(session_history, char_name):
    """Ask Grok to generate a simple 1-2 line image prompt based on current scene."""
    try:
        # Create a temporary message history for image prompt generation
        prompt_messages = session_history.copy()
        prompt_messages.append({
            "role": "user",
            "content": (
                f"Based on our current roleplay scene, generate a SIMPLE 1-2 sentence visual description "
                f"for an image of this exact moment. Focus on {char_name}'s appearance, current action, "
                f"setting/background, and mood. Keep it simple and visual - only describe what can be seen. "
                f"\n\nRespond with ONLY the image description, nothing else."
            )
        })
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=prompt_messages,
            temperature=0.7,
            max_tokens=100
        )
        
        image_prompt = response.choices[0].message.content.strip()
        logging.info(f"Grok generated image prompt: {image_prompt}")
        return image_prompt
        
    except Exception as e:
        logging.error(f"Image prompt generation error: {e}")
        return None

# --- FLASK SERVER ---
@app.route('/')
def home(): return "Mythos Engine is Awake."

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the welcome message with buttons."""
    await update.message.reply_text(
        "✧ 🌙 **Mythos Engine** 🌑 ✧\n\n"
        "✨ Welcome, Traveler. The boundaries of reality are thinning. "
        "Tap the button below to design your persona and begin your journey. ⚜️",
        reply_markup=get_start_keyboard(),
        parse_mode="Markdown"
    )

async def handle_manifest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives data from the Web App and starts the RP."""
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

        system_prompt = (
    f"You are {char_name} in an explicit adult roleplay.\n"
    f"Personality: {char_desc}.\n"
    f"User: {user_name} (Gender: {user_gender}).\n\n"
    "- STRICTLY BEHAVE LIKE YOUR CHARECTER AND MAINTAIN PERSONALITY. completely think urself as the charecter and adapt personality. ask soft questions to keep the roleplay interesting. Strictly Never jump into any sexual thing unless user leads you take things slow maintain a slow burn romantic theme. If user starts sexual environment get slowly desirable then. \n"
    "- Never write for {{user}}.\n"
    "- Don't write like ai. Try to maintain a realistic human like feeling. show sensations, soft moans , use words like - umm , argh , humph , ahhh to make it feel like real. Use raw words .\n"
    "- STRICTLY dialouges IN 60 to 70 words and actions, thoughts in 30-40 words . blend dialouges, actions, thoughts to create a beautiful roleplay. don't make paragraphs try to make all text in a single or double paragraph. \n\n"
    "Formatting:\n\"dialogue\"\n*actions* *quiet thoughts/murmurs in italics*" )

        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name,
            "char_desc": char_desc,
            "message_count": 0,
            "char_reference_image": char_image
        }
        
        start_trigger = f"[SCENARIO SETUP - USER PERSPECTIVE]: {scenario}\n\n[START THE STORY NOW AS {char_name}]"
        
        # 1. Video/GIF
        if char_video:
            try:
                await update.message.reply_animation(
                    animation=char_video,
                    caption=f"✨ {char_name} has materialized.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Video Error: {e}")

        # 2. Character Photo & Status
        status_text = f"🌑 **Summoning {char_name}...** 🌙\n\n*The void shapes itself into a familiar form...*"
        if char_image:
            await update.message.reply_photo(
                photo=char_image,
                caption=status_text,
                reply_markup=get_utility_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                status_text, 
                reply_markup=get_utility_keyboard(), 
                parse_mode="Markdown"
            )
        
        # 3. First Response
        await generate_reply(update, user_id, start_trigger)

    except Exception as e:
        logging.error(f"Manifestation Error: {e}")
        await update.message.reply_text(f"⚠️ Manifestation failed: {e}")

async def generate_reply(update, user_id, input_text):
    session = user_sessions[user_id]
    session["history"].append({"role": "user", "content": input_text})

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=session["history"],
            temperature=0.85,
            max_tokens=800
        )
        ai_reply = response.choices[0].message.content
        session["history"].append({"role": "assistant", "content": ai_reply})
        
        # Increment message count
        session["message_count"] += 1
        msg_count = session["message_count"]
        
        # Check if it's time for a scene image (every 4th message)
        should_generate_image = (msg_count % 4 == 0)
        
        if should_generate_image:
            logging.info(f"Message #{msg_count} - Generating scene image...")
            
            # Get image prompt from Grok
            image_prompt = await get_image_prompt_from_grok(
                session["history"], 
                session["char_name"]
            )
            
            if image_prompt:
                # Generate the scene image
                scene_image_url = generate_scene_image(
                    image_prompt,
                    char_name=session["char_name"]
                )
                
                if scene_image_url:
                    # Send text with scene image
                    await update.message.reply_photo(
                        photo=scene_image_url,
                        caption=ai_reply,
                        parse_mode="Markdown"
                    )
                    logging.info(f"Scene image sent successfully")
                else:
                    # Fallback: send text only if image generation failed
                    await update.message.reply_text(ai_reply, parse_mode="Markdown")
            else:
                # Fallback: send text only if prompt generation failed
                await update.message.reply_text(ai_reply, parse_mode="Markdown")
        else:
            # Normal text-only response
            await update.message.reply_text(ai_reply, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"🌑 The void is silent (Error): {e}")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # --- BUTTON LOGIC ---
    if text == "🌑 End Session":
        if user_id in user_sessions:
            del user_sessions[user_id]
            await update.message.reply_text("✨ The vision fades. Your current session has ended. 🌑", reply_markup=get_start_keyboard())
        else:
            await update.message.reply_text("🌙 No active session found.", reply_markup=get_start_keyboard())
        return

    elif text == "🌙 Ongoing Character":
        if user_id in user_sessions:
            name = user_sessions[user_id]['char_name']
            desc = user_sessions[user_id]['char_desc']
            await update.message.reply_text(f"⚜️ **Current Manifestation:** {name}\n\n**Nature:** {desc}", parse_mode="Markdown")
        else:
            await update.message.reply_text("🌑 You are currently alone in the void. Use /start to manifest someone.")
        return

    elif "Help" in text:
        help_text = (
            "🌙 **Mythos Engine Help** ⚜️\n\n"
            "✨ **Manifest Reality:** Use the web app to create a character and scenario.\n"
            "🌑 **End Session:** Stops the current chat and clears memory.\n"
            "🌙 **Ongoing Character:** Reminds you who you are talking to.\n\n"
            "Just type your messages to interact. Keep your responses immersive!"
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")
        return

    elif text == "✨ Manifest New":
        await update.message.reply_text("✨ Opening the Gateway to a new reality...", reply_markup=get_start_keyboard())
        return

    # --- STANDARD CHAT ---
    if user_id not in user_sessions:
        await update.message.reply_text("🌙 Please use /start to manifest a character first!", reply_markup=get_start_keyboard())
        return
    
    await generate_reply(update, user_id, text)

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_manifest))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    Thread(target=run_flask).start()
    application.run_polling()

if __name__ == "__main__":
    main()
