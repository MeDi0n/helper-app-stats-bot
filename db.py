import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "stats.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    tu_id INTEGER NOT NULL,
    ru_id INTEGER NOT NULL,
    ru_name TEXT,
    backfilled INTEGER NOT NULL DEFAULT 0,
    oldest_message_id TEXT,
    newest_message_id TEXT,
    last_activity_at TEXT,     -- lastAt из communication/list - для отбора "что реально менялось"
    last_synced_at TEXT,
    blocked INTEGER NOT NULL DEFAULT 0,  -- клиент заблокировал анкету (флаг flags.blocked)
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tu_id, ru_id)
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    tu_id INTEGER NOT NULL,
    ru_id INTEGER NOT NULL,
    ru_name TEXT,
    author TEXT NOT NULL,       -- tu (анкета) | ru (реальный клиент)
    kind TEXT NOT NULL,         -- text | sticker | gift | paidContent | media | ...
    created_date TEXT NOT NULL, -- ISO UTC с мс, формат из API
    content_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages (tu_id, ru_id, created_date);
CREATE INDEX IF NOT EXISTS idx_messages_kind ON messages (kind);
CREATE INDEX IF NOT EXISTS idx_messages_author ON messages (author);
"""


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.executescript(SCHEMA)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(chats)")}
    if "blocked" not in existing_cols:
        conn.execute("ALTER TABLE chats ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    return conn


def upsert_chat(conn, tu_id, ru_id, ru_name, last_activity_at=None, blocked=None):
    conn.execute(
        """
        INSERT INTO chats (tu_id, ru_id, ru_name, last_activity_at, blocked)
        VALUES (?, ?, ?, ?, COALESCE(?, 0))
        ON CONFLICT(tu_id, ru_id) DO UPDATE SET
            ru_name = COALESCE(excluded.ru_name, chats.ru_name),
            last_activity_at = COALESCE(excluded.last_activity_at, chats.last_activity_at),
            blocked = COALESCE(?, chats.blocked)
        """,
        (tu_id, ru_id, ru_name, last_activity_at, 1 if blocked else (None if blocked is None else 0),
         1 if blocked else (None if blocked is None else 0)),
    )


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_state(conn, key, value):
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_chat(conn, tu_id, ru_id):
    row = conn.execute(
        "SELECT tu_id, ru_id, ru_name, backfilled, oldest_message_id, newest_message_id "
        "FROM chats WHERE tu_id = ? AND ru_id = ?",
        (tu_id, ru_id),
    ).fetchone()
    if not row:
        return None
    keys = ["tu_id", "ru_id", "ru_name", "backfilled", "oldest_message_id", "newest_message_id"]
    return dict(zip(keys, row))


def list_chats(conn):
    rows = conn.execute(
        "SELECT tu_id, ru_id, ru_name, backfilled, last_activity_at, last_synced_at FROM chats"
    ).fetchall()
    keys = ["tu_id", "ru_id", "ru_name", "backfilled", "last_activity_at", "last_synced_at"]
    return [dict(zip(keys, r)) for r in rows]


def update_chat_progress(conn, tu_id, ru_id, *, backfilled=None, oldest_message_id=None,
                          newest_message_id=None, last_synced_at=None):
    sets, args = [], []
    if backfilled is not None:
        sets.append("backfilled = ?")
        args.append(1 if backfilled else 0)
    if oldest_message_id is not None:
        sets.append("oldest_message_id = ?")
        args.append(oldest_message_id)
    if newest_message_id is not None:
        sets.append("newest_message_id = ?")
        args.append(newest_message_id)
    if last_synced_at is not None:
        sets.append("last_synced_at = ?")
        args.append(last_synced_at)
    args.extend([tu_id, ru_id])
    conn.execute(f"UPDATE chats SET {', '.join(sets)} WHERE tu_id = ? AND ru_id = ?", args)


def insert_messages(conn, rows) -> int:
    if not rows:
        return 0
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO messages
            (message_id, tu_id, ru_id, ru_name, author, kind, created_date, content_json)
        VALUES (:message_id, :tu_id, :ru_id, :ru_name, :author, :kind, :created_date, :content_json)
        """,
        rows,
    )
    return conn.total_changes - before


def message_exists(conn, message_id) -> bool:
    return conn.execute("SELECT 1 FROM messages WHERE message_id = ?", (message_id,)).fetchone() is not None
