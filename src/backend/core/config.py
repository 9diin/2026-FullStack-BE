from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py
# /project/app/core/config.py
# → parents[2] = /project
ROOT_DIR = Path(__file__).resolve().parents[3]

dotenv_filename = ROOT_DIR / "env" / "development.env"
local_env_filename = ROOT_DIR / ".env.local"


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str = "default-key"
    REFRESH_COOKIE_SECURE: bool = True
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_FROM_EMAIL: str | None = None
    SMTP_USE_TLS: bool = True
    EMAIL_VERIFICATION_EXPIRE_MINUTES: int = 10
    EMAIL_VERIFICATION_RESEND_SECONDS: int = 60
    EMAIL_VERIFICATION_MAX_ATTEMPTS: int = 5

    model_config = SettingsConfigDict(
        # Keep personal credentials in the ignored local file. It overrides
        # development defaults, while real process environment variables win over both.
        env_file=(dotenv_filename, local_env_filename),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
