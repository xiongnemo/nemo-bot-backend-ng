"""
SQLite connection manager.

Uses WAL journal mode for concurrent reads + a per-thread connection via
threading.local() so the same Database instance can be safely used from
Flask threads, dispatch threads, and the scheduler thread.

Worker processes (ProcessPoolExecutor) should create their own Database
instances — they run in separate address spaces anyway.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = "data/nemo.sqlite"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._local = threading.local()
        # Run migrations on the first connection
        self._migrate()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def get_conn(self) -> sqlite3.Connection:
        """Return a per-thread SQLite connection (created lazily)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    def _migrate(self):
        conn = self.get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()
        logger.info("Database migration complete: %s", self.db_path)


# ======================================================================
# Schema — all tables live here so we have a single source of truth.
# ======================================================================

_SCHEMA = """
-- Full message log (every message that enters /ingest)
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    frontend    TEXT    NOT NULL,
    group_id    TEXT    DEFAULT '',
    user_id     TEXT    NOT NULL,
    user_name   TEXT    DEFAULT '',
    text        TEXT    NOT NULL,
    message_id  TEXT    DEFAULT '',
    ated        INTEGER DEFAULT 0,
    imgs_json   TEXT    DEFAULT '[]',
    raw_json    TEXT    DEFAULT '',
    timestamp   REAL    NOT NULL,
    created_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_msg_group_ts  ON messages(group_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_msg_user_ts   ON messages(user_id, timestamp);

-- FTS5 full-text search on message text
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    text,
    content=messages,
    content_rowid=id,
    tokenize='unicode61'
);

-- Triggers to keep FTS in sync with the messages table
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;

-- Generic key-value state store
CREATE TABLE IF NOT EXISTS kv (
    namespace   TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'global',
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (namespace, scope, key)
);

-- LLM conversation history
CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key     TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    metadata_json TEXT DEFAULT '',
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_scope ON conversations(scope_key, created_at);

-- Scheduler job cursors / state (for cron jobs like github-monitor)
-- Reuses the kv table with namespace='scheduler'.

-- ==========================================
-- Information Feed Hub Schema (Pub/Sub)
-- ==========================================

-- Information sources (Channels)
CREATE TABLE IF NOT EXISTS channels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT ''
);

-- Group Subscriptions to Channels
CREATE TABLE IF NOT EXISTS subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_name TEXT NOT NULL,
    target_group TEXT NOT NULL,
    keywords     TEXT DEFAULT '',
    FOREIGN KEY(channel_name) REFERENCES channels(name) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sub_channel ON subscriptions(channel_name);

-- Ingested Feeds
CREATE TABLE IF NOT EXISTS feeds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_name  TEXT NOT NULL,
    title         TEXT NOT NULL,
    content       TEXT NOT NULL,
    original_time INTEGER NOT NULL,  -- Unix timestamp provided by external source
    created_at    REAL NOT NULL,     -- Ingestion timestamp
    is_duplicate  INTEGER DEFAULT 0, -- Set by Gatekeeper LLM
    meta_score    INTEGER DEFAULT 0, -- Set by Gatekeeper LLM
    meta_json     TEXT DEFAULT '{}', -- Extra info like source_link
    FOREIGN KEY(channel_name) REFERENCES channels(name) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_feeds_channel ON feeds(channel_name, original_time);

-- Mid-Term Memory: Topics
CREATE TABLE IF NOT EXISTS topics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key     TEXT NOT NULL,
    topic_summary TEXT NOT NULL,
    created_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_scope ON topics(scope_key, created_at);
"""
