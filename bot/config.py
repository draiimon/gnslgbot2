import os
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# Configuration class
class Config:
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    GROQ_API_KEY = os.getenv('GROQ_API_KEY')
    COMMAND_PREFIX = 'g!'

    # Add this utility method for removing <think>...</think> tags
    @staticmethod
    def strip_think_blocks(text: str) -> str:
        """Removes <think>...</think> blocks from the given text."""
        return re.sub(r"<think>.*?</think>",
                      "",
                      text,
                      flags=re.DOTALL | re.IGNORECASE).strip()

    # Channel IDs
    RULES_CHANNEL_ID = 1345727358015115385
    ANNOUNCEMENTS_CHANNEL_ID = 1345727358015115389
    AUTO_MESSAGE_CHANNEL_ID = 1345727358015115389  # Updated to use the announcements channel
    GREETINGS_CHANNEL_ID = 1345727358149328952  # Channel for morning/night greetings

    # Greetings settings
    GOOD_MORNING_HOUR = 8  # 8:00 AM
    GOOD_NIGHT_HOUR = 22  # 10:00 PM

    # Rate limiting settings
    RATE_LIMIT_MESSAGES = 5
    RATE_LIMIT_PERIOD = 60

    # Conversation memory settings
    MAX_CONTEXT_MESSAGES = 10  # Increased for better conversation memory and coherence

    # Groq API settings
    GROQ_MODEL = "qwen/qwen3-32b"
    MAX_TOKENS = 4096  # Keep this to ensure concise responses
    TEMPERATURE = 0.6  # Lowered to be much more coherent and human-like

    # Bot personality settings
    BOT_LANGUAGE = "Tagalog"
    BOT_PERSONALITY = "Aggressively Rude and Insulting"  # Added personality descriptor
    BOT_CREATOR = "Mason Calix 2025"

    # Unicode map for text conversion - bold font style
    UNICODE_MAP = {
        'A': '𝐀',
        'B': '𝐁',
        'C': '𝐂',
        'D': '𝐃',
        'E': '𝐄',
        'F': '𝐅',
        'G': '𝐆',
        'H': '𝐇',
        'I': '𝐈',
        'J': '𝐉',
        'K': '𝐊',
        'L': '𝐋',
        'M': '𝐌',
        'N': '𝐍',
        'O': '𝐎',
        'P': '𝐏',
        'Q': '𝐐',
        'R': '𝐑',
        'S': '𝐒',
        'T': '𝐓',
        'U': '𝐔',
        'V': '𝐕',
        'W': '𝐖',
        'X': '𝐗',
        'Y': '𝐘',
        'Z': '𝐙',
        'a': '𝐚',
        'b': '𝐛',
        'c': '𝐜',
        'd': '𝐝',
        'e': '𝐞',
        'f': '𝐟',
        'g': '𝐠',
        'h': '𝐡',
        'i': '𝐢',
        'j': '𝐣',
        'k': '𝐤',
        'l': '𝐥',
        'm': '𝐦',
        'n': '𝐧',
        'o': '𝐨',
        'p': '𝐩',
        'q': '𝐪',
        'r': '𝐫',
        's': '𝐬',
        't': '𝐭',
        'u': '𝐮',
        'v': '𝐯',
        'w': '𝐰',
        'x': '𝐱',
        'y': '𝐲',
        'z': '𝐳',
        '0': '𝟎',
        '1': '𝟏',
        '2': '𝟐',
        '3': '𝟑',
        '4': '𝟒',
        '5': '𝟓',
        '6': '𝟔',
        '7': '𝟕',
        '8': '𝟖',
        '9': '𝟗',
        ' ': ' ',
        '_': '_',
        '-': '-',
        '.': '.',
        ',': ',',
        '!': '!',
        '?': '?',
        ':': ':',
        '|': '|',
        '(': '(',
        ')': ')',
        '[': '[',
        ']': ']',
        '{': '{',
        '}': '}',
        '#': '#',
        '*': '*',
        '+': '+',
        '=': '=',
        '/': '/',
        '\\': '\\',
        '<': '<',
        '>': '>',
        '~': '~',
        '@': '@',
        '$': '$',
        '%': '%',
        '^': '^',
        '&': '&'
    }

    # Role IDs and Emojis - centralized configuration
    # This avoids duplicated data in cog.py
    ROLE_EMOJI_MAP = {
        705770837399306332: "🌿",  # Owner
        1345727357662658603: "🌿",  # 𝐇𝐈𝐆𝐇
        1345727357645885448: "🍆",  # 𝐊𝐄𝐊𝐋𝐀𝐑𝐒
        1345727357645885449: "💦",  # 𝐓𝐀𝐌𝐎𝐃𝐄𝐑𝐀𝐓𝐎𝐑
        1348305679877935124: "🚀",  # 𝐀𝐒𝐀 𝐒𝐏𝐀𝐂𝐄𝐒𝐇𝐈𝐏
        1345727357612195890: "🌸",  # 𝐕𝐀𝐕𝐀𝐈𝐇𝐀𝐍
        1345727357612195889: "💪",  # 𝐁𝐎𝐒𝐒𝐈𝐍𝐆
        1345727357612195887: "☁️",  # 𝐁𝐖𝐈𝐒𝐈𝐓𝐀
        1345727357645885446: "🍑",  # 𝐁𝐎𝐓 𝐒𝐈 𝐁𝐇𝐈𝐄
        1345727357612195885: "🛑",  # 𝐁𝐎𝐁𝐎
        1363575609363665079: "🤤",  # 𝐌𝐀𝐍𝐘𝐀𝐊𝐎𝐋
        1363574928707948654: "⭐",  # 𝐕𝐈𝐏
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

    # Bots to ignore in nickname formatting
    BOTS_TO_IGNORE = [
        # Music bots removed as they're no longer needed
    ]

    # Admin role IDs for setupnn command permission
    ADMIN_ROLE_IDS = [
        1345727357662658603,  # 𝐇𝐈𝐆𝐇
        1345727357645885449,  # 𝐓𝐀𝐌𝐎𝐃𝐄𝐑𝐀𝐓𝐎𝐑
        1345727357645885448,  # 𝐊𝐄𝐊𝐋𝐀𝐑𝐒
    ]

    # UI settings
    EMBED_COLOR_PRIMARY = 0xFF5733  # Bright orange-red
    EMBED_COLOR_SUCCESS = 0x33FF57  # Bright green
    EMBED_COLOR_ERROR = 0xFF3357  # Bright red
    EMBED_COLOR_INFO = 0x3357FF  # Bright blue

    # Audio streaming settings - using direct FFmpeg playback only
    # This gives maximum reliability and avoids any external API dependencies
    USE_DIRECT_STREAMING = True
