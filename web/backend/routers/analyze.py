"""
Анализ фото кожи.
"""
import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from auth import validate_telegram_webapp_data
from database import get_db

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@router.post("/")
async def analyze_photo(
    init_data: str = Form(...),
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    user = validate_telegram_webapp_data(init_data)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    contents = await photo.read()
    b64 = base64.b64encode(contents).decode("utf-8")

    # TODO: интегрировать реальный 8-слойный пайплайн из bot.py
    # Пока возвращаем структуру-заглушку
    return {
        "status": "success",
        "diagnosis": "требуется интеграция пайплайна",
        "photo_preview": b64[:100],
        "vision": {},
        "reasoning": {},
        "questions": [],
        "recommendations": "Скоро здесь будет полный анализ от SkinCoach.",
    }
