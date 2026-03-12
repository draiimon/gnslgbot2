import asyncio
import collections
import logging
import os
import sys
import time
import wave

import discord
from discord.ext import commands
from groq import Groq

from bot.config import Config
from bot.runtime_config import can_use_audio_features

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Suppress noisy voice_recv logs BEFORE importing the library
logging.getLogger('discord.ext.voice_recv.reader').setLevel(logging.WARNING)
logging.getLogger('discord.ext.voice_recv.opus').setLevel(logging.WARNING)
logging.getLogger('discord.ext.voice_recv.gateway').setLevel(logging.WARNING)

# Conditionally import PyAudio-dependent modules
try:
    if can_use_audio_features():
        import speech_recognition as sr
        import edge_tts
        from pydub import AudioSegment
        from discord.ext import voice_recv
    else:
        # Create dummy imports for render compatibility
        sr = None
        edge_tts = None
        AudioSegment = None
        voice_recv = None
except ImportError:
    print("⚠️ Speech recognition dependencies not available")
    sr = None
    edge_tts = None
    AudioSegment = None
    voice_recv = None

# Define base class handling for when dependency is missing
AudioSinkBase = voice_recv.AudioSink if voice_recv else object

class VoiceSink(AudioSinkBase):
    def __init__(self, cog, guild_id, target_user_id=None):
        if not voice_recv:
            return
            
        self.cog = cog
        self.guild_id = guild_id
        self.target_user_id = target_user_id  # Only listen to this user (None = listen to all)
        self.buffer = collections.deque(maxlen=1000)  # ~20 seconds of audio
        self.silence_threshold = 2000  # Increased to reduce false positives from background noise
        self.silence_duration = 0.0
        self.is_speaking = False
        self.audio_data = bytearray()
        self.last_speech_time = time.time()
        self.last_silence_log = 0.0  # Track last logged silence value
        self.processing = False
        self.sample_width = 2
        self.channels = 2
        self.sample_rate = 48000
        self._last_cleanup_at = 0.0

    def wants_opus(self):
        return False

    def write(self, user, data):
        if self.processing:
            return

        # Ignore bots and self
        if not user or user.bot:
            return
        
        # If we're filtering by user, only process audio from target user
        if self.target_user_id and user.id != self.target_user_id:
            return

        # Simple energy-based silence detection
        # This is a very basic implementation
        # For production, we might want to use webrtcvad
        
        # Convert PCM data to potential energy level
        try:
            # Check maximum amplitude in this chunk
            max_amp = 0
            for i in range(0, len(data.pcm), 2):
                sample = int.from_bytes(data.pcm[i:i+2], byteorder='little', signed=True)
                max_amp = max(max_amp, abs(sample))
            
            if max_amp > self.silence_threshold:
                if not self.is_speaking:
                    self.is_speaking = True
                    print(f"🗣️ Speech detected from {user.display_name} (amp: {max_amp})")
                
                self.silence_duration = 0.0
                self.last_silence_log = 0.0  # Reset silence log tracker
                self.audio_data.extend(data.pcm)
                self.last_speech_time = time.time()
            else:
                if self.is_speaking:
                    self.silence_duration += 0.02  # Each chunk is 20ms
                    self.audio_data.extend(data.pcm)
                    
                    
                    # Debug: Log silence progress every 0.5s
                    if self.silence_duration >= self.last_silence_log + 0.5:
                        print(f"⏱️ Silence: {self.silence_duration:.1f}s (need 0.8s to process)")
                        self.last_silence_log = self.silence_duration
                    
                    # Modern VAD: Shorter silence threshold for natural conversation (like ChatGPT 2026)
                    # 0.8s is enough to detect end of sentence without long awkward pauses
                    if self.silence_duration > 0.8:  # 800ms silence - modern voice detection!
                        self.is_speaking = False  # Reset flag BEFORE processing
                        
                        # Only process if not already processing (prevents queue buildup)
                        if not self.processing:
                            audio_to_process = bytes(self.audio_data)  # Copy the data
                            self.audio_data = bytearray()  # Clear for next recording
                            print(f"🔇 Silence detected from {user.display_name}, processing audio ({len(audio_to_process)} bytes)")
                            
                            if len(audio_to_process) < 96000:
                                print(f"â­ï¸ Skipping short audio clip ({len(audio_to_process)} bytes)")
                            else:
                                # Mark as processing to prevent overlapping transcriptions
                                self.processing = True
                                asyncio.run_coroutine_threadsafe(self.process_audio(user, audio_to_process), self.cog.bot.loop)
                        else:
                            # Already processing, discard this audio to prevent queue buildup
                            print(f"⏭️ Skipping audio from {user.display_name} - still processing previous speech")
                            self.audio_data = bytearray()
                        
        except Exception as e:
            print(f"Error in write: {e}")
            import traceback
            traceback.print_exc()

    async def process_audio(self, user, audio_data):
        if len(audio_data) < 96000:  # Ignore very short clips (<1.0s) - increased to reduce hallucinations
            print(f"⏭️ Skipping short audio clip ({len(audio_data)} bytes)")
            return
            
        self.processing = True
        try:
            # Save to temporary wav file
            timestamp = int(time.time() * 1000)
            filename = os.path.join(self.cog.temp_dir, f"recording_{self.guild_id}_{timestamp}.wav")
            
            with wave.open(filename, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.sample_width)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_data)
                
            # Transcribe with Groq
            if self.cog.groq_client:
                # Transcribe
                print(f"🎤 Transcribing audio for guild {self.guild_id}...")
                with open(filename, "rb") as file:
                    try:
                        transcription = await asyncio.to_thread(
                            self.cog.groq_client.audio.transcriptions.create,
                            file=(filename, file.read()),
                            model="whisper-large-v3",
                            temperature=0,
                            response_format="verbose_json",
                            prompt="",  # Empty prompt to reduce hallucinations
                        )
                        text = transcription.text.strip()
                        print(f"📝 Transcription: '{text}'")
                        
                        if text and len(text) > 2:  # Ignore empty or very short transcriptions
                            # Persist transcript like JanJan (messages table) for memory + auditing
                            try:
                                if self.cog.db and self.cog.db.connected:
                                    text_channel = self.cog._pick_text_channel(self.guild_id)
                                    if text_channel:
                                        self.cog.db.log_message(
                                            self.guild_id,
                                            int(text_channel.id),
                                            int(user.id if user else 0),
                                            str(user.display_name if user else "unknown"),
                                            text,
                                            is_bot=False,
                                        )
                            except Exception as e:
                                print(f"⚠️ Failed to persist STT transcript: {e}")

                            # Check if user said "stop" or "cancel"
                            if text.lower() in ["stop", "cancel", "hinto", "tigil", "tama na"]:
                                await self.cog.speak_message(self.guild_id, "Okay, stopping conversation.")
                                # We'll handle stopping in the cog
                                if self.guild_id in self.cog.listening_guilds:
                                    self.cog.listening_guilds.discard(self.guild_id)
                                    # Disconnect logic...
                            else:
                                # Process as a question
                                await self.cog.handle_voice_command(
                                    self.guild_id,
                                    user.id if user else 0,
                                    text,
                                    text_channel=self.cog._pick_text_channel(self.guild_id),
                                )

                                # JanJan-style: wait for TTS to finish before allowing next utterance
                                try:
                                    vc = self.cog.voice_clients.get(self.guild_id)
                                    if vc and vc.is_connected():
                                        deadline = time.time() + 30.0
                                        while vc.is_playing() and time.time() < deadline:
                                            await asyncio.sleep(0.1)
                                except Exception:
                                    pass
                                
                    except Exception as e:
                        if "429" in str(e):
                            print("⚠️ Groq Rate Limit Reached")
                            await self.cog.speak_message(self.guild_id, "Rate limit reached. Please wait a moment.")
                        else:
                            print(f"❌ Groq Error: {e}")
            
            # Cleanup
            if os.path.exists(filename):
                os.remove(filename)
                
        except Exception as e:
            print(f"Error processing audio: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.processing = False
            self.audio_data = bytearray()

    def cleanup(self):
        """Called when the audio sink is done being used"""
        self.audio_data = bytearray()
        self.buffer.clear()
        print(f"🧹 VoiceSink for guild {self.guild_id} cleaned up")
        # If the underlying voice_recv packet router dies (e.g., OpusError: corrupted stream),
        # the sink gets cleaned up but our listening task might still be running.
        # Trigger a best-effort restart on the bot loop.
        try:
            now = time.time()
            if now - self._last_cleanup_at < 3.0:
                return
            self._last_cleanup_at = now
            if getattr(self.cog, "bot", None) and getattr(self.cog.bot, "loop", None):
                asyncio.run_coroutine_threadsafe(
                    self.cog._on_sink_cleanup(self.guild_id),
                    self.cog.bot.loop,
                )
        except Exception:
            # Never let cleanup raise (called from voice thread)
            pass


class SpeechRecognitionCog(commands.Cog):
    """Cog for handling speech recognition and voice interactions"""
    
    def __init__(self, bot):
        self.bot = bot
        self.listening_guilds = set()  # Set of guild IDs that are listening
        self.recognizer = sr.Recognizer() if sr else None  # type: ignore
        self.voice_clients = {}  # guild_id: voice_client
        self.tts_queue = {}  # guild_id: list of messages to speak
        self.listening_tasks = {}  # guild_id: asyncio task
        self.active_voice_users = {}  # guild_id: user_id of active voice user
        self.temp_dir = "temp_audio"
        self.connection_monitors = {}  # guild_id: task monitoring connection status
        self.monitor_task = None  # Will store the monitor task 
        self.commands_checked = False  # Flag to ensure commands are properly registered
        self._listening_sessions = {}  # guild_id: {channel_id:int, target_user_id:int|None}
        self._receive_restart_inflight = set()  # guild_id currently restarting
        self._receive_restart_backoff_until = {}  # guild_id: monotonic seconds
        
        # Make sure temp directory exists
        os.makedirs(self.temp_dir, exist_ok=True)
        
        print("🎤 SpeechRecognitionCog initialized with commands:")
        for cmd in self.__cog_commands__:
            print(f"  - {cmd.name} (aliases: {cmd.aliases})")
        
        # Default voice settings
        self.default_voice = "en-US-GuyNeural"
        # Voice preferences now stored in Postgres
        
        # Track most recently active users in each guild for voice preferences
        self.last_user_speech = {}  # user_id: timestamp
        
        # Database connection (will be set from main.py)
        self.db = None
        self.saved_voice_state = None
        self.voice_state_restored = False
        
        # Get Groq client from the bot (assuming it's stored there)
        self.get_ai_response = None  # This will be set when the cog is loaded
        
        # Initialize Groq client
        try:
            self.groq_client = Groq(
                api_key=Config.GROQ_API_KEY,
                base_url="https://api.groq.com",
            )
            print("✅ Groq client initialized for STT")
        except Exception as e:
            print(f"⚠️ Failed to initialize Groq client: {e}")
            self.groq_client = None
        
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
            
        # Start the voice connection monitor task (moved from __init__ to fix Render deployment)
        if not self.monitor_task or self.monitor_task.done():
            print("🔄 Starting voice connection monitor task...")
            self.monitor_task = asyncio.create_task(self.monitor_voice_connections())
            print("✅ Voice connection monitor started")

        if not self.voice_state_restored:
            self.voice_state_restored = True
            self.bot.loop.create_task(self._restore_saved_voice_state())

    def _pick_text_channel(self, guild_id):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None

        for channel in guild.text_channels:
            try:
                if channel.permissions_for(guild.me).send_messages:
                    return channel
            except Exception:
                continue

        return None

    def _tts_available(self):
        return edge_tts is not None

    async def _deliver_voice_or_text(self, guild_id, message, *, user_id=None, text_channel=None):
        if self._tts_available():
            await self.speak_message(guild_id, message, user_id=user_id)
            return

        if text_channel:
            await text_channel.send(message)
            return

        fallback_channel = self._pick_text_channel(guild_id)
        if fallback_channel:
            await fallback_channel.send(message)

    def _persist_voice_state(self, guild_id, channel_id):
        if not self.db or not self.db.connected:
            return

        try:
            self.db.save_voice_state(guild_id, channel_id)
            self.saved_voice_state = {"guild_id": int(guild_id), "channel_id": int(channel_id)}
        except Exception as e:
            print(f"⚠️ Failed to persist voice state: {e}")

    def _clear_persisted_voice_state(self):
        if not self.db or not self.db.connected:
            self.saved_voice_state = None
            return

        try:
            self.db.clear_voice_state()
        except Exception as e:
            print(f"⚠️ Failed to clear persisted voice state: {e}")
        finally:
            self.saved_voice_state = None

    async def _restore_saved_voice_state(self):
        if not self.db or not self.db.connected:
            return

        try:
            saved_state = self.db.get_saved_voice_state()
            if not saved_state:
                return

            self.saved_voice_state = saved_state
            await asyncio.sleep(max(Config.VOICE_REJOIN_DELAY_SECONDS, 1))

            guild = self.bot.get_guild(int(saved_state["guild_id"]))
            if not guild:
                return

            channel = guild.get_channel(int(saved_state["channel_id"]))
            if channel and hasattr(channel, "connect"):
                print(f"🔄 Restoring saved voice channel: {channel.name}")
                await self._ensure_voice_connection(channel)
        except Exception as e:
            print(f"⚠️ Failed to restore saved voice state: {e}")



    
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
                if voice_recv:
                    voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
                else:
                    voice_client = await voice_channel.connect()
                print(f"✅ Connected to voice channel: {voice_channel.name}")
            except Exception as e:
                print(f"❌ Error connecting to voice channel: {e}")
                await ctx.send(f"**ERROR!** Cannot connect to voice channel: {e}")
                return
        
        # Update our internal tracking
        self.voice_clients[ctx.guild.id] = ctx.guild.voice_client
        self._persist_voice_state(ctx.guild.id, voice_channel.id)
        
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

        if not self._tts_available():
            await ctx.send("❌ TTS is unavailable on this host right now.")
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
            try:
                if voice_recv:
                    voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient)
                else:
                    voice_client = await voice_channel.connect()
                self.voice_clients[ctx.guild.id] = voice_client
                self._persist_voice_state(ctx.guild.id, voice_channel.id)
            except Exception as e:
                print(f"❌ Error connecting in listen command: {e}")
                await ctx.send(f"❌ Error connecting: {e}")
                return
        
        # Start listening
        self.listening_guilds.add(ctx.guild.id)
        if ctx.guild.id not in self.tts_queue:
            self.tts_queue[ctx.guild.id] = []
        
        # DIRECT QUESTION MODE - Process the question immediately if provided with the command
        if question:
            # Process the question directly
            await self.handle_voice_command(
                ctx.guild.id,
                ctx.author.id,
                question,
                text_channel=ctx.channel,
            )
            return

        if not voice_recv:
            self.listening_guilds.discard(ctx.guild.id)
            await ctx.send("❌ Live STT listening is unavailable on this host right now. Gumamit ka muna ng `g!ask <tanong>` para direct reply.")
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
    
    async def start_listening_for_speech(self, ctx, target_user_id=None):
        """Listen for voice commands using discord-ext-voice-recv
        
        Args:
            ctx: Command context
            target_user_id: If provided, only listen to this specific user
        """
        guild_id = ctx.guild.id
        
        # Set up the voice channel
        voice_channel = ctx.author.voice.channel if ctx.author.voice else None
        if not voice_channel:
            return
            
        # Log that we're starting to listen
        print(f"🎧 Starting voice listening in {voice_channel.name} for guild {guild_id}")
        
        # Connect if not connected
        vc = await self._ensure_voice_connection(voice_channel)
        
        try:
            # Check if voice_recv is available
            if not voice_recv:
                print("❌ discord-ext-voice-recv not available")
                await ctx.send("❌ Voice receiving is not available on this host.")
                return

            # Start receiving with optional user filter
            sink = VoiceSink(self, guild_id, target_user_id)
            vc.listen(sink)
            self._listening_sessions[guild_id] = {
                "channel_id": int(voice_channel.id),
                "target_user_id": int(target_user_id) if target_user_id else None,
            }
            user_filter_msg = f" (only listening to user {target_user_id})" if target_user_id else ""
            print(f"✅ Voice receiving started for guild {guild_id}{user_filter_msg}")
            
            # Keep the task alive and auto-reconnect if needed
            while guild_id in self.listening_guilds:
                if not vc.is_connected():
                    print(f"⚠️ Voice connection lost for guild {guild_id}, attempting to reconnect...")
                    try:
                        # Try to reconnect
                        vc = await self._ensure_voice_connection(voice_channel)
                        # Restart listening with same user filter
                        sink = VoiceSink(self, guild_id, target_user_id)
                        vc.listen(sink)
                        print(f"✅ Reconnected and resumed listening for guild {guild_id}")
                    except Exception as reconnect_error:
                        print(f"❌ Failed to reconnect: {reconnect_error}")
                        break
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"⚠️ Error in listening task: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print(f"🛑 Stopped listening in guild {guild_id}")
            # We don't stop listening explicitly here because the vc might be used for other things
            # But if we were truly done, we would call vc.stop_listening()

    async def _on_sink_cleanup(self, guild_id: int) -> None:
        """Called when voice_recv stops delivering audio (e.g., decoder/router crash)."""
        if guild_id not in self.listening_guilds:
            return

        # Simple per-guild backoff to avoid tight restart loops.
        now = time.monotonic()
        until = self._receive_restart_backoff_until.get(guild_id, 0.0)
        if now < until:
            return
        if guild_id in self._receive_restart_inflight:
            return

        self._receive_restart_inflight.add(guild_id)
        try:
            await asyncio.sleep(1.0)  # give discord.py a moment to settle after a crash

            session = self._listening_sessions.get(guild_id)
            if not session:
                return

            guild = self.bot.get_guild(guild_id)
            if not guild:
                return

            channel = guild.get_channel(int(session["channel_id"]))
            if not channel or not hasattr(channel, "connect"):
                return

            target_user_id = session.get("target_user_id")
            print(f"🔁 Restarting voice receiving for guild {guild_id} (reason: sink cleanup)")

            # Ensure connection is healthy, then restart listen with a new sink.
            vc = await self._ensure_voice_connection(channel)
            try:
                # Best-effort stop (may not exist on standard voice client)
                stop = getattr(vc, "stop_listening", None)
                if callable(stop):
                    stop()
            except Exception:
                pass

            sink = VoiceSink(self, guild_id, target_user_id)
            vc.listen(sink)
            print(f"✅ Voice receiving restarted for guild {guild_id}")

            # If it keeps failing, increase backoff gradually.
            self._receive_restart_backoff_until[guild_id] = time.monotonic() + 5.0
        except Exception as e:
            print(f"⚠️ Failed to restart voice receiving for guild {guild_id}: {e}")
            # Back off harder on failure
            self._receive_restart_backoff_until[guild_id] = time.monotonic() + 15.0
        finally:
            self._receive_restart_inflight.discard(guild_id)
    
    @commands.command(name="leave", aliases=["disconnect", "dc", "bye"])
    async def leave(self, ctx):
        """Disconnect the bot from your voice channel"""
        if ctx.guild.id in self.voice_clients and self.voice_clients[ctx.guild.id].is_connected():
            self._clear_persisted_voice_state()
            await self.voice_clients[ctx.guild.id].disconnect()
            del self.voice_clients[ctx.guild.id]
            self.listening_guilds.discard(ctx.guild.id)
            self._listening_sessions.pop(ctx.guild.id, None)
            
            # Clean up active voice user
            if ctx.guild.id in self.active_voice_users:
                del self.active_voice_users[ctx.guild.id]
            
            # Cancel any active listening task
            if ctx.guild.id in self.listening_tasks:
                try:
                    self.listening_tasks[ctx.guild.id].cancel()
                except:
                    pass
                
            await ctx.send("👋 **SIGE! ALIS NA AKO!** Leaving voice channel as requested.")
        else:
            await ctx.send("**TANGA KA BA?** I'm not in any voice channel.")
    
    @commands.command(name="stoplisten", aliases=["stop"])
    async def stoplisten(self, ctx):
        """Stop listening for voice commands"""
        if ctx.guild.id in self.listening_guilds:
            self._clear_persisted_voice_state()
            # Clean up resources
            self.listening_guilds.discard(ctx.guild.id)
            self._listening_sessions.pop(ctx.guild.id, None)
            
            # Clean up active voice user
            if ctx.guild.id in self.active_voice_users:
                del self.active_voice_users[ctx.guild.id]
            
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
            
        # PART 1: Handle Auto TTS functionality using the database
        try:
            if self.db:
                # Get auto TTS settings from the database
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
    
    async def handle_voice_command(self, guild_id, user_id, command, *, text_channel=None):
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
            
            try:
                self.db.set_user_voice_preference(user_id, gender)  # type: ignore
                gender_name = "male" if gender == "m" else "female"
                await self._deliver_voice_or_text(
                    guild_id,
                    f"Sige. {gender_name} voice na ako ngayon, gago.",
                    user_id=user_id,
                    text_channel=text_channel,
                )
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
            await self._deliver_voice_or_text(
                guild_id,
                "Sorry, I can't process AI responses right now. The AI handler is not connected properly.",
                user_id=user_id,
                text_channel=text_channel,
            )
            return
        else:
            print("✅ AI response handler is available")
        
        # Get the guild and channel
        guild = self.bot.get_guild(guild_id)
        if not guild:
            print(f"❌ ERROR: Could not find guild with ID {guild_id}")
            return
        
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
            response = await self.get_ai_response(
                conversation,
                channel_id=guild.voice_client.channel.id if guild.voice_client and guild.voice_client.channel else None,
                author_id=user_id,
                author_tag=f"{member.display_name} (@{member.name})" if member.display_name != member.name else member.display_name,
                voice_members=[m.display_name for m in guild.voice_client.channel.members if not m.bot]
                if guild.voice_client and guild.voice_client.channel
                else None,
            )
            print(f"✅ AI response generated: '{response[:50]}...'")
            
            await self._deliver_voice_or_text(
                guild_id,
                response,
                user_id=user_id,
                text_channel=text_channel,
            )

            # Persist bot reply to DB (messages table) like JanJan
            try:
                if self.db and self.db.connected:
                    if text_channel:
                        bot_user = getattr(self.bot, "user", None)
                        bot_id = int(getattr(bot_user, "id", 0) or 0)
                        bot_tag = str(getattr(bot_user, "name", "gnslg-bot") or "gnslg-bot")
                        self.db.log_message(
                            int(guild_id),
                            int(text_channel.id),
                            bot_id,
                            bot_tag,
                            response,
                            is_bot=True,
                        )
            except Exception as e:
                print(f"⚠️ Failed to persist bot voice reply: {e}")
        except Exception as e:
            error_message = f"Error generating response: {str(e)}"
            print(f"❌ AI ERROR: {error_message}")
            import traceback
            traceback.print_exc()
            await self._deliver_voice_or_text(
                guild_id,
                "Sorry, I encountered an error processing your request.",
                user_id=user_id,
                text_channel=text_channel,
            )
    
    async def speak_message(self, guild_id, message, user_id=None):
        """Use TTS to speak a message in the voice channel using in-memory processing"""
        if not self._tts_available():
            print(f"⚠️ TTS runtime unavailable for guild {guild_id}")
            return

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
        
        # Limit queue size to prevent memory issues and lag
        if len(self.tts_queue[guild_id]) >= 5:
            self.tts_queue[guild_id].pop(0)  # Remove oldest message
            print(f"⚠️ TTS queue full for guild {guild_id}, dropped oldest message")

        # Store as tuple (message, user_id)
        self.tts_queue[guild_id].append((message, user_id))
        
        # Process the queue if we're not already speaking
        if not self.voice_clients[guild_id].is_playing():
            await self.process_tts_queue(guild_id)
            
        return message  # Return for callback tracking
    
    async def process_tts_queue(self, guild_id):
        """Process messages in the TTS queue using in-memory approach"""
        if not self._tts_available():
            print(f"⚠️ Skipping TTS queue for guild {guild_id} because edge_tts is unavailable")
            self.tts_queue[guild_id] = []
            return

        if guild_id not in self.tts_queue or not self.tts_queue[guild_id]:
            return
        
        # Get the next message
        item = self.tts_queue[guild_id].pop(0)
        
        # Handle both old string format (if any lingering) and new tuple format
        if isinstance(item, tuple):
            message, user_id = item
        else:
            message = item
            user_id = None
        
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
            
            # Determine user from guild context or explicit user_id
            current_user_id = user_id
            if not current_user_id:
                for guild in self.bot.guilds:
                    if guild.id == guild_id:
                        # Find the most active voice user
                        for member in guild.members:
                            if member.id in self.last_user_speech:
                                current_user_id = member.id
                                break
            
            # Get gender preference from the database, fallback to default
            gender_preference = "f"  # Default to female
            
            # Check for user preferences in the database
            if current_user_id and self.db:
                try:
                    # Get voice preference from the database
                    gender_preference = self.db.get_user_voice_preference(current_user_id)
                    # print(f"DEBUG: Using voice preference '{gender_preference}' for user {current_user_id}")
                except Exception as e:
                    print(f"⚠️ Error getting voice preference from database: {e}")
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
            # Removed -ar 48000 -ac 2 to prevent "Multiple options" warnings
            source = discord.FFmpegPCMAudio(
                temp_file,
                options='-vn -loglevel warning'
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
    
    async def _safe_disconnect(self, guild):
        """Safely disconnect from voice channel handling all edge cases"""
        try:
            if guild.id in self.voice_clients:
                vc = self.voice_clients[guild.id]
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass
                self.voice_clients.pop(guild.id, None)
            
            if guild.voice_client:
                try:
                    await guild.voice_client.disconnect(force=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ Error during safe disconnect: {e}")

    async def _ensure_voice_connection(self, voice_channel):
        """Ensure the bot is connected to the voice channel, reconnecting if necessary"""
        try:
            # Check if we're already connected to the correct channel
            if voice_channel.guild.voice_client:
                if voice_channel.guild.voice_client.channel and voice_channel.id == voice_channel.guild.voice_client.channel.id:
                    if voice_channel.guild.voice_client.is_connected():
                        # Update our local tracking just in case
                        self.voice_clients[voice_channel.guild.id] = voice_channel.guild.voice_client
                        self._persist_voice_state(voice_channel.guild.id, voice_channel.id)
                        return voice_channel.guild.voice_client
                
                # If connected to wrong channel or dead connection, disconnect first
                print(f"🔄 optimizing connection to {voice_channel.name}...")
                await self._safe_disconnect(voice_channel.guild)
                await asyncio.sleep(1.0)  # Wait for cleanup

            print(f"🔄 Connecting to voice channel {voice_channel.name}...")
            
            # Try to connect with retries
            for attempt in range(3):
                try:
                    # Clean up any residual connection state
                    if attempt > 0:
                        await self._safe_disconnect(voice_channel.guild)
                        await asyncio.sleep(2.0 * attempt)

                    # Connect using VoiceRecvClient
                    if voice_recv:
                        voice_client = await voice_channel.connect(cls=voice_recv.VoiceRecvClient, timeout=30.0, reconnect=True)
                    else:
                        print("⚠️ voice_recv not found, falling back to standard voice client")
                        voice_client = await voice_channel.connect(timeout=30.0, reconnect=True)
                    
                    self.voice_clients[voice_channel.guild.id] = voice_client
                    self._persist_voice_state(voice_channel.guild.id, voice_channel.id)
                    
                    # Initialize TTS queue if needed
                    if voice_channel.guild.id not in self.tts_queue:
                        self.tts_queue[voice_channel.guild.id] = []
                        
                    print(f"✅ Connected to voice channel: {voice_channel.name}")
                    return voice_client
                
                except discord.ClientException as e:
                    print(f"⚠️ Connection attempt {attempt+1} failed: {e}")
                    # If it says already connected but we don't have it, try to fetch it
                    if "Already connected" in str(e):
                         if voice_channel.guild.voice_client:
                             return voice_channel.guild.voice_client
                         else:
                             # Weird zombie state, force disconnect
                             await self._safe_disconnect(voice_channel.guild)
                except Exception as e:
                    print(f"⚠️ Connection attempt {attempt+1} error: {e}")
            
            raise Exception("Failed to connect after 3 attempts")

        except Exception as e:
            print(f"❌ Error connecting to voice channel: {e}")
            # Clean up on failure
            await self._safe_disconnect(voice_channel.guild)
            raise e
    
    @commands.command(name="autotts", aliases=["ttsauto"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def autotts(self, ctx, action: str = None):  # type: ignore
        """Toggle automatic text-to-speech for a channel
        
        Usage:
        g!autotts toggle - Toggle auto TTS in the current channel
        """
        try:
            if not self.db:
                await ctx.send("⚠️ **ERROR:** Database connection is required for auto TTS")
                return
                
            # Toggle auto TTS for the channel in the database
            enabled = self.db.toggle_auto_tts_channel(ctx.guild.id, ctx.channel.id)
            
            # Inform the user
            status = "ENABLED" if enabled else "DISABLED"
            await ctx.send(f"🔊 **AUTO TTS {status}!** Text-to-speech is now {'ON' if enabled else 'OFF'} for this channel.")
            
        except Exception as e:
            await ctx.send(f"❌ **ERROR:** {str(e)}")
            import traceback
            traceback.print_exc()
    
    @commands.command(name="ask")
    @commands.cooldown(1, 3, commands.BucketType.user)  # Rate limit: 1 use every 3 seconds
    async def ask(self, ctx, *, question: str = None):
        """Quick voice response to a question or start listening mode"""
        try:
            # Check if user is in a voice channel
            if not ctx.author.voice:
                await ctx.send("**TANGA KA!** You need to be in a voice channel first!")
                return
                
            voice_channel = ctx.author.voice.channel
            
            # Connect to voice channel using our helper - SILENTLY
            # No join message or acknowledgement, just connect
            await self._ensure_voice_connection(voice_channel)
            
            if question:
                # Process and answer the question directly - ultra clean flow
                await self.handle_voice_command(
                    ctx.guild.id,
                    ctx.author.id,
                    question,
                    text_channel=ctx.channel,
                )
            else:
                if not voice_recv:
                    await ctx.send("❌ Live STT listening is unavailable on this host right now. Gumamit ka muna ng `g!ask <tanong>` para direct reply.")
                    return

                # Check if someone else is already using voice in this guild
                if ctx.guild.id in self.active_voice_users:
                    active_user_id = self.active_voice_users[ctx.guild.id]
                    if active_user_id != ctx.author.id:
                        active_user = ctx.guild.get_member(active_user_id)
                        active_name = active_user.display_name if active_user else "someone"
                        await ctx.send(f"**OY TANGA!** {active_name} is using voice right now! Let them finish first, mag-`g!stop` ka muna!")
                        return
                
                # Start continuous listening mode (like g!listen)
                
                # Mark this user as active for voice
                self.active_voice_users[ctx.guild.id] = ctx.author.id
                
                # Start listening
                self.listening_guilds.add(ctx.guild.id)
                if ctx.guild.id not in self.tts_queue:
                    self.tts_queue[ctx.guild.id] = []
                    
                # Inform user
                await ctx.send(f"🎤 **GAME NA!** I'm listening in **{voice_channel.name}**! Just speak and I'll respond! (Type `g!stop` to end)")
                
                # Get list of members in voice channel (excluding bots)
                members_in_vc = [m for m in voice_channel.members if not m.bot]
                member_names = [m.display_name for m in members_in_vc]
                
                # Create greeting message with proper Tagalog
                if len(member_names) == 0:
                    greeting = "HOY TANGA! Handa na akong makinig, mag-salita ka lang!"
                elif len(member_names) == 1:
                    greeting = f"HOY TANGA {member_names[0]}! Handa na akong makinig, mag-salita ka lang!"
                elif len(member_names) == 2:
                    greeting = f"HOY TANGA {member_names[0]} at {member_names[1]}! Handa na akong makinig, mag-salita ka lang!"
                else:
                    # 3 or more people
                    names_except_last = ", ".join(member_names[:-1])
                    greeting = f"HOY TANGA {names_except_last}, at {member_names[-1]}! Handa na akong makinig, mag-salita ka lang!"
                
                # Speak the greeting
                await self.speak_message(ctx.guild.id, greeting)
                
                # Start listening for audio (in a separate task)
                if ctx.guild.id in self.listening_tasks and not self.listening_tasks[ctx.guild.id].done():
                    self.listening_tasks[ctx.guild.id].cancel()
                
                # Create a new listening task for this guild (with user filter)
                self.listening_tasks[ctx.guild.id] = asyncio.create_task(
                    self.start_listening_for_speech(ctx, target_user_id=ctx.author.id)
                )
            
        except Exception as e:
            await ctx.send(f"❌ **ERROR:** {str(e)}")
            import traceback
            traceback.print_exc()
            
    @commands.command(name="change")
    @commands.cooldown(1, 2, commands.BucketType.user)  # Rate limit: 1 use every 2 seconds
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
            
            # Store the preference in the database
            self.db.set_user_voice_preference(ctx.author.id, normalized_gender)  # type: ignore
            print(f"✅ Saved voice preference to database: User {ctx.author.id} preference {normalized_gender}")
            # Connect to voice if needed
            if not ctx.author.voice:
                await ctx.send(f"**VOICE CHANGED TO {gender_name.upper()}!** 👨 🔊\nPero wala kang voice channel, pumasok ka muna sa voice!")
                return
                
            voice_channel = ctx.author.voice.channel
            await self._ensure_voice_connection(voice_channel)
            
            # Confirm the change via voice message
            await ctx.send(f"**VOICE CHANGED TO {gender_name.upper()}!** 👨 🔊")
            await self._deliver_voice_or_text(
                ctx.guild.id,
                f"Voice changed to {gender_name}. This is how I sound now!",
                user_id=ctx.author.id,
                text_channel=ctx.channel,
            )
            
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
                                        if guild_id in self.listening_guilds and voice_recv:
                                            # After a reconnect, ensure voice receiving is re-armed.
                                            await self._on_sink_cleanup(guild_id)
                                        
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

                if self.saved_voice_state:
                    saved_guild_id = int(self.saved_voice_state["guild_id"])
                    saved_channel_id = int(self.saved_voice_state["channel_id"])
                    saved_voice_client = self.voice_clients.get(saved_guild_id)
                    if not saved_voice_client or not saved_voice_client.is_connected():
                        guild = self.bot.get_guild(saved_guild_id)
                        if guild:
                            voice_channel = guild.get_channel(saved_channel_id)
                            if voice_channel and hasattr(voice_channel, "connect"):
                                print(f"🔄 Restoring persistent voice connection for guild {saved_guild_id}")
                                await self._ensure_voice_connection(voice_channel)
                
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
