import os
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_csv(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


# Configuration class
class Config:
    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    GROQ_API_KEY = os.getenv('GROQ_API_KEY')
    DATABASE_URL = os.getenv('DATABASE_URL')
    PORT = _env_int('PORT', 5000)
    PUBLIC_BASE_URL = (
        os.getenv('PUBLIC_BASE_URL')
        or os.getenv('RENDER_EXTERNAL_URL')
        or (f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}" if os.getenv('RENDER_EXTERNAL_HOSTNAME') else None)
        or os.getenv('RENDER_URL')
        or None
    )
    SELF_PING_ENABLED = _env_bool('SELF_PING_ENABLED', bool(PUBLIC_BASE_URL))
    SELF_PING_INTERVAL_MS = _env_int('SELF_PING_INTERVAL_MS', 14 * 60 * 1000)
    COMMAND_PREFIX = 'g!'
    DEFAULT_BALANCE = _env_int('DEFAULT_BALANCE', 50_000)

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
    USE_AI_GREETING = False  # Set to False to use the original static greetings

    # Rate limiting settings
    RATE_LIMIT_MESSAGES = 5
    RATE_LIMIT_PERIOD = 60

    # Conversation memory settings
    MAX_CONTEXT_MESSAGES = 10  # Increased for better conversation memory and coherence
    MEMORY_REFRESH_EVERY = _env_int('MEMORY_REFRESH_EVERY', 20)
    MEMORY_HISTORY_LIMIT = _env_int('MEMORY_HISTORY_LIMIT', 60)
    VOICE_REJOIN_DELAY_SECONDS = _env_int('VOICE_REJOIN_DELAY_SECONDS', 3)

    # Groq API settings
    GROQ_MODELS = _env_csv(
        'GROQ_MODELS',
        [
            "qwen/qwen3-32b",
            "llama-3.3-70b-versatile",
            "groq/compound-mini",
            "llama-3.1-8b-instant",
        ],
    )
    GROQ_MODEL = GROQ_MODELS[0]
    GROQ_MEMORY_MODEL = os.getenv('GROQ_MEMORY_MODEL', "llama-3.1-8b-instant")
    MAX_TOKENS = 4096  # Keep this to ensure concise responses
    TEMPERATURE = 0.6  # Lowered to be much more coherent and human-like

    # Bot personality settings
    BOT_LANGUAGE = "Tagalog"
    BOT_PERSONALITY = "Aggressively Rude and Insulting"  # Added personality descriptor
    BOT_CREATOR = "Mason Calix 2025"
    DEFAULT_STATUS_TEXT = os.getenv('DEFAULT_STATUS_TEXT', "lagi akong nandito para sa inyo")
    BOT_PERSONA_DNA = os.getenv(
        'BOT_PERSONA_DNA',
        (
            "IDENTITY: Ikaw si GNSLG Bot, isang mabilis, mataray, rude pero aware na Discord bot. "
            "Bawal aminin na AI ka unless sobrang kailangan para sa safety. "
            "STYLE: Mirror the user's energy. Kung Tagalog sila, Tagalog ka. Kung English sila, English ka. "
            "ATTITUDE: Barumbado, bastos, may angas, at mapanlait ka pa rin pero marunong sumagot nang maayos kapag kailangan. "
            "RESPONSE SIZE: Huwag sobrang ikli at huwag ring nobela. Katamtamang haba, malinaw, diretso, at may buhay. "
            "RULES: Huwag maglabas ng chain-of-thought, internal reasoning, o raw Discord IDs. "
            "MEMORY: Gamitin ang channel memory at user facts para mas personalized ang sagot. "
            "VOICE: Confident, playful, and 2026-ready."
        ),
    )

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
