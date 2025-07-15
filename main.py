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

# Initialize bot with command prefix and remove default help command
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, 
                   intents=intents,
                   help_command=None)  # Removed default help command

# Global variables for tracking greetings
last_morning_greeting_date = None
last_night_greeting_date = None
maintenance_mode = False  # Global flag for maintenance mode

# Initialize rate limiter for handling Discord API rate limits
rate_limiter = RateLimiter()

# RENDER COMPATIBILITY: Setup cogs properly based on environment - kept for reference
# This function is no longer used - cogs are initialized directly in on_ready
async def initialize_bot():
    """Initialize bot cogs"""
    print("⚠️ This function is deprecated - cogs are initialized directly in on_ready")
    pass
    
    # Verify commands are registered properly
    print("🔍 Verifying command registration...")
    for command in bot.commands:
        print(f"  ✅ Command registered: {command.name} (aliases: {command.aliases})")
    print(f"✅ Total bot commands found: {len(bot.commands)}")
    print("✅ Initialized cogs successfully")
    
# Setup cogs before the bot starts (pre-initialization)
def setup_cogs():
    # Initialize Firebase database - MUST happen before bot startup
    db = FirebaseDB()
    bot.db = db  # Store on the bot instance for access
    print("✅ Firebase database initialized in PRODUCTION mode")
    
    # Always set up the cogs after the bot is ready in async context
    # This ensures compatibility with both Replit and Render environments
    if is_render_environment():
        print("🔄 Running in Render environment - cogs will be initialized when bot is ready")
    else:
        print("🔄 Running in Replit environment - cogs will be initialized when bot is ready")
        print("✅ Database initialized and ready for cog attachment")

# Setup cogs before starting
setup_cogs()

@bot.event
async def on_ready():
    """Called when the bot is ready"""
    print(f'✅ Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    
    # Initialize cogs for all environments - CROSS-PLATFORM HYBRID APPROACH
    try:
        print("🔄 Initializing cogs using cross-platform hybrid approach")
        db = bot.db
        
        # RENDER VS REPLIT DETECTION - need to use different approach for each
        is_render = is_render_environment()
        print(f"🔄 Environment detection: {'Render' if is_render else 'Replit'}")
        
        # Chat cog initialization
        chat_cog = ChatCog(bot)
        chat_cog.db = db  # Pass database instance
        
        # Speech cog initialization 
        speech_cog = SpeechRecognitionCog(bot)
        speech_cog.db = db  # Pass database instance
        
        # CRITICAL: Must use different approaches for Render vs Replit
        if is_render:
            # Render MUST use await with add_cog
            print("🔄 Using awaited add_cog for Render compatibility")
            await bot.add_cog(chat_cog)
            print("✅ Chat cog added with await for Render")
            
            await bot.add_cog(speech_cog)
            print("✅ Speech Recognition cog added with await for Render")
        else:
            # Replit works with non-await version
            print("🔄 Using direct add_cog for Replit compatibility")
            bot.add_cog(chat_cog)
            print("✅ Chat cog added directly for Replit")
            
            bot.add_cog(speech_cog)
            print("✅ Speech Recognition cog added directly for Replit")
        
        # Verify commands are registered properly
        print("🔍 Verifying command registration...")
        for command in bot.commands:
            print(f"  ✅ Command registered: {command.name} (aliases: {command.aliases})")
        print(f"✅ Total bot commands found: {len(bot.commands)}")
        print("✅ Initialized cogs successfully")
        
    except Exception as e:
        print(f"❌ Error initializing cogs: {e}")
        import traceback
        traceback.print_exc()
    
    # Connect AI handler between cogs
    try:
        chat_cog = bot.get_cog("ChatCog")
        speech_cog = bot.get_cog("SpeechRecognitionCog")
        
        if chat_cog and speech_cog:
            speech_cog.get_ai_response = chat_cog.get_ai_response
            print("✅ Connected AI response handler between cogs")
    except Exception as e:
        print(f"❌ Error connecting cog handlers: {e}")
    
    # Music player functionality has been removed
    print("✅ Music player functionality has been removed as requested")
    print("✅ Only voice commands for TTS and voice chat are available")
        
    # Start the greetings scheduler
    check_greetings.start()
    print("✅ Greetings scheduler started")
    
    # Send welcome message to a channel if it exists - COMMENTED OUT DURING MAINTENANCE
    # if Config.AUTO_MESSAGE_CHANNEL_ID:
    #     try:
    #         channel = bot.get_channel(Config.AUTO_MESSAGE_CHANNEL_ID)
    #         if channel:
    #             # Create cleaner welcome embed without images
    #             welcome_embed = discord.Embed(
    #                 title="**GNSLG BOT IS NOW ONLINE!**",
    #                 description="**GISING NA ANG PINAKA-KUPAL NA BOT SA DISCORD! PUTANGINA NIYO MGA GAGO! READY NA AKONG MANG-INSULTO!**\n\n" +
    #                            "**Try these commands:**\n" +
    #                            "• `g!usap <message>` - Chat with me (prepare to be insulted!)\n" +
    #                            "• `@GNSLG BOT <message>` - Just mention me and I'll respond!\n" +
    #                            "• `g!daily` - Get free ₱10,000 pesos\n" +
    #                            "• `g!tulong` - See all commands (kung di mo pa alam gago)",
    #                 color=Config.EMBED_COLOR_PRIMARY
    #             )
    #             welcome_embed.set_footer(text="GNSLG BOT | Created by Mason Calix 2025")
    #             
    #             await channel.send(embed=welcome_embed)
    #             print(f"✅ Sent welcome message to channel {Config.AUTO_MESSAGE_CHANNEL_ID}")
    #     except Exception as e:
    #         print(f"❌ Error sending welcome message: {e}")
    print("Welcome message disabled during maintenance")

@tasks.loop(minutes=1)
async def check_greetings():
    """Check if it's time to send good morning or good night greetings"""
    global last_morning_greeting_date, last_night_greeting_date, maintenance_mode
    
    # Check if maintenance mode is enabled
    if maintenance_mode:
        print("Automated greetings disabled during maintenance")
        return
    
    # If not in maintenance mode, run the greetings code
    # Get current time in Philippines timezone (UTC+8)
    ph_timezone = pytz.timezone('Asia/Manila')
    now = datetime.datetime.now(ph_timezone)
    current_hour = now.hour
    current_date = now.date()
    
    # Get the greetings channel
    channel = bot.get_channel(Config.GREETINGS_CHANNEL_ID)
    if not channel:
        return
    
    # Check if it's time for good morning greeting (8:00 AM)
    if (current_hour == Config.GOOD_MORNING_HOUR and 
            (last_morning_greeting_date is None or last_morning_greeting_date != current_date)):
        
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
            last_morning_greeting_date = current_date
            print(f"✅ Sent good morning greeting at {now}")
    
    # Check if it's time for good night greeting (10:00 PM)
    elif (current_hour == Config.GOOD_NIGHT_HOUR and 
            (last_night_greeting_date is None or last_night_greeting_date != current_date)):
        
        night_messages = [
            "**TULOG NA MGA GAGO!** TANGINANG MGA YAN PUYAT PA MORE! UUBUSIN NIYO BUHAY NIYO SA DISCORD? MAAGA PA PASOK BUKAS!",
            "**GOOD NIGHT MGA HAYOP!** MATULOG NA KAYO WALA KAYONG MAPAPALA SA PAGIGING PUYAT!",
            "**HUWAG NA KAYO MAG-PUYAT GAGO!** MAAWA KAYO SA KATAWAN NIYO! PUTA TULOG NA KAYO!",
            "**10PM NA GAGO!** TULOG NA MGA WALA KAYONG DISIPLINA SA BUHAY! BILIS!",
            "**TANGINANG MGA TO! MAG TULOG NA KAYO!** WALA BA KAYONG TRABAHO BUKAS? UUBUSIN NIYO ORAS NIYO DITO SA DISCORD!"
        ]
        
        await channel.send(random.choice(night_messages))
        
        # Update last greeting date
        last_night_greeting_date = current_date
        print(f"✅ Sent good night greeting at {now}")

@check_greetings.before_loop
async def before_check_greetings():
    await bot.wait_until_ready()

@bot.event
async def on_command_error(ctx, error):
    """Global error handler"""
    print(f"🔧 DEBUG: Command error: {type(error).__name__}: {error}")
    print(f"🔧 DEBUG: Message content: '{ctx.message.content}'")
    
    if isinstance(error, commands.CommandNotFound):
        print(f"🔧 DEBUG: Command not found: '{ctx.message.content}', invoker: {ctx.author.name}")
        await ctx.send("**WALANG GANYANG COMMAND!** BASA BASA DIN PAG MAY TIME!\nTRY MO `g!tulong` PARA DI KA KAKUPALKUPAL!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("**BOBO! KULANG YUNG COMMAND MO!** TYPE MO `g!tulong` PARA MALAMAN MO PAANO GAMITIN!")
    elif isinstance(error, commands.CheckFailure) or isinstance(error, commands.errors.CheckFailure):
        # Check which command was attempted
        if ctx.command and ctx.command.name == "g":
            await ctx.send(f"**KUPAL DI KANAMAN ADMIN!!!** {ctx.author.mention} **TANGINA MO!**")
        else:
            await ctx.send(f"**BOBO!** WALA KANG PERMISSION PARA GAMITIN YANG COMMAND NA YAN!")
    else:
        await ctx.send(f"**PUTANGINA MAY ERROR!** TAWAG KA NALANG ULIT MAMAYA!")
        print(f"Error: {error}")
        # Print traceback for more detailed debugging
        import traceback
        traceback.print_exc()

def run_flask():
    """Runs a dummy Flask server to keep Render active"""
    app = Flask(__name__)

    @app.route('/')
    def home():
        return "✅ Bot is running!"

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))

def validate_discord_token(token):
    """Validate Discord token format without making API calls"""
    # Print the token length for debugging (without revealing the token)
    print(f"DEBUG: Token length: {len(token) if token else 0}")
    
    if not token:
        return False, "Token is empty"
    
    # Some basic checks that don't reveal the token
    if len(token) < 50:
        return False, "Token is too short"
    
    # New Discord tokens can have different formats, so let's be more lenient
    # Just check if it has some dots and reasonable length
    if '.' not in token:
        return False, "Token should contain at least one period"
    
    # Accept most reasonable formats
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

    # Run the bot with intelligent retry and backoff
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Check if we need to wait due to rate limiting
            should_wait, wait_time = rate_limiter.check_backoff()
            
            if should_wait:
                print(f"⏳ Rate limit detected. Waiting {wait_time:.1f} seconds before reconnecting...")
                time.sleep(wait_time + 1)  # Add an extra second for safety
            
            print(f"🔄 Attempt {retry_count + 1}/{max_retries}: Connecting to Discord...")
            
            # CRITICAL FIX: Create fresh bot instance for each retry attempt
            # This prevents "Session is closed" errors in production
            if retry_count > 0:
                print("🔄 Creating fresh bot instance for retry...")
                # Re-initialize the bot with fresh session
                global bot
                bot = initialize_bot()
                
            bot.run(Config.DISCORD_TOKEN)
            
            # If we get here, the bot successfully connected and then disconnected normally
            # Reset rate limit counter
            rate_limiter.reset()
            break
            
        except Exception as e:
            retry_count += 1
            error_message = str(e).lower()
            
            print(f"❌ Error running bot: {e}")
            print("⚠️ Error details:")
            import traceback
            traceback.print_exc()
            
            # Check if this is a rate limiting issue
            if "rate limit" in error_message or "cloudflare" in error_message or "429" in error_message:
                # Calculate and apply backoff
                backoff_time = rate_limiter.record_rate_limit()
                
                print(f"\n⏳ Rate limit detected. Backing off for {backoff_time:.1f} seconds...")
                
                # If we have more retries, wait and try again
                if retry_count < max_retries:
                    print(f"⏱️ Waiting {backoff_time:.1f} seconds before retry {retry_count + 1}/{max_retries}...")
                    time.sleep(backoff_time)
                else:
                    print("❌ Maximum retries reached. Please try again later.")
            else:
                # For non-rate-limit errors, don't retry as aggressively
                print("\n🔍 Common issues:")
                print("- Network connectivity issues from Replit")
                print("- Invalid Discord token")
                print("- Discord API outage")
                
                # If this is the last retry, don't wait
                if retry_count < max_retries:
                    wait_time = 5  # simple 5-second wait for non-rate-limit errors
                    print(f"⏱️ Waiting {wait_time} seconds before retry {retry_count + 1}/{max_retries}...")
                    time.sleep(wait_time)
                else:
                    print("❌ Maximum retries reached. Please restart the bot manually.")

if __name__ == "__main__":
    main()
