"""
Анализ фото кожи через 8-слойный LLM-пайплайн.
"""
import base64
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Подключаем core-пайплайн из корня проекта
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from core.pipeline import pipeline_final, pipeline_photo

from auth import validate_telegram_webapp_data
from database import get_db
from models import Analysis, User

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@router.post("/")
async def analyze_photo(
    init_data: str = Form(...),
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    tg_user = validate_telegram_webapp_data(init_data)
    if not tg_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    telegram_id = str(tg_user.get("id"))
    username = tg_user.get("username")
    name = tg_user.get("first_name", "")

    # upsert пользователя
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user = User(telegram_id=telegram_id, username=username, name=name)
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)

    contents = await photo.read()
    b64 = base64.b64encode(contents).decode("utf-8")

    # Собираем user-dict для пайплайна
    pipeline_user = {
        "name": db_user.name or name or "друг",
        "duration": "не указано",
        "tried": "не указано",
        "day": 1,
        "week": 1,
        "diagnosis": None,
        "vision_data": None,
        "reasoning_data": None,
        "reasoner_a": None,
        "reasoner_b": None,
    }

    try:
        # Шаги 1-4: качество, визуальный анализ, reasoning, вопросы
        result_type, result = await pipeline_photo(b64, photo.filename or "", pipeline_user)

        if result_type == "ask_reshoot":
            return {"status": "reshoot", "message": result}

        if result_type == "error":
            return {"status": "error", "message": result}

        # Шаги 5-8: триаж, рекомендации, безопасность, финальный ответ
        final_text = await pipeline_final(pipeline_user, answers_text="")

        # Сохраняем анализ в БД
        analysis = Analysis(
            user_id=db_user.id,
            photo_b64=b64[:200],
            vision_data=pipeline_user.get("vision_data") or {},
            reasoning_data=pipeline_user.get("reasoning_data") or {},
            diagnosis=pipeline_user.get("diagnosis"),
            risk=pipeline_user.get("risk") or {},
            recommendations=final_text,
            questions=pipeline_user.get("pending_questions") or [],
        )
        db.add(analysis)
        await db.commit()

        return {
            "status": "success",
            "diagnosis": pipeline_user.get("diagnosis"),
            "photo_preview": b64[:100],
            "vision": pipeline_user.get("vision_data") or {},
            "reasoning": pipeline_user.get("reasoning_data") or {},
            "questions": pipeline_user.get("pending_questions") or {},
            "recommendations": final_text,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")
