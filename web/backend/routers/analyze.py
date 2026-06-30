"""
Анализ фото кожи через 8-слойный LLM-пайплайн + ML-модель.
"""
import base64
import os
import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Подключаем core-пайплайн из корня проекта
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
from core.pipeline import pipeline_final, pipeline_photo

from database import get_db
from models import Analysis, User

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")


async def call_ml_service(image_bytes: bytes) -> dict:
    """Вызывает ML-сервис для предсказания по фото."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            files = {"file": ("photo.jpg", image_bytes, "image/jpeg")}
            r = await client.post(f"{ML_SERVICE_URL}/predict", files=files)
            if r.status_code == 200:
                return r.json()
            return {"status": "error", "message": f"ML service: {r.status_code}"}
    except Exception as e:
        return {"status": "error", "message": f"ML service unavailable: {e}"}


@router.post("/")
async def analyze_photo(
    user_id: int = Form(...),
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # Найти пользователя
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    contents = await photo.read()
    b64 = base64.b64encode(contents).decode("utf-8")

    # ML-предсказание через отдельный сервис
    ml_result = await call_ml_service(contents)
    ml_top = ml_result.get("top_class")
    ml_conf = ml_result.get("confidence", 0.0)

    # Собираем user-dict для пайплайна
    pipeline_user = {
        "name": db_user.name or "друг",
        "duration": "не указано",
        "tried": "не указано",
        "day": 1,
        "week": 1,
        "diagnosis": ml_top,  # ← используем ML результат как стартовый диагноз
        "vision_data": {
            "ml_prediction": ml_top,
            "ml_confidence": ml_conf,
            "ml_top3": ml_result.get("predictions", []),
        },
        "reasoning_data": None,
        "reasoner_a": None,
        "reasoner_b": None,
    }

    try:
        # Шаги 1-4 пайплайна
        result_type, result = await pipeline_photo(b64, photo.filename or "", pipeline_user)

        if result_type == "ask_reshoot":
            return {"status": "reshoot", "message": result, "ml": ml_result}

        if result_type == "error":
            return {"status": "error", "message": result, "ml": ml_result}

        # Шаги 5-8: финальный ответ
        final_text = await pipeline_final(pipeline_user, answers_text="")

        # Сохраняем в БД
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

        # Приоритет диагноза: ML > LLM. Если LLM вернул "uncertain" — берём ML.
        llm_diagnosis = pipeline_user.get("diagnosis")
        uncertain = llm_diagnosis in ("требуется уточнение", "не определено", "требуется уточнить", None, "")
        final_diagnosis = ml_top if (uncertain and ml_top) else llm_diagnosis

        return {
            "status": "success",
            "diagnosis": final_diagnosis,
            "ml": ml_result,
            "vision": pipeline_user.get("vision_data") or {},
            "reasoning": pipeline_user.get("reasoning_data") or {},
            "questions": pipeline_user.get("pending_questions") or {},
            "recommendations": final_text,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")
