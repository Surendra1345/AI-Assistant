"""Tiny SQLite layer for to-dos/reminders and background task records."""
import sqlite3
import threading

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    due TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    notified INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS reported (
    task_id INTEGER PRIMARY KEY
);
"""


def _conn():
    config.HOME.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.HOME / "assistant.db", timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    if "pre_notified" not in {r["name"] for r in c.execute("PRAGMA table_info(todos)")}:
        c.execute("ALTER TABLE todos ADD COLUMN pre_notified INTEGER NOT NULL DEFAULT 0")  # heads-up before due time
        c.commit()
    return c


def execute(sql, params=()):
    with _lock:
        c = _conn()
        try:
            cur = c.execute(sql, params)
            c.commit()
            return cur.lastrowid
        finally:
            c.close()


def query(sql, params=()):
    with _lock:
        c = _conn()
        try:
            return [dict(r) for r in c.execute(sql, params).fetchall()]
        finally:
            c.close()
