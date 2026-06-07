"""
壹米云相册 - 数据库层
线程安全连接池 + 上下文管理器 + 自动迁移
"""
import os
import sqlite3
import time
import threading
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_migrate_lock = threading.Lock()
_migrated = False


class DatabasePool:
    def __init__(self, db_path, max_connections=10, busy_timeout=10000):
        self._path = db_path
        self._max = max_connections
        self._busy_timeout = busy_timeout
        self._pool = []
        self._lock = threading.Lock()

    def _create_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={self._busy_timeout}")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _is_alive(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    def get(self) -> sqlite3.Connection:
        with self._lock:
            # 从池中取连接，检查是否存活
            while self._pool:
                conn = self._pool.pop()
                if self._is_alive(conn):
                    return conn
                try:
                    conn.close()
                except Exception:
                    pass
            return self._create_conn()

    def release(self, conn: sqlite3.Connection):
        with self._lock:
            if len(self._pool) < self._max:
                self._pool.append(conn)
            else:
                conn.close()

    def close_all(self):
        with self._lock:
            for c in self._pool:
                try:
                    c.close()
                except Exception:
                    pass
            self._pool.clear()


_pool: DatabasePool = None


def init_pool():
    global _pool
    if _pool is None:
        from config import get, db_path
        _pool = DatabasePool(
            db_path=db_path(),
            max_connections=get("db_max_connections", 10),
            busy_timeout=get("db_busy_timeout", 10000),
        )


def get_pool() -> DatabasePool:
    if _pool is None:
        init_pool()
    return _pool


@contextmanager
def get_db(write: bool = True):
    """
    数据库上下文管理器。
    write=True 时自动 commit/rollback，write=False 时只读不提交。
    """
    pool = get_pool()
    conn = pool.get()
    try:
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        pool.release(conn)


def safe_execute(conn, sql, params=(), max_retries=3):
    for attempt in range(max_retries):
        try:
            return conn.execute(sql, params)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
    return None


def migrate_db():
    global _migrated
    with _migrate_lock:
        if _migrated:
            return
        _do_migrate()
        _migrated = True


def _do_migrate():
    with get_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            rel_path TEXT NOT NULL UNIQUE,
            original_path TEXT,
            thumb_small TEXT,
            thumb_medium TEXT,
            file_size INTEGER,
            file_hash TEXT,
            media_type TEXT,
            width INTEGER,
            height INTEGER,
            taken_at TEXT,
            location TEXT,
            latitude REAL,
            longitude REAL,
            is_favorite INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0,
            deleted_at TEXT,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS persons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            cover_photo_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS photo_persons (
            photo_id INTEGER, person_id INTEGER,
            PRIMARY KEY (photo_id, person_id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            cover_photo_id INTEGER,
            is_smart INTEGER DEFAULT 0,
            smart_rules TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS album_photos (
            album_id INTEGER, photo_id INTEGER,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (album_id, photo_id)
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )""")

        conn.execute("""CREATE TABLE IF NOT EXISTS photo_tags (
            photo_id INTEGER, tag_id INTEGER,
            PRIMARY KEY (photo_id, tag_id)
        )""")

        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_photos_taken ON photos(taken_at)",
            "CREATE INDEX IF NOT EXISTS idx_photos_hash ON photos(file_hash)",
            "CREATE INDEX IF NOT EXISTS idx_photos_deleted ON photos(is_deleted)",
            "CREATE INDEX IF NOT EXISTS idx_photos_favorite ON photos(is_favorite)",
            "CREATE INDEX IF NOT EXISTS idx_photos_deleted_taken ON photos(is_deleted, taken_at)",
            "CREATE INDEX IF NOT EXISTS idx_album_photos_album ON album_photos(album_id)",
            "CREATE INDEX IF NOT EXISTS idx_album_photos_photo ON album_photos(photo_id)",
        ]:
            conn.execute(idx_sql)

        for alter in [
            "ALTER TABLE album_photos ADD COLUMN added_at TEXT",
            "ALTER TABLE photos ADD COLUMN storage_path TEXT",
            "ALTER TABLE photos ADD COLUMN original_path TEXT",
        ]:
            try:
                conn.execute(alter)
            except sqlite3.OperationalError:
                pass

    logger.info("数据库迁移完成")
