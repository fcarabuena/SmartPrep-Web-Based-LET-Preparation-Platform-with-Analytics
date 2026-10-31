"""Application settings loaded from environment variables (and .env locally)."""
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-insecure-secret-change-me"


def normalize_database_url(url: str | None) -> str:
    """Return a SQLAlchemy URL. Empty -> local SQLite; postgres:// -> psycopg 3 driver + sslmode."""
    url = (url or "").strip()
    if not url:
        return "sqlite:///./smartprep.db"
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    if url.startswith("postgresql+psycopg://"):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        host = parts.hostname or ""
        if "sslmode" not in query and host not in ("localhost", "127.0.0.1"):
            query["sslmode"] = "require"
        url = urlunsplit(parts._replace(query=urlencode(query)))
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: str = "development"
    SECRET_KEY: str = DEV_SECRET
    DATABASE_URL: str = ""
    BASE_URL: str = ""

    BREVO_API_KEY: str = ""
    MAIL_FROM: str = "no-reply@smartprep.local"
    MAIL_FROM_NAME: str = "Smart Prep"

    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # contact sent in the scraper's User-Agent (many sites, e.g. Wikipedia, reject bots without one)
    SCRAPER_CONTACT: str = "fcarabuena793@gmail.com"

    APP_NAME: str = "Smart Prep"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"

    @property
    def sqlalchemy_url(self) -> str:
        return normalize_database_url(self.DATABASE_URL)

    @property
    def email_enabled(self) -> bool:
        return bool(self.BREVO_API_KEY)

    @property
    def google_enabled(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.GEMINI_API_KEY)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production and s.SECRET_KEY == DEV_SECRET:
        raise RuntimeError("SECRET_KEY must be set in production")
    return s


settings = get_settings()
