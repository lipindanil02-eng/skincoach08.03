"""
inference.py — Предсказание кожного заболевания по фото
Подключается к боту как модуль
"""
import json
import os
import torch
import torch.nn as nn
from torchvision import transforms, models
from PIL import Image

# Путь к модели (локальный или через переменную окружения)
MODEL_PATH = os.getenv("MODEL_PATH", "best_model.pth")
HF_MODEL_URL = "https://huggingface.co/danyil163/SCINCOACH/resolve/main/best_model.pth"


MIN_MODEL_SIZE = 10 * 1024 * 1024  # 10 MB minimum


def _is_valid_model_file(path: str) -> bool:
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < MIN_MODEL_SIZE:
        return False
    try:
        import zipfile
        with zipfile.ZipFile(path, "r"):
            pass
        return True
    except Exception:
        return False


def _download_model_if_needed():
    if _is_valid_model_file(MODEL_PATH):
        return
    if os.path.exists(MODEL_PATH):
        print(f"⚠️  Файл модели повреждён, удаляю и скачиваю заново...")
        os.remove(MODEL_PATH)
    print(f"⬇️  Скачиваю модель с HuggingFace → {MODEL_PATH}")
    os.makedirs(os.path.dirname(MODEL_PATH) or ".", exist_ok=True)

    import httpx
    with httpx.stream("GET", HF_MODEL_URL, follow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(MODEL_PATH, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (5 * 1024 * 1024) < 65536:
                    pct = downloaded / total * 100
                    print(f"   {pct:.0f}%", flush=True)
    print("✅ Модель скачана")
CLASS_MAP_PATH = "class_map.json"
IMG_SIZE = 300
CONFIDENCE_THRESHOLD = 0.5

CLASS_LABELS_RU = {
    "melanoma":              "Меланома",
    "nevus":                 "Невус (родинка)",
    "basal_cell_carcinoma":  "Базальноклеточный рак",
    "actinic_keratosis":     "Актинический кератоз",
    "keratosis":             "Себорейный кератоз",
    "psoriasis":             "Псориаз",
    "eczema":                "Экзема",
    "dermatitis":            "Дерматит",
    "acne":                  "Акне",
    "vitiligo":              "Витилиго",
    "rosacea":               "Розацеа",
    "other":                 "Другое заболевание",
}

_model = None
_class_map = None
_device = None

def load_model():
    global _model, _class_map, _device
    if _model is not None:
        return

    _download_model_if_needed()
    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    with open(CLASS_MAP_PATH, "r", encoding="utf-8") as f:
        _class_map = json.load(f)

    num_classes = len(_class_map)
    checkpoint = torch.load(MODEL_PATH, map_location=_device, weights_only=False)
    model_name = checkpoint.get("model_name", "efficientnet_b3")

    if model_name == "efficientnet_b3":
        model = models.efficientnet_b3(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier = nn.Sequential(
            nn.Dropout(p=0.4),
            nn.Linear(in_features, num_classes)
        )
    else:
        model = models.resnet50(weights=None)
        in_features = model.fc.in_features
        model.fc = nn.Sequential(
            nn.Dropout(p=0.4),
            nn.Linear(in_features, num_classes)
        )

    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(_device)
    model.eval()
    _model = model
    print(f"✅ Модель загружена | Классов: {num_classes} | {_device}")


_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


def predict_image(image_path: str) -> dict:
    """
    Предсказать заболевание по фото.
    Возвращает: diagnosis, diagnosis_ru, confidence, top3, reliable, message
    """
    load_model()

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        return {"error": f"Не удалось открыть изображение: {e}"}

    tensor = _transform(img).unsqueeze(0).to(_device)

    with torch.no_grad():
        outputs = _model(tensor)
        probs = torch.softmax(outputs, dim=1)[0]

    top_k = min(3, len(_class_map))
    top_probs, top_idx = probs.topk(top_k)
    top_probs = top_probs.cpu().numpy()
    top_idx = top_idx.cpu().numpy()

    # Определяем маппинг индекс → класс
    first_key = list(_class_map.keys())[0]
    if str(first_key).isdigit():
        idx_to_class = {int(k): v for k, v in _class_map.items()}
    else:
        idx_to_class = {v: k for k, v in _class_map.items()}

    best_class = idx_to_class.get(int(top_idx[0]), f"class_{top_idx[0]}")
    best_prob = float(top_probs[0])
    diagnosis_ru = CLASS_LABELS_RU.get(best_class, best_class)
    reliable = best_prob >= CONFIDENCE_THRESHOLD

    top3 = []
    for idx, prob in zip(top_idx, top_probs):
        cls = idx_to_class.get(int(idx), f"class_{idx}")
        top3.append({
            "diagnosis": cls,
            "diagnosis_ru": CLASS_LABELS_RU.get(cls, cls),
            "confidence_pct": f"{float(prob)*100:.1f}%"
        })

    if reliable:
        message = f"🔬 Модель определила: {diagnosis_ru} (уверенность {best_prob*100:.1f}%)"
    else:
        message = f"🔬 Вероятнее всего: {diagnosis_ru} ({best_prob*100:.1f}% — требует уточнения)"

    return {
        "diagnosis": best_class,
        "diagnosis_ru": diagnosis_ru,
        "confidence": round(best_prob, 4),
        "confidence_pct": f"{best_prob*100:.1f}%",
        "top3": top3,
        "reliable": reliable,
        "message": message,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = predict_image(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("Использование: python inference.py path/to/image.jpg")
