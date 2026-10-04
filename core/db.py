"""База данных: пользователи, баллы, история распознаваний и викторин.

Где хранится:
- на сайте — Supabase (Postgres), если задан DATABASE_URL (st.secrets) — данные не пропадают при перезапуске;
- локально и в тестах — файл SQLite data/app.db, как раньше.
Функции ниже одинаково работают с обоими вариантами (см. core/pg.py).
"""
import functools
import hashlib
import hmac
import os
import sqlite3
import threading
from pathlib import Path

from .content import POINTS_PER_CORRECT_ANSWER

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

# Streamlit обслуживает каждого посетителя в отдельном потоке, а соединение с базой
# одно на всех (st.cache_resource в app.py). Модуль sqlite3 такое соединение не защищает:
# запросы двух учеников в одну и ту же секунду перемешивались (в тесте на 16 потоков —
# ошибки «another row available», «cannot commit - no transaction is active» и потерянные баллы).
# Поэтому каждая функция ниже работает с базой по очереди — под общим «замком».
_LOCK = threading.RLock()

# Функции ниже работают и с SQLite (локально, в тестах), и с Postgres/Supabase (на сайте,
# обёртка core/pg.py с тем же интерфейсом: execute с «?», commit, rollback).
# Различия диалектов собраны здесь, остальной SQL общий.
_DAY_AGO = {  # «24 часа назад» (время в базе — UTC)
    "sqlite": "datetime('now', '-1 day')",
    "postgres": "timezone('utc', now()) - interval '1 day'",
}


def _dialect(conn):
    """'sqlite' для обычного sqlite3-соединения, 'postgres' — для обёртки из core/pg.py."""
    return getattr(conn, "dialect", "sqlite")


def _locked(func):
    @functools.wraps(func)
    def wrapper(conn, *args, **kwargs):
        with _LOCK:
            for attempt in range(2):
                try:
                    return func(conn, *args, **kwargs)
                except Exception as error:
                    try:
                        conn.rollback()  # не оставлять недописанную транзакцию следующему запросу
                    except Exception:
                        pass  # соединение уже оборвано — откатывать нечего
                    # Сетевая база (Supabase) может оборвать соединение: перезапуск сервера, сбой сети.
                    # Тогда переподключаемся и повторяем запрос один раз. У SQLite такого не бывает.
                    is_disconnect = getattr(conn, "is_disconnect", lambda e: False)
                    if attempt or not is_disconnect(error):
                        raise
                    conn.reconnect()
    return wrapper


def get_conn(url=None):
    """Соединение с базой: url (DATABASE_URL) → Postgres/Supabase, без него — локальный SQLite."""
    if url:
        from .pg import PostgresConnection
        return PostgresConnection(url)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@_locked
def init_db(conn):
    if _dialect(conn) == "postgres":
        conn.apply_migrations()  # таблицы Supabase — SQL-миграции из supabase/migrations/
        return
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        name TEXT NOT NULL,
        school TEXT DEFAULT '',
        points INTEGER DEFAULT 0,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS scans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        predicted TEXT NOT NULL,
        confidence REAL NOT NULL,
        corrected TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS quiz_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        score INTEGER NOT NULL,
        total INTEGER NOT NULL,
        mode TEXT NOT NULL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    # Миграция для уже существующих баз: столбец с отпечатком фото (md5 файла).
    # По нему видно, что пользователь уже присылал это фото, и баллы второй раз не даются.
    columns = [row[1] for row in conn.execute("PRAGMA table_info(scans)")]
    if "image_hash" not in columns:
        conn.execute("ALTER TABLE scans ADD COLUMN image_hash TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_user_hash ON scans(user_id, image_hash)")
    # Сколько баллов дала викторина — нужно для лимита «баллы за 3 викторины в сутки».
    if "points" not in [row[1] for row in conn.execute("PRAGMA table_info(quiz_results)")]:
        conn.execute("ALTER TABLE quiz_results ADD COLUMN points INTEGER DEFAULT 0")
        # до лимита баллы начислялись всегда: score × POINTS_PER_CORRECT_ANSWER
        conn.execute("UPDATE quiz_results SET points = score * ?", (POINTS_PER_CORRECT_ANSWER,))
    conn.commit()


# ---------- Пароли ----------
# Старый код хранил sha256(пароль) без «соли»: одинаковые пароли давали одинаковый хеш
# и легко подбирались по готовым таблицам. Теперь: PBKDF2 + случайная соль.

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    if stored.startswith("pbkdf2$"):
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    # совместимость со старой базой (sha256 без соли)
    return hmac.compare_digest(stored, hashlib.sha256(password.encode()).hexdigest())


# ---------- Пользователи ----------

def register_user(conn, username, password, name, school=""):
    """Возвращает (ok, сообщение)."""
    username = username.strip()
    if len(username) < 3:
        return False, "Логин должен быть не короче 3 символов."
    if len(password) < 6:
        return False, "Пароль должен быть не короче 6 символов."
    hashed = hash_password(password)  # медленная операция — до замка, чтобы не задерживать других
    if not _insert_user(conn, username, hashed, name.strip(), school.strip()):
        return False, "Такой логин уже занят."
    return True, "Аккаунт создан. Теперь войдите."


@_locked
def _insert_user(conn, username, hashed, name, school):
    """Проверка «логин свободен» и запись — одним куском под замком. False, если логин занят."""
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return False
    try:
        conn.execute(
            "INSERT INTO users (username, password, name, school) VALUES (?, ?, ?, ?)",
            (username, hashed, name, school),
        )
        conn.commit()
    except conn.IntegrityError:  # логин заняли в ту же секунду (например, из другого процесса)
        conn.rollback()
        return False
    return True


def authenticate(conn, username, password):
    row = _password_row(conn, username.strip())
    # проверка пароля (PBKDF2, ~0,1 с) — уже вне замка, чтобы не тормозить остальных
    if not (row and verify_password(row[1], password)):
        return None
    if not row[1].startswith("pbkdf2$"):
        # старый хэш sha256 без соли (база версии 1) — при первом же входе заменяем на PBKDF2 с солью
        _set_password_hash(conn, row[0], hash_password(password))
    return row[0]


@_locked
def _password_row(conn, username):
    return conn.execute("SELECT id, password FROM users WHERE username = ?", (username,)).fetchone()


@_locked
def _set_password_hash(conn, user_id, hashed):
    conn.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, user_id))
    conn.commit()


@_locked
def get_user(conn, user_id):
    row = conn.execute(
        "SELECT id, username, name, school, points FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        return None
    return dict(zip(["id", "username", "name", "school", "points"], row))


@_locked
def add_points(conn, user_id, points):
    if user_id:
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (points, user_id))
        conn.commit()


# ---------- Распознавания и викторины ----------

@_locked
def save_scan(conn, user_id, predicted, confidence, image_hash=None):
    scan_id = conn.execute(  # RETURNING id работает и в SQLite (3.35+), и в Postgres — lastrowid только в SQLite
        "INSERT INTO scans (user_id, predicted, confidence, image_hash) VALUES (?, ?, ?, ?) RETURNING id",
        (user_id, predicted, confidence, image_hash),
    ).fetchone()[0]
    conn.commit()
    return scan_id


@_locked
def find_scan(conn, user_id, image_hash):
    """Это фото пользователь уже присылал? Возвращает (id, исправленный_класс) или None."""
    return conn.execute(
        "SELECT id, corrected FROM scans WHERE user_id = ? AND image_hash = ? ORDER BY id LIMIT 1",
        (user_id, image_hash),
    ).fetchone()


@_locked
def correct_scan(conn, scan_id, corrected):
    conn.execute("UPDATE scans SET corrected = ? WHERE id = ?", (corrected, scan_id))
    conn.commit()


@_locked
def save_quiz(conn, user_id, score, total, mode, points=0):
    conn.execute(
        "INSERT INTO quiz_results (user_id, score, total, mode, points) VALUES (?, ?, ?, ?, ?)",
        (user_id, score, total, mode, points),
    )
    conn.commit()


@_locked
def rewarded_quizzes_last_day(conn, user_id):
    """Сколько викторин за последние 24 часа принесли пользователю баллы.

    Окно «24 часа назад от сейчас», а не календарный день: время в базе — UTC,
    а у школьников Астаны UTC+5, и «полночь» сервера пришлась бы на 5 утра.
    """
    return conn.execute(
        f"SELECT COUNT(*) FROM quiz_results WHERE user_id = ? AND points > 0 AND date >= {_DAY_AGO[_dialect(conn)]}",
        (user_id,),
    ).fetchone()[0]


@_locked
def user_scans(conn, user_id, limit=20):
    return conn.execute(
        "SELECT predicted, confidence, corrected, date FROM scans WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


@_locked
def user_quizzes(conn, user_id, limit=20):
    return conn.execute(
        "SELECT score, total, mode, points, date FROM quiz_results WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


@_locked
def leaderboard_users(conn, limit=20):
    return conn.execute(
        "SELECT name, school, points FROM users ORDER BY points DESC, id ASC LIMIT ?", (limit,)
    ).fetchall()


@_locked
def leaderboard_schools(conn, limit=20):
    return conn.execute(
        """SELECT school, SUM(points) AS pts, COUNT(*) AS people
           FROM users WHERE school != '' GROUP BY school ORDER BY pts DESC LIMIT ?""",
        (limit,),
    ).fetchall()


@_locked
def global_stats(conn):
    scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    corrected = conn.execute("SELECT COUNT(*) FROM scans WHERE corrected IS NOT NULL").fetchone()[0]
    by_class = conn.execute(
        "SELECT COALESCE(corrected, predicted) AS c, COUNT(*) FROM scans GROUP BY c"
    ).fetchall()
    return {"scans": scans, "users": users, "corrected": corrected, "by_class": by_class}
