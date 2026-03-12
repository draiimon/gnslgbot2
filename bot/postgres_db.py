import atexit
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .config import Config


class PostgresDB:
    """Neon/Postgres-backed persistence layer for the Discord bot."""

    def __init__(self) -> None:
        if not Config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required")

        self.connected = False
        self.default_balance = Config.DEFAULT_BALANCE
        self.pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=Config.DATABASE_URL,
            sslmode="require",
        )
        self._closed = False
        self._init_schema()
        self.connected = True
        atexit.register(self.close)

    @contextmanager
    def _connection(self):
        connection = self.pool.getconn()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self.pool.putconn(connection)

    def _init_schema(self) -> None:
        schema = f"""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            balance BIGINT NOT NULL DEFAULT {self.default_balance},
            last_daily TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        ALTER TABLE users ALTER COLUMN balance SET DEFAULT {self.default_balance};

        CREATE TABLE IF NOT EXISTS rate_limits (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id BIGSERIAL PRIMARY KEY,
            channel_id BIGINT NOT NULL,
            is_user BOOLEAN NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS messages (
            id BIGSERIAL PRIMARY KEY,
            guild_id BIGINT NULL,
            channel_id BIGINT NOT NULL,
            author_id BIGINT NOT NULL,
            author_tag TEXT NOT NULL,
            content TEXT NOT NULL,
            is_bot BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS blackjack_games (
            user_id BIGINT PRIMARY KEY,
            player_hand JSONB NOT NULL,
            dealer_hand JSONB NOT NULL,
            bet BIGINT NOT NULL,
            game_state TEXT NOT NULL DEFAULT 'in_progress',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS voice_preferences (
            user_id BIGINT PRIMARY KEY,
            voice TEXT NOT NULL DEFAULT 'f',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS auto_tts_channels (
            guild_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (guild_id, channel_id)
        );

        CREATE TABLE IF NOT EXISTS channel_memory (
            channel_id BIGINT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            message_count INTEGER NOT NULL DEFAULT 0,
            last_summarized_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS user_memory (
            user_id BIGINT PRIMARY KEY,
            facts TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS persona (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_rate_limits_user_created
            ON rate_limits (user_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_conversations_channel_created
            ON conversations (channel_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_messages_channel_created
            ON messages (channel_id, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_messages_author_created
            ON messages (author_id, created_at DESC);
        """

        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(schema)
                cursor.execute(
                    """
                    INSERT INTO persona (key, value)
                    VALUES (%s, %s)
                    ON CONFLICT (key) DO NOTHING
                    """,
                    ("master_dna", Config.BOT_PERSONA_DNA),
                )

    def close(self) -> None:
        if not self._closed and getattr(self, "pool", None) is not None:
            self.pool.closeall()
            self._closed = True
            self.connected = False

    def healthcheck(self) -> bool:
        try:
            with self._connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            return True
        except Exception:
            return False

    def _ensure_user(self, user_id: int) -> None:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (user_id, balance)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (int(user_id), self.default_balance),
                )

    def get_user_balance(self, user_id: int) -> int:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (user_id, balance)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (int(user_id), self.default_balance),
                )
                cursor.execute(
                    "SELECT balance FROM users WHERE user_id = %s",
                    (int(user_id),),
                )
                row = cursor.fetchone()
                return int(row["balance"]) if row else self.default_balance

    def add_coins(self, user_id: int, amount: int) -> int:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (user_id, balance)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE
                    SET balance = users.balance + %s,
                        updated_at = NOW()
                    RETURNING balance
                    """,
                    (int(user_id), self.default_balance + amount, amount),
                )
                row = cursor.fetchone()
                return int(row["balance"])

    def deduct_coins(self, user_id: int, amount: int) -> int | None:
        self._ensure_user(user_id)
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET balance = balance - %s,
                        updated_at = NOW()
                    WHERE user_id = %s AND balance >= %s
                    RETURNING balance
                    """,
                    (amount, int(user_id), amount),
                )
                row = cursor.fetchone()
                return int(row["balance"]) if row else None

    def update_daily_cooldown(self, user_id: int) -> bool:
        self._ensure_user(user_id)
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE users
                    SET last_daily = NOW(),
                        updated_at = NOW()
                    WHERE user_id = %s
                    """,
                    (int(user_id),),
                )
        return True

    def get_daily_cooldown(self, user_id: int):
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT last_daily FROM users WHERE user_id = %s",
                    (int(user_id),),
                )
                row = cursor.fetchone()
                return row["last_daily"] if row else None

    def add_rate_limit_entry(self, user_id: int) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO rate_limits (user_id) VALUES (%s)",
                    (int(user_id),),
                )
        return True

    def is_rate_limited(self, user_id: int, limit: int = 5, period_seconds: int = 60) -> bool:
        threshold = datetime.now(timezone.utc) - timedelta(seconds=period_seconds)
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM rate_limits
                    WHERE user_id = %s AND created_at > %s
                    """,
                    (int(user_id), threshold),
                )
                row = cursor.fetchone()
                return int(row["count"]) >= limit

    def clear_old_rate_limits(self) -> int:
        threshold = datetime.now(timezone.utc) - timedelta(hours=1)
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "DELETE FROM rate_limits WHERE created_at < %s RETURNING id",
                    (threshold,),
                )
                return len(cursor.fetchall())

    def add_to_conversation(self, channel_id: int, is_user: bool, content: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations (channel_id, is_user, content)
                    VALUES (%s, %s, %s)
                    """,
                    (int(channel_id), bool(is_user), content),
                )
        return True

    def get_conversation_history(self, channel_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT is_user, content
                    FROM conversations
                    WHERE channel_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (int(channel_id), limit),
                )
                rows = cursor.fetchall()
                rows.reverse()
                return [
                    {"is_user": bool(row["is_user"]), "content": row["content"]}
                    for row in rows
                ]

    def clear_conversation_history(self, channel_id: int) -> int:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "DELETE FROM conversations WHERE channel_id = %s RETURNING id",
                    (int(channel_id),),
                )
                return len(cursor.fetchall())

    def save_blackjack_game(
        self,
        user_id: int,
        player_hand: list[int],
        dealer_hand: list[int],
        bet: int,
        game_state: str = "in_progress",
    ) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO blackjack_games (user_id, player_hand, dealer_hand, bet, game_state, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET player_hand = EXCLUDED.player_hand,
                        dealer_hand = EXCLUDED.dealer_hand,
                        bet = EXCLUDED.bet,
                        game_state = EXCLUDED.game_state,
                        updated_at = NOW()
                    """,
                    (int(user_id), Json(player_hand), Json(dealer_hand), bet, game_state),
                )
        return True

    def get_blackjack_game(self, user_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT player_hand, dealer_hand, bet, game_state
                    FROM blackjack_games
                    WHERE user_id = %s
                    """,
                    (int(user_id),),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    "player_hand": list(row["player_hand"]),
                    "dealer_hand": list(row["dealer_hand"]),
                    "bet": int(row["bet"]),
                    "game_state": row["game_state"],
                }

    def delete_blackjack_game(self, user_id: int) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM blackjack_games WHERE user_id = %s",
                    (int(user_id),),
                )
        return True

    def get_leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT user_id, balance
                    FROM users
                    ORDER BY balance DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [
                    {"user_id": str(row["user_id"]), "balance": int(row["balance"])}
                    for row in cursor.fetchall()
                ]

    def get_user_stats(self, user_id: int) -> dict[str, Any]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT user_id, balance, last_daily, created_at
                    FROM users
                    WHERE user_id = %s
                    """,
                    (int(user_id),),
                )
                row = cursor.fetchone()
                if not row:
                    return {"user_id": int(user_id), "balance": self.default_balance}
                return {
                    "user_id": int(row["user_id"]),
                    "balance": int(row["balance"]),
                    "last_daily": row["last_daily"],
                    "created_at": row["created_at"],
                }

    def get_user_voice_preference(self, user_id: int) -> str:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT voice FROM voice_preferences WHERE user_id = %s",
                    (int(user_id),),
                )
                row = cursor.fetchone()
                return row["voice"] if row else "f"

    def set_user_voice_preference(self, user_id: int, voice_type: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO voice_preferences (user_id, voice, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET voice = EXCLUDED.voice,
                        updated_at = NOW()
                    """,
                    (int(user_id), voice_type),
                )
        return True

    def get_auto_tts_channels(self) -> dict[str, list[str]]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT guild_id, channel_id
                    FROM auto_tts_channels
                    WHERE enabled = TRUE
                    ORDER BY guild_id, channel_id
                    """
                )
                result: dict[str, list[str]] = {}
                for row in cursor.fetchall():
                    guild_id = str(row["guild_id"])
                    result.setdefault(guild_id, []).append(str(row["channel_id"]))
                return result

    def toggle_auto_tts_channel(self, guild_id: int, channel_id: int) -> bool:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT enabled
                    FROM auto_tts_channels
                    WHERE guild_id = %s AND channel_id = %s
                    """,
                    (int(guild_id), int(channel_id)),
                )
                row = cursor.fetchone()
                if row and row["enabled"]:
                    cursor.execute(
                        """
                        DELETE FROM auto_tts_channels
                        WHERE guild_id = %s AND channel_id = %s
                        """,
                        (int(guild_id), int(channel_id)),
                    )
                    return False

                cursor.execute(
                    """
                    INSERT INTO auto_tts_channels (guild_id, channel_id, enabled, updated_at)
                    VALUES (%s, %s, TRUE, NOW())
                    ON CONFLICT (guild_id, channel_id) DO UPDATE
                    SET enabled = TRUE,
                        updated_at = NOW()
                    """,
                    (int(guild_id), int(channel_id)),
                )
                return True

    def log_message(
        self,
        guild_id: int | None,
        channel_id: int,
        author_id: int,
        author_tag: str,
        content: str,
        *,
        is_bot: bool = False,
    ) -> bool:
        sanitized_content = content.strip() or "[attachment]"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO messages (guild_id, channel_id, author_id, author_tag, content, is_bot)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        int(guild_id) if guild_id is not None else None,
                        int(channel_id),
                        int(author_id),
                        author_tag,
                        sanitized_content,
                        is_bot,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO channel_memory (channel_id, summary, message_count, last_summarized_count, updated_at)
                    VALUES (%s, '', 1, 0, NOW())
                    ON CONFLICT (channel_id) DO UPDATE
                    SET message_count = channel_memory.message_count + 1,
                        updated_at = NOW()
                    """,
                    (int(channel_id),),
                )
        return True

    def get_recent_messages(self, channel_id: int, limit: int = 60) -> list[dict[str, Any]]:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT guild_id, channel_id, author_id, author_tag, content, is_bot, created_at
                    FROM messages
                    WHERE channel_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (int(channel_id), limit),
                )
                rows = cursor.fetchall()
                rows.reverse()
                return [dict(row) for row in rows]

    def should_refresh_channel_memory(self, channel_id: int, every: int = 20) -> bool:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT message_count, last_summarized_count
                    FROM channel_memory
                    WHERE channel_id = %s
                    """,
                    (int(channel_id),),
                )
                row = cursor.fetchone()
                if not row:
                    return False
                return int(row["message_count"]) - int(row["last_summarized_count"]) >= every

    def get_channel_memory(self, channel_id: int) -> str:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT summary FROM channel_memory WHERE channel_id = %s",
                    (int(channel_id),),
                )
                row = cursor.fetchone()
                return row["summary"] if row else ""

    def set_channel_memory(self, channel_id: int, summary: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO channel_memory (channel_id, summary, message_count, last_summarized_count, updated_at)
                    VALUES (%s, %s, 0, 0, NOW())
                    ON CONFLICT (channel_id) DO UPDATE
                    SET summary = EXCLUDED.summary,
                        last_summarized_count = channel_memory.message_count,
                        updated_at = NOW()
                    """,
                    (int(channel_id), summary.strip()),
                )
        return True

    def get_user_memory(self, user_id: int) -> str:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT facts FROM user_memory WHERE user_id = %s",
                    (int(user_id),),
                )
                row = cursor.fetchone()
                return row["facts"] if row else ""

    def set_user_memory(self, user_id: int, facts: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO user_memory (user_id, facts, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET facts = EXCLUDED.facts,
                        updated_at = NOW()
                    """,
                    (int(user_id), facts.strip()[:2000]),
                )
        return True

    def merge_user_memory(self, user_id: int, facts: str) -> bool:
        existing = self.get_user_memory(user_id)
        chunks = [chunk.strip() for chunk in existing.split("|") if chunk.strip()]
        for chunk in [item.strip() for item in facts.split("|") if item.strip()]:
            if chunk not in chunks:
                chunks.append(chunk)
        return self.set_user_memory(user_id, " | ".join(chunks)[-2000:])

    def clear_user_memory(self, user_id: int) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM user_memory WHERE user_id = %s",
                    (int(user_id),),
                )
        return True

    def get_persona(self, key: str, default: str = "") -> str:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT value FROM persona WHERE key = %s",
                    (key,),
                )
                row = cursor.fetchone()
                return row["value"] if row else default

    def set_persona(self, key: str, value: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO persona (key, value, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (key, value),
                )
        return True

    def save_voice_state(self, guild_id: int, channel_id: int) -> bool:
        return self.set_state(
            "voice_state",
            {
                "guild_id": int(guild_id),
                "channel_id": int(channel_id),
                "saved_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def get_saved_voice_state(self) -> dict[str, Any] | None:
        payload = self.get_state("voice_state")
        return payload if isinstance(payload, dict) else None

    def clear_voice_state(self) -> bool:
        return self.delete_state("voice_state")

    def save_bot_status(self, status_text: str) -> bool:
        return self.set_state("custom_status", {"text": status_text})

    def get_bot_status(self) -> str | None:
        payload = self.get_state("custom_status")
        if isinstance(payload, dict):
            return payload.get("text")
        return None

    def set_state(self, key: str, value: dict[str, Any]) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO bot_state (key, value, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = NOW()
                    """,
                    (key, Json(value)),
                )
        return True

    def get_state(self, key: str) -> Any:
        with self._connection() as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT value FROM bot_state WHERE key = %s", (key,))
                row = cursor.fetchone()
                return row["value"] if row else None

    def delete_state(self, key: str) -> bool:
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM bot_state WHERE key = %s", (key,))
        return True
