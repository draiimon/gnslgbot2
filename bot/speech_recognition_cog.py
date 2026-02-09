import asyncio
import discord
import os
import io
import time
import json
import threading
import subprocess
from bot.runtime_config import can_use_audio_features

# Conditionally import PyAudio-dependent modules
try:
    if can_use_audio_features():
        import speech_recognition as sr
        import edge_tts
        from pydub import AudioSegment
    else:
        # Create dummy imports for render compatibility
        sr = None
        edge_tts = None
        AudioSegment = None
except ImportError:
    print("⚠️ Speech recognition dependencies not available")
    sr = None
    edge_tts = None
    AudioSegment = None

from discord.ext import commands  # Make sure we always have commands

class SpeechRecognitionCog(commands.Cog):
    """Cog for handling speech recognition and voice interactions"""
    
    def __init__(self, bot):
        self.bot = bot
        self.listening_guilds = set()  # Set of guild IDs that are listening
        self.recognizer = sr.Recognizer() if sr else None  # type: ignore
        self.voice_clients = {}  # guild_id: voice_client
        self.tts_queue = {}  # guild_id: list of messages to speak
        self.listening_tasks = {}  # guild_id: asyncio task
        self.temp_dir = "temp_audio"
        self.connection_monitors = {}  # guild_id: task monitoring connection status
        self.monitor_task = None  # Will store the monitor task 
        self.commands_checked = False  # Flag to ensure commands are properly registered
        
        # Make sure temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
        
        print("🎤 SpeechRecognitionCog initialized with commands:")
        for cmd in self.__cog_commands__:
            print(f"  - {cmd.name} (aliases: {cmd.aliases})")
        
        # Default voice settings
        self.default_voice = "en-US-GuyNeural"
        # Voice preferences now stored in Firebase only
        
        # Track most recently active users in each guild for voice preferences
        self.last_user_speech = {}  # user_id: timestamp
        
        # Database connection (will be set from main.py)
        self.db = None
        
        # Get Groq client from the bot (assuming it's stored there)
        self.get_ai_response = None  # This will be set when the cog is loaded
        
        # We'll start our connection monitor task in on_ready instead of here
        # This fixes the "loop attribute cannot be accessed in non-async contexts" error
        
        print("✅ Speech Recognition Cog initialized with voice command support")
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready"""
        # Try to get the get_ai_response method from ChatCog
        print("🔍 Looking for AI response handler in cogs...")
        for cog_name, cog in self.bot.cogs.items():
            print(f"  - Checking cog: {cog_name}, type: {type(cog).__name__}")
            if hasattr(cog, 'get_ai_response'):
                self.get_ai_response = cog.get_ai_response
                print(f"✅ Found AI response handler in {cog_name}")
                break
        
        if not self.get_ai_response:
            print("❌ Could not find AI response handler - AI responses won't work!")
            
        # Verify all commands are properly registered
        if not self.commands_checked:
            print("🔍 Verifying command registration...")
            cmd_count = 0
            for cmd in self.bot.commands:
                cmd_count += 1
                if cmd.cog_name == self.__class__.__name__:
                    print(f"  ✅ Command registered: {cmd.name} (aliases: {cmd.aliases})")
            print(f"✅ Total bot commands found: {cmd_count}")
            self.commands_checked = True
            
        # Start the voice connection monitor task (moved from __init__ to fix Render deployment)
        if not self.monitor_task or self.monitor_task.done():
            print("🔄 Starting voice connection monitor task...")
            self.monitor_task = asyncio.create_task(self.monitor_voice_connections())
            print("✅ Voice connection monitor started")
    
    @commands.command(name="joinvc", aliases=["join", "summon"])
    async def joinvc(self, ctx):
        """Join your voice channel for TTS and voice commands"""
        print(f"🔧 DEBUG: joinvc command received from {ctx.author.name} in guild {ctx.guild.name}")
        if not ctx.author.voice:
            await ctx.send("**TANGA KA!** You need to be in a voice channel first!")
            return
        
        # Get the voice channel
        voice_channel = ctx.author.voice.channel
        
        # Check if bot is already connected via Discord.py's built-in voice client
        if ctx.guild.voice_client:
            # Already connected, just move to the new channel if needed
            if ctx.guild.voice_client.channel.id != voice_channel.id:
                await ctx.guild.voice_client.move_to(voice_channel)
                print(f"✅ Moved to voice channel: {voice_channel.name}")
            else:
                print(f"✅ Already connected to {voice_channel.name}")
        else:
            # Not connected, connect to the voice channel
            try:
                voice_client = await voice_channel.connect()
                print(f"✅ Connected to voice channel: {voice_channel.name}")
            except Exception as e:
                print(f"❌ Error connecting to voice channel: {e}")
                await ctx.send(f"**ERROR!** Cannot connect to voice channel: {e}")
                return
        
        # Update our internal tracking
        self.voice_clients[ctx.guild.id] = ctx.guild.voice_client
        
        # Start listening
        self.listening_guilds.add(ctx.guild.id)
        if ctx.guild.id not in self.tts_queue:
            self.tts_queue[ctx.guild.id] = []
        
        # Inform user
        await ctx.send(f"🎤 **GAME NA!** I'm now in **{voice_channel.name}**! Just type g!vc <message> and I'll speak it!")
        
    @commands.command(name="vc", aliases=["speak", "sabihin", "tts"])
    async def voice_command(self, ctx, *, message: str = None):  # type: ignore
        """Use text-to-speech to speak a message in your voice channel"""
        if not message:
            await ctx.send("**LOKO KA BA?** Tell me what to say!")
            return
            
        if not ctx.author.voice:
            await ctx.send("**TANGA KA!** You need to be in a voice channel first!")
            return
            
        # Connect to the voice channel if not already connected
        if ctx.guild.id not in self.voice_clients or not self.voice_clients[ctx.guild.id].is_connected():
            await self.joinvc(ctx)
            
        # Queue the message for TTS
        await self.speak_message(ctx.guild.id, message)
        await ctx.message.add_reaction("🔊")  # React to confirm received

    @commands.command()
    async def listen(self, ctx, *, question: str = None):  # type: ignore
        """Start listening for voice commands in your current voice channel or ask a direct question"""
        if not ctx.author.voice:
            await ctx.send("**TANGA KA!** You need to be in a voice channel first!")
            return
        
        # Connect to the voice channel
        voice_channel = ctx.author.voice.channel
        if ctx.guild.id in self.voice_clients:
            # Already connected, just move to the new channel if needed
            if self.voice_clients[ctx.guild.id].channel.id != voice_channel.id:
                await self.voice_clients[ctx.guild.id].move_to(voice_channel)
        else:
            # Connect to new channel
            voice_client = await voice_channel.connect()
            self.voice_clients[ctx.guild.id] = voice_client
        
        # Start listening
        self.listening_guilds.add(ctx.guild.id)
        if ctx.guild.id not in self.tts_queue:
            self.tts_queue[ctx.guild.id] = []
        
        # DIRECT QUESTION MODE - Process the question immediately if provided with the command
        if question:
            # Process the question directly
            await self.handle_voice_command(ctx.guild.id, ctx.author.id, question)
            return
        
        # LISTENING MODE - If no question was provided, start listening mode
        # Inform user
        await ctx.send(f"🎤 **GAME NA!** I'm now in **{voice_channel.name}**! Just type your message and I'll respond!")
        
        # Start listening for audio (in a separate task)
        if ctx.guild.id in self.listening_tasks and not self.listening_tasks[ctx.guild.id].done():
            self.listening_tasks[ctx.guild.id].cancel()
        
        # Create a new listening task for this guild
        self.listening_tasks[ctx.guild.id] = asyncio.create_task(self.start_listening_for_speech(ctx))
        
        # No need to speak any welcome message - let's be faster and cleaner
        # await self.speak_message(ctx.guild.id, "Ginslog Bot is now listening! Just type your message in chat and I'll respond!")
    
    async def start_listening_for_speech(self, ctx):
        """Listen for voice commands using a Discord-compatible approach"""
        guild_id = ctx.guild.id
        
        # Set up the voice channel
        voice_channel = ctx.author.voice.channel if ctx.author.voice else None
        if not voice_channel:
            return
            
        # Log that we're starting to listen
        print(f"🎧 Starting voice listening in {voice_channel.name} for guild {guild_id}")
        
        # No confirmation message needed - keep interaction clean and simple
        
        # In listening mode, just keep the task alive to maintain the connection
        while guild_id in self.listening_guilds:
            try:
                # Just keep the task alive and monitor the voice channel
                await asyncio.sleep(60)
            except Exception as e:
                print(f"⚠️ Error in listening task: {e}")
                await asyncio.sleep(10)
        
        print(f"🛑 Stopped listening in guild {guild_id}")
    
    @commands.command(name="leave", aliases=["disconnect", "dc", "bye"])
    async def leave(self, ctx):
        """Disconnect the bot from your voice channel"""
        if ctx.guild.id in self.voice_clients and self.voice_clients[ctx.guild.id].is_connected():
            await self.voice_clients[ctx.guild.id].disconnect()
            del self.voice_clients[ctx.guild.id]
            self.listening_guilds.discard(ctx.guild.id)
            
            # Cancel any active listening task
            if ctx.guild.id in self.listening_tasks:
                try:
                    self.listening_tasks[ctx.guild.id].cancel()
                except:
                    pass
                
            await ctx.send("👋 **SIGE! ALIS NA AKO!** Leaving voice channel as requested.")
        else:
            await ctx.send("**TANGA KA BA?** I'm not in any voice channel.")
    
    @commands.command()
    async def stoplisten(self, ctx):
        """Stop listening for voice commands"""
        if ctx.guild.id in self.listening_guilds:
            # Clean up resources
            self.listening_guilds.discard(ctx.guild.id)
            
            # Cancel the listening task
            if ctx.guild.id in self.listening_tasks:
                try:
                    self.listening_tasks[ctx.guild.id].cancel()
                    print(f"🛑 Cancelled listening task for guild {ctx.guild.id}")
                except:
                    pass
            
            # Disconnect from voice
            if ctx.guild.id in self.voice_clients:
                await self.voice_clients[ctx.guild.id].disconnect()
                del self.voice_clients[ctx.guild.id]
            
            await ctx.send("🛑 **OKS LANG!** I've stopped listening for voice commands.")
        else:
            await ctx.send("**LOKO KA BA?** I wasn't listening in any channel.")
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for special speech recognition commands and handle Auto TTS"""
        # Skip messages from bots or non-guild messages
        if message.author.bot or not message.guild:
            return
            
        # PART 1: Handle Auto TTS functionality using Firebase
        try:
            if self.db:
                # Get auto TTS settings from Firebase
                auto_tts_channels = self.db.get_auto_tts_channels()
                
                # Check if this channel is in the auto TTS list
                guild_id = str(message.guild.id)
                channel_id = str(message.channel.id)
                
                if guild_id in auto_tts_channels and channel_id in auto_tts_channels[guild_id]:
                    # Channel has auto TTS enabled, speak the message if it's not a command
                    if not message.content.startswith(self.bot.command_prefix):
                        # Connect to voice channel if needed
                        if message.author.voice:
                            await self._ensure_voice_connection(message.author.voice.channel)
                            
                            # Format the message for TTS
                            tts_message = f"{message.author.display_name} says: {message.content}"
                            
                            # Speak the message
                            await self.speak_message(message.guild.id, tts_message)
        except Exception as e:
            print(f"Error in Auto TTS: {e}")
            
        # We've removed the code that automatically processes all messages in listening channels
        # The bot will now only respond to explicit g!ask commands
        # This change was made as per the user's request to prevent automatic responses to messages
        # Users must now use g!ask explicitly
    
    async def handle_voice_command(self, guild_id, user_id, command):
        """Process a voice command from a user"""
        print(f"🗣️ Processing voice command from user {user_id}: '{command}'")
        
        # No manipulation of the command needed - let the AI handle it naturally
        # with its personality mirroring directive
            
        # Update last user speech timestamp
        self.last_user_speech[user_id] = time.time()
        
        # First, check if this is a voice change request
        voice_change_patterns = [
            "palit voice", "palit boses", "gawin mong lalaki voice", "babae voice", 
            "gusto ko lalaki", "gusto ko babae", "lalaki na voice", "babae na voice",
            "change voice", "voice to male", "voice to female", "male voice", "female voice"
        ]
        
        # Check if the command contains any voice change patterns
        is_voice_change = any(pattern in command.lower() for pattern in voice_change_patterns)
        
        # Additional voice change detection - smart patterns based on AI context
        ai_voice_commands = [
            "change your voice", "use male voice", "use female voice", 
            "speak like a man", "speak like a woman", "speak as a man", "speak as a woman",
            "as a man", "as a woman", "switch to male", "switch to female",
            "be a man", "be a woman", "talk like a guy", "talk like a girl",
            "palit ka voice", "palit ka boses", "maging lalaki ka", "maging babae ka"
        ]
        
        ai_instruction_change = any(pattern in command.lower() for pattern in ai_voice_commands)
        
        if is_voice_change or ai_instruction_change:
            # Determine gender from command
            male_patterns = ["lalaki", "male", "guy", "boy", "man", "as a man", "like a man", "speak as a man"]
            female_patterns = ["babae", "female", "girl", "woman", "as a woman", "like a woman", "speak as a woman"]
            
            # Default to male if command doesn't specify
            cmd_lower = command.lower()
            gender = "m"  # Default
            
            # Determine gender based on what's in the command
            if any(pattern in cmd_lower for pattern in female_patterns):
                gender = "f"
            elif any(pattern in cmd_lower for pattern in male_patterns):
                gender = "m"
            
            # Find the audio cog
            audio_cog = None
            for cog_name, cog in self.bot.cogs.items():
                if "audio" in cog_name.lower():
                    audio_cog = cog
                    break
            
            if audio_cog:
                try:
                    # Update user voice preference in Firebase
                    self.db.set_user_voice_preference(user_id, gender)  # type: ignore
                    gender_name = "male" if gender == "m" else "female"
                    
                    # Get the guild and a text channel
                    guild = self.bot.get_guild(guild_id)
                    if guild:
                        # Find a suitable text channel
                        for channel in guild.text_channels:
                            if channel.permissions_for(guild.me).send_messages:
                                await channel.send(f"**VOICE CHANGED TO {gender_name.upper()}!** 👨 🔊")
                                break
                    
                    # Speak a confirmation with the new voice
                    await self.speak_message(guild_id, f"Voice changed to {gender_name}. This is how I sound now!")
                    
                    # Log the change
                    print(f"✅ User {user_id} changed voice preference to {gender_name} through AI")
                    return True
                except Exception as e:
                    print(f"❌ Error changing voice through cog: {e}")
                    import traceback
                    traceback.print_exc()
        
        # Continue with regular command processing
        # First, check if we have the AI response handler
        if not self.get_ai_response:
            print("❌ ERROR: No AI response handler available!")
            await self.speak_message(guild_id, "Sorry, I can't process AI responses right now. The AI handler is not connected properly.")
            return
        else:
            print("✅ AI response handler is available")
        
        # Get the guild and channel
        guild = self.bot.get_guild(guild_id)
        if not guild:
            print(f"❌ ERROR: Could not find guild with ID {guild_id}")
            return
        
        # Don't send logs to any channel for voice commands (g!ask)
        # Only log to console and speak the response
        text_channel = None
        
        # Skip the error for having no text channel - we deliberately don't want one here
        
        # Get the member
        member = guild.get_member(int(user_id))
        if not member:
            print(f"❌ ERROR: Could not find member with ID {user_id}")
            return
        
        # Create conversation context for AI
        conversation = [
            {"is_user": True, "content": command}
        ]
        
        # Only log to console what the user asked - no channel message
        print(f"🎤 User {member.display_name}: {command}")
        
        # Get AI response
        try:
            print(f"🧠 Generating AI response for command: '{command}'")
            response = await self.get_ai_response(conversation)
            print(f"✅ AI response generated: '{response[:50]}...'")
            
            # No text channel logging - only speak the response
            await self.speak_message(guild_id, response)
        except Exception as e:
            error_message = f"Error generating response: {str(e)}"
            print(f"❌ AI ERROR: {error_message}")
            import traceback
            traceback.print_exc()
            await self.speak_message(guild_id, "Sorry, I encountered an error processing your request.")
    
    async def speak_message(self, guild_id, message):
        """Use TTS to speak a message in the voice channel using in-memory processing"""
        # Check if we're connected to voice and try to reconnect if needed
        if guild_id not in self.voice_clients or not self.voice_clients[guild_id].is_connected():
            # Try to reconnect if we know the channel
            try:
                # Find the guild
                guild = self.bot.get_guild(guild_id)
                if guild:
                    # Try to find any voice channel with members in it
                    for voice_channel in guild.voice_channels:
                        if len(voice_channel.members) > 0:
                            # Found a channel with users, try to connect
                            print(f"🔄 Auto-reconnecting to {voice_channel.name} in {guild.name}")
                            await self._ensure_voice_connection(voice_channel)
                            break
            except Exception as e:
                print(f"⚠️ Error auto-reconnecting: {e}")
                return
            
            # If we still don't have a connection, return
            if guild_id not in self.voice_clients or not self.voice_clients[guild_id].is_connected():
                print(f"⚠️ Cannot speak message in guild {guild_id} - no voice connection")
                return
        
        # Add to the queue
        if guild_id not in self.tts_queue:
            self.tts_queue[guild_id] = []
        self.tts_queue[guild_id].append(message)
        
        # Process the queue if we're not already speaking
        if not self.voice_clients[guild_id].is_playing():
            await self.process_tts_queue(guild_id)
            
        return message  # Return for callback tracking
    
    async def process_tts_queue(self, guild_id):
        """Process messages in the TTS queue using in-memory approach"""
        if guild_id not in self.tts_queue or not self.tts_queue[guild_id]:
            return
        
        # Get the next message
        message = self.tts_queue[guild_id].pop(0)
        
        # Normalize text to handle fancy fonts
        try:
            from bot.text_normalizer import normalize_text
            # Normalize the message content
            original_message = message
            message = normalize_text(message)
            if original_message != message:
                print(f"🔄 Normalized TTS text: '{original_message}' -> '{message}'")
        except ImportError:
            print("⚠️ Text normalizer not found, skipping normalization")
        except Exception as e:
            print(f"⚠️ Error normalizing text: {e}")
        
        # Generate TTS audio directly in memory
        try:
            # Detect language (simplified version)
            language = "en"
            tagalog_words = ["ako", "ikaw", "siya", "kami", "tayo", "kayo", "sila", "na", "at", "ang", "mga"]
            if any(word in message.lower() for word in tagalog_words):
                language = "fil"
            
            # Get the audio cog for voice preferences
            audio_cog = None
            user_preferences = {}
            for cog_name, cog in self.bot.cogs.items():
                if "audio" in cog_name.lower():
                    try:
                        audio_cog = cog
                        # Get access to the user voice preferences
                        if hasattr(cog, 'user_voice_preferences'):
                            user_preferences = cog.user_voice_preferences
                        break
                    except Exception as e:
                        print(f"Error accessing audio cog: {e}")
                        break
            
            # Determine user from guild context
            current_user_id = None
            for guild in self.bot.guilds:
                if guild.id == guild_id:
                    # Find the most active voice user
                    for member in guild.members:
                        if member.id in self.last_user_speech:
                            current_user_id = member.id
                            break
            
            # Get gender preference from Firebase, fallback to default
            gender_preference = "f"  # Default to female
            
            # Check for user preferences in Firebase
            if current_user_id and self.db:
                try:
                    # Get voice preference from Firebase
                    gender_preference = self.db.get_user_voice_preference(current_user_id)
                except Exception as e:
                    print(f"⚠️ Error getting voice preference from Firebase: {e}")
                    # Fallback to default
            
            # Choose voice based on language and gender
            if language == "fil":
                # Filipino voices
                voice = "fil-PH-AngeloNeural" if gender_preference == "m" else "fil-PH-BlessicaNeural"
            else:
                # English voices
                voice = "en-US-GuyNeural" if gender_preference == "m" else "en-US-JennyNeural"
            
            # Generate unique filename for this TTS
            timestamp = int(time.time() * 1000)
            temp_file = os.path.join(self.temp_dir, f"tts_{timestamp}.mp3")
            
            # Generate TTS audio and save to temporary file
            tts = edge_tts.Communicate(text=message, voice=voice, rate="+10%", volume="+30%")  # type: ignore
            await tts.save(temp_file)  # type: ignore
            
            # Verify voice client is still connected before playing
            if guild_id not in self.voice_clients or not self.voice_clients[guild_id].is_connected():
                print(f"⚠️ Voice client disconnected, skipping TTS playback")
                # Clean up temp file
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                return
            
            # Create FFmpeg audio source with optimized settings for Discord
            source = discord.FFmpegPCMAudio(
                temp_file,
                options='-vn -ar 48000 -ac 2 -b:a 128k'
            )
            
            # Play the TTS message with cleanup callback
            def after_playback(error):
                if error:
                    print(f"⚠️ Error in TTS playback: {error}")
                
                # Clean up temp file after playback
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as e:
                    print(f"⚠️ Error cleaning up temp file: {e}")
                
                # Process next message
                asyncio.run_coroutine_threadsafe(
                    self.after_speaking(error, guild_id, None),
                    self.bot.loop
                )
            
            self.voice_clients[guild_id].play(source, after=after_playback)
            
            print(f"✅ Speaking message: {message[:50]}...")
            
        except Exception as e:
            print(f"⚠️ Error generating TTS: {e}")
            import traceback
            traceback.print_exc()
            
            # Process next message if any
            if self.tts_queue[guild_id]:
                await self.process_tts_queue(guild_id)
    
    async def after_speaking(self, error, guild_id, _):
        """Called after a TTS message has finished playing"""
        if error:
            print(f"⚠️ Error in TTS playback: {error}")
        
        # Process next message if any
        if guild_id in self.tts_queue and self.tts_queue[guild_id]:
            await self.process_tts_queue(guild_id)
    
    async def _ensure_voice_connection(self, voice_channel):
        """Ensure we have a voice connection to the specified channel"""
        guild_id = voice_channel.guild.id
        guild = voice_channel.guild
        
        # Check if we have a connection in our own tracking
        if guild_id in self.voice_clients and self.voice_clients[guild_id].is_connected():
            # Already connected, just move to the new channel if needed
            if self.voice_clients[guild_id].channel.id != voice_channel.id:
                await self.voice_clients[guild_id].move_to(voice_channel)
        else:
            # We don't have a valid connection in our tracking
            
            # Check if discord.py thinks we have a connection
            voice_client = guild.voice_client
            if voice_client and voice_client.is_connected():
                # Discord.py has a connection, use it instead of creating a new one
                self.voice_clients[guild_id] = voice_client
                
                # Move to the requested channel if needed
                if voice_client.channel.id != voice_channel.id:
                    await voice_client.move_to(voice_channel)
            else:
                # No connection exists anywhere, create a new one
                try:
                    voice_client = await voice_channel.connect()
                    self.voice_clients[guild_id] = voice_client
                except discord.errors.ClientException as e:
                    # If we get "already connected" error, try to find and use the existing connection
                    if "Already connected" in str(e):
                        print(f"⚠️ Error connecting: {e}, attempting to find existing connection")
                        voice_client = guild.voice_client
                        if voice_client:
                            self.voice_clients[guild_id] = voice_client
                            # Move to requested channel
                            if voice_client.channel.id != voice_channel.id:
                                await voice_client.move_to(voice_channel)
                        else:
                            # If all else fails, force disconnect and try again
                            for vc in self.bot.voice_clients:
                                if vc.guild.id == guild_id:
                                    await vc.disconnect(force=True)
                            # Now try connecting again
                            voice_client = await voice_channel.connect()
                            self.voice_clients[guild_id] = voice_client
                    else:
                        # Some other error, re-raise
                        raise
        
        # Initialize TTS queue if needed
        if guild_id not in self.tts_queue:
            self.tts_queue[guild_id] = []
        
        return self.voice_clients[guild_id]
    
    @commands.command(name="autotts", aliases=["ttsauto"])
    async def autotts(self, ctx, action: str = None):  # type: ignore
        """Toggle automatic text-to-speech for a channel
        
        Usage:
        g!autotts toggle - Toggle auto TTS in the current channel
        """
        try:
            if not self.db:
                await ctx.send("⚠️ **ERROR:** Firebase database connection is required for auto TTS")
                return
                
            # Toggle auto TTS for the channel in Firebase
            enabled = self.db.toggle_auto_tts_channel(ctx.guild.id, ctx.channel.id)
            
            # Inform the user
            status = "ENABLED" if enabled else "DISABLED"
            await ctx.send(f"🔊 **AUTO TTS {status}!** Text-to-speech is now {'ON' if enabled else 'OFF'} for this channel.")
            
        except Exception as e:
            await ctx.send(f"❌ **ERROR:** {str(e)}")
            import traceback
            traceback.print_exc()
    
    @commands.command(name="ask")
    async def ask(self, ctx, *, question: str):
        """Quick voice response to a question (no need for g!joinvc first)"""
        try:
            # Check if user is in a voice channel
            if not ctx.author.voice:
                await ctx.send("**TANGA KA!** You need to be in a voice channel first!")
                return
                
            voice_channel = ctx.author.voice.channel
            
            # Connect to voice channel using our helper - SILENTLY
            # No join message or acknowledgement, just connect
            await self._ensure_voice_connection(voice_channel)
            
            # Process and answer the question directly - ultra clean flow
            await self.handle_voice_command(ctx.guild.id, ctx.author.id, question)
            
        except Exception as e:
            await ctx.send(f"❌ **ERROR:** {str(e)}")
            import traceback
            traceback.print_exc()
            
    @commands.command(name="change")
    async def change_voice(self, ctx, gender: str):
        """Change the bot's voice to male (m) or female (f)"""
        try:
            # Validate the gender parameter
            if gender.lower() not in ['m', 'f', 'male', 'female']:
                await ctx.send("**TANGA KA!** Use `m` or `f` para mag-change ng voice (e.g., `g!change m` or `g!change f`)!")
                return
                
            # Normalize the gender
            normalized_gender = 'm' if gender.lower() in ['m', 'male'] else 'f'
            gender_name = "male" if normalized_gender == 'm' else "female"
            
            # Store the preference in Firebase if available
            # Always use Firebase for voice preferences in production mode
            self.db.set_user_voice_preference(ctx.author.id, normalized_gender)  # type: ignore
            print(f"✅ Saved voice preference to Firebase: User {ctx.author.id} preference {normalized_gender}")
            # Connect to voice if needed
            if not ctx.author.voice:
                await ctx.send(f"**VOICE CHANGED TO {gender_name.upper()}!** 👨 🔊\nPero wala kang voice channel, pumasok ka muna sa voice!")
                return
                
            voice_channel = ctx.author.voice.channel
            await self._ensure_voice_connection(voice_channel)
            
            # Confirm the change via voice message
            await ctx.send(f"**VOICE CHANGED TO {gender_name.upper()}!** 👨 🔊")
            await self.speak_message(ctx.guild.id, f"Voice changed to {gender_name}. This is how I sound now!")
            
        except Exception as e:
            await ctx.send(f"❌ **ERROR:** {str(e)}")
            import traceback
            traceback.print_exc()
            
    async def monitor_voice_connections(self):
        """Background task to monitor voice connections and ensure they stay active"""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                # Check all active voice connections
                for guild_id, voice_client in list(self.voice_clients.items()):
                    # Check if connection is still valid
                    if not voice_client.is_connected():
                        print(f"🔍 Detected disconnected voice client in guild {guild_id}")
                        
                        # Try to recover by finding a voice channel to reconnect to
                        guild = self.bot.get_guild(guild_id)
                        if guild:
                            reconnected = False
                            
                            # First, look for channels with members
                            for voice_channel in guild.voice_channels:
                                if len(voice_channel.members) > 0:
                                    try:
                                        # Try to reconnect to this channel
                                        print(f"🔄 Auto-reconnecting to {voice_channel.name} in {guild.name}")
                                        await self._ensure_voice_connection(voice_channel)
                                        reconnected = True
                                        
                                        # If this guild was in listening mode, send a message
                                        if guild_id in self.listening_guilds:
                                            for text_channel in guild.text_channels:
                                                if text_channel.permissions_for(guild.me).send_messages:
                                                    await text_channel.send("🔄 **Reconnected to voice channel!** I was disconnected but now I'm back.")
                                                    break
                                        
                                        break
                                    except Exception as e:
                                        print(f"⚠️ Error during auto-reconnect: {e}")
                            
                            if not reconnected:
                                print(f"❌ Could not find a suitable voice channel to reconnect to in guild {guild_id}")
                                # Remove from listening guilds if we couldn't reconnect
                                self.listening_guilds.discard(guild_id)
                
                # Sleep for a bit to avoid constant checking
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"⚠️ Error in voice connection monitor: {e}")
                await asyncio.sleep(30)  # Longer sleep on error

async def setup(bot):
    """Asynchronous setup function for the cog"""
    cog = SpeechRecognitionCog(bot)
    
    # Set database connection from bot instance
    if hasattr(bot, 'db'):
        cog.db = bot.db
    
    # Await to properly register all commands
    await bot.add_cog(cog)
    print("✅ Speech Recognition Cog loaded with await")