"""
Аутентификация и текущий пользователь.
Поддерживает два режима:
- /telegram — вход через Telegram WebApp
- /login — простой вход по имени (без пароля, без Telegram)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import is_admin, validate_telegram_webapp_data
from database import get_db
from models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(payload: dict, db: AsyncSession = Depends(get_db)):
    """
    Простой вход по имени. Без пароля, без Telegram.
    Создаёт пользователя, если такого имени ещё нет.
    """
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="Name too long")

    # Ищем по name (case-insensitive)
    result = await db.execute(
        select(User).where(User.name.ilike(name))
    )
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user = User(name=name, username=name.lower())
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)

    is_user_admin = (name.lower() == "kinesispro")

    return {
        "user": {
            "id": db_user.id,
            "name": db_user.name,
            "username": db_user.username,
            "is_admin": is_user_admin,
        }
    }


@router.post("/telegram")
async def auth_telegram(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    init_data = data.get("init_data", "")
    user = validate_telegram_webapp_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    telegram_id = str(user.get("id"))
    username = user.get("username")
    name = user.get("first_name", "")

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user = User(telegram_id=telegram_id, username=username, name=name)
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)

    return {
        "user": {
            "id": db_user.id,
            "telegram_id": db_user.telegram_id,
            "username": db_user.username,
            "name": db_user.name,
            "is_admin": is_admin(user),
        }
    }
