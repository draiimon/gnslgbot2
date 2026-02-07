import os
import discord
import asyncio
from discord.ext import commands, tasks
import logging
import sys

from bot.config import Config
from bot.cog import ChatCog
from bot.speech_recognition_cog import SpeechRecognitionCog
from flask import Flask
import threading
import datetime
import random
import pytz  # For timezone support
import time
from bot.firebase_db import FirebaseDB
from bot.runtime_config import can_use_audio_features, is_render_environment
from bot.rate_limiter import RateLimiter

# Load Opus library for voice support
if not discord.opus.is_loaded():
    try:
        discord.opus.load_opus('libopus.so.0')
        print("✅ Loaded opus library: libopus.so.0")
    except Exception as e:
        try:
            discord.opus.load_opus('libopus.so')
            print("✅ Loaded opus library: libopus.so")
        except Exception as e2:
            try:
                discord.opus.load_opus('opus')
                print("✅ Loaded opus library: opus")
            except Exception as e3:
                print(f"⚠️ Could not load opus library manually: {e}, {e2}, {e3}")
                print("⚠️ Will attempt to use system-loaded opus")
else:
    print("✅ Opus library already loaded")

class GinsilogBot(commands.Bot):
    def __init__(self):
        # Initialize intents
        intents = discord.Intents.all()
        super().__init__(command_prefix=Config.COMMAND_PREFIX, 
                         intents=intents,
                         help_command=None)
        
        # Initialize state
        self.last_morning_greeting_date = None
        self.last_night_greeting_date = None
        self.maintenance_mode = False
        self.db = None
        
        # Rate limiter
        self.rate_limiter = RateLimiter()
        
    async def setup_hook(self):
        """Called during bot startup to setup extensions and database"""
        print("🔄 Setting up GinsilogBot...")
        
        # Initialize Firebase
        self.db = FirebaseDB()
        print("✅ Firebase database initialized")
        
        # Determine environment
        is_render = is_render_environment()
        print(f"🔄 Environment detection: {'Render' if is_render else 'Replit'}")
        
        # Initialize cogs
        chat_cog = ChatCog(self)
        chat_cog.db = self.db
        
        speech_cog = SpeechRecognitionCog(self)
        speech_cog.db = self.db
        
        # Connect AI handler
        speech_cog.get_ai_response = chat_cog.get_ai_response
        print("✅ Connected AI response handler between cogs")
        
        # Add cogs
        await self.add_cog(chat_cog)
        print("✅ Chat cog added")
        await self.add_cog(speech_cog)
        print("✅ Speech Recognition cog added")

        # Start greetings task
        self.check_greetings.start()
        print("✅ Greetings scheduler started")

    async def on_ready(self):
        print(f'✅ Logged in as {self.user.name} ({self.user.id})')
        print('------')
        
        # Verify commands are registered properly
        print("🔍 Verifying command registration...")
        for command in self.commands:
            print(f"  ✅ Command registered: {command.name} (aliases: {command.aliases})")
        print(f"✅ Total bot commands found: {len(self.commands)}")
        
        print("✅ Music player functionality has been removed as requested")
        print("✅ Only voice commands for TTS and voice chat are available")

    async def on_command_error(self, ctx, error):
        """Global error handler"""
        print(f"🔧 DEBUG: Command error: {type(error).__name__}: {error}")
        
        if isinstance(error, commands.CommandNotFound):
            # Reduced chatter for command not found
            pass
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("**BOBO! KULANG YUNG COMMAND MO!** TYPE MO `g!tulong` PARA MALAMAN MO PAANO GAMITIN!")
        elif isinstance(error, commands.CheckFailure):
            if ctx.command and ctx.command.name == "g":
                await ctx.send(f"**KUPAL DI KANAMAN ADMIN!!!** {ctx.author.mention} **TANGINA MO!**")
            else:
                await ctx.send(f"**BOBO!** WALA KANG PERMISSION PARA GAMITIN YANG COMMAND NA YAN!")
        else:
            print(f"Error: {error}")
            import traceback
            traceback.print_exc()

    @tasks.loop(minutes=1)
    async def check_greetings(self):
        """Check if it's time to send good morning or good night greetings"""
        if self.maintenance_mode:
            return
        
        # Get current time in Philippines timezone (UTC+8)
        ph_timezone = pytz.timezone('Asia/Manila')
        now = datetime.datetime.now(ph_timezone)
        current_hour = now.hour
        current_date = now.date()
        
        # Get the greetings channel
        channel = self.get_channel(Config.GREETINGS_CHANNEL_ID)
        if not channel:
            return
        
        # Check if it's time for good morning greeting (8:00 AM)
        if (current_hour == Config.GOOD_MORNING_HOUR and 
                (self.last_morning_greeting_date is None or self.last_morning_greeting_date != current_date)):
            
            # Get all online members
            online_members = [member for member in channel.guild.members 
                             if member.status == discord.Status.online and not member.bot]
            
            # If there are online members, mention them
            if online_members:
                mentions = " ".join([member.mention for member in online_members])
                morning_messages = [
                    f"**MAGANDANG UMAGA MGA GAGO!** {mentions} GISING NA KAYO! DALI DALI TRABAHO NA!",
                    f"**RISE AND SHINE MGA BOBO!** {mentions} TANGINA NIYO GISING NA! PRODUCTIVITY TIME!",
                    f"**GOOD MORNING MOTHERFUCKERS!** {mentions} WELCOME TO ANOTHER DAY OF YOUR PATHETIC LIVES!",
                    f"**HOY GISING NA!** {mentions} TANGHALI NA GAGO! DALI DALI MAG-TRABAHO KA NA!",
                    f"**AYAN! UMAGA NA!** {mentions} BILISAN MO NA! SIBAT NA SA TRABAHO!"
                ]
                await channel.send(random.choice(morning_messages))
                
                # Update last greeting date
                self.last_morning_greeting_date = current_date
                print(f"✅ Sent good morning greeting at {now}")
        
        # Check if it's time for good night greeting (10:00 PM)
        elif (current_hour == Config.GOOD_NIGHT_HOUR and 
                (self.last_night_greeting_date is None or self.last_night_greeting_date != current_date)):
            
            night_messages = [
                "**TULOG NA MGA GAGO!** TANGINANG MGA YAN PUYAT PA MORE! UUBUSIN NIYO BUHAY NIYO SA DISCORD? MAAGA PA PASOK BUKAS!",
                "**GOOD NIGHT MGA HAYOP!** MATULOG NA KAYO WALA KAYONG MAPAPALA SA PAGIGING PUYAT!",
                "**HUWAG NA KAYO MAG-PUYAT GAGO!** MAAWA KAYO SA KATAWAN NIYO! PUTA TULOG NA KAYO!",
                "**10PM NA GAGO!** TULOG NA MGA WALA KAYONG DISIPLINA SA BUHAY! BILIS!",
                "**TANGINANG MGA TO! MAG TULOG NA KAYO!** WALA BA KAYONG TRABAHO BUKAS? UUBUSIN NIYO ORAS NIYO DITO SA DISCORD!"
            ]
            
            await channel.send(random.choice(night_messages))
            
            # Update last greeting date
            self.last_night_greeting_date = current_date
            print(f"✅ Sent good night greeting at {now}")

    @check_greetings.before_loop
    async def before_check_greetings(self):
        await self.wait_until_ready()

def run_flask():
    """Runs a dummy Flask server to keep Render active"""
    app = Flask(__name__)

    @app.route('/')
    def home():
        return "✅ Bot is running!"

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

def validate_discord_token(token):
    """Validate Discord token format without making API calls"""
    if not token:
        return False, "Token is empty"
    
    if len(token) < 50:
        return False, "Token is too short"
    
    if '.' not in token:
        return False, "Token should contain at least one period"
    
    return True, "Token format seems reasonable"

def main():
    """Main function to run the bot"""
    # Check for required environment variables
    if not Config.DISCORD_TOKEN:
        print("❌ Error: Discord token not found in environment variables")
        return
    
    # Validate token format
    is_valid, reason = validate_discord_token(Config.DISCORD_TOKEN)
    if not is_valid:
        print(f"❌ Error: Discord token validation failed - {reason}")
        print("⚠️ Please check your DISCORD_TOKEN environment variable")
        return

    if not Config.GROQ_API_KEY:
        print("❌ Error: Groq API key not found in environment variables")
        return
        
    # Check for PyAudio availability
    if not can_use_audio_features():
        print("⚠️ Running in text-only mode - voice features disabled")
        print("⚠️ This is normal when running on Render.com")
    else:
        print("✅ Full audio features enabled")

    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Initialize RateLimiter
    connection_limiter = RateLimiter()
    
    # "Ultimate Fix" Retry Loop
    print("🚀 Starting GNSLG Bot with ULTIMATE RETRY LOGIC")
    retry_count = 0
    
    while True:
        try:
            # Check if we need to wait due to rate limiting
            should_wait, wait_time = connection_limiter.check_backoff()
            
            if should_wait:
                print(f"⏳ Rate limit active. Waiting {wait_time:.1f} seconds...")
                time.sleep(wait_time + 5) # Extra buffer
            
            print(f"🔄 Connection Attempt {retry_count + 1}...")
            
            # Create a FRESH bot instance for every attempt
            bot = GinsilogBot()
            bot.run(Config.DISCORD_TOKEN)
            
            # If we get here, the bot disconnected gracefully
            print("✅ Bot disconnected gracefully.")
            # Reset rate limiter on successful run duration (if needed)
            break
            
        except discord.errors.LoginFailure:
            print("❌ FATAL: Invalid Discord Token. Please check your .env file.")
            return # Exit immediately, do not retry invalid tokens
            
        except discord.errors.HTTPException as e:
            retry_count += 1
            print(f"❌ HTTP Error: {e}")
            
            if e.status == 429 or "Too Many Requests" in str(e):
                print("🛑 HIT DISCORD RATE LIMIT (429)!")
                backoff = connection_limiter.record_rate_limit()
                print(f"🛑 Sleeping for {backoff:.1f} seconds to respect rate limit...")
                time.sleep(backoff)
            else:
                print("⚠️ HTTP Exception (non-429). Waiting 10s...")
                time.sleep(10)
                
        except Exception as e:
            retry_count += 1
            error_message = str(e).lower()
            print(f"❌ Error running bot: {e}")
            
            # Check for Cloudflare/Rate Limit keywords
            if "rate limit" in error_message or "cloudflare" in error_message or "403" in error_message:
                backoff = connection_limiter.record_rate_limit()
                print(f"🛑 Cloudflare/Rate Limit detected. BACKING OFF for {backoff:.1f} seconds...")
                time.sleep(backoff)
            else:
                print("⚠️ Unexpected error. Retrying in 10s...")
                time.sleep(10)

if __name__ == "__main__":
    main()
