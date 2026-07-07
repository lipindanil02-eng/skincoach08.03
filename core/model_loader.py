"""
core/model_loader.py — Единая загрузка ML-модели (EfficientNet-B3 / ResNet50).

Объединяет подходы из:
  - inference.py (torch.load + HTTP-стрим из HuggingFace)
  - web/ml_service/main.py (huggingface_hub.hf_hub_download)

Использование:
    from core.model_loader import load_model, load_class_map, TRANSFORM, IMG_SIZE

    model, class_map, device = load_model()
    # model — nn.Module в режиме eval
    # class_map — {int_index: str_class_name}
"""
import json
import logging
import os
from typing import Optional, Tuple

import torch
import torch.nn as nn
from torchvision import transforms, models

log = logging.getLogger("skincoach.model_loader")

# ─── Конфигурация из переменных окружения ─────────────────────────────────────
MODEL_PATH = os.getenv("MODEL_PATH", "best_model.pth")
HF_REPO = os.getenv("HF_REPO", "danyil163/SCINCOACH")
HF_MODEL_FILE = os.getenv("HF_MODEL_FILE", "best_model.pth")
HF_MODEL_URL = os.getenv(
    "HF_MODEL_URL",
    "https://huggingface.co/danyil163/SCINCOACH/resolve/main/best_model.pth",
)
CLASS_MAP_PATH = os.getenv("CLASS_MAP_PATH", "class_map.json")
HF_CLASS_MAP_FILE = os.getenv("HF_CLASS_MAP_FILE", "class_map.json")
DEVICE = os.getenv("DEVICE", "cpu")

MIN_MODEL_SIZE = 10 * 1024 * 1024  # 10 MB minimum

# ─── Трансформации изображения ────────────────────────────────────────────────
IMG_SIZE = 300
TRANSFORM = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])


# ─── Валидация / скачивание файлов ────────────────────────────────────────────

def _is_valid_model_file(path: str) -> bool:
    """Проверяет, что файл существует, не меньше MIN_MODEL_SIZE и является zip."""
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


def _download_via_httpx(url: str, dest: str) -> None:
    """Скачивание через HTTP-стрим (прямой URL HuggingFace)."""
    import httpx
    log.info("⬇️  Скачиваю через HTTP → %s", dest)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and downloaded % (5 * 1024 * 1024) < 65536:
                    pct = downloaded / total * 100
                    log.info("   %.0f%%", pct)
    log.info("✅ Скачивание завершено")


def _download_via_hf_hub(repo_id: str, filename: str, dest: str) -> None:
    """Скачивание через huggingface_hub."""
    from huggingface_hub import hf_hub_download
    log.info("⬇️  Скачиваю %s/%s → %s", repo_id, filename, dest)
    downloaded = hf_hub_download(
        repo_id=repo_id, filename=filename, local_dir=os.path.dirname(dest) or "."
    )
    if downloaded != dest and os.path.exists(downloaded):
        if os.path.exists(dest):
            os.remove(dest)
        os.rename(downloaded, dest)


def download_model_file() -> None:
    """Скачивает .pth файл модели, если его нет или он повреждён.

    Стратегия:
      1. huggingface_hub (надёжнее для HF-репозиториев)
      2. Прямой HTTP-стрим (fallback)
    """
    if _is_valid_model_file(MODEL_PATH):
        return

    if os.path.exists(MODEL_PATH):
        log.warning("⚠️  Файл модели повреждён, удаляю и скачиваю заново...")
        os.remove(MODEL_PATH)

    os.makedirs(os.path.dirname(MODEL_PATH) or ".", exist_ok=True)

    # Попытка 1: huggingface_hub
    try:
        _download_via_hf_hub(HF_REPO, HF_MODEL_FILE, MODEL_PATH)
        if _is_valid_model_file(MODEL_PATH):
            return
        log.warning("Файл после hf_hub повреждён, пробую HTTP...")
    except Exception as e:
        log.warning("hf_hub не сработал (%s), пробую HTTP...", e)

    # Попытка 2: прямой HTTP-стрим
    _download_via_httpx(HF_MODEL_URL, MODEL_PATH)


def download_class_map() -> None:
    """Скачивает class_map.json, если его нет на диске."""
    if os.path.exists(CLASS_MAP_PATH):
        return
    try:
        _download_via_hf_hub(HF_REPO, HF_CLASS_MAP_FILE, CLASS_MAP_PATH)
    except Exception as e:
        log.warning("Не удалось скачать class_map через hf_hub: %s", e)
        try:
            url = HF_MODEL_URL.replace(HF_MODEL_FILE, HF_CLASS_MAP_FILE)
            _download_via_httpx(url, CLASS_MAP_PATH)
        except Exception as e2:
            log.warning("Не удалось скачать class_map через HTTP: %s", e2)


# ─── Загрузка class_map ───────────────────────────────────────────────────────

def load_class_map() -> dict:
    """Загружает class_map.json, возвращает ``{int_index: str_class_name}``.

    Если файла нет — скачивает. Если после скачивания нет — пустой dict.
    """
    download_class_map()
    if not os.path.exists(CLASS_MAP_PATH):
        return {}
    with open(CLASS_MAP_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Ключи в JSON — строки-цифры; приводим к int
    return {int(k): v for k, v in data.items()}


# ─── Создание архитектуры ─────────────────────────────────────────────────────

def _create_model(num_classes: int, model_name: str = "efficientnet_b3") -> nn.Module:
    """Создаёт модель с заменой головы классификатора.

    Поддерживаемые архитектуры:
      - ``efficientnet_b3`` (основная)
      - ``resnet50`` (fallback из старых чекпоинтов)
    """
    if model_name == "efficientnet_b3":
        model = models.efficientnet_b3(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier = nn.Sequential(
            nn.Dropout(p=0.4),
            nn.Linear(in_features, num_classes),
        )
    else:
        model = models.resnet50(weights=None)
        in_features = model.fc.in_features
        model.fc = nn.Sequential(
            nn.Dropout(p=0.4),
            nn.Linear(in_features, num_classes),
        )
    return model


# ─── Основная функция загрузки ────────────────────────────────────────────────

def load_model(
    model_path: Optional[str] = None,
    device: Optional[str] = None,
) -> Tuple[nn.Module, dict, str]:
    """Загружает (или скачивает и загружает) модель + class_map.

    Args:
        model_path: Путь к .pth файлу (по умолчанию ``MODEL_PATH`` из env).
        device: Устройство, ``"cpu"`` / ``"cuda"`` (по умолчанию ``DEVICE`` из env).

    Returns:
        (model, class_map, device_str)
    """
    model_path = model_path or MODEL_PATH
    device_str = device or DEVICE

    # Определяем реальное устройство
    if device_str == "cuda" and not torch.cuda.is_available():
        device_str = "cpu"
    _device = torch.device(device_str)

    # Скачиваем модель, если нет на диске
    download_model_file()

    # Загружаем class_map
    class_map = load_class_map()
    num_classes = len(class_map) if class_map else 12

    # Загружаем чекпоинт
    log.info("🔄 Загружаю модель из %s ...", model_path)
    checkpoint = torch.load(model_path, map_location=_device, weights_only=False)

    # Определяем архитектуру из чекпоинта (если сохранена)
    if isinstance(checkpoint, dict) and "model_name" in checkpoint:
        model_name = checkpoint["model_name"]
    else:
        model_name = "efficientnet_b3"

    # Создаём архитектуру
    model = _create_model(num_classes, model_name)

    # Загружаем веса
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
    else:
        model.load_state_dict(checkpoint)

    model.to(_device)
    model.eval()

    log.info(
        "✅ Модель загружена | Архитектура: %s | Классов: %d | %s",
        model_name, num_classes, _device,
    )

    return model, class_map, device_str
