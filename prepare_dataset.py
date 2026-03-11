"""
prepare_dataset.py — Подготовка датасета из HAM10000 + Fitzpatrick17k
Запускать в Google Colab или локально ПЕРЕД обучением.

Использование:
    python prepare_dataset.py --ham /path/to/HAM10000 --fitz /path/to/fitzpatrick17k --out ./dataset
"""

import os
import shutil
import argparse
import random
import csv
import json
from pathlib import Path

# ============================================================
# МАППИНГ КЛАССОВ
# ============================================================

# HAM10000: короткие коды → наши классы
HAM_CLASS_MAP = {
    "mel":   "melanoma",
    "nv":    "nevus",
    "bcc":   "basal_cell_carcinoma",
    "akiec": "actinic_keratosis",
    "bkl":   "keratosis",
    "df":    "other",       # dermatofibroma → other (мало фото)
    "vasc":  "other",       # vascular → other (мало фото)
}

# Fitzpatrick17k: label → наши классы (lowercase matching)
FITZ_CLASS_MAP = {
    # Псориаз
    "psoriasis":                     "psoriasis",
    "pustular psoriasis":            "psoriasis",
    "guttate psoriasis":             "psoriasis",
    "inverse psoriasis":             "psoriasis",
    "plaque psoriasis":              "psoriasis",

    # Экзема
    "eczema":                        "eczema",
    "dyshidrotic eczema":            "eczema",
    "nummular eczema":               "eczema",
    "atopic dermatitis":             "eczema",

    # Дерматит
    "allergic contact dermatitis":   "dermatitis",
    "contact dermatitis":            "dermatitis",
    "seborrheic dermatitis":         "dermatitis",
    "perioral dermatitis":           "dermatitis",
    "irritant contact dermatitis":   "dermatitis",

    # Акне
    "acne":                          "acne",
    "acne vulgaris":                 "acne",
    "comedonal acne":                "acne",
    "cystic acne":                   "acne",

    # Витилиго
    "vitiligo":                      "vitiligo",

    # Розацеа
    "rosacea":                       "rosacea",

    # Меланома
    "melanoma":                      "melanoma",
    "superficial spreading melanoma":"melanoma",
    "nodular melanoma":              "melanoma",

    # Базальноклеточный рак
    "basal cell carcinoma":          "basal_cell_carcinoma",
    "nodular basal cell carcinoma":  "basal_cell_carcinoma",

    # Актинический кератоз
    "actinic keratosis":             "actinic_keratosis",
    "squamous cell carcinoma":       "actinic_keratosis",  # похожи клинически

    # Крапивница и другое
    "urticaria":                     "other",
    "scabies":                       "other",
    "tinea":                         "other",
    "tinea versicolor":              "other",
    "folliculitis":                  "other",
    "molluscum contagiosum":         "other",
    "warts":                         "other",
    "keloid":                        "other",
}

ALL_CLASSES = [
    "melanoma", "nevus", "basal_cell_carcinoma", "actinic_keratosis",
    "keratosis", "psoriasis", "eczema", "dermatitis",
    "acne", "vitiligo", "rosacea", "other"
]

VAL_RATIO = 0.2
RANDOM_SEED = 42

# ============================================================

def make_dirs(out_dir):
    for split in ["train", "val"]:
        for cls in ALL_CLASSES:
            os.makedirs(os.path.join(out_dir, split, cls), exist_ok=True)

def copy_file(src, dst_dir, filename):
    dst = os.path.join(dst_dir, filename)
    if not os.path.exists(dst):
        shutil.copy2(src, dst)

def split_and_copy(files, train_dir, val_dir):
    random.shuffle(files)
    n_val = max(1, int(len(files) * VAL_RATIO))
    for f in files[n_val:]:
        copy_file(f, train_dir, os.path.basename(f))
    for f in files[:n_val]:
        copy_file(f, val_dir, os.path.basename(f))

def process_ham10000(ham_dir, out_dir):
    """
    HAM10000 структура:
    ham_dir/
      HAM10000_images_part_1/  (или images/)
      HAM10000_images_part_2/
      HAM10000_metadata.csv
    """
    print("\n📂 Обрабатываю HAM10000...")

    # Ищем CSV
    csv_path = None
    for name in ["HAM10000_metadata.csv", "metadata.csv"]:
        p = os.path.join(ham_dir, name)
        if os.path.exists(p):
            csv_path = p
            break
    if not csv_path:
        print("  ❌ HAM10000_metadata.csv не найден!")
        return

    # Ищем папки с изображениями
    img_dirs = []
    for name in ["HAM10000_images_part_1", "HAM10000_images_part_2",
                 "images", "HAM10000_images"]:
        p = os.path.join(ham_dir, name)
        if os.path.isdir(p):
            img_dirs.append(p)
    if not img_dirs:
        # Попробуем сам ham_dir
        img_dirs = [ham_dir]

    # Читаем CSV
    class_files = {cls: [] for cls in ALL_CLASSES}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dx = row.get("dx", "").strip().lower()
            our_class = HAM_CLASS_MAP.get(dx)
            if not our_class:
                continue
            img_id = row.get("image_id", "").strip()
            # Ищем файл
            for img_dir in img_dirs:
                for ext in [".jpg", ".jpeg", ".png"]:
                    p = os.path.join(img_dir, img_id + ext)
                    if os.path.exists(p):
                        class_files[our_class].append(p)
                        break

    for cls, files in class_files.items():
        if not files:
            continue
        train_dir = os.path.join(out_dir, "train", cls)
        val_dir   = os.path.join(out_dir, "val",   cls)
        split_and_copy(files, train_dir, val_dir)
        print(f"  {cls}: {len(files)} фото")


def process_fitzpatrick(fitz_dir, out_dir):
    """
    Fitzpatrick17k структура:
    fitz_dir/
      data/finalfitz17k/   (или images/)
      fitzpatrick17k.csv
    """
    print("\n📂 Обрабатываю Fitzpatrick17k...")

    # Ищем CSV
    csv_path = None
    for name in ["fitzpatrick17k.csv", "fitzpatrick17k_labels.csv", "data.csv"]:
        p = os.path.join(fitz_dir, name)
        if os.path.exists(p):
            csv_path = p
            break
    if not csv_path:
        print("  ❌ fitzpatrick17k.csv не найден!")
        return

    # Ищем папку с изображениями
    img_dir = None
    for name in ["data/finalfitz17k", "images", "finalfitz17k"]:
        p = os.path.join(fitz_dir, name)
        if os.path.isdir(p):
            img_dir = p
            break
    if not img_dir:
        img_dir = fitz_dir

    class_files = {cls: [] for cls in ALL_CLASSES}
    skipped = set()

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Fitzpatrick может иметь разные названия колонок
            label = (row.get("label") or row.get("condition") or
                     row.get("three_partition_label") or "").strip().lower()
            our_class = FITZ_CLASS_MAP.get(label)
            if not our_class:
                skipped.add(label)
                continue

            # Имя файла
            fname = (row.get("md5hash") or row.get("image_id") or
                     row.get("filename") or "").strip()
            if not fname:
                continue

            for ext in ["", ".jpg", ".jpeg", ".png"]:
                p = os.path.join(img_dir, fname + ext)
                if os.path.exists(p):
                    class_files[our_class].append(p)
                    break

    for cls, files in class_files.items():
        if not files:
            continue
        train_dir = os.path.join(out_dir, "train", cls)
        val_dir   = os.path.join(out_dir, "val",   cls)
        split_and_copy(files, train_dir, val_dir)
        print(f"  {cls}: {len(files)} фото")

    if skipped:
        print(f"  ⚠️  Пропущены метки (не в маппинге): {', '.join(sorted(skipped)[:10])}...")


def print_stats(out_dir):
    print("\n📊 ИТОГОВАЯ СТАТИСТИКА:")
    total = 0
    for split in ["train", "val"]:
        print(f"\n  {split}/")
        for cls in ALL_CLASSES:
            path = os.path.join(out_dir, split, cls)
            n = len(os.listdir(path)) if os.path.exists(path) else 0
            total += n
            status = "✅" if n >= 50 else ("⚠️ " if n > 0 else "❌")
            print(f"    {status} {cls}: {n}")
    print(f"\n  Итого: {total} фото")


def save_class_map(out_dir):
    """Сохраняет class_map.json в алфавитном порядке (как ImageFolder)"""
    sorted_classes = sorted(ALL_CLASSES)
    class_map = {str(i): cls for i, cls in enumerate(sorted_classes)}
    path = os.path.join(out_dir, "..", "class_map.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(class_map, f, indent=2, ensure_ascii=False)
    print(f"\n✅ class_map.json сохранён: {class_map}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ham",  default=None, help="Путь к папке HAM10000")
    parser.add_argument("--fitz", default=None, help="Путь к папке Fitzpatrick17k")
    parser.add_argument("--out",  default="./dataset", help="Выходная папка датасета")
    args = parser.parse_args()

    random.seed(RANDOM_SEED)

    print(f"📁 Выходная папка: {args.out}")
    make_dirs(args.out)

    if args.ham:
        process_ham10000(args.ham, args.out)
    else:
        print("⚠️  --ham не указан, пропускаю HAM10000")

    if args.fitz:
        process_fitzpatrick(args.fitz, args.out)
    else:
        print("⚠️  --fitz не указан, пропускаю Fitzpatrick17k")

    print_stats(args.out)
    save_class_map(args.out)
    print("\n🚀 Датасет готов! Запускай train.py")
