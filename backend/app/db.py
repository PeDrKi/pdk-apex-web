"""Cơ sở dữ liệu cho tài khoản, phiên đăng nhập và lịch sử.

- Mặc định: SQLite trong backend/data (có sẵn trong Python, không cần cài gì).
- Khi đặt DATABASE_URL (ví dụ Postgres của Supabase): dùng Postgres. Cần gói psycopg.

Mã gọi vào đây viết SQL kiểu SQLite (tham số `?` hoặc `:ten`); lớp này tự đổi sang
cú pháp của psycopg khi chạy trên Postgres. Mỗi lần gọi mở một kết nối riêng."""
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import settings

DATA_DIR = Path(settings.data_dir) if settings.data_dir else Path(__file__).resolve().parents[1] / "data"
DB_PATH = DATA_DIR / "app.db"
DATABASE_URL = settings.database_url.strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash     TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    recovery_hash TEXT,
    totp TEXT
);
CREATE TABLE IF NOT EXISTS auth_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    user_id     INTEGER,
    username    TEXT NOT NULL,
    event       TEXT NOT NULL,
    ip          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_events_name ON auth_events(username, ts);
CREATE INDEX IF NOT EXISTS auth_events_user ON auth_events(user_id, ts);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  INTEGER NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    encrypted   INTEGER NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    psnr        REAL,
    redundancy  INTEGER NOT NULL,
    stego_bytes INTEGER NOT NULL,
    keys_bytes  INTEGER NOT NULL,
    stego_sha256 TEXT,
    keys_sha256  TEXT
);
CREATE INDEX IF NOT EXISTS items_user ON items(user_id, created_at);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    username    TEXT NOT NULL,
    pw_hash     TEXT NOT NULL,
    created_at  BIGINT NOT NULL,
    recovery_hash TEXT,
    totp TEXT
);
CREATE TABLE IF NOT EXISTS auth_events (
    id          BIGSERIAL PRIMARY KEY,
    ts          BIGINT NOT NULL,
    user_id     BIGINT,
    username    TEXT NOT NULL,
    event       TEXT NOT NULL,
    ip          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_events_name ON auth_events(username, ts);
CREATE INDEX IF NOT EXISTS auth_events_user ON auth_events(user_id, ts);
CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower ON users (lower(username));
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  BIGINT NOT NULL,
    expires_at  BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS items (
    id          TEXT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  BIGINT NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    encrypted   BOOLEAN NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    psnr        DOUBLE PRECISION,
    redundancy  INTEGER NOT NULL,
    stego_bytes BIGINT NOT NULL,
    keys_bytes  BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_user ON items(user_id, created_at);
"""

# Cột thêm sau bản đầu tiên (dấu thời gian chứng minh): tự thêm vào cơ sở dữ liệu cũ khi khởi động.
_ADDED_COLUMNS = (("items", "stego_sha256"), ("items", "keys_sha256"), ("users", "recovery_hash"), ("users", "totp"))
# Supabase mở các bảng trong schema public qua REST cho khoá anon/publishable. Bật RLS mà không tạo
# policy nào thì các khoá đó không đọc được gì; backend nối bằng vai trò chủ bảng nên không bị ảnh hưởng.
_RLS_TABLES = ("users", "sessions", "items", "auth_events")
_LATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS items_stego_sha ON items(stego_sha256)",
    "CREATE INDEX IF NOT EXISTS items_keys_sha ON items(keys_sha256)",
)

_ready = False
_init_lock = threading.Lock()

if IS_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row

    IntegrityError: tuple = (psycopg.IntegrityError, sqlite3.IntegrityError)
else:
    IntegrityError = (sqlite3.IntegrityError,)

_NAMED = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def _to_psycopg(sql: str) -> str:
    """`?` -> `%s`, `:ten` -> `%(ten)s` (SQL trong ứng dụng không chứa dấu % hay chuỗi có dấu :)."""
    return _NAMED.sub(r"%(\1)s", sql.replace("?", "%s"))


class _PgConn:
    """Bọc kết nối psycopg cho giống sqlite3.Connection ở những chỗ ứng dụng dùng."""

    def __init__(self, con):
        self._con = con

    def execute(self, sql: str, params=()):
        return self._con.execute(_to_psycopg(sql), params)


def _pg_connect():
    # prepare_threshold=None: tương thích với pooler chế độ transaction của Supabase.
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, prepare_threshold=None,
                           connect_timeout=15, autocommit=False)


def _init() -> None:
    global _ready
    with _init_lock:
        if _ready:
            return
        if IS_POSTGRES:
            with _pg_connect() as con:
                for stmt in filter(str.strip, POSTGRES_SCHEMA.split(";")):
                    con.execute(stmt)
                for table, col in _ADDED_COLUMNS:  # cơ sở dữ liệu tạo từ bản cũ chưa có các cột này
                    con.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} TEXT")
                for table in _RLS_TABLES:
                    con.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                for stmt in _LATE_INDEXES:
                    con.execute(stmt)
        else:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(DB_PATH)
            try:
                con.execute("PRAGMA journal_mode=WAL")
                con.executescript(SQLITE_SCHEMA)
                for table, col in _ADDED_COLUMNS:
                    if col not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
                for stmt in _LATE_INDEXES:
                    con.execute(stmt)
                con.commit()
            finally:
                con.close()
        _ready = True


@contextmanager
def connect():
    """Kết nối có giao dịch: tự commit khi xong, rollback khi có lỗi."""
    if not _ready:
        _init()
    if IS_POSTGRES:
        con = _pg_connect()
        try:
            yield _PgConn(con)
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
        return
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
