# 📖 ПОЛНАЯ ИНСТРУКЦИЯ: Обучение ML-модели для SkinCoach

> Написано после 3 дней работы. Содержит все ошибки, решения и предостережения.
> Цель: следующий раз обучить модель с первого раза.

---

## 🏗️ АРХИТЕКТУРА ПРОЕКТА

```
skincoach08.03/
├── bot.py              — Telegram-бот, 8-шаговый пайплайн
├── inference.py        — Загрузка и запуск ML-модели
├── upload_server.py    — HTTP-сервер для загрузки модели на Railway Volume
├── class_map.json      — Маппинг индексов классов → названия болезней
├── best_model.pth      — Файл обученной модели (НЕ хранить в git!)
├── requirements.txt
├── Procfile            — Railway: запускает bot.py + upload_server.py
└── prompts/            — Текстовые промпты для LLM-пайплайна
```

---

## 🎯 ШАГИ ОТ НУЛЯ ДО РАБОЧЕГО БОТА

### ШАГ 1: Подготовка датасета

**Структура папок (обязательно такая):**
```
dataset/
├── train/
│   ├── melanoma/     (фото меланомы)
│   ├── nevus/        (фото родинок)
│   ├── psoriasis/    (фото псориаза)
│   ├── dermatitis/   (фото дерматита)
│   ├── eczema/       (фото экземы)
│   └── other/        (остальные болезни)
└── val/
    ├── melanoma/
    ├── nevus/
    ├── psoriasis/
    ├── dermatitis/
    ├── eczema/
    └── other/
```

**Источники датасетов:**
- https://www.kaggle.com/datasets/kmader/skin-lesion-analysis-toward-melanoma-detection
- https://www.kaggle.com/datasets/shubhamgoel27/dermnet (DermNet — псориаз, дерматит, экзема)
- ISIC Archive: https://www.isic-archive.com/
- HAM10000: https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/DBW86T

**Минимум изображений на класс:** 200+ (лучше 500+)
**Рекомендуемое соотношение train/val:** 80/20

⚠️ **ПРЕДОСТЕРЕЖЕНИЕ:** Если взять только 3 класса и обучить — модель будет работать только с 3 классами. Нельзя просто добавить классы в class_map.json после обучения — архитектура выходного слоя фиксируется при обучении.

---

### ШАГ 2: Код для обучения (Google Colab / локально)

Создай файл `train.py` или Jupyter notebook:

```python
import torch
import torch.nn as nn
from torchvision import models, transforms, datasets
from torch.utils.data import DataLoader
import json, os

# === КОНФИГУРАЦИЯ ===
DATA_DIR = "./dataset"
MODEL_SAVE_PATH = "./best_model.pth"
IMG_SIZE = 300
BATCH_SIZE = 32
EPOCHS = 20
LR = 1e-4
MODEL_NAME = "efficientnet_b3"  # или "resnet50"

# === ТРАНСФОРМАЦИИ ===
train_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomRotation(15),
    transforms.ColorJitter(brightness=0.2, contrast=0.2),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])
val_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225]),
])

# === ДАТАСЕТ ===
train_ds = datasets.ImageFolder(os.path.join(DATA_DIR, "train"), transform=train_transform)
val_ds   = datasets.ImageFolder(os.path.join(DATA_DIR, "val"),   transform=val_transform)
train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=2)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=2)

# Сохраняем class_map.json
class_map = {str(v): k for k, v in train_ds.class_to_idx.items()}
with open("class_map.json", "w") as f:
    json.dump(class_map, f, indent=2)
print("Классы:", class_map)

num_classes = len(train_ds.classes)

# === МОДЕЛЬ ===
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Устройство: {device}")

if MODEL_NAME == "efficientnet_b3":
    model = models.efficientnet_b3(weights=models.EfficientNet_B3_Weights.DEFAULT)
    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.4),
        nn.Linear(in_features, num_classes)
    )
else:  # resnet50
    model = models.resnet50(weights=models.ResNet50_Weights.DEFAULT)
    in_features = model.fc.in_features
    model.fc = nn.Sequential(
        nn.Dropout(p=0.4),
        nn.Linear(in_features, num_classes)
    )
model = model.to(device)

# === ОБУЧЕНИЕ ===
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.Adam(model.parameters(), lr=LR)
scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)

best_val_acc = 0.0

for epoch in range(EPOCHS):
    # Train
    model.train()
    total_loss, correct, total = 0, 0, 0
    for images, labels in train_loader:
        images, labels = images.to(device), labels.to(device)
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
        correct += (outputs.argmax(1) == labels).sum().item()
        total += labels.size(0)
    train_acc = correct / total

    # Validation
    model.eval()
    val_correct, val_total = 0, 0
    with torch.no_grad():
        for images, labels in val_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            val_correct += (outputs.argmax(1) == labels).sum().item()
            val_total += labels.size(0)
    val_acc = val_correct / val_total

    print(f"Epoch {epoch+1}/{EPOCHS} | Loss: {total_loss/len(train_loader):.4f} | Train: {train_acc:.3f} | Val: {val_acc:.3f}")

    # Сохраняем лучшую модель
    if val_acc > best_val_acc:
        best_val_acc = val_acc
        torch.save({
            "model_name": MODEL_NAME,
            "model_state_dict": model.state_dict(),
            "class_map": class_map,
            "val_acc": val_acc,
            "num_classes": num_classes,
        }, MODEL_SAVE_PATH)
        print(f"  ✅ Сохранена лучшая модель (val_acc={val_acc:.3f})")

    scheduler.step()

print(f"\n🏆 Обучение завершено. Лучшая val_acc: {best_val_acc:.3f}")
```

---

### ШАГ 3: Где обучать

**Вариант A: Google Colab (рекомендуется для старта)**
- Бесплатно: Tesla T4 GPU
- Colab Pro: A100 GPU (~$10/мес)
- Время обучения на T4: ~30-60 мин для 6 классов, 500 фото/класс, 20 эпох

```python
# В Colab первой строкой:
!pip install torch torchvision
# Монтируем Google Drive для сохранения модели:
from google.colab import drive
drive.mount('/content/drive')
MODEL_SAVE_PATH = "/content/drive/MyDrive/skincoach/best_model.pth"
```

**Вариант B: Kaggle Notebooks**
- Бесплатно: P100 GPU, 30 ч/неделю
- Хорошо для воспроизводимости

**Вариант C: Локально (если есть NVIDIA GPU)**
- Установить CUDA + PyTorch с CUDA

⚠️ **НИКОГДА** не обучать на CPU Railway/Heroku — слишком медленно и дорого.

---

### ШАГ 4: Загрузка модели на HuggingFace

1. Создать аккаунт: https://huggingface.co
2. Создать новый Model Repository (например `username/SCINCOACH`)
3. Загрузить файлы через web-интерфейс или CLI:

```bash
pip install huggingface_hub
huggingface-cli login  # вводишь токен из HF Settings
huggingface-cli upload username/SCINCOACH best_model.pth best_model.pth
huggingface-cli upload username/SCINCOACH class_map.json class_map.json
```

4. Обновить URL в `inference.py`:
```python
HF_MODEL_URL = "https://huggingface.co/USERNAME/REPONAME/resolve/main/best_model.pth"
```

⚠️ **ПРЕДОСТЕРЕЖЕНИЕ:** HuggingFace использует редиректы (302). Старый код с `urllib.request.urlretrieve` скачивал HTML-страницу вместо файла. Используй только `httpx` с `follow_redirects=True` (как в текущем inference.py).

---

### ШАГ 5: Обновить class_map.json

После обучения — заменить `class_map.json` на тот что сгенерировал скрипт обучения:

```json
{
  "0": "dermatitis",
  "1": "eczema",
  "2": "melanoma",
  "3": "nevus",
  "4": "other",
  "5": "psoriasis"
}
```

⚠️ **КРИТИЧНО:** Порядок классов определяется алфавитным порядком папок в `ImageFolder`. Всегда используй `class_map.json` сгенерированный при обучении, не создавай вручную.

---

### ШАГ 6: Деплой на Railway

**Структура Railway проекта:**
- Service: основной сервис (бот)
- Volume: постоянный диск смонтированный в `/data`
- Переменные окружения (Environment Variables)

**Обязательные переменные окружения:**
```
TELEGRAM_TOKEN=...          # токен бота от @BotFather
OPENROUTER_API_KEY=...      # ключ от openrouter.ai
MODEL_PATH=/data/best_model.pth   # путь на постоянном диске
UPLOAD_TOKEN=секретный_токен      # для upload_server.py
PORT=8080
```

**Procfile:**
```
web: sh -c "python upload_server.py & python -u bot.py"
```

**Как Railway деплоит:**
- Следит за веткой `main` на GitHub
- При каждом пуше в `main` → автоматический редеплой
- Переменные окружения НЕ теряются при редеплое
- Volume (диск) НЕ теряется при редеплое → модель скачивается только один раз

---

## 🚨 СПИСОК ВСЕХ ОШИБОК КОТОРЫЕ МЫ СОВЕРШИЛИ

### Ошибка 1: urllib не обрабатывал редиректы HuggingFace
**Симптом:** `PytorchStreamReader failed reading zip archive: failed finding central directory`
**Причина:** `urllib.request.urlretrieve` скачивал HTML вместо .pth файла
**Решение:** Использовать `httpx` с `follow_redirects=True`
```python
import httpx
with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
    r.raise_for_status()
    for chunk in r.iter_bytes(chunk_size=65536):
        f.write(chunk)
```

### Ошибка 2: Повреждённый файл не перекачивался
**Симптом:** Модель не загружается, но скачивания нет в логах
**Причина:** Код проверял только `os.path.exists()`, не проверял целостность
**Решение:** Проверять размер и валидность zip-архива перед использованием:
```python
def _is_valid_model_file(path):
    if not os.path.exists(path): return False
    if os.path.getsize(path) < 10 * 1024 * 1024: return False  # < 10 MB
    try:
        import zipfile
        with zipfile.ZipFile(path, "r"): pass
        return True
    except: return False
```

### Ошибка 3: class_map.json содержал только 3 из 6 классов
**Симптом:** `✅ Модель загружена | Классов: 3`
**Причина:** Датасет для обучения содержал только melanoma/nevus/other
**Решение:** Собрать полный датасет со всеми 6 классами ПЕРЕД обучением

### Ошибка 4: history.json содержал обучающие данные вместо состояния пользователей
**Симптом:** Бот падал при старте с ошибкой парсинга JSON
**Причина:** В репозиторий случайно попал файл обучающих данных с именем history.json
**Решение:** Проверять формат history.json, добавить в .gitignore

### Ошибка 5: upload_server.py читал файл целиком в память
**Симптом:** Зависание/падение при загрузке модели через HTTP
**Причина:** `f.read()` для 129 MB файла = Out of Memory на Railway
**Решение:** Читать чанками:
```python
while True:
    chunk = file.file.read(65536)
    if not chunk: break
    f.write(chunk)
```

### Ошибка 6: FutureWarning от torch.load
**Симптом:** `FutureWarning: You are using torch.load with weights_only=False`
**Решение:** Явно указывать параметр:
```python
checkpoint = torch.load(MODEL_PATH, map_location=device, weights_only=False)
```

### Ошибка 7: gemini-2.5-flash-preview возвращает 400
**Симптом:** `WARNING: google/gemini-2.5-flash-preview: 400`
**Причина:** Модель недоступна через OpenRouter или не поддерживает данный формат
**Решение:** Убрать из списка моделей или заменить на `google/gemini-2.0-flash-001`

### Ошибка 8: Claude Code не может пушить в main (403)
**Симптом:** `error: RPC failed; HTTP 403`
**Причина:** Системное ограничение — Claude Code может пушить только в ветки `claude/...`
**Решение:** Создавать PR из `claude/...` ветки в `main` и мержить вручную на GitHub

---

## 📋 ЧЕКЛИСТ ПЕРЕД ОБУЧЕНИЕМ

- [ ] Датасет содержит ВСЕ нужные классы (не частичный)
- [ ] Минимум 200 фото на класс в train, 50 в val
- [ ] Папки названы правильно (lowercase, без пробелов)
- [ ] Google Colab открыт с GPU (Runtime → Change runtime type → GPU)
- [ ] HuggingFace токен готов для загрузки

## 📋 ЧЕКЛИСТ ПОСЛЕ ОБУЧЕНИЯ

- [ ] `best_model.pth` загружен на HuggingFace
- [ ] `class_map.json` обновлён (взят из скрипта обучения, не написан вручную)
- [ ] `HF_MODEL_URL` в `inference.py` указывает на правильный репозиторий
- [ ] Протестирован локально: `python inference.py test_image.jpg`
- [ ] Задеплоено на Railway, в логах есть `✅ Модель загружена | Классов: 6`

---

## 🔧 ТЕХНИЧЕСКИЙ СТЕК

| Компонент | Технология | Версия |
|-----------|-----------|--------|
| ML модель | PyTorch EfficientNet-B3 | torch 2.5.1 |
| Telegram бот | python-telegram-bot | 22.6 |
| LLM API | OpenRouter.ai | — |
| LLM модели | Gemini 2.0 Flash Lite | — |
| HTTP клиент | httpx | 0.28.1 |
| Деплой | Railway | — |
| Хранение модели | HuggingFace Hub | — |
| Диск (Volume) | Railway Volumes | /data |

---

## 💡 СОВЕТЫ

1. **Сначала обучи на малом датасете** (50 фото/класс) чтобы проверить что пайплайн работает, затем на полном
2. **Сохраняй checkpoint каждые 5 эпох** — если Colab упадёт, не потеряешь прогресс
3. **val_acc > 0.75** — приемлемый результат для медицинских изображений
4. **Augmentation обязателен** — медицинские датасеты маленькие, без аугментации модель переобучится
5. **EfficientNet-B3 лучше ResNet50** для небольших датасетов кожных заболеваний
6. **Никогда не коммить best_model.pth** — файл 100+ MB, GitHub отклонит пуш. Используй HuggingFace.
7. **Railway Volume** — модель скачивается один раз при первом запуске, затем берётся с диска
8. **OpenRouter fallback** — всегда указывай 3+ fallback модели, некоторые могут быть недоступны
