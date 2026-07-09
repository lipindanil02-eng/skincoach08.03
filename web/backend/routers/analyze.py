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
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env", override=True)

from core.config import LLM_AVAILABLE
from core import pipeline as core_pipeline
from core.pipeline import pipeline_final, pipeline_photo

from database import get_db
from models import Analysis, User

log = logging.getLogger("skincoach.web.analyze")

router = APIRouter(prefix="/api/analyze", tags=["analyze"])

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001").strip()

ML_LABELS = {
    "melanoma": "подозрение на меланому",
    "nevus": "невус",
    "other": "неспецифическое кожное изменение",
}


def public_ml_label(value: str | None) -> str | None:
    if not value:
        return value
    return ML_LABELS.get(str(value).strip().lower(), value)


def public_ml_result(result: dict) -> dict:
    clean = dict(result or {})
    predictions = []
    for item in clean.get("predictions", []) or []:
        prediction = dict(item)
        raw_name = prediction.get("class_name")
        prediction["class_name"] = public_ml_label(raw_name)
        predictions.append(prediction)
    clean["predictions"] = predictions
    clean["top_class"] = public_ml_label(clean.get("top_class"))
    return clean


async def call_ml_service(image_bytes: bytes) -> dict:
    """Вызывает ML-сервис. Если модель не загружена — триггерит загрузку и сразу возвращает."""
    if not ML_SERVICE_URL:
        return {"status": "skipped", "message": "ML_SERVICE_URL not configured"}
    
    # Проверяем статус модели
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            cr = await client.get(f"{ML_SERVICE_URL}/")
            if cr.status_code == 200:
                info = cr.json()
                if not info.get("model_loaded"):
                    # Модель не загружена — триггерим загрузку коротким вызовом
                    log.info("ML модель не загружена — триггерим загрузку в фоне")
                    try:
                        async with httpx.AsyncClient(timeout=5) as client2:
                            files = {"file": ("trigger.jpg", image_bytes[:100], "image/jpeg")}
                            await client2.post(f"{ML_SERVICE_URL}/predict", files=files)
                    except Exception:
                        pass  # Ожидаемо — таймаут, но загрузка идёт
                    return {"status": "loading", "message": "Модель грузится, попробуй через 30 секунд"}
    except Exception:
        pass
    
    # Модель готова — делаем предсказание
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            files = {"file": ("photo.jpg", image_bytes, "image/jpeg")}
            r = await client.post(f"{ML_SERVICE_URL}/predict", files=files)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 503:
                return {"status": "loading", "message": "Модель ещё грузится, попробуй через минуту"}
            return {"status": "error", "message": f"ML service: {r.status_code}"}
    except Exception as e:
        return {"status": "loading", "message": f"Модель грузится, попробуй через минуту ({type(e).__name__})"}


@router.post("/")
async def analyze_photo(
    user_id: int = Form(...),
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        db_user = User(id=user_id, name="user")
        db.add(db_user)
        await db.commit()

    contents = await photo.read()
    b64 = base64.b64encode(contents).decode("utf-8")

    # 1. ML-предсказание (опционально)
    ml_result = public_ml_result(await call_ml_service(contents))
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
            # ML недоступен — показываем что происходит
            ml_msg = ml_result.get("message", "неизвестно")
            ml_stat = ml_result.get("status", "unknown")
            if ml_stat == "loading":
                diagnosis = "⏳ Модель загружается"
                recommendations = f"ML-модель скачивается с HuggingFace (~40 MB).\nЭто занимает 30-60 секунд при первом запуске.\n\nНажми 'Загрузить' снова через минуту — анализ заработает."
            else:
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


@router.get("/test-ml")
async def test_ml():
    """Тест ML-сервиса: шлёт тестовую картинку, возвращает результат."""
    result = {"ml_service": {"url": ML_SERVICE_URL, "available": False}}
    
    if not ML_SERVICE_URL:
        result["ml_service"]["error"] = "not configured"
        return result
    
    # Минимальный валидный JPEG (1x1 пиксель) в base64
    minimal_jpeg_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAAA//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8Af//Z"
    try:
        img_bytes = base64.b64decode(minimal_jpeg_b64)
        async with httpx.AsyncClient(timeout=60) as client:
            files = {"file": ("test.jpg", img_bytes, "image/jpeg")}
            r = await client.post(f"{ML_SERVICE_URL}/predict", files=files)
            result["ml_service"]["status_code"] = r.status_code
            if r.status_code == 200:
                result["ml_service"]["available"] = True
                result["ml_service"]["response"] = public_ml_result(r.json())
            else:
                result["ml_service"]["error"] = f"HTTP {r.status_code}"
                try:
                    result["ml_service"]["body"] = r.text[:500]
                except:
                    pass
    except httpx.TimeoutException:
        result["ml_service"]["error"] = "timeout (модель ещё грузится)"
    except Exception as e:
        result["ml_service"]["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    
    return result


@router.get("/debug")
async def debug_status():
    """Диагностика: что работает на сервере."""
    ml_status = "unknown"
    ml_info = {}
    if ML_SERVICE_URL:
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
        "version": "v8",
        "llm_configured": LLM_AVAILABLE,
        "llm_models": {
            "vision": core_pipeline.VISION_MODEL,
            "reasoner_a": core_pipeline.REASONER_A_MODEL,
            "reasoner_b": core_pipeline.REASONER_B_MODEL,
            "reason": core_pipeline.REASON_MODEL,
            "judge": core_pipeline.JUDGE_MODEL,
            "vision_fallbacks": core_pipeline.VISION_FALLBACKS,
            "text_fallbacks": core_pipeline.TEXT_FALLBACKS,
        } if LLM_AVAILABLE else {},
        "ml_service_url": ML_SERVICE_URL,
        "ml_service_status": ml_status,
        "ml_service_info": ml_info,
        "ml_loading": ml_status == "ok" and not ml_info.get("model_loaded"),
    }
