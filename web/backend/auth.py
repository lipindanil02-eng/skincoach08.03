"""
Аутентификация через Telegram WebApp (Mini App).
"""
import hashlib
import hmac
import json
import time
from typing import Optional

from config import get_settings

settings = get_settings()


def validate_telegram_webapp_data(init_data: str) -> Optional[dict]:
    """
    Проверяет подпись данных от Telegram WebApp.
    Возвращает dict пользователя или None.
    """
    if not settings.telegram_bot_token:
        # В режиме разработки принимаем любые данные
        return {"id": "dev", "username": "dev", "first_name": "Dev"}

    try:
        parsed = dict(x.split("=") for x in init_data.split("&") if "=" in x)
        received_hash = parsed.pop("hash", "")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(
            b"WebAppData",
            settings.telegram_bot_token.encode(),
            hashlib.sha256,
        ).digest()
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if calculated_hash != received_hash:
            return None

        # Проверяем свежесть
        auth_date = int(parsed.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            return None

        user = json.loads(parsed.get("user", "{}"))
        return user
    except Exception:
        return None


def is_admin(user: dict) -> bool:
    if not user:
        return False
    username = (user.get("username") or "").lower()
    if username == settings.admin_username.lower():
        return True
    return False
