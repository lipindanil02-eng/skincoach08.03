"""
train.py — Обучение EfficientNet-B3 на HAM10000 + SCIN + Fitzpatrick17k
Запускать на Kaggle (GPU T4 x2) или Google Colab.

Использование:
    python train.py --data ./dataset --epochs 30 --hf_repo danyil163/SCINCOACH
"""

import os
import json
import argparse
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim.lr_scheduler import CosineAnnealingLR
from torch.utils.data import DataLoader
from torchvision import transforms, models, datasets
from collections import Counter
import numpy as np

# ============================================================
# АРГУМЕНТЫ
# ============================================================
parser = argparse.ArgumentParser()
parser.add_argument("--data",     default="./dataset",       help="Папка с train/ val/ подпапками")
parser.add_argument("--epochs",   type=int, default=30,      help="Кол-во эпох")
parser.add_argument("--batch",    type=int, default=32,       help="Размер батча")
parser.add_argument("--lr",       type=float, default=1e-4,  help="Learning rate")
parser.add_argument("--out",      default="best_model.pth",  help="Путь для сохранения модели")
parser.add_argument("--hf_repo",  default="",                help="HuggingFace repo (danyil163/SCINCOACH)")
parser.add_argument("--hf_token", default="",                help="HuggingFace write token")
parser.add_argument("--workers",  type=int, default=4,       help="DataLoader workers")
parser.add_argument("--resume",   default="",                help="Путь к best_model.pth для дообучения")
args = parser.parse_args()

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"🖥  Device: {DEVICE}")

# ============================================================
# ТРАНСФОРМАЦИИ
# ============================================================
IMG_SIZE = 300

train_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE + 20, IMG_SIZE + 20)),
    transforms.RandomCrop(IMG_SIZE),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.05),
    transforms.RandomRotation(15),
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

# ============================================================
# ДАТАСЕТ
# ============================================================
train_dir = os.path.join(args.data, "train")
val_dir   = os.path.join(args.data, "val")

train_dataset = datasets.ImageFolder(train_dir, transform=train_transform)
val_dataset   = datasets.ImageFolder(val_dir,   transform=val_transform)

num_classes = len(train_dataset.classes)
print(f"📊 Классов: {num_classes} | Train: {len(train_dataset)} | Val: {len(val_dataset)}")
print(f"   Классы: {train_dataset.classes}")

# Сохраняем class_map.json (индекс → имя класса)
class_map = {str(i): cls for i, cls in enumerate(train_dataset.classes)}
with open("class_map.json", "w", encoding="utf-8") as f:
    json.dump(class_map, f, indent=2, ensure_ascii=False)
print(f"✅ class_map.json сохранён")

# ============================================================
# ВЗВЕШИВАНИЕ КЛАССОВ (для дисбаланса)
# ============================================================
label_counts = Counter(train_dataset.targets)
total = len(train_dataset)
class_weights = torch.tensor(
    [total / (num_classes * label_counts[i]) for i in range(num_classes)],
    dtype=torch.float
).to(DEVICE)
print(f"⚖️  Class weights: {[f'{w:.2f}' for w in class_weights.cpu().tolist()]}")

train_loader = DataLoader(train_dataset, batch_size=args.batch, shuffle=True,
                          num_workers=args.workers, pin_memory=True)
val_loader   = DataLoader(val_dataset,   batch_size=args.batch, shuffle=False,
                          num_workers=args.workers, pin_memory=True)

# ============================================================
# МОДЕЛЬ: EfficientNet-B3 (pretrained ImageNet)
# ============================================================
model = models.efficientnet_b3(weights=models.EfficientNet_B3_Weights.DEFAULT)
in_features = model.classifier[1].in_features
model.classifier = nn.Sequential(
    nn.Dropout(p=0.4),
    nn.Linear(in_features, num_classes)
)
model = model.to(DEVICE)

# Дообучение: загружаем веса из существующей модели
if args.resume and os.path.exists(args.resume):
    print(f"🔄 Загружаем веса для дообучения: {args.resume}")
    checkpoint = torch.load(args.resume, map_location=DEVICE)
    saved_map = checkpoint.get("class_map", {})
    saved_classes = [saved_map[str(i)] for i in range(len(saved_map))]
    current_classes = train_dataset.classes

    if saved_classes == current_classes:
        # Классы совпадают — загружаем все веса
        raw_model = model.module if hasattr(model, "module") else model
        raw_model.load_state_dict(checkpoint["model_state_dict"])
        print(f"✅ Веса загружены полностью (val_acc было {checkpoint.get('val_acc', '?'):.4f})")
    else:
        # Классы изменились — загружаем только backbone, голову переобучаем с нуля
        print(f"⚠️  Классы изменились: было {len(saved_classes)}, стало {len(current_classes)}")
        print("   Загружаем только backbone (feature extractor), голову обучаем заново")
        raw_model = model.module if hasattr(model, "module") else model
        old_state = checkpoint["model_state_dict"]
        new_state = raw_model.state_dict()
        # Копируем все слои кроме classifier
        for k in new_state:
            if not k.startswith("classifier") and k in old_state and old_state[k].shape == new_state[k].shape:
                new_state[k] = old_state[k]
        raw_model.load_state_dict(new_state)
        print("✅ Backbone загружен, classifier инициализирован заново")
elif args.resume:
    print(f"⚠️  --resume указан, но файл не найден: {args.resume}")

# Если несколько GPU
if torch.cuda.device_count() > 1:
    print(f"🔥 Используем {torch.cuda.device_count()} GPU")
    model = nn.DataParallel(model)

# ============================================================
# ОБУЧЕНИЕ
# ============================================================
criterion = nn.CrossEntropyLoss(weight=class_weights)
optimizer = optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
scheduler = CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=1e-6)

best_val_acc = 0.0
best_epoch   = 0

for epoch in range(1, args.epochs + 1):
    t0 = time.time()

    # ── TRAIN ──
    model.train()
    train_loss, train_correct = 0.0, 0
    for images, labels in train_loader:
        images, labels = images.to(DEVICE), labels.to(DEVICE)
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        train_loss    += loss.item() * images.size(0)
        train_correct += (outputs.argmax(1) == labels).sum().item()

    # ── VAL ──
    model.eval()
    val_loss, val_correct = 0.0, 0
    with torch.no_grad():
        for images, labels in val_loader:
            images, labels = images.to(DEVICE), labels.to(DEVICE)
            outputs = model(images)
            loss = criterion(outputs, labels)
            val_loss    += loss.item() * images.size(0)
            val_correct += (outputs.argmax(1) == labels).sum().item()

    scheduler.step()

    train_acc = train_correct / len(train_dataset)
    val_acc   = val_correct   / len(val_dataset)
    elapsed   = time.time() - t0

    print(f"Epoch {epoch:02d}/{args.epochs} | "
          f"Train loss={train_loss/len(train_dataset):.4f} acc={train_acc:.3f} | "
          f"Val loss={val_loss/len(val_dataset):.4f} acc={val_acc:.3f} | "
          f"{elapsed:.0f}s")

    if val_acc > best_val_acc:
        best_val_acc = val_acc
        best_epoch   = epoch
        # Сохраняем state_dict базовой модели (без DataParallel обёртки)
        raw_model = model.module if hasattr(model, "module") else model
        torch.save({
            "model_state_dict": raw_model.state_dict(),
            "model_name":       "efficientnet_b3",
            "num_classes":      num_classes,
            "class_map":        class_map,
            "val_acc":          best_val_acc,
            "epoch":            epoch,
        }, args.out)
        print(f"   💾 Сохранено → {args.out} (val_acc={best_val_acc:.4f})")

print(f"\n🏆 Лучший результат: epoch {best_epoch}, val_acc={best_val_acc:.4f}")

# ============================================================
# ЗАГРУЗКА НА HUGGINGFACE
# ============================================================
if args.hf_repo and args.hf_token:
    print(f"\n⬆️  Загружаю модель на HuggingFace → {args.hf_repo}")
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        api.upload_file(
            path_or_fileobj=args.out,
            path_in_repo="best_model.pth",
            repo_id=args.hf_repo,
            token=args.hf_token,
        )
        api.upload_file(
            path_or_fileobj="class_map.json",
            path_in_repo="class_map.json",
            repo_id=args.hf_repo,
            token=args.hf_token,
        )
        print(f"✅ Модель загружена на HuggingFace!")
    except Exception as e:
        print(f"❌ Ошибка при загрузке на HuggingFace: {e}")
else:
    print("\n⚠️  HuggingFace не настроен (--hf_repo и --hf_token не указаны)")
    print(f"   Модель сохранена локально: {args.out}")
