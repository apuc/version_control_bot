"""
Telegram-бот для уведомления о новых коммитах.

Мониторит несколько репозиториев из SQLite-базы и отправляет
уведомления в привязанные чаты.

Запуск:
    python bot.py
"""

import asyncio
import logging
import subprocess
import textwrap
from typing import Optional

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

import database as db
from config import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Git утилиты
# ---------------------------------------------------------------------------

def _git(repo_path: str, *args: str) -> str:
    """Запускает git-команду и возвращает stdout."""
    result = subprocess.run(
        ["git", "-C", repo_path] + list(args),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def get_latest_commit_hash(repo_path: str) -> str:
    return _git(repo_path, "rev-parse", "HEAD")


def get_new_commits(repo_path: str, since_hash: str) -> list[dict]:
    fmt = "%H%n%h%n%an%n%ai%n%s"
    log_output = _git(
        repo_path, "log", f"{since_hash}..HEAD", f"--pretty=format:{fmt}", "--reverse"
    )
    if not log_output:
        return []

    commits: list[dict] = []
    lines = log_output.split("\n")
    for i in range(0, len(lines), 5):
        if i + 4 >= len(lines):
            break
        commits.append({
            "hash": lines[i],
            "short_hash": lines[i + 1],
            "author": lines[i + 2],
            "date": lines[i + 3],
            "subject": lines[i + 4],
        })
    return commits


def format_commit_message(commit: dict) -> str:
    return textwrap.dedent(f"""\
        *{commit['short_hash']}* {commit['subject']}
        Автор: {commit['author']}  ·  {commit['date']}
    """)


def format_new_commits_message(repo_name: str, commits: list[dict]) -> str:
    parts = [f"🔔 *{repo_name}* — {len(commits)} коммит(ов)\n"]
    for c in commits:
        parts.append(format_commit_message(c))
    return "\n---\n".join(parts)


# ---------------------------------------------------------------------------
# Telegram команды
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Привет! Я бот для уведомления о коммитах.\n\n"
        "Команды:\n"
        "/status — список репозиториев\n"
        "/last <id> — последние коммиты репозитория"
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    repos = db.list_repos()
    if not repos:
        await update.message.reply_text("Репозитории не настроены.")
        return

    lines = ["*Репозитории:*\n"]
    for r in repos:
        status = "✅" if r.enabled else "⏸"
        bindings = db.list_bindings(repo_id=r.id)
        chats = ", ".join(b.chat_title or b.chat_id for b in bindings) or "нет чатов"
        lines.append(
            f"{status} *{r.name}* (id={r.id})\n"
            f"   {r.path} · {r.branch} · {r.poll_interval}с\n"
            f"   Чаты: {chats}"
        )
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_last(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Использование: /last <id репозитория>")
        return

    try:
        repo_id = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("ID должен быть числом.")
        return

    repo = db.get_repo(repo_id)
    if not repo:
        await update.message.reply_text(f"Репозиторий id={repo_id} не найден.")
        return

    try:
        fmt = "%H%n%h%n%an%n%ai%n%s"
        log_output = _git(repo.path, "log", "-5", f"--pretty=format:{fmt}")
        lines = log_output.split("\n")
        parts = []
        for i in range(0, len(lines), 5):
            if i + 4 >= len(lines):
                break
            parts.append(
                f"*{lines[i+1]}* {lines[i+4]}\n"
                f"  {lines[i+2]} · {lines[i+3]}"
            )
        text = f"*Последние коммиты — {repo.name}:*\n\n" + "\n\n".join(parts)
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")


# ---------------------------------------------------------------------------
# Поллинг нескольких репозиториев
# ---------------------------------------------------------------------------

async def polling_loop(bot: Bot) -> None:
    """Периодически проверяет все включённые репозитории."""
    # repo_id -> последний известный хеш
    state: dict[int, str] = {}

    # Инициализация: запоминаем текущие коммиты
    for repo in db.list_repos(enabled_only=True):
        try:
            state[repo.id] = get_latest_commit_hash(repo.path)
            logger.info("Repo %s: стартовый коммит %s", repo.name, state[repo.id][:8])
        except Exception:
            logger.exception("Не удалось прочитать коммиты для %s", repo.name)
            state[repo.id] = ""

    while True:
        await asyncio.sleep(10)  # базовый тик

        for repo in db.list_repos(enabled_only=True):
            # проверяем только если прошёл интервал
            try:
                current_hash = get_latest_commit_hash(repo.path)
            except Exception:
                logger.exception("Ошибка чтения repo %s", repo.name)
                continue

            if current_hash == state.get(repo.id):
                continue

            # Есть новые коммиты
            if state.get(repo.id):
                try:
                    commits = get_new_commits(repo.path, state[repo.id])
                except Exception:
                    logger.exception("Ошибка получения коммитов для %s", repo.name)
                    commits = []

                if commits:
                    message = format_new_commits_message(repo.name, commits)
                    bindings = db.list_bindings(repo_id=repo.id)
                    for b in bindings:
                        try:
                            await bot.send_message(
                                chat_id=b.chat_id,
                                text=message,
                                parse_mode="Markdown",
                            )
                        except Exception:
                            logger.exception(
                                "Не удалось отправить в чат %s", b.chat_id
                            )
                    logger.info(
                        "Repo %s: отправлено %d коммит(ов) в %d чат(ов)",
                        repo.name, len(commits), len(bindings),
                    )

            state[repo.id] = current_hash
            db.update_repo(repo.id, last_commit=current_hash)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

def main() -> None:
    db.init_db()

    builder = Application.builder().token(config.telegram_token)

    # Проброс прокси для Telegram API
    if config.proxy_url:
        builder = builder.proxy(config.proxy_url).get_updates_proxy(config.proxy_url)
        logger.info("Прокси: %s", config.proxy_url)

    application = builder.build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("last", cmd_last))

    async def post_init(app: Application) -> None:
        asyncio.create_task(polling_loop(app.bot))
        logger.info("Polling запущен")

    application.post_init = post_init
    logger.info("Бот запускается...")
    application.run_polling()


if __name__ == "__main__":
    main()
