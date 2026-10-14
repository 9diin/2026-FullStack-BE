from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# config.py
# /project/app/core/config.py
# → parents[2] = /project
ROOT_DIR = Path(__file__).resolve().parents[3]

dotenv_filename = ROOT_DIR / "env" / "development.env"


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str = "default-key"
    REFRESH_COOKIE_SECURE: bool = True
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=dotenv_filename,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
