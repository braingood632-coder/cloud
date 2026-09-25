import sqlite3
import time
from contextlib import contextmanager
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    phone TEXT,
    first_name TEXT,
    username TEXT,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS subscriptions (
    telegram_id INTEGER PRIMARY KEY,
    end_date INTEGER NOT NULL DEFAULT 0,
    plan_months INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payments (
    invoice_id TEXT PRIMARY KEY,
    telegram_id INTEGER NOT NULL,
    plan_months INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'initiated',
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS warn_state (
    telegram_id INTEGER PRIMARY KEY,
    last_warned_at INTEGER
);
"""

DEFAULT_SETTINGS = {
    "bot_display_name": "SubmKut",
    "group_id": "",
}
# الأسعار (3 أشهر=50 ريال / 6 أشهر=80 ريال) ثابتة ورسمية ومكتوبة بالكود في bot.py (PLANS)
# وليست مخزّنة بقاعدة البيانات ولا قابلة للتعديل من داخل البوت.


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )


# ---------- settings ----------
def get_setting(key: str, default: str = "") -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ---------- users ----------
def upsert_user(telegram_id: int, phone: str = None, first_name: str = None, username: str = None):
    with db() as conn:
        row = conn.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        if row:
            if phone:
                conn.execute("UPDATE users SET phone=? WHERE telegram_id=?", (phone, telegram_id))
            if first_name:
                conn.execute("UPDATE users SET first_name=? WHERE telegram_id=?", (first_name, telegram_id))
            if username:
                conn.execute("UPDATE users SET username=? WHERE telegram_id=?", (username, telegram_id))
        else:
            conn.execute(
                "INSERT INTO users (telegram_id, phone, first_name, username, created_at) VALUES (?,?,?,?,?)",
                (telegram_id, phone, first_name, username, int(time.time())),
            )


def get_user(telegram_id: int):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()


def has_phone(telegram_id: int) -> bool:
    u = get_user(telegram_id)
    return bool(u and u["phone"])


# ---------- subscriptions ----------
def is_subscribed(telegram_id: int) -> bool:
    with db() as conn:
        row = conn.execute("SELECT end_date FROM subscriptions WHERE telegram_id=?", (telegram_id,)).fetchone()
        return bool(row and row["end_date"] > int(time.time()))


def get_subscription_end(telegram_id: int):
    with db() as conn:
        row = conn.execute("SELECT end_date FROM subscriptions WHERE telegram_id=?", (telegram_id,)).fetchone()
        return row["end_date"] if row else 0


def extend_subscription(telegram_id: int, months: int):
    """يمدد الاشتراك من تاريخ اليوم أو من نهاية اشتراكه الحالي أيهما أبعد (مدة كاملة، بدون خصم)."""
    now = int(time.time())
    seconds_per_month = 30 * 24 * 60 * 60
    current_end = get_subscription_end(telegram_id)
    base = current_end if current_end > now else now
    new_end = base + months * seconds_per_month
    with db() as conn:
        conn.execute(
            "INSERT INTO subscriptions (telegram_id, end_date, plan_months) VALUES (?,?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET end_date=excluded.end_date, plan_months=excluded.plan_months",
            (telegram_id, new_end, months),
        )
    return new_end


# ---------- payments ----------
def create_payment(invoice_id: str, telegram_id: int, plan_months: int, amount: int):
    with db() as conn:
        conn.execute(
            "INSERT INTO payments (invoice_id, telegram_id, plan_months, amount, status, created_at) "
            "VALUES (?,?,?,?, 'initiated', ?)",
            (invoice_id, telegram_id, plan_months, amount, int(time.time())),
        )


def get_payment(invoice_id: str):
    with db() as conn:
        return conn.execute("SELECT * FROM payments WHERE invoice_id=?", (invoice_id,)).fetchone()


def mark_payment_status(invoice_id: str, status: str):
    with db() as conn:
        conn.execute("UPDATE payments SET status=? WHERE invoice_id=?", (status, invoice_id))


# ---------- anti-spam warn cooldown ----------
def should_warn(telegram_id: int, cooldown_seconds: int) -> bool:
    now = int(time.time())
    with db() as conn:
        row = conn.execute("SELECT last_warned_at FROM warn_state WHERE telegram_id=?", (telegram_id,)).fetchone()
        if row and now - row["last_warned_at"] < cooldown_seconds:
            return False
        conn.execute(
            "INSERT INTO warn_state (telegram_id, last_warned_at) VALUES (?,?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET last_warned_at=excluded.last_warned_at",
            (telegram_id, now),
        )
        return True
