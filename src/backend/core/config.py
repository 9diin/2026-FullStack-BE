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

    model_config = SettingsConfigDict(
        env_file=dotenv_filename,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
