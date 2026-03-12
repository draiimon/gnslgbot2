import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore
from psycopg2.extras import Json

from .postgres_db import PostgresDB


def _load_firebase_credentials_path() -> Path | None:
    candidates = [
        Path("firebase-credentials.json"),
        Path("/app/firebase-credentials.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raw_credentials = os.getenv("FIREBASE_CREDENTIALS")
    if not raw_credentials:
        return None

    target = Path("firebase-credentials.json")
    target.write_text(raw_credentials, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return target


def _coerce_timestamp(value: Any):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _init_firestore():
    credentials_path = _load_firebase_credentials_path()
    if not credentials_path:
        raise RuntimeError("Firebase credentials were not found")

    try:
        app = firebase_admin.get_app()
    except ValueError:
        app = firebase_admin.initialize_app(credentials.Certificate(str(credentials_path)))
    return firestore.client(app=app)


def migrate_firestore_to_postgres() -> dict[str, int]:
    source = _init_firestore()
    target = PostgresDB()

    migrated = {
        "users": 0,
        "conversations": 0,
        "rate_limits": 0,
        "blackjack_games": 0,
        "voice_preferences": 0,
        "auto_tts_channels": 0,
    }

    with target._connection() as connection:
        with connection.cursor() as cursor:
            for document in source.collection("users").stream():
                payload = document.to_dict() or {}
                cursor.execute(
                    """
                    INSERT INTO users (user_id, balance, last_daily, created_at, updated_at)
                    VALUES (%s, %s, %s, COALESCE(%s, NOW()), NOW())
                    ON CONFLICT (user_id) DO UPDATE
                    SET balance = EXCLUDED.balance,
                        last_daily = EXCLUDED.last_daily,
                        updated_at = NOW()
                    """,
                    (
                        int(payload.get("user_id", document.id)),
                        int(payload.get("balance", target.default_balance)),
                        _coerce_timestamp(payload.get("last_daily")),
                        _coerce_timestamp(payload.get("created_at")),
                    ),
                )
                migrated["users"] += 1

            for document in source.collection("conversations").stream():
                payload = document.to_dict() or {}
                cursor.execute(
                    """
                    INSERT INTO conversations (channel_id, is_user, content, created_at)
                    VALUES (%s, %s, %s, COALESCE(%s, NOW()))
                    """,
                    (
                        int(payload["channel_id"]),
                        bool(payload.get("is_user", True)),
                        payload.get("content", ""),
                        _coerce_timestamp(payload.get("timestamp")),
                    ),
                )
                migrated["conversations"] += 1

            for document in source.collection("rate_limits").stream():
                payload = document.to_dict() or {}
                cursor.execute(
                    """
                    INSERT INTO rate_limits (user_id, created_at)
                    VALUES (%s, COALESCE(%s, NOW()))
                    """,
                    (
                        int(payload["user_id"]),
                        _coerce_timestamp(payload.get("timestamp")),
                    ),
                )
                migrated["rate_limits"] += 1

            for document in source.collection("blackjack").stream():
                payload = document.to_dict() or {}
                cursor.execute(
                    """
                    INSERT INTO blackjack_games (user_id, player_hand, dealer_hand, bet, game_state, updated_at)
                    VALUES (%s, %s, %s, %s, %s, COALESCE(%s, NOW()))
                    ON CONFLICT (user_id) DO UPDATE
                    SET player_hand = EXCLUDED.player_hand,
                        dealer_hand = EXCLUDED.dealer_hand,
                        bet = EXCLUDED.bet,
                        game_state = EXCLUDED.game_state,
                        updated_at = NOW()
                    """,
                    (
                        int(document.id),
                        Json(payload.get("player_hand", [])),
                        Json(payload.get("dealer_hand", [])),
                        int(payload.get("bet", 0)),
                        payload.get("game_state", "in_progress"),
                        _coerce_timestamp(payload.get("updated_at")),
                    ),
                )
                migrated["blackjack_games"] += 1

            for document in source.collection("audio_preferences").stream():
                payload = document.to_dict() or {}
                cursor.execute(
                    """
                    INSERT INTO voice_preferences (user_id, voice, updated_at)
                    VALUES (%s, %s, COALESCE(%s, NOW()))
                    ON CONFLICT (user_id) DO UPDATE
                    SET voice = EXCLUDED.voice,
                        updated_at = NOW()
                    """,
                    (
                        int(payload.get("user_id", document.id)),
                        payload.get("voice", "f"),
                        _coerce_timestamp(payload.get("updated_at")),
                    ),
                )
                migrated["voice_preferences"] += 1

            for document in source.collection("auto_tts_settings").stream():
                payload = document.to_dict() or {}
                channels = payload.get("channels", [])
                for channel_id in channels:
                    cursor.execute(
                        """
                        INSERT INTO auto_tts_channels (guild_id, channel_id, enabled, updated_at)
                        VALUES (%s, %s, TRUE, COALESCE(%s, NOW()))
                        ON CONFLICT (guild_id, channel_id) DO UPDATE
                        SET enabled = TRUE,
                            updated_at = NOW()
                        """,
                        (
                            int(document.id),
                            int(channel_id),
                            _coerce_timestamp(payload.get("updated_at")),
                        ),
                    )
                    migrated["auto_tts_channels"] += 1

    target.set_persona("migration_source", "firestore")
    return migrated
