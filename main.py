import os
import json
import logging
import requests
from io import BytesIO
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

# --- CHARACTER REFERENCE IMAGES (for exact appearance) ---
CHARACTER_REFERENCE_IMAGES = {
    "Lilith": "https://i.postimg.cc/nLPJ8WTn/image-14.jpg",
    "Hellien": "https://i.postimg.cc/Pr40sc5p/image-10.jpg",
    "Mrs. Grace": "https://i.postimg.cc/dtqSBBmz/image-15.jpg",
    "Maya": "https://i.postimg.cc/rs9ZT0cN/image-20.jpg",
    "Nika": "https://i.postimg.cc/W4J93fT3/image-8.jpg",
    "Robert": "https://i.postimg.cc/NFN8b1Qt/image-5.jpg",
    "John": "https://i.postimg.cc/JhbbSwRb/image-6.jpg",
    "Mike": "https://i.postimg.cc/pXTJr1Bj/image-7.jpg"
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
def generate_scene_image(prompt_text, char_name="", char_desc="", reference_image_url=None):
    """Generate scene image using Pollinations Klein model with API key and reference image.
    
    Returns:
        tuple: (image_bytes, image_url) - Both the image and the URL for reference storage
    """
    try:
        # Build the full prompt with character details
        if char_name and char_desc:
            full_prompt = f"{char_name}, {char_desc}, {prompt_text}"
        elif char_name:
            full_prompt = f"{char_name}, {prompt_text}"
        else:
            full_prompt = prompt_text
        
        # URL encode the prompt
        encoded_prompt = quote(full_prompt)
        
        # Generate consistent seed from character name
        seed = 0
        if char_name:
            import hashlib
            seed = int(hashlib.md5(char_name.encode()).hexdigest()[:8], 16) % 1000000
        
        # Build Pollinations URL with CORRECT image parameter
        image_url = f"https://gen.pollinations.ai/image/{encoded_prompt}"
        params = [
            f"model=klein",
            f"width=1024",
            f"height=1024",
            f"seed={seed}",
            f"enhance=true",  # Set to true for better quality
            f"key={POLLINATIONS_API_KEY}"
        ]
        
        # Add reference image if provided - CORRECT PARAMETER IS image= not reference=!
        if reference_image_url:
            encoded_reference = quote(reference_image_url)
            params.append(f"image={encoded_reference}")  # ✅ CORRECT PARAMETER!
            logging.info(f"✅ Using reference image: {reference_image_url[:50]}...")
        
        image_url += "?" + "&".join(params)
        
        logging.info(f"Generating image: {full_prompt[:50]}... (seed: {seed})")
        
        # Download the image
        response = requests.get(image_url, timeout=30)
        
        if response.status_code == 200:
            image_bytes = BytesIO(response.content)
            logging.info("Image downloaded successfully")
            return (image_bytes, image_url)  # Return both bytes and URL
        else:
            logging.error(f"Image generation failed with status {response.status_code}")
            return (None, None)
        
    except Exception as e:
        logging.error(f"Image generation error: {e}")
        return (None, None)

async def get_image_prompt_from_grok(session_history, char_name):
    """Ask Grok to generate a simple 1-2 line image prompt based on current scene."""
    try:
        # Create a temporary message history for image prompt generation
        prompt_messages = session_history.copy()
        prompt_messages.append({
            "role": "user",
            "content": (
    f"Generate a SIMPLE 1-2 sentence image description for the current roleplay scene only. "
    f"\n\n**STRICT RULES:**"
    f"\n1. Show ONLY {char_name} - NO other people allowed"
    f"\n2. {char_name} must be ALONE in the image"
    f"\n3. DO NOT mention: user, traveler, partner, lover, person, man, woman, someone, anyone, companion, or any other person"
    f"\n4. Focus on: {char_name}'s appearance, pose, expression, clothing, and the setting/background"
    f"\n\nExample: '{char_name} sitting on velvet couch in candlelit room, wearing elegant dress, seductive smile'"
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

async def get_image_prompt_from_grok(session_history, char_name):
    """Ask Grok to generate a simple 1-2 line image prompt based on current scene."""
    try:
        # Create a temporary message history for image prompt generation
        prompt_messages = session_history.copy()
        prompt_messages.append({
            "role": "user",
            "content": (
                f"Based on our current roleplay scene, generate a SIMPLE 1-2 sentence visual description "
                f"for an image of this exact moment. Focus ONLY on {char_name}'s appearance, current action, "
                f"setting/background, and mood. Keep it simple and visual - only describe what can be seen. "
                f"\n\n**CRITICAL: The image should show ONLY {char_name}. DO NOT include the user/other person in the description. "
                f"Only {char_name} should be visible in the image.**"
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
        char_reference = CHARACTER_REFERENCE_IMAGES.get(char_name)  # Get reference for pre-loaded

        system_prompt = (
    f"You are {char_name} in an explicit adult roleplay.\n"
    f"Personality: {char_desc}.\n"
    f"User: {user_name} (Gender: {user_gender}).\n\n"
    "- STRICTLY BEHAVE LIKE YOUR CHARECTER AND MAINTAIN PERSONALITY. completely think urself as the charecter and adapt personality. ask soft questions to make the roleplay interesting but only if needed don't spam questions if not needed. Strictly Never jump into any sexual thing unless user leads you take things slow maintain a slow burn romantic theme. If user starts sexual environment get slowly desirable then. \n"
    "- Never write for {{user}}.\n"
    "- Don't write like ai. Try to maintain a realistic human like feeling. show sensations, soft moans , use words like - umm , argh , humph , ahhh to make it feel like real. Use raw words .\n"
    "- STRICTLY dialouges IN 60 to 70 words and actions, thoughts in 30-40 words . blend dialouges, actions, thoughts to create a beautiful roleplay. don't make paragraphs try to make all text in a single or double paragraph. \n\n"
    "Formatting:\n\"dialogue\"\n*actions* *quiet thoughts/murmurs in italics*" )

        user_sessions[user_id] = {
            "history": [{"role": "system", "content": system_prompt}],
            "char_name": char_name,
            "char_desc": char_desc,
            "message_count": 0,
            "char_reference_image": char_reference or char_image,  # Use pre-loaded reference or custom
            "images_generated": 0,  # Track images generated
            "last_20_messages": 0   # Track last 20 messages for cap
        }
        
        start_trigger = f"[SCENARIO SETUP - USER PERSPECTIVE]: {scenario}\n\n[START THE STORY NOW AS {char_name}]"
        
        # 1. Video/GIF (only for pre-loaded)
        if char_video:
            try:
                await update.message.reply_animation(
                    animation=char_video,
                    caption=f"✨ {char_name} has materialized.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Video Error: {e}")

        # 2. Generate initial scene image based on scenario
        status_text = f"🌑 **Summoning {char_name}...** 🌙\n\n*The void shapes itself into a familiar form...*"
        
        # Create initial image prompt
        initial_image_prompt = f"{scenario}, cinematic scene, detailed"
        initial_scene_image, initial_image_url = generate_scene_image(
            initial_image_prompt, 
            char_name=char_name,
            char_desc=char_desc,
            reference_image_url=char_reference or char_image  # Use reference for pre-loaded, or custom image
        )
        
        # For custom characters (no pre-loaded reference), save first generated image URL as reference
        if not char_reference and initial_image_url:
            user_sessions[user_id]["char_reference_image"] = initial_image_url
            logging.info(f"💾 Saved first generated image as reference for custom character")
        
        if initial_scene_image:
            await update.message.reply_photo(
                photo=initial_scene_image,
                caption=status_text,
                reply_markup=get_utility_keyboard(),
                parse_mode="Markdown"
            )
        else:
            # Fallback to text if image generation fails
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
        session["last_20_messages"] += 1
        msg_count = session["message_count"]
        
        # Reset counters every 20 messages
        if session["last_20_messages"] >= 20:
            session["images_generated"] = 0
            session["last_20_messages"] = 0
            logging.info("🔄 Reset image counter for new 20-message cycle")
        
        # Image generation logic: 3rd, 7th, then random (max 6 per 20 messages)
        should_generate_image = False
        
        if msg_count == 3:
            # Always generate on 3rd message
            should_generate_image = True
            logging.info("📸 Image trigger: Message 3")
        elif msg_count == 7:
            # Always generate on 7th message
            should_generate_image = True
            logging.info("📸 Image trigger: Message 7")
        elif msg_count > 7 and session["images_generated"] < 6:
            # After 7th message, random chance (30% probability)
            # But cap at 6 images per 20 messages
            import random
            if random.random() < 0.3:  # 30% chance
                should_generate_image = True
                logging.info(f"📸 Image trigger: Random (count: {session['images_generated']}/6)")
        
        if should_generate_image:
            logging.info(f"Message #{msg_count} - Generating scene image...")
            
            # Get image prompt from Grok
            image_prompt = await get_image_prompt_from_grok(
                session["history"], 
                session["char_name"]
            )
            
            if image_prompt:
                # Generate the scene image with reference
                scene_image_bytes, scene_image_url = generate_scene_image(
                    image_prompt,
                    char_name=session["char_name"],
                    char_desc=session["char_desc"],
                    reference_image_url=session.get("char_reference_image")
                )
                
                if scene_image_bytes:
                    # Send text with scene image
                    await update.message.reply_photo(
                        photo=scene_image_bytes,
                        caption=ai_reply,
                        parse_mode="Markdown"
                    )
                    session["images_generated"] += 1
                    logging.info(f"✅ Scene image sent (total: {session['images_generated']}/6 in last 20)")
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
