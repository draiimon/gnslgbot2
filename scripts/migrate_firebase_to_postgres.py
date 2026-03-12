from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.firebase_migration import migrate_firestore_to_postgres


def main() -> int:
    migrated = migrate_firestore_to_postgres()
    for collection_name, count in migrated.items():
        print(f"{collection_name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
