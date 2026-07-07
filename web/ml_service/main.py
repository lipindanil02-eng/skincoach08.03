"""
SkinCoach ML Service — загружает EfficientNet-B3 с HuggingFace
и отдаёт предсказания кожных заболеваний через /predict.
"""
import io
import logging

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from core.model_loader import (
    load_model as _load_model_shared,
    TRANSFORM,
    DEVICE,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("skincoach.ml")

app = FastAPI(title="SkinCoach ML Service", debug=False)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальные переменные для модели
model = None
class_map = {}
transform = TRANSFORM


def load_model() -> None:
    """Загружает PyTorch модель через единый загрузчик."""
    global model, class_map, transform

    log.info("🔄 Загружаю модель...")
    model, class_map, device_str = _load_model_shared()
    transform = TRANSFORM
    log.info("✅ Модель загружена")


@app.get("/")
async def root():
    return {
        "service": "SkinCoach ML",
        "model_loaded": model is not None,
        "num_classes": len(class_map),
        "device": DEVICE,
        "status": "ready" if model is not None else "model not loaded (call /predict to trigger)",
    }


@app.get("/health")
async def health():
    if model is None:
        return {"status": "starting", "detail": "Model not loaded yet, call /predict to load"}
    return {"status": "ok"}


async def ensure_model():
    """Ленивая загрузка модели при первом запросе."""
    global model
    if model is None:
        log.info("🔄 Ленивая загрузка модели...")
        try:
            load_model()
        except Exception as e:
            log.error(f"Ошибка загрузки модели: {e}")
            raise HTTPException(status_code=500, detail=f"Model load failed: {e}")


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    """Принимает изображение, возвращает top-3 предсказания.
    Модель загружается лениво при первом вызове (не при старте сервера).
    """
    await ensure_model()

    try:
        import torch
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        x = transform(img).unsqueeze(0).to(DEVICE)

        with torch.no_grad():
            logits = model(x)
            probs = torch.nn.functional.softmax(logits, dim=1)[0]

        top_k = min(3, len(class_map) or probs.size(0))
        top_probs, top_idx = torch.topk(probs, top_k)

        results = []
        for prob, idx in zip(top_probs.tolist(), top_idx.tolist()):
            results.append({
                "class_id": idx,
                "class_name": class_map.get(idx, f"class_{idx}"),
                "probability": round(prob, 4),
            })

        return {
            "status": "ok",
            "predictions": results,
            "top_class": results[0]["class_name"] if results else None,
            "confidence": results[0]["probability"] if results else 0.0,
        }
    except Exception as e:
        log.error(f"Ошибка предсказания: {e}")
        raise HTTPException(status_code=500, detail=str(e))
