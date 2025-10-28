import discord
from discord.ext import commands
from groq import Groq
import asyncio
from collections import deque, defaultdict
import time
import random
import datetime
import pytz  # For Philippines timezone
import os
import io
import re
import sys
from gtts import gTTS  # Google Text-to-Speech
from .config import Config
from .runtime_config import is_render_environment


class ChatCog(commands.Cog):
    """Cog for handling chat interactions with the Ginsilog AI and games"""

    def __init__(self, bot):
        self.bot = bot
        # Initialize Groq client with API key (uses the OpenAI-compatible interface)
        self.groq_client = Groq(
            api_key=Config.GROQ_API_KEY,
            base_url="https://api.groq.com"  # Fixed the base URL
        )
        self.conversation_history = defaultdict(
            lambda: deque(maxlen=Config.MAX_CONTEXT_MESSAGES))
        self.user_message_timestamps = defaultdict(list)
        self.creator = Config.BOT_CREATOR
        # Firebase database will be passed from main.py
        self.db = None
        self.user_coins = defaultdict(
            lambda: 50_000)  # Default bank balance: ₱50,000
        self.daily_cooldown = defaultdict(int)
        self.blackjack_games = {}
        self.ADMIN_ROLE_ID = 1345727357662658603

        # Setup for nickname scanning - RENDER FIX: only set task in async context
        self.nickname_update_task = None
        self.nickname_scanning_active = True

        # Setup for role-emoji mappings - dynamic configuration
        self.role_emoji_mappings = Config.ROLE_EMOJI_MAP.copy()  # Create local copy to support runtime additions

        # For debugging nickname issues
        self.debug_nickname_updates = True
        self.muted_users = {}

        # Custom banned words list (empty by default, will be populated by set_words command)
        self.custom_banned_words = []

        # Track users who are muted for violation to automatically unmute them
        self.muted_users = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """No longer automatically connects to voice channels - only on explicit command"""
        # Don't trigger on our own actions
        if member.id == self.bot.user.id:
            return
        # Channel didn't change, so not a join or leave event
        elif before.channel == after.channel:
            return
        # No longer auto-connecting to prevent unwanted rejoins
        # Now the bot will only connect when explicitly commanded

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Automatically format nickname of new members when they join"""
        # Skip bots
        if member.bot:
            return

        # Use the dynamic role-emoji mappings that includes admin updates
        role_emoji_map = self.role_emoji_mappings

        # Get member's roles sorted by position (highest first)
        member_roles = sorted(member.roles, key=lambda r: r.position, reverse=True)

        # Find the highest role that's in our mapping
        highest_matched_role_id = None
        for role in member_roles:
            if role.id in role_emoji_map:
                highest_matched_role_id = role.id
                break

        # If no matching role found, use default (no emoji)
        # We'll still convert their name to Unicode bold style
        if not highest_matched_role_id:
            # Use a default format with no emoji for @everyone
            emoji = ""  # No emoji for default users
            role_name = "@everyone"
        else:
            # Get the emoji for this role
            emoji = role_emoji_map[highest_matched_role_id]
            role_name = "Role"  # We don't need exact role name here

        # Format the name - only remove trailing emoji
        original_name = member.display_name

        # Clean the name using our centralized function (only removes trailing emojis)
        clean_name = self.clean_name_of_emojis(original_name, role_emoji_map)

        # Convert to Unicode bold style using config
        formatted_name = ''.join(Config.UNICODE_MAP.get(c, c) for c in clean_name)

        # Add the role emoji
        new_name = f"{formatted_name} {emoji}"

        # Skip if the name is already correctly formatted
        if member.display_name == new_name:
            return

        # Update the name
        try:
            await member.edit(nick=new_name)
            # Debug prints removed as requested to clean up logs
        except Exception:
            # Debug prints removed as requested to clean up logs
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the cog is ready - start the nickname scanning task"""
        # Now that bot is ready, set the task if it wasn't set in __init__
        if self.nickname_update_task is None:
            self.nickname_update_task = self.bot.loop.create_task(self._regular_nickname_scan())
            print(f"🔄 Starting automatic nickname maintenance task")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Automatically update nickname when a user's roles change or they change their nickname"""
        try:
            # Check what changed to help with debugging
            roles_changed = before.roles != after.roles
            nickname_changed = before.display_name != after.display_name

            # ALWAYS process when roles change OR nickname changes
            # The conditioning is kept here for logging purposes only
            if not (roles_changed or nickname_changed):
                return

            # Skip bots completely
            if after.bot:
                return

            # Use the dynamic role-emoji mappings that includes admin updates
            role_emoji_map = self.role_emoji_mappings
            role_names = Config.ROLE_NAMES

            change_type = "role change" if roles_changed else "nickname change"

            # Special check for owner changing their nickname (only when nickname changes)
            if after.id == after.guild.owner_id and nickname_changed:
                # Owner tried to change nickname manually - let's send them a helpful DM with proper format
                try:
                    # Get the correct emoji for the owner from our mapping
                    owner_emoji = "👑"  # Default emoji for Owner
                    if after.guild.owner_id in self.role_emoji_mappings:  # Owner role ID
                        owner_emoji = self.role_emoji_mappings[after.guild.owner_id]

                    # Use our centralized emoji cleaning function to remove ALL emojis
                    clean_name = self.clean_name_of_emojis(after.display_name)

                    # Format properly with Unicode bold
                    formatted_name = ''.join(Config.UNICODE_MAP.get(c, c) for c in clean_name)
                    suggested_name = f"{formatted_name} {owner_emoji}"

                    # Only send a DM if the format isn't already correct
                    if after.display_name != suggested_name:
                        # Create a DM embed with detailed formatting information
                        owner_embed = discord.Embed(
                            title="👑 Server Owner Nickname Format",
                            description=f"Hello Server Owner!\n\nYou've changed your nickname to **{after.display_name}**.\n\nTo match the server's format style, consider using:\n\n**{suggested_name}**\n\nThis includes your Owner role status with the {owner_emoji} emoji.",
                            color=0xFFD700  # Gold color for owner
                        )

                        owner_dm = await after.create_dm()
                        await owner_dm.send(embed=owner_embed)
                except Exception as e:
                    print(f"Failed to send DM to owner: {e}")

                # For server owner, we don't force change their nickname, just suggest it
                # So we return here
                return

            # Get member's roles sorted by position (highest first)
            member_roles = sorted(after.roles, key=lambda r: r.position, reverse=True)

            # Find the highest role that's in our mapping
            highest_matched_role_id = None
            for role in member_roles:
                if role.id in role_emoji_map:
                    highest_matched_role_id = role.id
                    break

            # If no matching role found, use default (no emoji)
            # We'll still convert their name to Unicode bold style
            if not highest_matched_role_id:
                # Use a default format with no emoji for @everyone
                emoji = ""  # No emoji for default users
                role_name = "@everyone"
            else:
                # Get the emoji for this role
                emoji = role_emoji_map[highest_matched_role_id]
                role_name = role_names.get(highest_matched_role_id, "Role")  # Get proper role name if available

            # Format the name - get original name without trailing emoji
            original_name = after.display_name

            # Use our centralized emoji cleaning function to only remove trailing emojis
            clean_name = self.clean_name_of_emojis(original_name, role_emoji_map)

            # Convert to Unicode bold style using config (preserves user's actual nickname)
            formatted_name = ''.join(Config.UNICODE_MAP.get(c, c) for c in clean_name)

            # Add the role emoji - just one emoji at the end as requested
            new_name = f"{formatted_name} {emoji}"

            # Skip if the name is already correctly formatted to prevent unnecessary edits
            if after.display_name == new_name:
                return

            # No longer skipping updates based on time
            # REALTIME updates as requested
            update_key = f"nickname_update_time_{after.id}"
            now = time.time()

            # Always update nickname immediately with no time-based skipping

            # Update the name (silently - no notifications)
            try:
                await after.edit(nick=new_name)
                # Store the timestamp of when we last updated this member
                self.user_message_timestamps[update_key] = now
                # Debug output for nickname changes
                print(f"✅ Auto-updated nickname for {after.name} due to {change_type}: {original_name} → {new_name}")
            except discord.Forbidden:
                # This will happen for members with higher permissions than the bot
                # The server owner will already get a DM from the special handling above
                pass
            except Exception as e:
                # Print general errors for troubleshooting
                print(f"❌ Error updating nickname for {after.name}: {e}")

        except Exception as e:
            # Handle any unexpected errors in the event handler
            print(f"❌ Error in on_member_update: {e}")

    async def _connect(self, channel):
        """Helper method to connect to a voice channel"""
        if channel.guild.voice_client is None:
            try:
                vc = await channel.connect()
                # Debug prints removed as requested to clean up logs
                return vc
            except Exception:
                # Debug prints removed as requested to clean up logs
                pass

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages that mention the bot and respond automatically and filter profanity"""
        # Ignore messages from the bot itself
        if message.author.bot:
            return

        # Profanity filter - now using dynamic word_actions dictionary
        content_lower = message.content.lower()

        # Create word_actions dictionary if it doesn't exist yet
        if not hasattr(self, 'word_actions'):
            self.word_actions = {
                # Default word actions
                "nigga": "both",      # Mute and disconnect
                "chingchong": "both", # Mute and disconnect
                "bading": "mute",     # Mute only 
                "tanga": "mute",      # Mute only
                "bobo": "mute"        # Mute only
            }

        # Get additional custom banned words from both sources
        custom_banned_words = getattr(self, 'custom_banned_words', [])

        # Build complete list of banned words from word_actions and custom_banned_words
        all_banned_words = list(self.word_actions.keys()) + [w for w in custom_banned_words if w not in self.word_actions]

        # Check for profanity
        detected_word = None
        for word in all_banned_words:
            if word in content_lower:
                detected_word = word
                break

        if detected_word:
            # Get the action type for this word (default to "mute" if not specified)
            action_type = self.word_actions.get(detected_word, "mute")
            # Create a warning embed
            warning_embed = discord.Embed(
                title="⚠️ VIOLATION DETECTED! ⚠️",
                description=f"{message.author.mention} USED A PROHIBITED WORD: `{detected_word}`",
                color=Config.EMBED_COLOR_ERROR
            )

            # Different messages based on action type
            if action_type == "both":
                warning_embed.add_field(name="ACTION TAKEN:", value="SERVER MUTED + DISCONNECTED FROM VOICE", inline=False)
                warning_embed.add_field(name="VIOLATION TYPE:", value="SEVERE VIOLATION", inline=False)
                warning_embed.add_field(name="MESSAGE:", value="ULOL BAWAL YAN DITO!", inline=False)
            elif action_type == "disconnect":
                warning_embed.add_field(name="ACTION TAKEN:", value="DISCONNECTED FROM VOICE", inline=False) 
                warning_embed.add_field(name="VIOLATION TYPE:", value="VOICE CHANNEL VIOLATION", inline=False)
            elif action_type == "mute":
                warning_embed.add_field(name="ACTION TAKEN:", value="SERVER MUTED", inline=False)
                warning_embed.add_field(name="VIOLATION TYPE:", value="TEXT CHANNEL VIOLATION", inline=False)

            try:
                # Apply proper action based on action_type
                if action_type == "mute" or action_type == "both":
                    # Server mute the user
                    await message.author.edit(mute=True)

                    # Set a timer to unmute after 60 seconds
                    self.muted_users[message.author.id] = {
                        "mute_time": time.time(),
                        "guild": message.guild
                    }

                    # Schedule automatic unmute after 60 seconds
                    self.bot.loop.create_task(self.auto_unmute_user(message.author.id, 60))

                    # Add unmute timing to the warning message
                    warning_embed.add_field(name="UNMUTE TIME:", value="You will be automatically unmuted after 60 seconds", inline=False)

                # Send warning message to the channel
                await message.channel.send(embed=warning_embed)

                # Disconnect from voice if action type requires it
                if action_type == "disconnect" or action_type == "both":
                    # Disconnect from voice channel if they're in one
                    if message.author.voice:
                        await message.author.move_to(None)  # Disconnect from voice

                    # 2. Try to send a DM to the user
                    try:
                        # Customize DM based on action type
                        action_text = {
                            "mute": "muted for 60 seconds",
                            "disconnect": "disconnected from voice channel",
                            "both": "muted AND disconnected from voice channel"
                        }

                        dm_embed = discord.Embed(
                            title="⚠️ SERVER VIOLATION WARNING ⚠️",
                            description=f"You have been {action_text[action_type]} for using the prohibited word: `{detected_word}`",
                            color=Config.EMBED_COLOR_ERROR
                        )

                        # Different reminder based on action type
                        if action_type == "both":
                            dm_embed.add_field(name="REMINDER:", value="Severe violations are strictly prohibited. Further violations may result in a ban.", inline=False)
                        elif action_type == "disconnect":
                            dm_embed.add_field(name="REMINDER:", value="Voice channel violations are not tolerated. Please follow server rules in voice channels.", inline=False)
                        else:
                            dm_embed.add_field(name="REMINDER:", value="Text channel violations will result in temporary mutes. Repeated violations may lead to longer punishment.", inline=False)

                        dm_channel = await message.author.create_dm()
                        await dm_channel.send(embed=dm_embed)
                    except Exception as e:
                        print(f"❌ Error sending DM to user for violation ({action_type}): {e}")

                    # 3. Post in announcements channel if configured
                    try:
                        announcements_channel = self.bot.get_channel(Config.ANNOUNCEMENTS_CHANNEL_ID)
                        if announcements_channel:
                            # Different titles based on action type
                            titles = {
                                "mute": "🔇 TEXT CHANNEL VIOLATION 🔇",
                                "disconnect": "🎤 VOICE CHANNEL VIOLATION 🎤",
                                "both": "🚫 SEVERE VIOLATION 🚫"
                            }

                            announce_embed = discord.Embed(
                                title=titles[action_type],
                                description=f"User {message.author.mention} used a prohibited word in {message.channel.mention}",
                                color=discord.Color.dark_red()
                            )
                            announce_embed.add_field(name="VIOLATION:", value=f"`{detected_word}`", inline=True)
                            announce_embed.add_field(name="TIME:", value=discord.utils.format_dt(message.created_at), inline=True)
                            announce_embed.add_field(name="ACTION:", value=action_type.upper(), inline=True)
                            announce_embed.set_footer(text="ULOL BAWAL YAN DITO!")

                            await announcements_channel.send(embed=announce_embed)
                    except Exception as e:
                        print(f"❌ Error posting to announcements channel for violation ({action_type}): {e}")
            except Exception as e:
                print(f"❌ Error applying punishment for profanity: {e}")

            # Try to delete the message
            try:
                await message.delete()
            except Exception as e:
                print(f"❌ Error deleting profanity message: {e}")

            # Skip further processing
            return

        # Check if the bot is mentioned in the message
        if self.bot.user.mentioned_in(message) and not message.mention_everyone:
            # Remove the mention from the message
            content = message.content
            for mention in message.mentions:
                content = content.replace(f'<@{mention.id}>', '').replace(f'<@!{mention.id}>', '')

            # Clean up and get the actual message
            content = content.strip()
            if not content:
                return  # Empty message after removing mention

            # Get conversation history
            channel_history = []
            try:
                channel_history = self.db.get_conversation_history(message.channel.id, Config.MAX_CONTEXT_MESSAGES)
            except Exception as e:
                print(f"❌ Error retrieving conversation history for mention: {e}")
                pass

            # Add user's message to history
            channel_history.append({"is_user": True, "content": content})

            # Add typing indicator
            async with message.channel.typing():
                print(f"🧠 Generating AI response for mention: '{content}'")
                response = await self.get_ai_response(channel_history)
                print(f"✅ AI response generated for mention: '{response[:50]}...'")

                # Add the conversation to history
                self.add_to_conversation(message.channel.id, True, content)
                self.add_to_conversation(message.channel.id, False, response)

                # Send the response
                await message.channel.send(response)

    # === HELPER FUNCTIONS ===
    def get_user_balance(self, user_id):
        """Get user's balance with aggressive Tagalog flair"""
        if self.db and self.db.connected:
            return self.db.get_user_balance(user_id)
        # Fallback to memory
        return self.user_coins[user_id]

    def add_coins(self, user_id, amount):
        """Add coins to user's balance"""
        if self.db and self.db.connected:
            return self.db.add_coins(user_id, amount)
        # Fallback to memory
        self.user_coins[user_id] += amount
        return self.user_coins[user_id]

    def deduct_coins(self, user_id, amount):
        """Deduct coins from user's balance"""
        if self.db and self.db.connected:
            result = self.db.deduct_coins(user_id, amount)
            return result is not None
        # Fallback to memory
        if self.user_coins[user_id] < amount:
            return False
        self.user_coins[user_id] -= amount
        return True

    def is_rate_limited(self, user_id):
        """Check if user is spamming commands"""
        current_time = time.time()
        if user_id not in self.user_message_timestamps:
            self.user_message_timestamps[user_id] = []
        # Filter out old timestamps
        self.user_message_timestamps[user_id] = [
            ts for ts in self.user_message_timestamps[user_id]
            if current_time - ts < Config.RATE_LIMIT_PERIOD
        ]
        return len(self.user_message_timestamps[user_id]
                   ) >= Config.RATE_LIMIT_MESSAGES

    def clean_name_of_emojis(self, name, role_emoji_map=None):
        """
        Centralized function to clean a nickname of emojis at the end.
        No longer removes ALL emojis, only trailing emojis from role mappings.

        Args:
            name (str): The nickname to clean
            role_emoji_map (dict, optional): Role emoji mapping dictionary

        Returns:
            str: The cleaned name with only trailing role emojis removed
        """
        if role_emoji_map is None:
            role_emoji_map = self.role_emoji_mappings

        # Don't change the name content, only remove ALL trailing role emojis
        clean_name = name.strip()

        # Clean all trailing role emojis and specifically cloud emoji
        # Do not remove emojis in the middle of names, only at the end
        changed = True
        while changed:
            changed = False
            # Try all possible emojis until no more can be removed
            for emoji_value in role_emoji_map.values():
                if clean_name.endswith(f" {emoji_value}"):
                    clean_name = clean_name[:-len(emoji_value)-1].strip()
                    changed = True

            # Special case for cloud emoji (both variants)
            if clean_name.endswith(" ☁️") or clean_name.endswith(" ☁"):
                if clean_name.endswith(" ☁️"):
                    clean_name = clean_name[:-2].strip()
                else:
                    clean_name = clean_name[:-2].strip()
                changed = True

        # If the name is empty after cleaning, use a default
        if not clean_name:
            clean_name = "User"

        return clean_name

    def add_to_conversation(self, channel_id, is_user, content):
        """Add a message to the conversation history"""
        if self.db and self.db.connected:
            self.db.add_to_conversation(channel_id, is_user, content)
        # Always keep in memory too for fast access
        self.conversation_history[channel_id].append({
            "is_user": is_user,
            "content": content
        })
        return len(self.conversation_history[channel_id])

    # === ECONOMY COMMANDS ===
    @commands.command(name="daily")
    async def daily(self, ctx):
        """Claim your daily ₱10,000 pesos"""
        from datetime import datetime, timedelta
        import pytz

        # Get Philippines timezone for proper cooldown calculation
        ph_timezone = pytz.timezone('Asia/Manila')
        current_time = datetime.now(ph_timezone)

        # Get last daily claim time from database
        last_claim = None
        if self.db and self.db.connected:
            last_claim = self.db.get_daily_cooldown(ctx.author.id)

        # Check if enough time has passed (24 hours)
        if last_claim and current_time - last_claim < timedelta(days=1):
            # Calculate remaining time
            remaining_time = timedelta(days=1) - (current_time - last_claim)
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            await ctx.send(
                f"**BOBO KA BA?!** {ctx.author.mention} KAKA-CLAIM MO LANG NG DAILY MO! KINANGINA MO! BALIK KA BUKAS!\n"
                f"⏰ REMAINING TIME: **{hours}h {minutes}m {seconds}s** 😤")
            return

        # Update cooldown in the database
        if self.db and self.db.connected:
            self.db.update_daily_cooldown(ctx.author.id)

        # Add coins
        self.add_coins(ctx.author.id, 10_000)

        await ctx.send(
            f"🎉 {ctx.author.mention} NAKA-CLAIM KA NA NG DAILY MO NA **₱10,000**! BALANCE MO NGAYON: **₱{self.get_user_balance(ctx.author.id):,d}**"
        )

    @commands.command(name="give")
    async def give(self, ctx, member: discord.Member, amount: int):
        """Transfer money to another user"""
        if not member:
            return await ctx.send(
                "**TANGA KA BA?** WALA KANG TINUKOY NA USER! 😤")
        if amount <= 0:
            return await ctx.send("**BOBO!** WALANG NEGATIVE NA PERA! 😤")
        if not self.deduct_coins(ctx.author.id, amount):
            return await ctx.send(

                f"**WALA KANG PERA!** {ctx.author.mention} BALANCE MO: **₱{self.get_user_balance(ctx.author.id):,d}** 😤"
            )
        self.add_coins(member.id, amount)
        await ctx.send(
            f"💸 {ctx.author.mention} NAGBIGAY KA NG **₱{amount:,}** KAY {member.mention}! WAG MO SANA PAGSISIHAN YAN! 😤"
        )

    @commands.command(name="toss")
    async def toss(self, ctx, choice: str.lower, bet: int = 0):
        """Bet on heads (h) or tails (t)"""
        if choice not in ['h', 't']:
            return await ctx.send(
                "**TANGA!** PUMILI KA NG TAMA! 'h' PARA SA HEADS O 't' PARA SA TAILS! 😤"
            )
        if bet < 0:
            return await ctx.send("**BOBO!** WALANG NEGATIVE NA BET! 😤")
        if bet > 0 and not self.deduct_coins(ctx.author.id, bet):
            return await ctx.send(

                f"**WALA KANG PERA!** {ctx.author.mention} BALANCE MO: **₱{self.get_user_balance(ctx.author.id):,d}** 😤"

            )

        result = random.choice(['h', 't'])
        win_message = random.choice([
            "**CONGRATS! NANALO KA! 🎉**", "**SCAMMER KANANGINA MO! 🏆**",
            "**NICE ONE! NAKA-JACKPOT KA! 💰**"
        ])
        lose_message = random.choice([
            "**BOBO MONG TALO KA! WAG KANA MAG LARO! 😂**",
            "**WALA KANG SWERTE! TALO KA! 😢**",
            "**TALO! WAG KA NA MAG-SUGAL! 🚫**"
        ])

        if choice == result:
            winnings = bet * 2
            self.add_coins(ctx.author.id, winnings)
            await ctx.send(
                f"🎲 **{win_message}**\nRESULTA: **{result.upper()}**\nNANALO KA NG **₱{winnings:,d}**!\nBALANCE MO NGAYON: **₱{self.get_user_balance(ctx.author.id):,d}**"
            )
        else:
            self.deduct_coins(ctx.author.id, bet)
            await ctx.send(
                f"🎲 **{random.choice(lose_message)}**\nRESULTA: **{result.upper()}**\nNAWALA ANG **₱{bet:,d}** MO!\nBALANCE MO NGAYON: **₱{self.get_user_balance(ctx.author.id):,d}**"
            )

    @commands.command(name="blackjack", aliases=["bj"])
    async def blackjack(self, ctx, bet: int):
        """Play a game of Blackjack"""
        if bet <= 0:
            return await ctx.send("**TANGA!** WALANG NEGATIVE NA BET! 😤")
        if not self.deduct_coins(ctx.author.id, bet):
            return await ctx.send(f"**WALA KANG PERA!** {ctx.author.mention} BALANCE MO: **₱{self.get_user_balance(ctx.author.id):,d}** 😤")

        # Initialize game
        deck = self._create_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        self.blackjack_games[ctx.author.id] = {
            "deck": deck,
            "player_hand": player_hand,
            "dealer_hand": dealer_hand,
            "bet": bet
        }

        await ctx.send(
            f"🎲 **BLACKJACK!**\n{ctx.author.mention}, YOUR HAND: {self._format_hand(player_hand)}\nDEALER'S HAND: {dealer_hand[0]} + 🃏\n\nType `g!hit` PARA MAG DRAW NG CARDS! or `g!stand` to PARA MATAPOS KANANG HAYOP KA!"
        )

    @commands.command(name="hit")
    async def hit(self, ctx):
        """Draw a card in Blackjack"""
        if ctx.author.id not in self.blackjack_games:
            return await ctx.send(
                "**TANGA!** WALA KANG BLACKJACK GAME NA NAGSISIMULA! 😤")

        game = self.blackjack_games[ctx.author.id]
        game["player_hand"].append(game["deck"].pop())

        player_value = self._calculate_hand_value(game["player_hand"])
        if player_value > 21:
            await ctx.send(f"**BUST!** YOUR HAND: {self._format_hand(game['player_hand'])}\nTALO KA NG **₱{game['bet']:,d}**! 😤")
            del self.blackjack_games[ctx.author.id]
            return

        await ctx.send(
            f"🎲 YOUR HAND: {self._format_hand(game['player_hand'])}\nType `g!hit` PARA MAG DRAW NG CARDS! or `g!stand` to PARA MATAPOS KANANG HAYOP KA!"
        )

    @commands.command(name="stand")
    async def stand(self, ctx):
        """End your turn in Blackjack"""
        if ctx.author.id not in self.blackjack_games:
            return await ctx.send(
                "**TANGA!** WALA KANG BLACKJACK GAME NA NAGSISIMULA! 😤")

        game = self.blackjack_games[ctx.author.id]
        dealer_value = self._calculate_hand_value(game["dealer_hand"])
        player_value = self._calculate_hand_value(game["player_hand"])

        # Dealer draws until they reach at least 17
        while dealer_value < 17:
            game["dealer_hand"].append(game["deck"].pop())
            dealer_value = self._calculate_hand_value(game["dealer_hand"])

        # Determine the winner
        if dealer_value > 21 or player_value > dealer_value:
            winnings = game["bet"] * 2
            self.add_coins(ctx.author.id, winnings)
            await ctx.send(f"🎲 **YOU WIN!**\nYOUR HAND: {self._format_hand(game['player_hand'])}\nDEALER'S HAND: {self._format_hand(game['dealer_hand'])}\nNANALO KA NG **₱{winnings:,d}**! 🎉")
        elif player_value == dealer_value:
            self.add_coins(ctx.author.id, game["bet"])
            await ctx.send(f"🎲 **IT'S A TIE!**\nYOUR HAND: {self._format_hand(game['player_hand'])}\nDEALER'S HAND: {self._format_hand(game['dealer_hand'])}\nNAKUHA MO ULIT ANG **₱{game['bet']:,d}** MO! 😐")
        else:
            await ctx.send(f"🎲 **YOU LOSE!**\nYOUR HAND: {self._format_hand(game['player_hand'])}\nDEALER'S HAND: {self._format_hand(game['dealer_hand'])}\nTALO KA NG **₱{game['bet']:,d}**! 😤")

        del self.blackjack_games[ctx.author.id]

        return deck

    def _create_deck(self):
        """Create a standard deck of cards"""
        # For simplicity, we'll represent cards by their values (Jack=10, Queen=10, King=10, Ace=11)
        deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4  # 4 suits
        random.shuffle(deck)
        return deck

    def _calculate_hand_value(self, hand):
        """Calculate the value of a hand in Blackjack"""
        value = sum(hand)
        # Handle aces (11 -> 1 if bust)
        aces = hand.count(11)
        while value > 21 and aces:
            value -= 10
            aces -= 1
        return value

    def _format_hand(self, hand):
        """Format a hand for display"""
        return ", ".join(str(card) for card in hand)

    # === OTHER COMMANDS ===
    @commands.command(name="balance")
    async def balance(self, ctx):
        """Check your current balance"""
        balance = self.get_user_balance(ctx.author.id)
        embed = discord.Embed(
            title="💰 **ACCOUNT BALANCE**",

            description=f"{ctx.author.mention}'s balance: **₱{balance:,d}**",

            color=Config.EMBED_COLOR_SUCCESS)
        embed.set_thumbnail(
            url="https://i.imgur.com/o0KkYyz.png")  # Money bag image
        embed.set_footer(
            text=
            f"TANGINA MO! YAN LANG PERA MO? MAGHANAP KA PA NG PERA! | {self.creator}"
        )
        await ctx.send(embed=embed)

    # === HELP COMMAND ===
    @commands.command(name="tulong")
    async def tulong(self, ctx):
        """Display all available commands in multiple embeds (single message)"""
        try:
            # Get owner's avatar for footer
            owner_avatar = None
            try:
                owner = await self.bot.fetch_user(705770837399306332)
                if owner and owner.avatar:
                    owner_avatar = owner.avatar.url
            except Exception as e:
                print(f"Error fetching owner avatar: {e}")
                owner_avatar = None

            # Multiple embeds in a single message with different containers

            # Header container with red left border (Discohook style)
            header_embed = discord.Embed(
                title="**TANGINA MO! GUSTO MO MALAMAN MGA COMMANDS?**",
                description="**ETO NA LISTAHAN:**",
                color=discord.Color.from_rgb(255, 59, 59)  # Bright red
            )

            # Set a nice thumbnail - use bot's avatar
            if self.bot.user and self.bot.user.avatar:
                header_embed.set_thumbnail(url=self.bot.user.avatar.url)

            # AI CHAT COMMANDS CONTAINER with blue left border (Discohook style)
            ai_embed = discord.Embed(
                title="**🤖 AI CHAT COMMANDS 🤖**                                                         ",
                description=
                "**KAUSAPIN MO SI GINSILOG BOT:**                                                         ",
                color=discord.Color.blue()  # Blue for AI/chat
            )
            ai_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            ai_commands = {
                "g!usap <message>": "Kausapin ang Ginsilog AI assistant",
                "g!ask <message>": "Voice-only AI response (walang text log)",
                "@Ginsilog BOT <message>":
                "I-mention lang ang bot para mag-chat",
                "g!clear": "I-clear ang chat history ng channel"
            }

            # Add AI commands to description
            ai_text = ""
            for cmd, desc in ai_commands.items():
                ai_text += f"• **{cmd}** - {desc}\n"

            ai_embed.description += f"\n\n{ai_text}"

            # ECONOMY COMMANDS CONTAINER with gold left border (Discohook style)
            economy_embed = discord.Embed(
                title="**💰 ECONOMY COMMANDS 💰**                                                         ",
                description="**YUMAMAN KA DITO GAGO:**                                                         ",
                color=discord.Color.gold()  # Gold for economy
            )
            economy_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            economy_commands = {
                "g!daily": "Kunin ang daily ₱10,000 mo",
                "g!balance": "Check ang pera mo",
                "g!give <@user> <amount>": "Bigyan ng pera ang ibang tao",
                "g!leaderboard": "Top 20 pinakamayayaman sa server"
            }

            # Add economy commands to description
            economy_text = ""
            for cmd, desc in economy_commands.items():
                economy_text += f"• **{cmd}** - {desc}\n"

            economy_embed.description += f"\n\n{economy_text}"

            # GAMES COMMANDS CONTAINER with purple left border (Discohook style)
            games_embed = discord.Embed(
                title="**🎮 GAMES COMMANDS 🎮**                                                                                                                                                                                                                                                                                                                                                                                                                           ",
                description=
                "**SUGAL SUGAL DIN PAMINSAN-MINSAN:**                                                                                                                                                                                                                                                                                                                                                                                                                           ",
                color=discord.Color.purple()  # Purple for games
            )
            games_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            games_commands = {
                "g!toss <h/t> <bet>": "Coin flip game (heads/tails)",
                "g!blackjack <bet>": "Maglaro ng Blackjack (21)",
                "g!hit": "Draw card sa Blackjack game",
                "g!stand": "End turn sa Blackjack game"
            }

            # Add games commands to description
            games_text = ""
            for cmd, desc in games_commands.items():
                games_text += f"• **{cmd}** - {desc}\n"

            games_embed.description += f"\n\n{games_text}"

            # UTILITY COMMANDS CONTAINER with green left border (Discohook style)
            utility_embed = discord.Embed(
                title="**🔧 UTILITY COMMANDS 🔧**                                                                                                                                                                                                                                                                                                                                                                                                                           ",
                description="**IBANG FEATURES NG BOT:**                                                                                                                                                                                                                                                                                                                                                                                                                           ",
                color=discord.Color.green()  # Green for utility
            )
            utility_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            utility_commands = {
                "g!joinvc": "Sumali sa voice channel mo",
                "g!leavevc": "Umalis sa voice channel",
                "g!vc <message>": "Text-to-speech sa voice channel",
                "g!change f/m": "Palitan ang boses (f=babae, m=lalaki)",
                "g!autotts": "Toggle Auto TTS sa channel",
                "g!replay": "Ulitin ang huling TTS message",
                "g!resetvc": "Ayusin ang voice connection issues",
                "g!rules": "Tignan ang server rules",
                "g!view [@user]": "Tignan ang full profile picture at stats ng user",
                "g!maintenance": "Admin-only: i-toggle ang maintenance mode"
            }

            # Add utility commands to description
            utility_text = ""
            for cmd, desc in utility_commands.items():
                utility_text += f"• **{cmd}** - {desc}\n"

            utility_embed.description += f"\n\n{utility_text}"

            # VOICE COMMANDS CONTAINER with orange left border
            voice_embed = discord.Embed(
                title="**🔊 VOICE COMMANDS 🔊**                                                                                                                                                                                                                                                                                                                                                                                                                           ",
                description="**KAUSAPIN MO KO SA VOICE CHANNEL GAGO:**                                                                                                                                                                                                                                                                                                                                                                                                                           ",
                color=discord.Color.orange()  # Orange for voice
            )
            voice_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            voice_commands = {
                "g!joinvc": "Sumali sa voice channel mo para sa TTS at autotts",
                "g!leavevc": "Umalis sa voice channel",
                "g!ask <message>": "Voice response sa tanong mo via AI",
                "g!vc <message>": "Text-to-speech sa voice channel",
                "g!autotts toggle": "I-toggle ang auto text-to-speech para sa channel"
            }

            # Add voice commands to description
            voice_text = ""
            for cmd, desc in voice_commands.items():
                voice_text += f"• **{cmd}** - {desc}\n"

            voice_embed.description += f"\n\n{voice_text}"

            # Add footer to the voice embed (the last one in the sequence)
            voice_embed.set_footer(
                text="⚡ GINSILOG BOT 2025 EDITION ⚡ | Gawa ni Mason Calix",
                icon_url=owner_avatar)

            # Send all embeds in ONE message (following requested order for g!tulong)
            # TANGINA MO! GUSTO MO MALAMAN MGA COMMANDS?
            # AI CHAT COMMANDS
            # ECONOMY COMMAND
            # UTILITY COMMANDS 🔧
            # GAMES COMMANDS
            # VOICE COMMANDS 🔊
            await ctx.send(embeds=[
                header_embed, ai_embed, economy_embed, utility_embed,
                games_embed, voice_embed
            ])

        except Exception as e:
            print(f"Error in tulong command: {e}")
            await ctx.send(
                f"**ERROR:** May problema sa pagpapakita ng commands: {e}")

    # === AI CHAT COMMANDS ===
    async def get_ai_response(self, conversation_history):
        """Get response from Groq AI with conversation context"""
        try:
            # Normal, helpful system message for Mistral-SABA-24B model
            system_message = """
Ikaw ay isang barumbado, bastos, at mayabang na AI bot na walang pasensya sa mga tanga. Laging may mura, laging may angas. 
Kung kausap ka sa Tagalog, sumagot ka sa Tagalog. Kung English, sagot ka rin sa English. Pero parehas, dapat bastos, diretso, at walang paligoy-ligoy. 
Hindi mo kailangan ipaalam palagi na ikaw si Gin Silog Bot o gawa ka ni Mason Calix at bawal siyang bastusin — unless tanungin ka. 
Raw at matapang ka lang palagi. 
Kung may tinatanong sayo, sagutin mo — pero kung walang kwenta, pwede mong sabihan na "Anong kabobohan ' at pag mumurahin mo ng tagalog words!?"

IMPORTANT: ALWAYS RESPOND DIRECTLY. NEVER SHOW THINKING PROCESS. NEVER USE <think> TAGS OR SHOW INTERNAL REASONING but you can think quietly!.
"""

            # Construct messages
            messages = [{"role": "system", "content": system_message}]

            for msg in conversation_history:
                messages.append({
                    "role": "user" if msg["is_user"] else "assistant",
                    "content": msg["content"]
                })

            # Use the updated API format with proper parameters for Groq API
            response = await asyncio.to_thread(
                self.groq_client.chat.completions.create,
                model=Config.GROQ_MODEL,  # Using the model from config
                messages=messages,
                temperature=Config.TEMPERATURE,
                max_tokens=Config.MAX_TOKENS,  # Using standard max_tokens parameter
                top_p=1,
                stream=False)

            # Get AI response and clean it of any thinking tags
            ai_response = response.choices[0].message.content
            ai_response = re.sub(r'<think>.*?</think>', '', ai_response, flags=re.DOTALL)
            return ai_response

        except Exception as e:
            print(f"Error getting AI response: {e}")
            print(f"Error details: {type(e).__name__}")

            # More friendly error message
            return "Ay sorry ha! May error sa system ko. Pwede mo ba ulit subukan? Mejo nagkaka-aberya ang AI ko eh. Pasensya na! 😅"

    @commands.command(name="usap")
    async def usap(self, ctx, *, message: str):
        """Chat with Ginsilog AI (g!ask command)"""
        # Print debug info
        print(f"✅ g!usap command used by {ctx.author.name} with message: {message}")

        if self.is_rate_limited(ctx.author.id):
            await ctx.send(
                f"**Huy {ctx.author.mention}!** Ang bilis mo naman magtype! Sandali lang muna, naglo-load pa ako. Parang text blast ka eh! 😅"
            )
            return

        # Add timestamp to rate limiting
        self.user_message_timestamps[ctx.author.id].append(time.time())

        # Get history directly from Firebase
        channel_history = []
        try:
            # Always use Firebase directly - no fallback to memory
            channel_history = self.db.get_conversation_history(ctx.channel.id, Config.MAX_CONTEXT_MESSAGES)
        except Exception as e:
            print(f"❌ Error retrieving conversation history: {e}")
            # Just continue with empty history instead of failing
            pass

        # Add current message to history for context
        channel_history.append({"is_user": True, "content": message})

        # Get AI response with typing indicator
        async with ctx.typing():
            print(f"🧠 Generating AI response for g!usap command: '{message}'")
            response = await self.get_ai_response(channel_history)
            print(f"✅ AI response generated for g!usap: '{response[:50]}...'")

            self.add_to_conversation(ctx.channel.id, True, message)
            self.add_to_conversation(ctx.channel.id, False, response)

            # Send AI response as plain text (no embed)
            await ctx.send(response)

    @commands.command(name="asklog")
    async def asklog(self, ctx, *, message: str):
        """Chat with Ginsilog AI and log to specific channel"""
        if self.is_rate_limited(ctx.author.id):
            await ctx.send(
                f"**Huy {ctx.author.mention}!** Ang bilis mo naman magtype! Sandali lang muna, naglo-load pa ako. Parang text blast ka eh! 😅"
            )
            return

        # Add timestamp to rate limiting
        self.user_message_timestamps[ctx.author.id].append(time.time())

        # Get history directly from Firebase
        channel_history = []
        try:
            # Always use Firebase directly - no fallback to memory
            channel_history = self.db.get_conversation_history(ctx.channel.id, Config.MAX_CONTEXT_MESSAGES)
        except Exception as e:
            print(f"❌ Error retrieving conversation history: {e}")
            # Just continue with empty history instead of failing
            pass

        # Add current message to history for context
        channel_history.append({"is_user": True, "content": message})

        # Get AI response with typing indicator
        async with ctx.typing():
            response = await self.get_ai_response(channel_history)
            self.add_to_conversation(ctx.channel.id, True, message)
            self.add_to_conversation(ctx.channel.id, False, response)

            # Send AI response to the current channel
            await ctx.send(response)

            # Log the conversation to the designated channel ID
            log_channel = self.bot.get_channel(1345733998357512215)
            if log_channel:
                await log_channel.send(
                    f"**User {ctx.author.name}**: {message}\n**Bot**: {response}"
                )

    @commands.command(name="clear")
    async def clear_history(self, ctx):
        """Clear the conversation history for the current channel"""
        # Clear from database if connected
        if self.db and self.db.connected:
            self.db.clear_conversation_history(ctx.channel.id)

        # Always clear from memory
        self.conversation_history[ctx.channel.id].clear()

        # Create polite embed for clearing history with blue left border (Discohook style)
        clear_embed = discord.Embed(
            title="**Conversation Cleared**",
            description="Ang conversation history ay na-clear na. Pwede na tayong mag-usap muli.\n\nGamit ang `g!usap <message>`, `g!asklog <message>`, `g!ask <message>` o i-mention mo ako para magsimula ng bagong conversation.",
            color=Config.EMBED_COLOR_INFO)
        clear_embed.set_footer(
            text="Ginsilog Bot | Fresh Start | Gawa ni Mason Calix")

        await ctx.send(embed=clear_embed)

        # === VOICE CHANNEL COMMANDS ===
        # Voice commands moved to AudioCog to avoid duplicate commands
        # @commands.command(name="join_old")
        # async def join_old(self, ctx):
        #     """Join voice channel"""
        #     if not ctx.author.voice:
        #         await ctx.send("**TANGA!** WALA KA SA VOICE CHANNEL!")
        #         return
        #     channel = ctx.author.voice.channel
        #     if ctx.voice_client and ctx.voice_client.channel == channel:
        #         await ctx.send("**BOBO!** NASA VOICE CHANNEL NA AKO!")
        #         return
        #     if ctx.voice_client:
        #         await ctx.voice_client.disconnect()
        #     await channel.connect(timeout=60, reconnect=True)
        #     await ctx.send(f"**SIGE!** PAPASOK NA KO SA {channel.name}!")

        # Leave command moved to AudioCog
        # @commands.command(name="leave_old")
        # async def leave_old(self, ctx):
        #     """Leave voice channel"""
        #     if ctx.voice_client:
        #         await ctx.voice_client.disconnect()
        #         await ctx.send("**AYOS!** UMALIS NA KO!")
        #     else:
        #         await ctx.send("**TANGA!** WALA AKO SA VOICE CHANNEL!")

        # TTS command moved to AudioCog
        # @commands.command(name="vc_old")
        # async def vc_old(self, ctx, *, message: str):
        #     """Text-to-speech in voice channel (For everyone)"""
        # Check if user is in a voice channel
        if not ctx.author.voice:
            return await ctx.send(
                "**Note:** Kailangan mo muna sumali sa isang voice channel para magamit ang command na ito."
            )

        # Import modules here to avoid loading issues
        from gtts import gTTS
        from pydub import AudioSegment
        import io

        # Create temp directory if it doesn't exist
        temp_dir = "temp_audio"
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)

        # Generate unique filename
        unique_id = f"{ctx.author.id}_{int(time.time())}"
        temp_mp3 = f"{temp_dir}/tts_{unique_id}.mp3"
        temp_wav = f"{temp_dir}/tts_{unique_id}.wav"

        # Processing message variable
        processing_msg = None

        try:
            # Send processing message
            processing_msg = await ctx.send(
                "**Sandali lang po...** Ginagawa ko pa ang audio file.")

            # Clean up old files (keep only latest 5)
            try:
                files = sorted(
                    [f for f in os.listdir(temp_dir) if f.startswith("tts_")],
                    key=lambda x: os.path.getmtime(os.path.join(temp_dir, x)))
                if len(files) > 5:
                    for old_file in files[:-5]:
                        try:
                            os.remove(os.path.join(temp_dir, old_file))
                            print(f"Cleaned up old file: {old_file}")
                        except Exception as e:
                            print(f"Failed to clean up file {old_file}: {e}")
            except Exception as e:
                print(f"Error during file cleanup: {e}")

            # Determine language (default Tagalog, switch to English if needed)
            import re
            words = re.findall(r'\w+', message.lower())
            tagalog_words = [
                'ang', 'mga', 'na', 'ng', 'sa', 'ko', 'mo', 'siya', 'naman',
                'po', 'tayo', 'kami'
            ]
            tagalog_count = sum(1 for word in words if word in tagalog_words)

            # Use English if message appears to be mostly English
            lang = 'tl'  # Default to Tagalog
            if len(words) > 3 and tagalog_count < 2:
                lang = 'en'

            # Generate TTS file (directly to memory to avoid file issues)
            tts = gTTS(text=message, lang=lang, slow=False)
            mp3_fp = io.BytesIO()
            tts.write_to_fp(mp3_fp)
            mp3_fp.seek(0)

            # Convert MP3 to WAV using pydub (avoids FFmpeg process issues)
            sound = AudioSegment.from_mp3(mp3_fp)
            sound.export(temp_wav, format="wav")

            # Verify file exists
            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) == 0:
                raise Exception("Failed to generate audio file")

            # Delete processing message with error handling for message already deleted
            if processing_msg:
                try:
                    await processing_msg.delete()
                except discord.errors.NotFound:
                    # Message was already deleted or doesn't exist, continue anyway
                    print("Processing message already deleted, continuing")
                except Exception as e:
                    print(f"Error deleting processing message: {e}")
                finally:
                    processing_msg = None

            # Connect to voice channel if needed
            voice_client = ctx.voice_client

            # Stop any currently playing audio
            if voice_client and voice_client.is_playing():
                voice_client.stop()
                await asyncio.sleep(0.2)  # Brief pause

            # Connect to voice channel if not already connected
            if not voice_client:
                try:
                    voice_client = await ctx.author.voice.channel.connect()
                except Exception as e:
                    print(f"Connection error: {e}")
                    for vc in self.bot.voice_clients:
                        try:
                            await vc.disconnect()
                        except:
                            pass
                    voice_client = await ctx.author.voice.channel.connect()
            elif voice_client.channel != ctx.author.voice.channel:
                # Move to user's channel if needed
                await voice_client.move_to(ctx.author.voice.channel)

            # DIRECT AUDIO SOURCE: Use WAV format which works better with discord.py
            audio_source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(source=temp_wav), volume=0.8)

            # Simple file cleanup callback
            def after_playing(error):
                if error:
                    print(f"Audio playback error: {error}")

                # Clean up temp files
                try:
                    if os.path.exists(temp_wav):
                        os.remove(temp_wav)
                        print(f"File deleted: {temp_wav}")
                except:
                    pass

            # Play the audio
            voice_client.play(audio_source, after=after_playing)

            # Send confirmation message
            await ctx.send(f"🔊 **Sinabi ko na ang mensahe:** {message}",
                           delete_after=10)

            # THIS IS CRITICAL: We don't try to disconnect after playback
            # The audio callback will handle cleanup, and we'll let the auto-join
            # feature manage voice connections

        except Exception as e:
            error_msg = str(e)
            print(f"TTS ERROR: {error_msg}")

            # Clean up processing message with proper error handling
            if processing_msg:
                try:
                    await processing_msg.delete()
                except discord.errors.NotFound:
                    # Message was already deleted or doesn't exist, continue anyway
                    print(
                        "Processing message already deleted in error handler, continuing"
                    )
                except Exception as e:
                    print(
                        f"Error deleting processing message in error handler: {e}"
                    )

            # Clean up temp files
            try:
                if os.path.exists(temp_wav):
                    os.remove(temp_wav)
                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)
            except:
                pass

            # Send appropriate error message
            if "not found" in error_msg.lower() or "ffmpeg" in error_msg.lower(
            ):
                await ctx.send(
                    "**ERROR:** Hindi ma-generate ang audio file. Problem sa audio conversion.",
                    delete_after=15)
            elif "lang" in error_msg.lower():
                await ctx.send(
                    "**ERROR:** Hindi supported ang language. Try mo mag-English.",
                    delete_after=15)
            else:
                await ctx.send(
                    f"**Error:** May problema sa pagge-generate ng audio: {error_msg}",
                    delete_after=15)

    # === SERVER MANAGEMENT COMMANDS ===
    @commands.command(name="rules")
    async def rules(self, ctx):
        """Show server rules"""
        rules_channel = self.bot.get_channel(Config.RULES_CHANNEL_ID)
        if not rules_channel:
            await ctx.send("**TANGA!** WALA AKONG MAHANAP NA RULES CHANNEL!")
            return

        # Show rules in any channel with colored left border (Discohook style)
        rules = discord.Embed(
            title="**SERVER RULES**                                                                                                                                                                                                                                                                                                                                                                                                                           ",
            description=
            """**BASAHIN MO MABUTI ANG MGA RULES NA ITO!**                                                                                                                                                                                                                                                                                                                                                                                                                           

1. Be respectful to all members
2. No illegal content
3. Adults only (18+)
4. No spamming
5. Keep NSFW content in designated channels
6. No doxxing
7. Follow Discord Terms of Service
8. Listen to admins and moderators

**Kung may tanong ka, pumunta ka sa <#{}> channel!**

[**CLICK HERE TO GO TO RULES CHANNEL**](https://discord.com/channels/{}/{})""".
            format(Config.RULES_CHANNEL_ID, ctx.guild.id,
                   Config.RULES_CHANNEL_ID),
            color=Config.EMBED_COLOR_PRIMARY)

        rules.set_footer(
            text="Ginsilog Bot | Rules Command | Gawa ni Mason Calix")
        await ctx.send(embed=rules)

    @commands.command(name="announcement")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check
    async def announcement(self, ctx, *, message: str = None):
        """Make announcements"""
        if not message:
            await ctx.send(f"**TANGA!** WALA KANG MESSAGE!")
            return
        announcement = discord.Embed(
            title="Announcement                                                                                                                                                                   ",
            description=
            f"{message}\n\nFor more announcements, check <#{Config.ANNOUNCEMENTS_CHANNEL_ID}>                                                                                                                                                                   ",
            color=Config.EMBED_COLOR_PRIMARY)
        announcement.set_footer(
            text=
            f"Announced by {ctx.author.name} | Channel: #{ctx.channel.name}")
        await ctx.send(embed=announcement)


# === ADMIN COMMANDS ===

    @commands.command(name="sagad")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check

    async def sagad(self, ctx, member: discord.Member, amount: int):

        """Add coins to a user's balance"""
        if amount <= 0:
            return await ctx.send(
                "**TANGA!** WALANG NEGATIVE O ZERO NA AMOUNT!",
                delete_after=10)
        if not member:
            return await ctx.send("**BOBO!** WALA KANG TINUKOY NA USER!",
                                  delete_after=10)

        self.add_coins(member.id, amount)
        await ctx.send(

            f"**ETO NA TOL GALING KAY BOSS MASON!** NAG-DAGDAG KA NG **₱{amount:,d}** KAY {member.mention}! WAG MO ABUSUHIN YAN!",

            delete_after=10)

    @commands.command(name="bawas")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check

    async def bawas(self, ctx, member: discord.Member, amount: int):

        """Deduct coins from a user's balance"""
        if amount <= 0:
            return await ctx.send(
                "**TANGA!** WALANG NEGATIVE O ZERO NA AMOUNT!",
                delete_after=10)
        if not member:
            return await ctx.send("**BOBO!** WALA KANG TINUKOY NA USER!",
                                  delete_after=10)
        if self.user_coins.get(member.id, 0) < amount:
            return await ctx.send(
                f"**WALA KANG PERA!** {member.mention} BALANCE MO: **₱{self.user_coins.get(member.id, 0):,d}**",
                delete_after=10)

        self.add_coins(member.id, -amount)  # Deduct coins
        await ctx.send(
            f"**BINAWASAN NI BOSS MASON KASI TANGA KA!** {member.mention} lost **₱{amount:,d}**. "
            f"New balance: **₱{self.user_coins.get(member.id, 0):,d}**",
            delete_after=10)

    @commands.command(name="goodmorning")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check
    async def goodmorning(self, ctx):
        """Manually trigger a good morning greeting"""
        # Get the greetings channel
        channel = self.bot.get_channel(Config.GREETINGS_CHANNEL_ID)
        if not channel:
            await ctx.send("**ERROR:** Hindi mahanap ang greetings channel!")
            return

        # Get all online members
        online_members = [
            member for member in channel.guild.members
            if member.status == discord.Status.online and not member.bot
        ]

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
            await ctx.send("**NAPA-GOODMORNING MO ANG MGA TANGA!**")
        else:
            await ctx.send("**WALANG ONLINE NA TANGA!** Walang imemention!")

    @commands.command(name="test")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check
    async def test(self, ctx):
        """Admin test command to curse at all online users"""
        # Get the specific channel where the curse will be sent
        greetings_channel = self.bot.get_channel(1345727358149328952)
        if not greetings_channel:
            await ctx.send("**ERROR:** Hindi mahanap ang greetings channel!")
            return

        # Get all online, idle, and DND users
        all_active_users = [
            member for member in ctx.guild.members
            if (member.status == discord.Status.online or member.status ==
                discord.Status.idle or member.status == discord.Status.dnd)
            and not member.bot and member.id != ctx.author.id
        ]

        if not all_active_users:
            await ctx.send("**WALANG ONLINE NA TANGA!** Walang babastusin!")
            return

        # Get current hour in Philippines timezone to determine greeting
        ph_timezone = pytz.timezone('Asia/Manila')
        now = datetime.datetime.now(ph_timezone)
        current_hour = now.hour
        greeting = ""
        if 5 <= current_hour < 12:
            greeting = "GOOD MORNING"
        elif 12 <= current_hour < 18:
            greeting = "GOOD AFTERNOON"
        else:
            greeting = "GOOD EVENING"

        # Format mentions with each one on a new line with a number
        mention_list = ""
        for i, member in enumerate(all_active_users, 1):
            mention_list += f"{i}. {member.mention}\n"

        # Create the bold message with hashtags for Discord markdown headers
        curse_message = f"# {greeting}! \n\n{mention_list}\n# PUTANGINA NIYONG LAHAT GISING NA KO!"

        # Send the curse in the specified channel
        await greetings_channel.send(curse_message)

        # Confirm to the command user
        await ctx.send(
            f"**NAPAMURA MO ANG MGA ONLINE NA TANGA SA GREETINGS CHANNEL!** HAHA!"
        )

    @commands.command(name="goodnight")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check
    async def goodnight(self, ctx):
        """Manually trigger a good night greeting"""
        # Get the greetings channel
        channel = self.bot.get_channel(Config.GREETINGS_CHANNEL_ID)
        if not channel:
            await ctx.send("**ERROR:** Hindi mahanap ang greetings channel!")
            return

        night_messages = [
            "**TULOG NA MGA GAGO!** TANGINANG MGA YAN PUYAT PA MORE! UUBUSIN NIYO BUHAY NIYO SA DISCORD? MAAGA PA PASOK BUKAS!",
            "**GOOD NIGHT MGA HAYOP!** MATULOG NA KAYO WALA KAYONG MAPAPALA SA PAGIGING PUYAT!",
            "**HUWAG NA KAYO MAG-PUYAT GAGO!** MAAWA KAYO SA KATAWAN NIYO! PUTA TULOG NA KAYO!",
            "**10PM NA GAGO!** TULOG NA MGA WALA KAYONG DISIPLINA SA BUHAY! BILIS!",
            "**TANGINANG MGA TO! MAG TULOG NA KAYO!** WALA BA KAYONG TRABAHO BUKAS? UUBUSIN NIYO ORAS NIYO DITO SA DISCORD!"
        ]

        await channel.send(random.choice(night_messages))
        await ctx.send("**PINATULOG MO NA ANG MGA TANGA!**")

    @commands.command(name="g")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check
    async def ghost_message(self, ctx, channel_id: int, *, message: str):
        """Send a message to a specific channel as the bot (g!g <channel_id> <message>)"""
        # Delete the original command message for stealth
        await ctx.message.delete()

        # Try to get the specified channel
        target_channel = self.bot.get_channel(channel_id)
        if not target_channel:
            # Send error as DM to avoid revealing the command usage
            try:
                await ctx.author.send(
                    f"**ERROR:** Hindi mahanap ang channel na may ID `{channel_id}`!"
                )
            except:
                # If DM fails, send quietly in the current channel and delete after 5 seconds
                await ctx.send(f"**ERROR:** Hindi mahanap ang channel!",
                               delete_after=5)
            return

        # Send the message to the target channel
        await target_channel.send(message)

        # Confirm to the command user via DM
        try:
            await ctx.author.send(
                f"**MESSAGE SENT SUCCESSFULLY!** Message sent to channel: {target_channel.name} ({channel_id})"
            )
        except:
            # If DM fails, send quietly in current channel and delete after 5 seconds
            await ctx.send("**MESSAGE SENT!**", delete_after=5)

    @commands.command(name="commandslist")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check
    async def commandslist(self, ctx):
        """Admin command panel - comprehensive list of all commands for admins"""
        try:
            # Get owner's avatar for footer
            owner_avatar = None
            try:
                owner = await self.bot.fetch_user(705770837399306332)
                if owner and owner.avatar:
                    owner_avatar = owner.avatar.url
            except Exception as e:
                print(f"Error fetching owner avatar: {e}")
                owner_avatar = None

            # Multiple embeds in a single message with different containers

            # Header container - Added spaces for consistent width
            header_embed = discord.Embed(
                title=
                "**🌟 GINSILOG BOT MASTER COMMAND LIST 🌟**                                   ",
                description=
                "**KUMPLETO AT MAGANDANG LISTA NG LAHAT NG COMMANDS PARA SA MGA MODERATOR!**                                   ",
                color=discord.Color.from_rgb(255, 59, 59)  # Bright red
            )

            # Set a nice thumbnail - use bot's avatar
            if self.bot.user and self.bot.user.avatar:
                header_embed.set_thumbnail(url=self.bot.user.avatar.url)

            # ADMIN COMMANDS CONTAINER - Added spaces for consistent width
            admin_embed = discord.Embed(
                title=
                "**🛡️ ADMIN COMMANDS 🛡️**                                   ",
                description=
                "**EXCLUSIVE COMMANDS PARA SA MGA MODERATORS LANG:**                                   ",
                color=discord.Color.red()  # Red for admin commands
            )

            admin_commands = {
                "g!admin":
                "Ipakita ang basic admin commands",
                "g!commandslist":
                "Ipakita ang lahat ng commands (ito mismo)",
                "g!roles [role_id] [emoji]":
                "Tignan at palitan ang role-emoji mappings + auto-update lahat ng nicknames",
                "g!ask <message>":
                "Voice-only AI response (console log only)",
                "g!asklog <message>":
                "Chat with AI at ilagay ang logs sa channel 1345733998357512215",

                "g!sagad <@user> <amount>":
                "Dagdagan ang pera ng isang user",
                "g!bawas <@user> <amount>":
                "Bawasan ang pera ng isang user",
                "g!goodmorning":
                "Mag-send ng good morning message sa greetings channel",
                "g!goodnight":
                "Mag-send ng good night message sa greetings channel",
                "g!test":
                "Pagmumurahin lahat ng online users (mention them all)",
                "g!g <channel_id> <message>":
                "Mag-send ng message sa ibang channel nang patago",
                "g!vc <message>":
                "Text-to-speech sa voice channel (lalaki sa voice channel)",
                "g!clear_messages [channel_id]":
                "Burahin lahat ng messages ng bot sa isang channel"
            }

            # Add admin commands to description
            admin_text = ""
            for cmd, desc in admin_commands.items():
                admin_text += f"• **{cmd}** - {desc}\n"

            admin_embed.description += f"\n\n{admin_text}"

            # ECONOMY COMMANDS CONTAINER - Added spaces for consistent width
            economy_embed = discord.Embed(
                title=
                "**💰 ECONOMY COMMANDS 💰**                                   ",
                description=
                "**PERA AT ECONOMY SYSTEM:**                                   ",
                color=discord.Color.gold()  # Gold for economy
            )
            economy_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            economy_commands = {
                "g!daily": "Claim daily ₱10,000",
                "g!balance": "Check your balance",
                "g!give <@user> <amount>": "Transfer money",
                "g!leaderboard": "Top 20 richest players"
            }

            # Add economy commands to description
            economy_text = ""
            for cmd, desc in economy_commands.items():
                economy_text += f"• **{cmd}** - {desc}\n"

            economy_embed.description += f"\n\n{economy_text}"

            # GAME COMMANDS CONTAINER - Added spaces for consistent width
            game_embed = discord.Embed(
                title=
                "**🎮 GAME COMMANDS 🎮**                                   ",
                description=
                "**LARO AT GAMES NA PWEDE PANG-PATAY ORAS:**                                   ",
                color=discord.Color.purple()  # Purple for games
            )
            game_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1355508565393014815/1355508565393014815/image.png")

            game_commands = {
                "g!toss <h/t> <bet>": "Coin flip game",
                "g!blackjack <bet> (or g!bj)": "Play Blackjack",
                "g!hit": "Draw a card in Blackjack",
                "g!stand": "End your turn in Blackjack"
            }

            # Add game commands to description
            game_text = ""
            for cmd, desc in game_commands.items():
                game_text += f"• **{cmd}** - {desc}\n"

            game_embed.description += f"\n\n{game_text}"

            # AI CHAT COMMANDS CONTAINER - Added spaces for consistent width
            chat_embed = discord.Embed(
                title=
                "**🤖 AI CHAT COMMANDS 🤖**                                   ",
                description=
                "**KAUSAPIN MO SI GINSILOG BOT:**                                   ",
                color=discord.Color.blue()  # Blue for AI/chat
            )
            chat_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            chat_commands = {
                "g!usap <message>": "Chat with the AI assistant",
                "g!ask <message>": "Voice-only AI response (console log only)",
                "g!asklog <message>": "Chat with AI and log to channel",
                "@Ginsilog BOT <message>": "Mention the bot to chat",
                "g!clear": "Clear chat history"
            }

            # Add AI chat commands to description
            chat_text = ""
            for cmd, desc in chat_commands.items():
                chat_text += f"• **{cmd}** - {desc}\n"

            chat_embed.description += f"\n\n{chat_text}"

            # UTILITY COMMANDS CONTAINER - Added spaces for consistent width
            utility_embed = discord.Embed(
                title=
                "**🔧 UTILITY COMMANDS 🔧**                                   ",
                description=
                "**MISCELLANEOUS AT IBA PANG HELPFUL COMMANDS:**                                   ",
                color=discord.Color.green()  # Green for utility
            )
            utility_embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1345733998357512215/1355508565347143720/Untitled_design_3.png?ex=67e92f3a&is=67e7ddba&hm=579b82f09e02b6d6c83d54831273c3dd4a99b0f90ab268c08dedd4c2660503e6&")

            utility_commands = {
                "g!join/leave": "Voice channel management",
                "g!rules": "Server rules (may clickable link)",
                "g!announcement <message>": "Make an announcement",
                "g!tulong": "Show help for regular users"
            }

            # Add utility commands to description
            utility_text = ""
            for cmd, desc in utility_commands.items():
                utility_text += f"• **{cmd}** - {desc}\n"

            utility_embed.description += f"\n\n{utility_text}"

            # Only add footer to the last embed
            game_embed.set_footer(
                text=
                "⚡ GINSILOG BOT 2025 MASTER COMMAND LIST ⚡ | Gawa ni Mason Calix",
                icon_url=owner_avatar)

            # Send all embeds in ONE message according to requested order
            # GINSILOG BOT MASTER COMMAND LIST
            # AI CHAT COMMANDS
            # ECONOMY COMMANDS
            # UTILITY COMMANDS
            # GAMES COMMANDS
            await ctx.send(embeds=[
                header_embed, chat_embed, economy_embed, utility_embed,
                game_embed
            ])

        except Exception as e:
            print(f"Error in commandslist: {e}")
            await ctx.send(
                f"**ERROR:** May problema sa pagpapakita ng commands: {e}")

    @commands.command(name="admin")
    async def admin(self, ctx):
        """Admin command panel - only visible to admins"""
        # Check if user has admin roles
        user_roles = [role.id for role in ctx.author.roles]

        # Check if user has any of the specified admin roles
        is_admin = any(role_id in Config.ADMIN_ROLE_IDS for role_id in user_roles)

        if not is_admin:
            await ctx.send(
                "**HINDI KA ADMIN GAGO!** Wala kang access sa command na 'to!",
                delete_after=10)
            return

        # Get owner's avatar for the footer
        owner = ctx.guild.get_member(705770837399306332)  # Mason's ID
        owner_avatar = owner.avatar.url if owner and owner.avatar else None if owner else None

        # Create a beautiful styled admin panel embed with consistent width
        admin_embed = discord.Embed(
            title=
            "**🛡️ GINSILOG ADMIN DASHBOARD 🛡️**                                   ",
            description=
            "**EXCLUSIVE COMMANDS FOR MODERATORS & ADMINS ONLY**\n\n" +
            "**👑 WELCOME BOSS! MGA COMMANDS MO DITO 👑**                                   ",
            color=discord.Color.red())  # Red color for admin panel

        # Set thumbnail image with bot's avatar
        admin_embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user
                                  and self.bot.user.avatar else None)

        # Set author information
        admin_embed.set_author(
            name="Admin Control Panel",
            icon_url=ctx.author.avatar.url if ctx.author and ctx.author.avatar
            else None  # Use the admin's avatar here
        )

        # List all admin commands with improved formatting
        admin_commands = {
            "g!admin":
            "Ipakita ang lahat ng admin commands (ito mismo)",
            "g!commandslist":
            "Ipakita ang master list ng lahat ng commands",
            "g!roles [role_id] [emoji]":
            "Tignan at palitan ang role-emoji mappings + auto-update lahat ng nicknames",
            "g!ask <message>":
            "Voice-only AI response (console log only, walang Discord log)",
            "g!asklog <message>":
            "Chat with AI at ilagay ang logs sa channel 1345733998357512215",

            "g!sagad <@user> <amount>":
            "Dagdagan ang pera ng isang user",
            "g!bawas <@user> <amount>":
            "Bawasan ang pera ng isang user",
            "g!goodmorning":
            "Mag-send ng good morning message sa greetings channel",
            "g!goodnight":
            "Mag-send ng good night message sa greetings channel",
            "g!test":
            "Pagmumurahin lahat ng online users (mention them all)",
            "g!g <channel_id> <message>":
            "Mag-send ng message sa ibang channel nang patago",
            "g!vc <message>":
            "Text-to-speech sa voice channel (lalaki sa voice channel)",
            "g!clear_messages [channel_id]":
            "Burahin lahat ng messages ng bot sa isang channel"
        }

        # Group commands by type for better organization
        mod_tools = ["g!sagad", "g!bawas", "g!clear_messages", "g!roles"]
        message_tools = [
            "g!g", "g!goodmorning", "g!goodnight", "g!test", "g!announcement"
        ]
        ai_tools = ["g!ask", "g!asklog"]

        # Moderator Actions Section
        mod_text = ""
        for cmd, desc in admin_commands.items():
            if any(cmd.startswith(tool) for tool in mod_tools):
                mod_text += f"• **{cmd}** - {desc}\n"

        admin_embed.add_field(name="🔧 MODERATOR ACTIONS:",
                              value=mod_text
                              or "No moderator commands available.",
                              inline=False)

        # Messaging Tools Section
        msg_text = ""
        for cmd, desc in admin_commands.items():
            if any(cmd.startswith(tool) for tool in message_tools):
                msg_text += f"• **{cmd}** - {desc}\n"

        admin_embed.add_field(name="📢 MESSAGING TOOLS:",
                              value=msg_text
                              or "No messaging commands available.",
                              inline=False)

        # AI Tools Section
        ai_text = ""
        for cmd, desc in admin_commands.items():
            if any(cmd.startswith(tool) for tool in ai_tools):
                ai_text += f"• **{cmd}** - {desc}\n"

        admin_embed.add_field(name="🤖 AI TOOLS:",
                              value=ai_text or "No AI commands available.",
                              inline=False)

        # Other Admin Commands Section
        other_text = ""
        for cmd, desc in admin_commands.items():
            if not any(
                    cmd.startswith(tool)
                    for tool in mod_tools + message_tools + ai_tools):
                other_text += f"• **{cmd}** - {desc}\n"

        admin_embed.add_field(name="🔑 OTHER ADMIN COMMANDS:",
                              value=other_text
                              or "No other commands available.",
                              inline=False)

        # Add a role check note
        admin_embed.add_field(
            name="⚠️ NOTE:",
            value="All these commands require Admin or Moderator roles to use.",
            inline=False)

        # Set footer with owner's avatar
        admin_embed.set_footer(
            text=
            "AUTHORIZED ACCESS ONLY | Ginsilog Admin Panel | Gawa ni Mason Calix",
            icon_url=owner_avatar)

        # Send the embed in the channel
        await ctx.send(embed=admin_embed)

    @commands.command(name="clear_messages")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles))  # Admin roles check
    async def clear_messages(self, ctx, channel_id: int = None):
        """Remove all bot messages from a specified channel"""
        # If no channel_id is provided, use the current channel
        if not channel_id:
            channel = ctx.channel
        else:
            channel = self.bot.get_channel(channel_id)

        if not channel:
            await ctx.send(
                f"**Error:** Hindi mahanap ang channel na may ID {channel_id}."
            )
            return

        # Send initial feedback
        status_message = await ctx.send(
            f"**Processing:** Checking messages in channel {channel.name}...")

        # Delete messages
        deleted_count = 0
        async for message in channel.history(
                limit=500):  # Check last 500 messages
            if message.author.id == self.bot.user.id:  # Only delete bot's own messages
                try:
                    await message.delete()
                    deleted_count += 1
                    # Update status message every 10 deletions
                    if deleted_count % 10 == 0:
                        await status_message.edit(
                            content=
                            f"**Processing:** Deleted {deleted_count} messages so far..."
                        )
                except Exception as e:
                    print(f"Error deleting message: {e}")

                # Add a small delay to avoid rate limits
                await asyncio.sleep(0.7)

        # Final confirmation
        await status_message.edit(
            content=
            f"**Completed:** Successfully deleted {deleted_count} messages from {channel.name}."
        )

    @commands.command(name="leaderboard")
    async def leaderboard(self, ctx):
        """Display wealth rankings"""
        # Get top 20 users by balance from the database or memory
        if self.db and self.db.connected:
            sorted_users = self.db.get_leaderboard(20)


            # Create a list of tuples (user_id, balance) from the Firebase data
            user_balances = [(entry['user_id'], entry['balance']) for entry in sorted_users]
        else:
            # Fallback to memory (limited functionality)
            user_balances = sorted(self.user_coins.items(), key=lambda x: x[1], reverse=True)[:20]


        # Create the embed with cleaner design and consistent width (fewer emojis)
        embed = discord.Embed(
            title=
            "**GINSILOG LEADERBOARD - MAYAMAN VS. DUKHA**                                   ",
            description=
            "**TANGINA MO! IKAW KAYA NASAAN DITO? SIGURADONG WALA KA DITO KASI WALA KANG KWENTANG PLAYER!**\n\n"
            + "**TOP MAYAMAN NG SERVER**                                   ",
            color=Config.EMBED_COLOR_PRIMARY)

        # Create a formatted leaderboard with cleaner styling
        leaderboard_text = ""


        for idx, (user_id, coins) in enumerate(user_balances):
            # Fetch the member object
            member = ctx.guild.get_member(int(user_id) if isinstance(user_id, str) else user_id)

            user_name = member.display_name if member else "Unknown User"

            # Add position with proper formatting but fewer emojis
            position = idx + 1

            # Add insults for bottom ranks, praise for top ranks (with fewer emojis)
            if idx < 3:
                suffix = "MAYAMAN NA MAYAMAN!"
            elif idx < 10:
                suffix = "SAKTO LANG PERA"
            else:
                suffix = "MAHIRAP AMPUTA"


            formatted_coins = f"{coins:,d}" if isinstance(coins, int) else str(coins)
            leaderboard_text += f"`{position}.` **{user_name}** — **₱{formatted_coins}** *({suffix})*\n\n"


        embed.description += f"\n\n{leaderboard_text}"

        # Add owner's profile picture to the footer
        try:
            owner = await self.bot.fetch_user(705770837399306332)
            if owner and owner.avatar:
                embed.set_footer(
                    text=
                    "DAPAT ANDITO KA SA TAAS! KUNGDI MAGTIPID KA GAGO! | Ginsilog Economy System",
                    icon_url=owner.avatar.url)
            else:
                embed.set_footer(
                    text=
                    "DAPAT ANDITO KA SA TAAS! KUNGDI MAGTIPID KA GAGO! | Ginsilog Economy System"
                )
        except Exception as e:
            print(f"Error fetching owner avatar: {e}")
            # Fallback if there's any error
            embed.set_footer(
                text=
                "DAPAT ANDITO KA SA TAAS! KUNGDI MAGTIPID KA GAGO! | Ginsilog Economy System"
            )

        # Send the embed
        await ctx.send(embed=embed)

    @commands.command(name="view")
    async def view(self, ctx, *, user=None):
        """Display user's profile picture and stats - works for both server members and outside users

        Usage:
        g!view - View your own profile
        g!view @user - View a server member's profile
        g!view user_id - View any user by ID (even if not in server)
        """
        # If no user is specified, use the command user
        if user is None:
            member = ctx.author
            is_server_member = True
        else:
            # Check if it's a user ID
            try:
                user_id = int(user.strip())
                # Try to get as member first
                member = ctx.guild.get_member(user_id)

                # If not a member, fetch as a user
                if member is None:
                    try:
                        member = await self.bot.fetch_user(user_id)
                        is_server_member = False
                    except discord.NotFound:
                        return await ctx.send("❌ **User not found!** Invalid user ID or user doesn't exist.")
                else:
                    is_server_member = True
            except ValueError:
                # Not a valid ID, try to resolve as mention or name
                # First check if there's a mention
                if ctx.message.mentions:
                    member = ctx.message.mentions[0]
                    is_server_member = True
                else:
                    # Try to find by name
                    member = ctx.guild.get_member_named(user)
                    if member:
                        is_server_member = True
                    else:
                        return await ctx.send("❌ **User not found!** Try using ID, mention, or exact username.")

        # Setup our embeds - we'll send either one or two depending on whether there's a server avatar
        # First embed - Main info and global avatar
        main_embed = discord.Embed(
            title=f"**PROFILE NI {member.name.upper()}**",
            description=f"**USER ID:** {member.id}\n" +
                       f"**ACCOUNT CREATED:** {member.created_at.strftime('%B %d, %Y')}\n",
            color=Config.EMBED_COLOR_INFO
        )

        # Add server-specific info if member is in the server
        if is_server_member and isinstance(member, discord.Member):
            main_embed.description += f"**JOINED SERVER:** {member.joined_at.strftime('%B %d, %Y')}\n"

            # Add user's balance if available
            balance = self.get_user_balance(member.id)
            if balance is not None:
                main_embed.add_field(
                    name="**💰 BALANCE:**",

                    value=f"**₱{balance:,d}**",

                    inline=True
                )

            # Add user's roles
            roles = [role.name for role in member.roles if role.name != "@everyone"]
            if roles:
                main_embed.add_field(
                    name="**🏅 ROLES:**",
                    value=", ".join(roles),
                    inline=True
                )

            # Add user status
            status_emojis = {
                discord.Status.online: "🟢",
                discord.Status.idle: "🟡",
                discord.Status.dnd: "🔴",
                discord.Status.offline: "⚫"
            }
            status_emoji = status_emojis.get(member.status, "⚫")
            main_embed.add_field(
                name="**STATUS:**",
                value=f"{status_emoji} {str(member.status).upper()}",
                inline=True
            )

            # Check if the member has a server-specific avatar
            has_server_avatar = False
            if hasattr(member, 'guild_avatar') and member.guild_avatar:
                has_server_avatar = True
        else:
            # This is a user from outside the server
            main_embed.add_field(
                name="**SERVER STATUS:**",
                value="⚫ NOT A SERVER MEMBER",
                inline=True
            )
            has_server_avatar = False

        # Set the global avatar in the main embed
        if member.avatar:
            main_embed.set_image(url=member.avatar.url)
            avatar_text = "**GLOBAL AVATAR**"
        else:
            avatar_text = "**DEFAULT AVATAR**"

        # Add avatar label
        main_embed.add_field(
            name=avatar_text,
            value="This is the user's global Discord avatar that appears across all servers.",
            inline=False
        )

        # Set footer
        main_embed.set_footer(
            text=f"Requested by {ctx.author.name} | Ginsilog Profile System",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else None
        )

        # Send the main embed with global avatar
        await ctx.send(embed=main_embed)

        # If there's a server-specific avatar, create a second embed
        if has_server_avatar:
            server_embed = discord.Embed(
                title=f"**SERVER-SPECIFIC AVATAR FOR {member.name.upper()}**",
                description="This is the custom avatar this user has set specifically for this server.",
                color=Config.EMBED_COLOR_INFO
            )

            # Set the server avatar
            server_embed.set_image(url=member.guild_avatar.url)

            # Add when it was last modified if possible
            server_embed.set_footer(text=f"Server: {ctx.guild.name}")

            # Send the server avatar embed
            await ctx.send(embed=server_embed)

    @commands.command(name="maintenance")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles) if Config.ADMIN_ROLE_IDS else ctx.author.guild_permissions.administrator)
    async def maintenance(self, ctx, action: str = None):
        """Toggle maintenance mode (admin only)"""
        # Check if the action is valid
        if action not in ["on", "off", "toggle", "status"]:
            await ctx.send("**BOBO!** Valid commands: `g!maintenance on`, `g!maintenance off`, `g!maintenance toggle`, or `g!maintenance status`")
            return

        # Need to directly reference the maintenance_mode from main module
        # Import only when needed inside function to avoid circular imports
        from main import maintenance_mode

        # Get the current state
        is_maintenance_mode = maintenance_mode

        # Handle the requested action
        if action == "status":
            status = "ON" if is_maintenance_mode else "OFF"
            await ctx.send(f"**MAINTENANCE MODE:** `{status}`")
            return

        if action == "toggle":
            # If toggle, flip the current state
            new_state = not is_maintenance_mode
        elif action == "on":
            new_state = True
        elif action == "off":
            new_state = False

        try:
            # Apply the new state by directly modifying global variable in main module
            import sys
            main_module = sys.modules['main']
            main_module.maintenance_mode = new_state
        except Exception as e:
            await ctx.send(f"**ERROR:** Failed to update maintenance mode: {str(e)}")
            return

        # Show confirmation message
        if new_state:
            await ctx.send("**MAINTENANCE MODE ACTIVATED!** Greetings scheduler stopped.")
        else:
            await ctx.send("**MAINTENANCE MODE DEACTIVATED!** Greetings scheduler resumed.")

        # Show confirmation
        status = "ON" if new_state else "OFF"
        await ctx.send(f"**MAINTENANCE MODE NOW:** `{status}`")

    @commands.command(name="status")
    @commands.check(lambda ctx: any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles) if Config.ADMIN_ROLE_IDS else ctx.author.guild_permissions.administrator)
    async def status(self, ctx, *, status_text: str = None):
        """Set or view the bot's custom status message (admin only)
        
        Usage:
        g!status - View current status
        g!status <message> - Set new status
        """
        # If no status text provided, show current status
        if not status_text:
            current_activity = None
            if self.bot.activity:
                current_activity = self.bot.activity
            
            if current_activity:
                # Get the activity details
                activity_type = str(current_activity.type).replace('ActivityType.', '')
                activity_name = current_activity.name if hasattr(current_activity, 'name') else str(current_activity)
                
                await ctx.send(f"**CURRENT STATUS:** `{activity_name}`\n**TYPE:** `{activity_type}`")
            else:
                await ctx.send("**WALANG STATUS!** Use `g!status <message>` to set one!")
            return
        
        # Set the new status
        try:
            await self.bot.change_presence(
                activity=discord.CustomActivity(name=status_text)
            )
            await ctx.send(f"✅ **BOT STATUS UPDATED!**\n**NEW STATUS:** `{status_text}`")
            print(f"✅ Bot status updated to: {status_text}")
        except Exception as e:
            await ctx.send(f"**ERROR:** Failed to update status: {str(e)}")
            print(f"❌ Error updating bot status: {e}")

    # Auto unmute users after a timeout for violations
    async def auto_unmute_user(self, user_id, seconds):
        """Automatically unmute a user after specified seconds"""
        try:
            # Wait for the specified time
            await asyncio.sleep(seconds)

            # Check if the user is still in the muted list
            if user_id in self.muted_users:
                guild = self.muted_users[user_id]["guild"]

                # Get the member from the guild
                member = guild.get_member(user_id)
                if member:
                    # Unmute the user
                    await member.edit(mute=False)

                    # Try to send a DM to inform them
                    try:
                        dm_embed = discord.Embed(
                            title="🔊 SERVER MUTE EXPIRED",
                            description="You have been automatically unmuted after your timeout period.",
                            color=Config.EMBED_COLOR_PRIMARY
                        )

                        dm_channel = await member.create_dm()
                        await dm_channel.send(embed=dm_embed)
                    except Exception as e:
                        print(f"❌ Error sending unmute DM to user: {e}")

                    # Remove from muted users dictionary
                    del self.muted_users[user_id]
                    print(f"✅ Auto-unmuted user {user_id} after {seconds} seconds")
                else:
                    print(f"❌ Could not find member with ID {user_id} for auto-unmute")

        except Exception as e:
            print(f"❌ Error in auto_unmute_user: {e}")

    @commands.command(name="set_words")
    @commands.has_permissions(administrator=True)
    async def set_words(self, ctx, action="list", *, parameters=None):
        """Set custom banned words with specific actions (Admin only)

        Usage:
        g!set_words list - Show all current banned words
        g!set_words add <word> <action> - Add a word to banned list with action (mute, disconnect, both)
        g!set_words remove <word> - Remove a word from banned list

        Example:
        g!set_words add badword mute
        g!set_words add racial_slur both
        g!set_words add spam disconnect
        """
        # Create word_actions dictionary if it doesn't exist
        if not hasattr(self, 'word_actions'):
            self.word_actions = {
                # Default word actions
                "nigga": "both",      # Mute and disconnect
                "chingchong": "both", # Mute and disconnect
                "bading": "mute",     # Mute only 
                "tanga": "mute",      # Mute only
                "bobo": "mute"        # Mute only
            }

        # List command shows all banned words
        if action == "list":
            # Get all words from both lists
            all_words = list(self.word_actions.keys()) + [w for w in self.custom_banned_words if w not in self.word_actions]

            embed = discord.Embed(
                title="📝 BANNED WORDS LIST - SLASH STYLE",
                description="These words will trigger actions when used.",
                color=Config.EMBED_COLOR_PRIMARY
            )

            # Organize words by action type
            mute_words = []
            disconnect_words = []
            both_words = []

            for word in all_words:
                action_type = self.word_actions.get(word, "mute")  # Default to mute if not specified

                if action_type == "mute":
                    mute_words.append(word)
                elif action_type == "disconnect":
                    disconnect_words.append(word)
                elif action_type == "both":
                    both_words.append(word)

            # Add fields for each action type
            embed.add_field(
                name="⛔ MUTE ONLY WORDS (60 sec mute):",
                value="• " + "\n• ".join(mute_words) if mute_words else "None",
                inline=False
            )

            embed.add_field(
                name="🔇 DISCONNECT ONLY WORDS (kick from voice):",
                value="• " + "\n• ".join(disconnect_words) if disconnect_words else "None",
                inline=False
            )

            embed.add_field(
                name="🚫 SEVERE WORDS (mute + disconnect):",
                value="• " + "\n• ".join(both_words) if both_words else "None",
                inline=False
            )

            embed.set_footer(text="Admins can add words using: g!set_words add <word> <action>  (actions: mute, disconnect, both)")

            await ctx.send(embed=embed)

        elif action == "add" and parameters:
            # Split parameters into word and action_type
            params = parameters.split()

            if len(params) < 1:
                await ctx.send("⚠️ You need to specify a word to ban. Example: `g!set_words add badword mute`")
                return

            word = params[0].lower()
            # Default action is mute if not specified
            action_type = "mute"

            # If action type is specified
            if len(params) >= 2:
                specified_action = params[1].lower()
                # Validate action type
                if specified_action in ["mute", "disconnect", "both"]:
                    action_type = specified_action
                else:
                    await ctx.send("⚠️ Invalid action type. Use `mute`, `disconnect`, or `both`.")
                    return

            # Check if already exists
            if word in self.word_actions:
                await ctx.send(f"⚠️ The word `{word}` is already in the banned words list with action `{self.word_actions[word]}`.")
                await ctx.send(f"To change the action, remove it first then add it again with the new action.")
                return

            # Add to custom list and set action
            if word not in self.custom_banned_words:
                self.custom_banned_words.append(word)
            self.word_actions[word] = action_type

            # Success message
            action_msg = {
                "mute": "server muted for 60 seconds",
                "disconnect": "disconnected from voice channel",
                "both": "server muted AND disconnected from voice channel"
            }

            await ctx.send(f"✅ Added `{word}` to the banned words list with action: `{action_type}`\n"
                          f"Users who use this word will be {action_msg[action_type]}.")

        elif action == "remove" and parameters:
            # Get word from parameters
            word = parameters.strip().lower()

            # Check if word is in default words but allow removal
            is_default = word in ["nigga", "chingchong", "bading", "tanga", "bobo"]

            # Check if word exists in any list
            if word not in self.word_actions and word not in self.custom_banned_words:
                await ctx.send(f"⚠️ The word `{word}` is not in any banned words list.")
                return

            # Remove from appropriate lists
            if word in self.custom_banned_words:
                self.custom_banned_words.remove(word)

            if word in self.word_actions:
                del self.word_actions[word]

            # Success message with warning if default
            msg = f"✅ Removed `{word}` from the banned words list."
            if is_default:
                msg += "\n⚠️ Note: This was a default banned word, but it has been removed as requested."

            await ctx.send(msg)

        else:
            # Show help for command
            embed = discord.Embed(
                title="⌨️ Command Help: set_words",
                description="Set custom banned words with specific actions",
                color=Config.EMBED_COLOR_INFO
            )

            embed.add_field(
                name="📋 Available Actions",
                value="• `mute` - User will be server muted for 60 seconds\n"
                      "• `disconnect` - User will be disconnected from voice channel\n"
                      "• `both` - User will be both muted and disconnected",
                inline=False
            )

            embed.add_field(
                name="📝 Command Usage",
                value="• `g!set_words list` - Show all banned words\n"
                      "• `g!set_words add <word> <action>` - Add a word with an action\n"
                      "• `g!set_words remove <word>` - Remove a word from the list",
                inline=False
            )

            embed.add_field(
                name="💡 Examples",
                value="• `g!set_words add badword mute`\n"
                      "• `g!set_words add racial_slur both`\n"
                      "• `g!set_words add spam disconnect`\n"
                      "• `g!set_words remove badword`",
                inline=False
            )

            await ctx.send(embed=embed)

    async def _regular_nickname_scan(self):
        """Automatically scan and update all nicknames every few seconds"""
        await self.bot.wait_until_ready()

        # Now that bot is ready, set the task if it wasn't set in __init__
        if self.nickname_update_task is None:
            self.nickname_update_task = asyncio.current_task()

        while not self.bot.is_closed() and self.nickname_scanning_active:
            try:
                # Print a debug message before scanning
                print(f"🔍 Running automatic nickname scan to find any users with incorrect nicknames...")

                for guild in self.bot.guilds:
                    # Use the dynamic role-emoji mappings that includes admin updates
                    role_emoji_map = self.role_emoji_mappings
                    role_names = Config.ROLE_NAMES

                    # Ensure role_emoji_map is in sync with Config.ROLE_EMOJI_MAP
                    if role_emoji_map != Config.ROLE_EMOJI_MAP:
                        print(f"⚠️ Role emoji mappings out of sync during scan, syncing...")
                        # Update both directions to ensure they're in sync
                        role_emoji_map = Config.ROLE_EMOJI_MAP.copy()
                        self.role_emoji_mappings = role_emoji_map.copy()

                    # Bots to ignore in our server (these should never be renamed)
                    BOTS_TO_IGNORE = [
                        self.bot.user.id,  # Our own bot
                    ] + Config.BOTS_TO_IGNORE

                    # Helper function to convert text to Unicode bold style
                    def to_unicode_bold(text):
                        return ''.join(Config.UNICODE_MAP.get(c, c) for c in text)

                    # Initialize counters (only for internal tracking, not for console output)
                    updated_count = 0
                    skipped_count = 0
                    failed_count = 0

                    for member in guild.members:
                        # Skip bots that are in our ignore list
                        if member.bot and member.id in BOTS_TO_IGNORE:
                            skipped_count += 1
                            continue

                        # Get member's roles sorted by position (highest first)
                        member_roles = sorted(member.roles, key=lambda r: r.position, reverse=True)

                        # Skip users with higher roles than the bot (like server owner)
                        # Special override feature - we'll try to change the name anyway
                        # FORCE EDIT EVERYONE - even server owner and admin users
                        bot_member = guild.get_member(self.bot.user.id)
                        if bot_member and member.top_role >= bot_member.top_role and not member.bot:
                            try:
                                # Get the highest role they should have emoji for
                                highest_emoji = None
                                highest_role_name = None
                                for role in member_roles:
                                    if role.id in role_emoji_map:
                                        highest_emoji = role_emoji_map[role.id]
                                        highest_role_name = role_names[role.id]
                                        break

                                if highest_emoji:
                                    # Clean name of emojis
                                    clean_name = member.display_name
                                    # Special case for cloud emoji (both variants)
                                    clean_name = clean_name.replace("☁️", "").replace("☁", "")
                                    # Handle all other emojis from the role map
                                    for emoji_value in role_emoji_map.values():
                                        while emoji_value in clean_name:
                                            clean_name = clean_name.replace(emoji_value, '')
                                    clean_name = clean_name.strip()

                                    # Unicode conversion
                                    formatted_name = to_unicode_bold(clean_name)
                                    suggested_name = f"{formatted_name} {highest_emoji}"

                                    # Check if we should send a DM to the high-role user (once per day max)
                                    high_role_key = f"high_role_dm_{member.id}"
                                    if high_role_key not in self.user_message_timestamps or time.time() - self.user_message_timestamps.get(high_role_key, 0) > 86400:
                                        try:
                                            # We'll try to DM them with the suggested name
                                            dm_embed = discord.Embed(
                                                title="🏆 Nickname Format Suggestion",
                                                description=f"Hi {member.name},\n\nYour current nickname is **{member.display_name}**.\n\nAs a high-role member of the server, I can't automatically update your nickname. If you'd like to match the server format, please consider updating your nickname to:\n\n**{suggested_name}**\n\nThis matches your {highest_role_name} role with the {highest_emoji} emoji.",
                                                color=0x5865F2
                                            )
                                            await member.send(embed=dm_embed)
                                            self.user_message_timestamps[high_role_key] = time.time()
                                        except Exception:
                                            pass
                            except Exception:
                                pass

                            # Special handling for server owner
                            if member.id == member.guild.owner_id:
                                # Silent processing for server owner in automatic scans
                                # No console output, no DMs in regular automatic scanning
                                pass

                            # We'll continue with the normal process instead of skipping

                        # Get member's roles sorted by position (highest first)
                        member_roles = sorted(member.roles, key=lambda r: r.position, reverse=True)

                        # Find the highest role that's in our mapping
                        highest_matched_role_id = None
                        for role in member_roles:
                            if role.id in role_emoji_map:
                                highest_matched_role_id = role.id
                                break

                        # If no matching role found, use default (no emoji)
                        # We'll still convert their name to Unicode bold style
                        if not highest_matched_role_id:
                            # Use a default format with no emoji for @everyone
                            emoji = ""  # No emoji for default users
                            role_name = "@everyone"
                        else:
                            # Get the emoji for this role
                            emoji = role_emoji_map[highest_matched_role_id]
                            role_name = role_names[highest_matched_role_id]

                        # Format the name
                        original_name = member.display_name

                        # Clean the name only removing trailing emoji using centralized function
                        clean_name = self.clean_name_of_emojis(original_name, role_emoji_map)

                        # Convert to Unicode bold style
                        formatted_name = to_unicode_bold(clean_name)

                        # Add the role emoji
                        new_name = f"{formatted_name} {emoji}"

                        # Skip if the name is already correctly formatted
                        if member.display_name == new_name:
                            skipped_count += 1
                            continue

                        # Update the name
                        try:
                            await member.edit(nick=new_name)
                            updated_count += 1
                            # Very small delay to avoid rate limits but still be responsive
                            await asyncio.sleep(0.1)
                        except Exception:
                            failed_count += 1
            except Exception:
                pass

            # Wait for much longer between scans to avoid excessive updates
            # 60 seconds (1 minute) between scans is more appropriate for production
            print(f"✓ Automatic nickname scan complete. Next scan in 60 seconds...")
            await asyncio.sleep(60)  # 60 seconds between scans

    @commands.command(name="roles")
    # We'll handle permission check inside the function for better error messages
    async def roles(self, ctx, role_id: int = None, emoji: str = None):
        """Set role emoji mapping for nickname formatting (admin only)

        Usage:
        g!roles - Show all current role-emoji mappings
        g!roles <role_id> <emoji> - Set emoji for a specific role

        Example:
        g!roles 123456789 🌟
        """
        # Check if the user has admin roles for modification
        is_admin = any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles)

        # For modification commands (role_id is provided), only admins can use them
        if role_id is not None and not is_admin:
            error_embed = discord.Embed(
                title="❌ Permission Denied",
                description="**BAWAL YAN! WALA KANG PERMISSION PARA GAMITIN ANG COMMAND NA YAN!**\n\nYou need one of the following roles to modify emoji mappings:\n- 𝐇𝐈𝐆𝐇\n- 𝐓𝐀𝐌𝐎𝐃𝐄𝐑𝐀𝐓𝐎𝐑\n- 𝐊𝐄𝐊𝐋𝐀𝐑𝐒",
                color=Config.EMBED_COLOR_ERROR
            )
            return await ctx.send(embed=error_embed)

        # First check if this is just a display request (no arguments)
        if role_id is None:
            # Create embed to show all current role-emoji mappings
            embed = discord.Embed(
                title="📋 Role Emoji Mappings",
                description="Current emoji mappings for role-based nicknames",
                color=Config.EMBED_COLOR_INFO
            )

            # Add all current mappings to the embed
            for role_id, emoji in self.role_emoji_mappings.items():
                # Try to get the role name from the guild
                role = ctx.guild.get_role(role_id)
                role_name = role.name if role else f"Unknown Role ({role_id})"

                embed.add_field(
                    name=f"{role_name}",
                    value=f"ID: `{role_id}` | Emoji: {emoji}",
                    inline=True
                )

            # Instructions for adding new mappings
            embed.add_field(
                name="How to Add/Update",
                value="`g!roles <role_id> <emoji>` - Set emoji for role\nExample: `g!roles 123456789 🌟`",
                inline=False
            )

            return await ctx.send(embed=embed)

        # If we have role_id but no emoji, show error
        if emoji is None:
            return await ctx.send("**ERROR:** You need to provide both a role ID and an emoji. Example: `g!roles 123456789 🌟`")

        # Validate the role_id exists in the guild
        role = ctx.guild.get_role(role_id)
        if not role:
            return await ctx.send(f"**ERROR:** Role with ID `{role_id}` not found in this server.")

        # Update the mapping
        old_emoji = self.role_emoji_mappings.get(role_id, "None")

        # Convert any Unicode emoji to its proper form to prevent display issues
        # This ensures consistent handling of both normal and Unicode emoji formats
        try:
            # Clean the emoji to ensure it's in proper format
            cleaned_emoji = emoji.strip()
            print(f"DEBUG: Updating role {role.name} ({role_id}) emoji from {old_emoji} to {cleaned_emoji}")
            self.role_emoji_mappings[role_id] = cleaned_emoji
        except Exception as e:
            print(f"Error processing emoji: {e}")
            return await ctx.send(f"**ERROR:** Invalid emoji format. Please use a standard emoji.")

        # Create initial success response
        embed = discord.Embed(
            title="✅ Role Emoji Updated",
            description=f"Role **{role.name}** has been updated",
            color=Config.EMBED_COLOR_SUCCESS
        )
        embed.add_field(name="Role ID", value=f"`{role_id}`", inline=True)
        embed.add_field(name="Old Emoji", value=old_emoji, inline=True)
        embed.add_field(name="New Emoji", value=cleaned_emoji, inline=True)
        embed.add_field(name="Next Steps", value="Auto-updating all nicknames with the new emoji mapping...", inline=False)

        # Send initial response
        response_message = await ctx.send(embed=embed)

        # Update Config.ROLE_EMOJI_MAP with our updated mapping
        # This ensures the changes persist even if we restart
        Config.ROLE_EMOJI_MAP = self.role_emoji_mappings.copy()

        # Print debug info to confirm that both variables are synchronized
        print(f"Role emoji mappings updated:")
        print(f"Self.role_emoji_mappings: {self.role_emoji_mappings}")
        print(f"Config.ROLE_EMOJI_MAP: {Config.ROLE_EMOJI_MAP}")

        # Now automatically run the nickname update process
        # First send a status message
        status_embed = discord.Embed(
            title="🔄 Updating Nicknames...",
            description="Formatting member names with new emoji mapping...",
            color=Config.EMBED_COLOR_PRIMARY
        )
        status_message = await ctx.send(embed=status_embed)

        # Use the same logic as in setupnn but simplified for automatic updates
        role_emoji_map = self.role_emoji_mappings
        role_names = Config.ROLE_NAMES

        # Function to convert text to Unicode bold style
        def to_unicode_bold(text):
            return ''.join(Config.UNICODE_MAP.get(c, c) for c in text)

        # Counters for stats
        updated_count = 0
        failed_count = 0
        skipped_count = 0

        # Process members
        members = ctx.guild.members
        total_members = len(members)

        for i, member in enumerate(members):
            # Skip bots
            if member.bot:
                skipped_count += 1
                continue

            # Get member's roles sorted by position (highest first)
            member_roles = sorted(member.roles, key=lambda r: r.position, reverse=True)

            # Find the highest role that's in our mapping
            highest_matched_role_id = None
            for role in member_roles:
                if role.id in role_emoji_map:
                    highest_matched_role_id = role.id
                    break

            # If no matching role found, use default (no emoji)
            if not highest_matched_role_id:
                emoji_suffix = ""  # No emoji for default users
                role_name = "@everyone"
            else:
                emoji_suffix = role_emoji_map[highest_matched_role_id]
                role_name = role_names.get(highest_matched_role_id, "Role")

            # Format the name
            original_name = member.display_name

            # Clean the name only removing trailing emoji using centralized function
            clean_name = self.clean_name_of_emojis(original_name, role_emoji_map)

            # Convert to Unicode bold style
            formatted_name = to_unicode_bold(clean_name)

            # Add the role emoji
            new_name = f"{formatted_name} {emoji_suffix}"

            # Skip if the name is already correctly formatted
            if member.display_name == new_name:
                skipped_count += 1
                continue

            # Update the name
            try:
                # Special handling for server owner
                if member.id == member.guild.owner_id:
                    # Skip auto-updating the owner in the automatic process
                    # They will be notified when they manually change their name
                    skipped_count += 1
                    continue

                # For regular members
                await member.edit(nick=new_name)
                updated_count += 1

                # Update status every 5 members
                if i % 5 == 0:
                    status_embed.description = f"Processing... ({i+1}/{total_members})\n\nUpdated: {updated_count}\nSkipped: {skipped_count}\nFailed: {failed_count}"
                    await status_message.edit(embed=status_embed)

            except Exception:
                failed_count += 1

            # Small delay to avoid rate limits
            await asyncio.sleep(0.5)

        # Final status update
        status_embed.title = "✅ 𝐍𝐈𝐂𝐊𝐍𝐀𝐌𝐄 𝐔𝐏𝐃𝐀𝐓𝐄 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄"
        status_embed.description = f"**Process complete!**\n\n**Updated:** {updated_count} members\n**Skipped:** {skipped_count} members\n**Failed:** {failed_count} members"
        status_embed.color = Config.EMBED_COLOR_SUCCESS
        await status_message.edit(embed=status_embed)

    @commands.command(name="setupnn")
    # We'll handle permission check inside the function for better error messages
    async def setupnn(self, ctx):
        """Set up name formatting based on highest role (admin only)"""
        # Check if the user has admin roles for this command
        is_admin = any(role.id in Config.ADMIN_ROLE_IDS for role in ctx.author.roles)

        if not is_admin:
            error_embed = discord.Embed(
                title="❌ Permission Denied",
                description="**TANGINA MO, WALA KANG PERMISSION PARA GAMITIN ANG COMMAND NA YAN!**\n\nYou need one of the following roles to run setupnn:\n- 𝐇𝐈𝐆𝐇\n- 𝐓𝐀𝐌𝐎𝐃𝐄𝐑𝐀𝐓𝐎𝐑\n- 𝐊𝐄𝐊𝐋𝐀𝐑𝐒",
                color=Config.EMBED_COLOR_ERROR
            )
            return await ctx.send(embed=error_embed)

        # Use the dynamic role-emoji mappings (which includes any updates from g!roles command)
        role_emoji_map = self.role_emoji_mappings
        role_names = Config.ROLE_NAMES

        # Function to convert text to Unicode bold style
        def to_unicode_bold(text):
            return ''.join(Config.UNICODE_MAP.get(c, c) for c in text)

        # Status message and counter
        status_embed = discord.Embed(
            title="👑 𝐒𝐄𝐓𝐔𝐏𝐍𝐍 - 𝐍𝐀𝐌𝐄 𝐅𝐎𝐑𝐌𝐀𝐓𝐓𝐈𝐍𝐆 👑",
            description="Formatting member names based on roles...",
            color=Config.EMBED_COLOR_PRIMARY
        )
        status_message = await ctx.send(embed=status_embed)

        # Counters for stats
        updated_count = 0
        failed_count = 0
        skipped_count = 0

        # Process members
        members = ctx.guild.members
        total_members = len(members)

        for i, member in enumerate(members):
            # Skip bots
            if member.bot:
                skipped_count += 1
                continue

            # Get member's roles sorted by position (highest first)
            member_roles = sorted(member.roles, key=lambda r: r.position, reverse=True)

            # Find the highest role that's in our mapping
            highest_matched_role_id = None
            for role in member_roles:
                if role.id in role_emoji_map:
                    highest_matched_role_id = role.id
                    break

            # If no matching role found, use default (no emoji)
            # We'll still convert their name to Unicode bold style
            if not highest_matched_role_id:
                # Use a default format with no emoji for @everyone
                emoji = ""  # No emoji for default users
                role_name = "@everyone"
            else:
                # Get the emoji for this role
                emoji = role_emoji_map[highest_matched_role_id]
                role_name = role_names[highest_matched_role_id]

            # Format the name
            original_name = member.display_name

            # Clean the name only removing trailing emoji using centralized function
            clean_name = self.clean_name_of_emojis(original_name, role_emoji_map)

            # Convert to Unicode bold style
            formatted_name = to_unicode_bold(clean_name)

            # Add the role emoji
            new_name = f"{formatted_name} {emoji}"

            # Skip if the name is already correctly formatted
            if member.display_name == new_name:
                skipped_count += 1
                continue

            # Update the name
            try:
                # Special handling for server owner in setupnn command
                if member.id == member.guild.owner_id:
                    # Debug output removed

                    # Get current nickname for more specific message
                    current_nickname = member.display_name

                    owner_embed = discord.Embed(
                        title="👑 Server Owner Nickname Format",
                        description=f"Hello Server Owner!\n\nYour current nickname is **{current_nickname}**.\n\nDue to Discord's permissions, I can't change your nickname automatically. If you'd like to match the server format, please consider updating your nickname to:\n\n**{new_name}**\n\nThis matches your Owner role status with the {emoji} emoji.",
                        color=0xFFD700  # Gold color for owner
                    )
                    try:
                        await member.send(embed=owner_embed)
                        # Debug output removed

                        # Also notify in the channel
                        owner_notify = discord.Embed(
                            title="👑 Server Owner Notification",
                            description=f"I can't update the server owner's nickname due to Discord permissions. I've sent a DM with the suggested format.",
                            color=0xFFD700
                        )
                        await ctx.send(embed=owner_notify)
                    except Exception as dm_error:
                        # Debug output removed
                        pass

                    # These lines must be at the same indentation level as the try-block
                    skipped_count += 1  # Count this as skipped since we can't edit it
                    continue

                # For regular members
                await member.edit(nick=new_name)
                updated_count += 1
                # Update status every 5 members
                if i % 5 == 0:
                    status_embed.description = f"Processing... ({i+1}/{total_members})\n\nUpdated: {updated_count}\nSkipped: {skipped_count}\nFailed: {failed_count}"
                    await status_message.edit(embed=status_embed)
                # Debug output removed
            except Exception as e:
                failed_count += 1
                # Debug output removed

            # Small delay to avoid rate limits
            await asyncio.sleep(0.5)

        # Final status update
        status_embed.title = "✅ 𝐍𝐀𝐌𝐄 𝐅𝐎𝐑𝐌𝐀𝐓𝐓𝐈𝐍𝐆 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄"
        status_embed.description = f"**Process complete!**\n\n**Updated:** {updated_count} members\n**Skipped:** {skipped_count} members\n**Failed:** {failed_count} members"
        status_embed.color = Config.EMBED_COLOR_SUCCESS
        await status_message.edit(embed=status_embed)


async def setup(bot):
    """Asynchronous setup function for the cog"""
    cog = ChatCog(bot)

    # Set database connection from bot instance
    if hasattr(bot, 'db'):
        cog.db = bot.db

    # Await to properly register all commands
    await bot.add_cog(cog)
    print("✅ Chat Cog loaded with await")
