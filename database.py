"""
SQLite-хранилище для репозиториев и привязанных к ним чатов.

Таблицы:
    repos         — репозитории (путь, ветка, интервал)
    chat_bindings — связь репозиториев с Telegram-чатами
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent / "data" / "bot.db"


@dataclass
class Repo:
    id: Optional[int]
    name: str
    path: str
    branch: str = "main"
    poll_interval: int = 30
    enabled: bool = True


@dataclass
class ChatBinding:
    id: Optional[int]
    repo_id: int
    chat_id: str
    chat_title: str = ""


def _ensure_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_conn():
    """Контекстный менеджер для подключения к БД."""
    _ensure_dir()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS repos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                path        TEXT NOT NULL UNIQUE,
                branch      TEXT NOT NULL DEFAULT 'main',
                poll_interval INTEGER NOT NULL DEFAULT 30,
                enabled     INTEGER NOT NULL DEFAULT 1,
                last_commit TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_bindings (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id    INTEGER NOT NULL REFERENCES repos(id) ON DELETE CASCADE,
                chat_id    TEXT NOT NULL,
                chat_title TEXT NOT NULL DEFAULT '',
                UNIQUE(repo_id, chat_id)
            );
        """)


# ---- CRUD: Repos ----

def list_repos(enabled_only: bool = False) -> list[Repo]:
    with get_conn() as conn:
        sql = "SELECT * FROM repos"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql).fetchall()
    return [Repo(**dict(r)) for r in rows]


def get_repo(repo_id: int) -> Optional[Repo]:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
    return Repo(**dict(r)) if r else None


def add_repo(name: str, path: str, branch: str = "main",
             poll_interval: int = 30, enabled: bool = True) -> Repo:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO repos (name, path, branch, poll_interval, enabled) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, path, branch, poll_interval, int(enabled)),
        )
        return Repo(id=cur.lastrowid, name=name, path=path,
                     branch=branch, poll_interval=poll_interval, enabled=enabled)


def update_repo(repo_id: int, **kwargs) -> None:
    allowed = {"name", "path", "branch", "poll_interval", "enabled", "last_commit"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [repo_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE repos SET {sets} WHERE id = ?", vals)


def delete_repo(repo_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM repos WHERE id = ?", (repo_id,))


# ---- CRUD: Chat Bindings ----

def list_bindings(repo_id: Optional[int] = None) -> list[ChatBinding]:
    with get_conn() as conn:
        if repo_id is not None:
            rows = conn.execute(
                "SELECT * FROM chat_bindings WHERE repo_id = ?", (repo_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM chat_bindings").fetchall()
    return [ChatBinding(**dict(r)) for r in rows]


def add_binding(repo_id: int, chat_id: str, chat_title: str = "") -> ChatBinding:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO chat_bindings (repo_id, chat_id, chat_title) "
            "VALUES (?, ?, ?)",
            (repo_id, chat_id, chat_title),
        )
        return ChatBinding(id=cur.lastrowid, repo_id=repo_id,
                           chat_id=chat_id, chat_title=chat_title)


def delete_binding(binding_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM chat_bindings WHERE id = ?", (binding_id,))
