import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Конфигурация бота."""

    # Telegram
    telegram_token: str = field(default_factory=lambda: os.environ["TELEGRAM_TOKEN"])

    # Прокси
    proxy_url: str = field(
        default_factory=lambda: os.environ.get("PROXY_URL", "")
    )

    # Web-интерфейс
    web_host: str = field(
        default_factory=lambda: os.environ.get("WEB_HOST", "0.0.0.0")
    )
    web_port: int = field(
        default_factory=lambda: int(os.environ.get("WEB_PORT", "5000"))
    )
    web_secret_key: str = field(
        default_factory=lambda: os.environ.get(
            "WEB_SECRET_KEY", "change-me-in-production"
        )
    )


config = Config()
