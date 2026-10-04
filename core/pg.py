"""Postgres (Supabase) для core/db.py: подключение, SQL-миграции и интерфейс «как у sqlite3».

На сайте база — Supabase. Подключаться нужно через Session pooler
(хост aws-…pooler.supabase.com, порт 5432, пользователь postgres.<id проекта>):
прямой адрес db.<id проекта>.supabase.co работает только по IPv6, а у Streamlit Cloud его нет.
Строка подключения берётся из st.secrets (DATABASE_URL) — в коде её нет. Инструкция: docs/SUPABASE.md.
"""
from pathlib import Path
from urllib.parse import urlparse

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
_MIGRATIONS_LOCK = 420261004  # номер «замка» Postgres: два процесса не применяют миграции одновременно


class PostgresConnection:
    """Обёртка над psycopg с тем же интерфейсом, что у sqlite3: execute("… ? …", params), commit, rollback.

    Режим autocommit: каждая запись сохраняется сразу, и соединение между запросами не висит
    в открытой транзакции. commit/rollback оставлены пустыми — для совместимости с кодом под SQLite.
    """

    dialect = "postgres"

    def __init__(self, url):
        import psycopg  # импорт здесь: локально и в тестах на SQLite psycopg не обязателен

        self._psycopg = psycopg
        self.IntegrityError = psycopg.IntegrityError  # как sqlite3.Connection.IntegrityError
        self._url = url
        self._conn = None
        self.reconnect()

    def reconnect(self):
        self.close()
        try:
            self._conn = self._psycopg.connect(
                self._url,
                autocommit=True,
                connect_timeout=10,
                prepare_threshold=None,  # без подготовленных запросов: работает через пулер Supabase в любом режиме
                **_connect_options(self._url),
            )
        except self._psycopg.OperationalError as error:
            hint = connection_hint(self._url)
            raise self._psycopg.OperationalError(f"{error}\n{hint}" if hint else str(error)) from error

    def execute(self, sql, params=()):
        # «?» (стиль sqlite3) → «%s» (стиль psycopg); одиночный «%» в тексте запроса psycopg требует удвоить.
        return self._conn.execute(sql.replace("%", "%%").replace("?", "%s"), params)

    def commit(self):
        pass  # autocommit: всё уже сохранено

    def rollback(self):
        pass  # autocommit: откатывать нечего — неудачный запрос ничего не записал

    def is_disconnect(self, error):
        """Ошибка из-за оборванного соединения? Тогда core/db.py переподключится и повторит запрос."""
        return isinstance(error, self._psycopg.OperationalError) and (
            self._conn is None or self._conn.closed or self._conn.broken)

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def apply_migrations(self):
        """Применить ещё не применённые файлы supabase/migrations/*.sql по порядку имён.

        Каждый применённый файл записывается в schema_migrations, поэтому при следующих запусках
        сайта он пропускается. Всё в одной транзакции: если файл с ошибкой — не применится ничего.
        Возвращает список применённых сейчас версий.
        """
        applied = []
        with self._conn.transaction():
            self._conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATIONS_LOCK,))
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            self._conn.execute("ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY")
            done = {row[0] for row in self._conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem not in done:
                    self._conn.execute(path.read_text(encoding="utf-8"))  # без параметров: можно несколько команд
                    self._conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
                    applied.append(path.stem)
        return applied


def _connect_options(url):
    """Шифрование для Supabase (если в строке не указано) и keepalive — чтобы замечать оборванные соединения."""
    options = {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}
    host = urlparse(url).hostname or ""
    if host.endswith((".supabase.co", ".supabase.com")) and "sslmode=" not in url:
        options["sslmode"] = "require"
    return options


def connection_hint(url):
    """Подсказка по частым ошибкам в строке подключения — добавляется к тексту ошибки."""
    if "[YOUR-PASSWORD]" in url:
        return "В строке подключения остался шаблон [YOUR-PASSWORD] — вставьте вместо него пароль базы."
    try:
        parsed = urlparse(url)
        host, port = parsed.hostname or "", parsed.port
    except ValueError:
        return "Строка подключения не разбирается — проверьте её. Если в пароле есть @ : / ? # %, их нужно закодировать."
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return ("Это прямое подключение Supabase (db.….supabase.co): оно работает только по IPv6, а у Streamlit Cloud "
                "его нет. Возьмите строку «Session pooler» (…pooler.supabase.com, порт 5432) — см. docs/SUPABASE.md.")
    if host.endswith("pooler.supabase.com") and port == 6543:
        return "Порт 6543 — это Transaction pooler. Для сайта нужен Session pooler: тот же хост, порт 5432."
    if host.endswith("pooler.supabase.com"):
        return ("Проверьте пароль базы и что проект Supabase не на паузе. Если в пароле есть символы @ : / ? # %, "
                "их нужно закодировать (например, @ → %40) или сменить пароль на буквы и цифры.")
    return None
