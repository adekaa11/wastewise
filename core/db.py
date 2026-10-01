"""Работа с базой данных SQLite: пользователи, баллы, история распознаваний и викторин."""
import hashlib
import hmac
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
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
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return False, "Такой логин уже занят."
    conn.execute(
        "INSERT INTO users (username, password, name, school) VALUES (?, ?, ?, ?)",
        (username, hash_password(password), name.strip(), school.strip()),
    )
    conn.commit()
    return True, "Аккаунт создан. Теперь войдите."


def authenticate(conn, username, password):
    row = conn.execute("SELECT id, password FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row and verify_password(row[1], password):
        return row[0]
    return None


def get_user(conn, user_id):
    row = conn.execute(
        "SELECT id, username, name, school, points FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if not row:
        return None
    return dict(zip(["id", "username", "name", "school", "points"], row))


def add_points(conn, user_id, points):
    if user_id:
        conn.execute("UPDATE users SET points = points + ? WHERE id = ?", (points, user_id))
        conn.commit()


# ---------- Распознавания и викторины ----------

def save_scan(conn, user_id, predicted, confidence):
    cur = conn.execute(
        "INSERT INTO scans (user_id, predicted, confidence) VALUES (?, ?, ?)",
        (user_id, predicted, confidence),
    )
    conn.commit()
    return cur.lastrowid


def correct_scan(conn, scan_id, corrected):
    conn.execute("UPDATE scans SET corrected = ? WHERE id = ?", (corrected, scan_id))
    conn.commit()


def save_quiz(conn, user_id, score, total, mode):
    conn.execute(
        "INSERT INTO quiz_results (user_id, score, total, mode) VALUES (?, ?, ?, ?)",
        (user_id, score, total, mode),
    )
    conn.commit()


def user_scans(conn, user_id, limit=20):
    return conn.execute(
        "SELECT predicted, confidence, corrected, date FROM scans WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


def user_quizzes(conn, user_id, limit=20):
    return conn.execute(
        "SELECT score, total, mode, date FROM quiz_results WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()


def leaderboard_users(conn, limit=20):
    return conn.execute(
        "SELECT name, school, points FROM users ORDER BY points DESC, id ASC LIMIT ?", (limit,)
    ).fetchall()


def leaderboard_schools(conn, limit=20):
    return conn.execute(
        """SELECT school, SUM(points) AS pts, COUNT(*) AS people
           FROM users WHERE school != '' GROUP BY school ORDER BY pts DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def global_stats(conn):
    scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    corrected = conn.execute("SELECT COUNT(*) FROM scans WHERE corrected IS NOT NULL").fetchone()[0]
    by_class = conn.execute(
        "SELECT COALESCE(corrected, predicted) AS c, COUNT(*) FROM scans GROUP BY c"
    ).fetchall()
    return {"scans": scans, "users": users, "corrected": corrected, "by_class": by_class}
