"""
Анализ фото кожи через 8-слойный LLM-пайплайн + ML-модель.
Работает в деградированном режиме, если что-то недоступно.
"""
import base64
import logging
import os
import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import pipeline as core_pipeline
from core.pipeline import pipeline_final, pipeline_photo

from database import get_db
from models import Analysis, User

log = logging.getLogger("skincoach.web.analyze")

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")

# Проверяем, сконфигурирован ли OpenRouter
OR_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
LLM_AVAILABLE = bool(OR_KEY) and OR_KEY != ""


async def call_ml_service(image_bytes: bytes) -> dict:
    """Вызывает ML-сервис для предсказания по фото."""
    if not ML_SERVICE_URL or ML_SERVICE_URL == "http://localhost:8001":
        return {"status": "skipped", "message": "ML_SERVICE_URL not configured"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
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
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    contents = await photo.read()
    b64 = base64.b64encode(contents).decode("utf-8")

    # 1. ML-предсказание (опционально)
    ml_result = await call_ml_service(contents)
    ml_top = ml_result.get("top_class")
    ml_conf = ml_result.get("confidence", 0.0)
    ml_status = ml_result.get("status", "ok")

    # 2. Проверяем LLM
    if not LLM_AVAILABLE:
        # LLM не сконфигурирован — возвращаем только ML результат
        diagnosis = ml_top or "сервис анализа не настроен"
        recommendations = (
            f"ML-модель определила: {ml_top} (уверенность {ml_conf*100:.1f}%).\n\n"
            "⚠️ Подробный анализ временно недоступен — нужно настроить OPENROUTER_API_KEY на сервере."
        )
        analysis = Analysis(
            user_id=db_user.id,
            photo_b64=b64[:200],
            vision_data={"ml_prediction": ml_top, "ml_confidence": ml_conf, "ml_top3": ml_result.get("predictions", [])},
            reasoning_data={},
            diagnosis=diagnosis,
            risk={},
            recommendations=recommendations,
            questions={},
        )
        db.add(analysis)
        await db.commit()
        return {
            "status": "success",
            "diagnosis": diagnosis,
            "ml": ml_result,
            "vision": {},
            "reasoning": {},
            "questions": {},
            "recommendations": recommendations,
            "warnings": ["LLM не сконфигурирован на сервере (OPENROUTER_API_KEY)"],
        }

    # 3. Полный пайплайн
    pipeline_user = {
        "name": db_user.name or "друг",
        "duration": "не указано",
        "tried": "не указано",
        "day": 1,
        "week": 1,
        "diagnosis": ml_top,
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
        # Если ML дал диагноз — пропускаем vision (OpenRouter не работает с картинками)
        # Идём сразу к финальной генерации текста
        if ml_top:
            pipeline_user["vision_data"] = {
                "ml_prediction": ml_top,
                "ml_confidence": ml_conf,
                "ml_top3": ml_result.get("predictions", []),
                "description": f"ML-модель определила: {ml_top} ({ml_conf*100:.1f}%)",
            }
            pipeline_user["diagnosis"] = ml_top
            pipeline_user["reasoning_data"] = {
                "hypotheses": [{"diagnosis": ml_top, "probability": int(ml_conf*100), "reasoning": "ML prediction"}],
                "primary_diagnosis": ml_top,
                "confidence": int(ml_conf*100),
            }
        else:
            # ML недоступен — vision OpenRouter не работает, возвращаем заглушку
            diagnosis = "ML-сервис загружается, попробуй через 2-3 минуты"
            recommendations = (
                f"📸 Фото получено.\n\n"
                f"ML-сервис сейчас запускается (качает модель с HuggingFace).\n"
                f"Открой фото снова через 2-3 минуты — анализ заработает автоматически."
            )
            analysis = Analysis(
                user_id=db_user.id,
                photo_b64=b64[:200],
                vision_data={},
                reasoning_data={},
                diagnosis=diagnosis,
                risk={},
                recommendations=recommendations,
                questions={},
            )
            db.add(analysis)
            await db.commit()
            return {
                "status": "success",
                "diagnosis": diagnosis,
                "ml": ml_result,
                "vision": {},
                "reasoning": {},
                "questions": {},
                "recommendations": recommendations,
                "warnings": ["ML service not ready yet"],
            }

        final_text = await pipeline_final(pipeline_user, answers_text="")

        # Приоритет: ML > LLM
        llm_diagnosis = pipeline_user.get("diagnosis")
        uncertain = llm_diagnosis in ("требуется уточнение", "не определено", "требуется уточнить", None, "")
        final_diagnosis = ml_top if (uncertain and ml_top) else llm_diagnosis

        analysis = Analysis(
            user_id=db_user.id,
            photo_b64=b64[:200],
            vision_data=pipeline_user.get("vision_data") or {},
            reasoning_data=pipeline_user.get("reasoning_data") or {},
            diagnosis=final_diagnosis,
            risk=pipeline_user.get("risk") or {},
            recommendations=final_text,
            questions=pipeline_user.get("pending_questions") or [],
        )
        db.add(analysis)
        await db.commit()

        warnings = []
        if ml_status != "ok":
            warnings.append(f"ML: {ml_result.get('message', ml_status)}")

        return {
            "status": "success",
            "diagnosis": final_diagnosis,
            "ml": ml_result,
            "vision": pipeline_user.get("vision_data") or {},
            "reasoning": pipeline_user.get("reasoning_data") or {},
            "questions": pipeline_user.get("pending_questions") or {},
            "recommendations": final_text,
            "warnings": warnings,
        }
    except Exception as e:
        log.exception("Pipeline error")
        # Последний фоллбэк — только ML
        if ml_top:
            return {
                "status": "partial",
                "diagnosis": ml_top,
                "ml": ml_result,
                "recommendations": f"ML определил: {ml_top}. Подробный анализ временно недоступен.",
                "warnings": [f"Pipeline error: {str(e)}"],
            }
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


@router.get("/debug")
async def debug_status():
    """Диагностика: что работает на сервере."""
    ml_status = "unknown"
    ml_info = {}
    if ML_SERVICE_URL and ML_SERVICE_URL != "http://localhost:8001":
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{ML_SERVICE_URL}/")
                if r.status_code == 200:
                    ml_status = "ok"
                    ml_info = r.json()
                else:
                    ml_status = f"http_{r.status_code}"
        except Exception as e:
            ml_status = f"unreachable: {type(e).__name__}"
    else:
        ml_status = "not_configured"

    return {
        "llm_configured": LLM_AVAILABLE,
        "llm_models": {
            "vision": core_pipeline.VISION_M,
            "reasoner_a": core_pipeline.REASONER_A_M,
            "reasoner_b": core_pipeline.REASONER_B_M,
            "reason": core_pipeline.REASON_M,
            "judge": core_pipeline.JUDGE_M,
            "vision_fallbacks": core_pipeline.VIS_FB,
            "text_fallbacks": core_pipeline.TXT_FB,
        } if LLM_AVAILABLE else {},
        "ml_service_url": ML_SERVICE_URL,
        "ml_service_status": ml_status,
        "ml_service_info": ml_info,
    }
