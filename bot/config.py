import os
import re
import asyncio
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks

# Load environment variables
load_dotenv()

# Configuration class
class Config:
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    GROQ_API_KEY = os.getenv('GROQ_API_KEY')
    COMMAND_PREFIX = 'g!'  

    # Utility method
    @staticmethod
    def strip_think_blocks(text: str) -> str:
        """Removes <think>...</think> blocks from the given text."""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    # Channel IDs
    RULES_CHANNEL_ID = 1345727358015115385
    ANNOUNCEMENTS_CHANNEL_ID = 1345727358015115389
    AUTO_MESSAGE_CHANNEL_ID = 1345727358015115389
    GREETINGS_CHANNEL_ID = 1345727358149328952
    
    # Greetings settings
    GOOD_MORNING_HOUR = 8
    GOOD_NIGHT_HOUR = 22

    # Rate limiting settings
    RATE_LIMIT_MESSAGES = 5  
    RATE_LIMIT_PERIOD = 60   


    # Groq API settings
    GROQ_MODEL = "deepseek-r1-distill-llama-70b"  
    MAX_TOKENS = 4096
    TEMPERATURE = 0.6

    # Bot personality
    BOT_LANGUAGE = "Tagalog"
    BOT_PERSONALITY = "Aggressively Rude and Insulting"
    BOT_CREATOR = "Mason Calix 2025"

    # Unicode map for bold font
    UNICODE_MAP = {
        'A': '𝐀', 'B': '𝐁', 'C': '𝐂', 'D': '𝐃', 'E': '𝐄', 'F': '𝐅', 'G': '𝐆', 'H': '𝐇', 
        'I': '𝐈', 'J': '𝐉', 'K': '𝐊', 'L': '𝐋', 'M': '𝐌', 'N': '𝐍', 'O': '𝐎', 'P': '𝐏', 
        'Q': '𝐐', 'R': '𝐑', 'S': '𝐒', 'T': '𝐓', 'U': '𝐔', 'V': '𝐕', 'W': '𝐖', 'X': '𝐗', 
        'Y': '𝐘', 'Z': '𝐙',
        'a': '𝐚', 'b': '𝐛', 'c': '𝐜', 'd': '𝐝', 'e': '𝐞', 'f': '𝐟', 'g': '𝐠', 'h': '𝐡', 
        'i': '𝐢', 'j': '𝐣', 'k': '𝐤', 'l': '𝐥', 'm': '𝐦', 'n': '𝐧', 'o': '𝐨', 'p': '𝐩', 
        'q': '𝐪', 'r': '𝐫', 's': '𝐬', 't': '𝐭', 'u': '𝐮', 'v': '𝐯', 'w': '𝐰', 'x': '𝐱', 
        'y': '𝐲', 'z': '𝐳', 
        '0': '𝟎', '1': '𝟏', '2': '𝟐', '3': '𝟑', '4': '𝟒', 
        '5': '𝟓', '6': '𝟔', '7': '𝟕', '8': '𝟖', '9': '𝟗',
        ' ': ' ', '_': '_', '-': '-', '.': '.', ',': ',', '!': '!', '?': '?'
    }

    # Emoji Cycler settings
    EMOJI_SEQUENCE = ['🚀', '👽', '💥', '🛸', '🌌', '✨']
    ASA_SPACESHIP_ROLE_ID = 1348305679877935124


# Emoji Cycler
class EmojiCycler:
    def __init__(self, bot):
        self.bot = bot
        self.target_role_id = Config.ASA_SPACESHIP_ROLE_ID
        self.emojis = Config.EMOJI_SEQUENCE
        self.index = 0

    @tasks.loop(seconds=2.0)  # Adjust time between transitions (in seconds)
    async def cycle_emoji(self):
        for guild in self.bot.guilds:
            role = guild.get_role(self.target_role_id)
            if role:
                for member in role.members:
                    current_nickname = member.nick if member.nick else member.name
                    
                    # Find if any emoji is already in the nickname
                    current_emoji = None
                    for emoji in self.emojis:
                        if emoji in current_nickname:
                            current_emoji = emoji
                            break
                    
                    # If emoji is present, replace it; if not, add the first emoji
                    if current_emoji:
                        new_nickname = current_nickname.replace(current_emoji, self.emojis[self.index % len(self.emojis)])
                    else:
                        new_nickname = f"{current_nickname} {self.emojis[self.index % len(self.emojis)]}"
                    
                    try:
                        await member.edit(nick=new_nickname)
                        print(f"[INFO] Updated {member.name}'s nickname to: {new_nickname}")
                    except discord.Forbidden:
                        print("[ERROR] Missing permission to edit nickname.")
                    except Exception as e:
                        print(f"[ERROR] {e}")

        self.index += 1

    def start(self):
        self.cycle_emoji.start()


# Bot Setup
intents = discord.Intents.default()
intents.guilds = True
intents.guild_messages = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=Config.COMMAND_PREFIX, intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    bot.emoji_cycler = EmojiCycler(bot)
    bot.emoji_cycler.start()

# Test command
@bot.command()
async def hello(ctx):
    await ctx.send("Bot is alive. Gago ka daw sabi ni Mason 😤")

# Run bot
bot.run(Config.DISCORD_TOKEN)
