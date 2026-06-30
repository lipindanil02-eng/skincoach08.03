"""
SkinCoach Web — конфигурация бэкенда.
"""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "SkinCoach Web"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./skincoach_web.db"
    secret_key: str = "change-me-in-production"
    telegram_bot_token: str = ""
    openrouter_api_key: str = ""
    admin_username: str = "kinesispro"
    origins: str = "*"  # разделённые запятыми для CORS

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
