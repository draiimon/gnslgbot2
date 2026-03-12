import datetime
import logging
import os
import sys
import random
import threading
from typing import Any

import discord
import pytz
import requests
from discord.ext import commands, tasks
from flask import Flask, jsonify, render_template

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from bot.cog import ChatCog
from bot.config import Config
from bot.postgres_db import PostgresDB
from bot.runtime_config import can_use_audio_features
from bot.speech_recognition_cog import SpeechRecognitionCog


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gnslg.bot")


def load_opus_library() -> None:
    if discord.opus.is_loaded():
        return

    for candidate in ("libopus.so.0", "libopus.so", "opus"):
        try:
            discord.opus.load_opus(candidate)
            logger.info("Loaded opus library: %s", candidate)
            return
        except Exception:
            continue

    logger.warning("Could not load opus manually. Voice playback will rely on system defaults.")


load_opus_library()


last_morning_greeting_date = None
last_night_greeting_date = None
maintenance_mode = False


class GNSLGBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=Config.COMMAND_PREFIX,
            intents=discord.Intents.all(),
            help_command=None,
        )
        self.db = PostgresDB()
        self.booted_at = datetime.datetime.now(datetime.timezone.utc)
        self.self_ping_stop = threading.Event()
        self.status_restored = False

    async def setup_hook(self) -> None:
        chat_cog = ChatCog(self)
        chat_cog.db = self.db
        speech_cog = SpeechRecognitionCog(self)
        speech_cog.db = self.db

        await self.add_cog(chat_cog)
        await self.add_cog(speech_cog)
        speech_cog.get_ai_response = chat_cog.get_ai_response


bot = GNSLGBot()


def build_health_snapshot() -> dict[str, Any]:
    db_ok = bot.db.healthcheck() if getattr(bot, "db", None) else False
    saved_voice_state = bot.db.get_saved_voice_state() if db_ok else None
    uptime_seconds = int((datetime.datetime.now(datetime.timezone.utc) - bot.booted_at).total_seconds())

    return {
        "status": "ok",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "uptime_seconds": uptime_seconds,
        "discord": {
            "ready": bot.is_ready(),
            "latency_ms": round(bot.latency * 1000, 2) if bot.is_ready() else None,
            "guilds": len(bot.guilds),
            "commands": len(bot.commands),
            "voice_connections": sum(1 for voice_client in bot.voice_clients if voice_client.is_connected()),
        },
        "database": {
            "configured": bool(Config.DATABASE_URL),
            "connected": db_ok,
            "provider": "postgresql",
        },
        "keepalive": {
            "enabled": Config.SELF_PING_ENABLED and bool(Config.PUBLIC_BASE_URL),
            "target": f"{Config.PUBLIC_BASE_URL.rstrip('/')}/ping" if Config.PUBLIC_BASE_URL else None,
        },
        "runtime": {
            "audio_enabled": can_use_audio_features(),
            "maintenance_mode": maintenance_mode,
            "saved_voice_state": saved_voice_state,
        },
    }


def create_web_app() -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.get("/")
    def home():
        snapshot = build_health_snapshot()
        return render_template(
            "index.html",
            snapshot=snapshot,
            discord_ready=snapshot["discord"]["ready"],
            db_ready=snapshot["database"]["connected"],
            public_base_url=Config.PUBLIC_BASE_URL,
        )

    @app.get("/ping")
    def ping():
        snapshot = build_health_snapshot()
        return jsonify(
            {
                "message": "pong",
                "timestamp": snapshot["timestamp"],
                "uptime_seconds": snapshot["uptime_seconds"],
            }
        )

    @app.get("/ready")
    def ready():
        payload = {"ready": bot.is_ready(), "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        return jsonify(payload), 200 if payload["ready"] else 503

    @app.get("/health")
    def health():
        return jsonify(build_health_snapshot())

    return app


def start_web_server() -> None:
    app = create_web_app()
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=Config.PORT, use_reloader=False),
        daemon=True,
        name="gnslg-web",
    )
    thread.start()
    logger.info("Health server started on port %s", Config.PORT)


def start_self_ping() -> None:
    if not Config.SELF_PING_ENABLED or not Config.PUBLIC_BASE_URL:
        logger.info("Self-ping disabled. PUBLIC_BASE_URL is not configured.")
        return

    target_url = f"{Config.PUBLIC_BASE_URL.rstrip('/')}/ping"

    def worker() -> None:
        logger.info("Self-ping enabled -> %s every %ss", target_url, Config.SELF_PING_INTERVAL_MS // 1000)
        while not bot.self_ping_stop.wait(Config.SELF_PING_INTERVAL_MS / 1000):
            try:
                response = requests.get(target_url, timeout=10)
                logger.info("Self-ping OK (%s)", response.status_code)
            except Exception as exc:
                logger.warning("Self-ping failed: %s", exc)

    threading.Thread(target=worker, daemon=True, name="gnslg-self-ping").start()


@bot.event
async def on_ready():
    logger.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")
    logger.info("Registered %s commands", len(bot.commands))

    if not bot.status_restored:
        saved_status = bot.db.get_bot_status() or Config.DEFAULT_STATUS_TEXT
        if saved_status:
            await bot.change_presence(activity=discord.CustomActivity(name=saved_status))
        bot.status_restored = True

    if not check_greetings.is_running():
        check_greetings.start()


@tasks.loop(minutes=1)
async def check_greetings():
    global last_morning_greeting_date, last_night_greeting_date, maintenance_mode

    if maintenance_mode:
        return

    ph_timezone = pytz.timezone("Asia/Manila")
    now = datetime.datetime.now(ph_timezone)
    current_hour = now.hour
    current_date = now.date()

    channel = bot.get_channel(Config.GREETINGS_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(Config.GREETINGS_CHANNEL_ID)
        except Exception:
            return

    chat_cog = bot.get_cog("ChatCog")

    if (
        current_hour == Config.GOOD_MORNING_HOUR
        and (last_morning_greeting_date is None or last_morning_greeting_date != current_date)
    ):
        online_members = [
            member
            for member in channel.guild.members
            if member.status in [discord.Status.online, discord.Status.idle, discord.Status.dnd] and not member.bot
        ]
        if online_members:
            if chat_cog:
                greeting = await chat_cog.generate_greeting("morning", online_members)
            else:
                mentions = " ".join(member.mention for member in online_members)
                greeting = random.choice(
                    [
                        f"**MAGANDANG UMAGA MGA GAGO!** {mentions} GISING NA KAYO!",
                        f"**RISE AND SHINE MGA BOBO!** {mentions} PRODUCTIVITY TIME!",
                    ]
                )
            await channel.send(greeting)
            last_morning_greeting_date = current_date

    elif (
        current_hour == Config.GOOD_NIGHT_HOUR
        and (last_night_greeting_date is None or last_night_greeting_date != current_date)
    ):
        if chat_cog:
            greeting = await chat_cog.generate_greeting("night")
        else:
            greeting = random.choice(
                [
                    "**TULOG NA MGA GAGO!**",
                    "**GOOD NIGHT MGA HAYOP!**",
                ]
            )
        await channel.send(greeting)
        last_night_greeting_date = current_date


@check_greetings.before_loop
async def before_check_greetings():
    await bot.wait_until_ready()


@bot.event
async def on_command_error(ctx, error):
    logger.warning("Command error (%s): %s", type(error).__name__, error)

    if isinstance(error, commands.CommandNotFound):
        await ctx.send("**WALANG GANYANG COMMAND!** TRY MO `g!tulong` PARA MAY DIREKSYON KA.")
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("**KULANG YUNG COMMAND MO!** TYPE MO `g!tulong` PARA MALAMAN MO GAMITIN.")
        return

    if isinstance(error, commands.CheckFailure):
        if ctx.command and ctx.command.name == "g":
            await ctx.send(f"**KUPAL DI KA NAMAN ADMIN!!!** {ctx.author.mention}")
        else:
            await ctx.send("**WALA KANG PERMISSION PARA DIYAN!**")
        return

    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"**SAGLIT LANG!** Antay ka ng {error.retry_after:.1f}s.")
        return

    if isinstance(error, discord.HTTPException) and error.status == 429:
        logger.warning("Discord API rate limit triggered: %s", error)
        return

    try:
        await ctx.send("**MAY ERROR.** Subukan mo ulit mamaya.")
    except Exception:
        pass
    logger.error(
        "Unhandled command error: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )


def validate_discord_token(token: str | None) -> tuple[bool, str]:
    if not token:
        return False, "Token is empty"
    if len(token) < 50:
        return False, "Token is too short"
    if "." not in token:
        return False, "Token should contain a period"
    return True, "Token format looks valid"


def main() -> None:
    if not Config.DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is required")
    if not Config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required")
    if not Config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required")

    is_valid, reason = validate_discord_token(Config.DISCORD_TOKEN)
    if not is_valid:
        raise RuntimeError(f"Discord token validation failed: {reason}")

    if can_use_audio_features():
        logger.info("Full audio features enabled")
    else:
        logger.warning("Running in text-only mode. Voice features may be limited on this host.")

    start_web_server()
    start_self_ping()

    try:
        bot.run(Config.DISCORD_TOKEN, log_handler=None)
    finally:
        bot.self_ping_stop.set()
        bot.db.close()


if __name__ == "__main__":
    main()
