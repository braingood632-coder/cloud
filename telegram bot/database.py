"""
طبقة بسيطة للتعامل مع قاعدة بيانات SQLite.
تخزن: إعدادات الاشتراك (سعر / مدة / سعة) + المشتركين + الفواتير المعالجة.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from config import DB_PATH

DEFAULTS = {
    "price_sar": "30",
    "duration_days": "30",
    "capacity": "50",
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                expires_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_invoices (
                invoice_id TEXT PRIMARY KEY,
                user_id INTEGER,
                processed_at TEXT
            )
        """)
        for k, v in DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (k, v)
            )


def now_utc():
    return datetime.now(timezone.utc)


# ---------- إعدادات ----------
def get_config(key: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else DEFAULTS.get(key)


def set_config(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO config (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_price() -> float:
    return float(get_config("price_sar"))


def get_duration_days() -> int:
    return int(get_config("duration_days"))


def get_capacity() -> int:
    return int(get_config("capacity"))


# ---------- المشتركين ----------
def add_or_renew_subscriber(user_id: int, username: str, days: int):
    expires_at = (now_utc() + timedelta(days=days)).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO subscribers (user_id, username, expires_at, status) "
            "VALUES (?, ?, ?, 'active') "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "username=excluded.username, expires_at=excluded.expires_at, status='active'",
            (user_id, username, expires_at),
        )
    return expires_at


def get_subscriber(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM subscribers WHERE user_id=?", (user_id,)
        ).fetchone()


def is_active(user_id: int) -> bool:
    row = get_subscriber(user_id)
    if not row or row["status"] != "active":
        return False
    return datetime.fromisoformat(row["expires_at"]) > now_utc()


def get_active_count() -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT expires_at FROM subscribers WHERE status='active'"
        ).fetchall()
    n = now_utc()
    return sum(1 for r in rows if datetime.fromisoformat(r["expires_at"]) > n)


def get_expired_subscribers():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subscribers WHERE status='active'"
        ).fetchall()
    n = now_utc()
    return [r for r in rows if datetime.fromisoformat(r["expires_at"]) <= n]


def mark_expired(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE subscribers SET status='expired' WHERE user_id=?", (user_id,)
        )


# ---------- الفواتير ----------
def invoice_already_processed(invoice_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_invoices WHERE invoice_id=?", (invoice_id,)
        ).fetchone()
        return row is not None


def mark_invoice_processed(invoice_id: str, user_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO processed_invoices (invoice_id, user_id, processed_at) "
            "VALUES (?, ?, ?)",
            (invoice_id, user_id, now_utc().isoformat()),
        )
