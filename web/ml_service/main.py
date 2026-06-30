"""
SkinCoach ML Service — загружает EfficientNet-B3 с HuggingFace
и отдаёт предсказания кожных заболеваний через /predict.
"""
import io
import logging
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("skincoach.ml")

MODEL_PATH = os.getenv("MODEL_PATH", "./best_model.pth")
HF_REPO = os.getenv("HF_REPO", "danyil163/SCINCOACH")
HF_MODEL_FILE = os.getenv("HF_MODEL_FILE", "best_model.pth")
CLASS_MAP_PATH = os.getenv("CLASS_MAP_PATH", "./class_map.json")
HF_CLASS_MAP_FILE = os.getenv("HF_CLASS_MAP_FILE", "class_map.json")
DEVICE = os.getenv("DEVICE", "cpu")

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
transform = None


def download_file_from_hf(repo_id: str, filename: str, dest: str) -> None:
    """Скачивает файл с HuggingFace через huggingface_hub."""
    from huggingface_hub import hf_hub_download
    log.info(f"⬇️  Скачиваю {repo_id}/{filename} → {dest}")
    downloaded = hf_hub_download(
        repo_id=repo_id, filename=filename, local_dir=os.path.dirname(dest) or "."
    )
    if downloaded != dest and os.path.exists(downloaded):
        # переименуем если нужно
        if os.path.exists(dest):
            os.remove(dest)
        os.rename(downloaded, dest)


def load_class_map() -> dict:
    """Загружает class_map.json: {index: class_name}."""
    if not os.path.exists(CLASS_MAP_PATH):
        try:
            download_file_from_hf(HF_REPO, HF_CLASS_MAP_FILE, CLASS_MAP_PATH)
        except Exception as e:
            log.warning(f"Не удалось скачать class_map: {e}")
            return {}

    if os.path.exists(CLASS_MAP_PATH):
        import json
        with open(CLASS_MAP_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Преобразуем ключи в int
        return {int(k): v for k, v in data.items()}
    return {}


def load_model() -> None:
    """Загружает PyTorch модель один раз при старте."""
    global model, class_map, transform

    log.info("🔄 Загружаю модель...")
    import torch
    import torch.nn as nn
    from torchvision import models, transforms

    # Скачиваем модель если её нет
    if not os.path.exists(MODEL_PATH) or os.path.getsize(MODEL_PATH) < 10_000_000:
        try:
            download_file_from_hf(HF_REPO, HF_MODEL_FILE, MODEL_PATH)
        except Exception as e:
            log.error(f"Не удалось скачать модель: {e}")
            raise

    # Загружаем class_map
    class_map = load_class_map()
    num_classes = len(class_map) if class_map else 12
    log.info(f"📋 Классов: {num_classes}")

    # Создаём архитектуру
    try:
        net = models.efficientnet_b3(weights=None)
        net.classifier[1] = nn.Linear(net.classifier[1].in_features, num_classes)
    except Exception as e:
        log.error(f"Ошибка создания модели: {e}")
        raise

    # Загружаем веса
    try:
        checkpoint = torch.load(MODEL_PATH, map_location=DEVICE, weights_only=False)
        if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
            net.load_state_dict(checkpoint["model_state_dict"])
        else:
            net.load_state_dict(checkpoint)
        net.eval()
        net.to(DEVICE)
        model = net
        log.info("✅ Модель загружена")
    except Exception as e:
        log.error(f"Ошибка загрузки весов: {e}")
        raise

    # Трансформации
    transform = transforms.Compose([
        transforms.Resize((300, 300)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])


@app.on_event("startup")
async def startup_event():
    try:
        load_model()
    except Exception as e:
        log.error(f"Не удалось загрузить модель при старте: {e}")


@app.get("/")
async def root():
    return {
        "service": "SkinCoach ML",
        "model_loaded": model is not None,
        "num_classes": len(class_map),
        "device": DEVICE,
    }


@app.get("/health")
async def health():
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"status": "ok"}


@app.post("/predict")
async def predict(file: UploadFile = File(...)):
    """Принимает изображение, возвращает top-3 предсказания."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

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
