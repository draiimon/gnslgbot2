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

    # Conversation memory
    MAX_CONTEXT_MESSAGES = 10

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
        '5': '𝟓', '6': '𝟖', '7': '𝟕', '8': '𝟖', '9': '𝟗',
        ' ': ' ', '_': '_', '-': '-', '.': '.', ',': ',', '!': '!', '?': '?'
    }

    # Role Emojis
    ROLE_EMOJI_MAP = {
        705770837399306332: "🌿",
        1345727357662658603: "🌿",
        1345727357645885448: "🍆",
        1345727357645885449: "💦",
        1348305679877935124: "🚀",
        1345727357612195890: "🌸",
        1345727357612195889: "💪",
        1345727357612195887: "☁️",
        1345727357645885446: "🍑",
        1345727357612195885: "🛑",
    }

    ROLE_NAMES = {
        705770837399306332: "Owner",
        1345727357662658603: "𝐇𝐈𝐆𝐇",
        1345727357645885448: "𝐊𝐄𝐊𝐋𝐀𝐑𝐒",
        1345727357645885449: "𝐓𝐀𝐌𝐎𝐃𝐄𝐑𝐀𝐓𝐎𝐑",
        1348305679877935124: "𝐀𝐒𝐀 𝐒𝐏𝐀𝐂𝐄𝐒𝐇𝐈𝐏",
        1345727357612195890: "𝐕𝐀𝐕𝐀𝐈𝐇𝐀𝐍",
        1345727357612195889: "𝐁𝐎𝐒𝐒𝐈𝐍𝐆",
        1345727357612195887: "𝐁𝐖𝐈𝐒𝐈𝐓𝐀",
        1345727357645885446: "𝐁𝐎𝐓 𝐒𝐈 𝐁𝐇𝐈𝐄",
        1345727357612195885: "𝐁𝐎𝐁𝐎",
    }

    BOTS_TO_IGNORE = []

    ADMIN_ROLE_IDS = [
        1345727357662658603,
        1345727357645885449,
        1345727357645885448,
    ]

    EMBED_COLOR_PRIMARY = 0xFF5733
    EMBED_COLOR_SUCCESS = 0x33FF57
    EMBED_COLOR_ERROR = 0xFF3357
    EMBED_COLOR_INFO = 0x3357FF

    USE_DIRECT_STREAMING = True

    # For animated role
    ASA_SPACESHIP_ROLE_ID = 1348305679877935124
    EMOJI_SEQUENCE = ['🚀', '👽', '💥', '🛸', '🌌', '✨']


# Emoji Cycler for transitioning ASA SPACESHIP role users' nicknames
class EmojiCycler:
    def __init__(self, bot):
        self.bot = bot
        self.target_role_id = Config.ASA_SPACESHIP_ROLE_ID
        self.emojis = Config.EMOJI_SEQUENCE
        self.index = 0

    @tasks.loop(seconds=5.0)  # Adjust the time interval for the emoji transition
    async def cycle_emoji(self):
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:  # Skip bots
                    continue

                # Check if the member has the ASA SPACESHIP role
                if any(role.id == self.target_role_id for role in member.roles):
                    # Get current nickname and update it with the new emoji
                    current_nickname = member.nick if member.nick else member.display_name
                    emoji = self.emojis[self.index % len(self.emojis)]
                    new_nickname = f"{current_nickname} {emoji}"  # Replace old emoji with new one
                    
                    try:
                        await member.edit(nick=new_nickname)
                        print(f"[INFO] Updated {member.name}'s nickname to: {new_nickname}")
                    except discord.Forbidden:
                        print(f"[ERROR] Missing permission to edit {member.name}'s nickname.")
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
