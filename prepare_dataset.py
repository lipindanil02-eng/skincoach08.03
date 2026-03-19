"""
prepare_dataset.py — Подготовка датасета из HAM10000 + SCIN (Google) + Fitzpatrick17k

Использует ВСЕ болезни из датасетов как отдельные классы.
Порог: --min_count (default 50) фото → отдельный класс, иначе → "other".

Запускать в Google Colab / Kaggle ПЕРЕД обучением.

Использование:
    python prepare_dataset.py \
        --ham  /path/to/HAM10000 \
        --scin /path/to/scin \
        --fitz /path/to/fitzpatrick17k \
        --out  ./dataset \
        [--min_count 50]
"""

import os
import shutil
import argparse
import random
import csv
import json
from pathlib import Path
from collections import defaultdict

# ============================================================
# HAM10000: короткие коды → полные английские имена болезней
# ============================================================
HAM_LABEL_MAP = {
    "mel":   "melanoma",
    "nv":    "melanocytic_nevus",
    "bcc":   "basal_cell_carcinoma",
    "akiec": "actinic_keratosis",
    "bkl":   "seborrheic_keratosis",
    "df":    "dermatofibroma",
    "vasc":  "vascular_lesion",
}

VAL_RATIO   = 0.2
RANDOM_SEED = 42


def normalize(label: str) -> str:
    """'Acne Vulgaris' → 'acne_vulgaris'"""
    return (label.strip().lower()
            .replace(" ", "_").replace("-", "_")
            .replace("/", "_").replace("(", "").replace(")", ""))


# ============================================================
# УТИЛИТЫ
# ============================================================

def _find_csv(base, names):
    for name in names:
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    for fname in os.listdir(base):
        if fname.endswith(".csv"):
            return os.path.join(base, fname)
    return None


def _find_img_dirs(base, names):
    dirs = [os.path.join(base, n) for n in names if os.path.isdir(os.path.join(base, n))]
    return dirs if dirs else [base]


def _find_img_dir(base, names):
    for name in names:
        p = os.path.join(base, name)
        if os.path.isdir(p):
            return p
    return base


def make_dirs(out_dir: str, classes):
    for split in ["train", "val"]:
        for cls in classes:
            os.makedirs(os.path.join(out_dir, split, cls), exist_ok=True)


def copy_file(src, dst_dir, filename):
    dst = os.path.join(dst_dir, filename)
    if not os.path.exists(dst):
        shutil.copy2(src, dst)


def split_and_copy(files: list, cls: str, out_dir: str):
    random.shuffle(files)
    n_val = max(1, int(len(files) * VAL_RATIO))
    train_dir = os.path.join(out_dir, "train", cls)
    val_dir   = os.path.join(out_dir, "val",   cls)
    for f in files[n_val:]:
        copy_file(f, train_dir, os.path.basename(f))
    for f in files[:n_val]:
        copy_file(f, val_dir, os.path.basename(f))


# ============================================================
# СБОР ФАЙЛОВ ПО ИСТОЧНИКАМ
# ============================================================

HAM_ONEHOT_MAP = {
    "MEL": "melanoma",
    "NV":  "melanocytic_nevus",
    "BCC": "basal_cell_carcinoma",
    "AKIEC": "actinic_keratosis",
    "BKL": "seborrheic_keratosis",
    "DF":  "dermatofibroma",
    "VASC": "vascular_lesion",
}


def _parse_ham_groundtruth(csv_path, img_dirs):
    """Parse GroundTruth.csv (one-hot format): image,MEL,NV,BCC,AKIEC,BKL,DF,VASC"""
    result = defaultdict(list)
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_id = row.get("image", "").strip()
            if not img_id:
                continue
            label = None
            for code, name in HAM_ONEHOT_MAP.items():
                val = row.get(code, "0").strip()
                try:
                    if float(val) == 1.0:
                        label = name
                        break
                except ValueError:
                    continue
            if not label:
                continue
            for img_dir in img_dirs:
                for ext in ["", ".jpg", ".jpeg", ".png"]:
                    p = os.path.join(img_dir, img_id + ext)
                    if os.path.exists(p):
                        result[label].append(p)
                        break
    return result


def collect_ham(ham_dir: str) -> dict:
    """Возвращает {condition: [file_paths]}"""
    result = defaultdict(list)

    img_dirs = _find_img_dirs(ham_dir, [
        "HAM10000_images_part_1", "HAM10000_images_part_2",
        "images", "HAM10000_images"
    ])

    # Try GroundTruth.csv first (one-hot format from surajghuwalewala)
    gt_path = os.path.join(ham_dir, "GroundTruth.csv")
    if os.path.exists(gt_path):
        print(f"  📄 Используем GroundTruth.csv (one-hot формат)")
        result = _parse_ham_groundtruth(gt_path, img_dirs)
        for cls, files in result.items():
            print(f"  {cls}: {len(files)}")
        return result

    # Fallback to HAM10000_metadata.csv (dx column format)
    csv_path = _find_csv(ham_dir, ["HAM10000_metadata.csv", "metadata.csv"])
    if not csv_path:
        print("  ❌ HAM10000: CSV не найден (ни GroundTruth.csv, ни metadata.csv)")
        return result

    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dx    = row.get("dx", "").strip().lower()
            label = HAM_LABEL_MAP.get(dx, dx)
            img_id = row.get("image_id", "").strip()
            for img_dir in img_dirs:
                for ext in [".jpg", ".jpeg", ".png"]:
                    p = os.path.join(img_dir, img_id + ext)
                    if os.path.exists(p):
                        result[label].append(p)
                        break

    for cls, files in result.items():
        print(f"  {cls}: {len(files)}")
    return result


def collect_fitzpatrick(fitz_dir: str) -> dict:
    """Возвращает {condition: [file_paths]}"""
    result = defaultdict(list)
    csv_path = _find_csv(fitz_dir, [
        "fitzpatrick17k.csv", "fitzpatrick17k_labels.csv", "data.csv"
    ])
    if not csv_path:
        print("  ❌ Fitzpatrick17k: CSV не найден")
        return result

    img_dir = _find_img_dir(fitz_dir, ["data/finalfitz17k", "images", "finalfitz17k"])
    skipped = set()

    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label_raw = (row.get("label") or row.get("condition") or
                         row.get("three_partition_label") or "").strip()
            if not label_raw:
                continue
            label = normalize(label_raw)
            fname = (row.get("md5hash") or row.get("image_id") or
                     row.get("filename") or "").strip()
            if not fname:
                continue
            for ext in ["", ".jpg", ".jpeg", ".png"]:
                p = os.path.join(img_dir, fname + ext)
                if os.path.exists(p):
                    result[label].append(p)
                    break
            else:
                skipped.add(fname[:20])

    for cls, files in sorted(result.items(), key=lambda x: -len(x[1])):
        print(f"  {cls}: {len(files)}")
    if skipped:
        print(f"  ⚠️  Не найдено {len(skipped)} файлов")
    return result


def collect_scin(scin_dir: str) -> dict:
    """Возвращает {condition: [file_paths]}"""
    result = defaultdict(list)
    csv_path = _find_csv(scin_dir, [
        "scin_labels.csv", "labels.csv", "scin_data.csv",
        "train.csv", "scin_train_labels.csv"
    ])
    if not csv_path:
        print("  ❌ SCIN: CSV не найден в", scin_dir)
        return result

    img_dir = _find_img_dir(scin_dir, ["images", "scin_images", "imgs", "photos"])

    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label_raw = (row.get("label") or row.get("condition") or
                         row.get("skin_condition") or row.get("diagnosis") or "").strip()
            if not label_raw:
                continue
            label = normalize(label_raw)
            img_id = (row.get("image_id") or row.get("id") or
                      row.get("filename") or row.get("file_name") or "").strip()
            if not img_id:
                continue
            for ext in ["", ".jpg", ".jpeg", ".png", ".webp"]:
                p = os.path.join(img_dir, img_id + ext)
                if os.path.exists(p):
                    result[label].append(p)
                    break

    for cls, files in sorted(result.items(), key=lambda x: -len(x[1])):
        print(f"  {cls}: {len(files)}")
    return result


# ============================================================
# ОСНОВНАЯ ЛОГИКА
# ============================================================

def determine_valid_classes(all_counts: dict, min_count: int) -> set:
    """Определяет какие классы войдут как отдельные (≥ min_count фото)."""
    valid = set()
    print(f"\n📊 Анализ (порог ≥ {min_count} фото):")
    for label, files in sorted(all_counts.items(), key=lambda x: -len(x[1])):
        n = len(files)
        if n >= min_count:
            valid.add(label)
            print(f"  ✅ {n:5d}  {label}")
        else:
            print(f"  ❌ {n:5d}  {label}  → other")
    valid.add("other")
    print(f"\n  Итого классов: {len(valid)}")
    return valid


def copy_all(all_counts: dict, valid_classes: set, out_dir: str):
    """Копирует файлы: valid → свой класс, остальные → 'other'."""
    merged = defaultdict(list)
    for label, files in all_counts.items():
        target = label if label in valid_classes else "other"
        # Добавляем префикс источника к имени файла чтобы избежать конфликтов
        for f in files:
            merged[target].append(f)

    print("\n📋 Копирование файлов:")
    for cls in sorted(merged):
        files = merged[cls]
        split_and_copy(files, cls, out_dir)
        print(f"  {cls}: {len(files)} фото")


def print_stats(out_dir: str, classes):
    print("\n📊 ИТОГОВАЯ СТАТИСТИКА:")
    total = 0
    for split in ["train", "val"]:
        print(f"\n  {split}/")
        for cls in sorted(classes):
            path = os.path.join(out_dir, split, cls)
            n = len(os.listdir(path)) if os.path.exists(path) else 0
            total += n
            status = "✅" if n >= 50 else ("⚠️ " if n > 0 else "❌")
            print(f"    {status} {cls}: {n}")
    print(f"\n  Итого: {total} фото")


def save_class_map(classes, out_path: str):
    """Сохраняет class_map.json в алфавитном порядке (как ImageFolder)."""
    sorted_classes = sorted(classes)
    class_map = {str(i): cls for i, cls in enumerate(sorted_classes)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(class_map, f, indent=2, ensure_ascii=False)
    print(f"\n✅ class_map.json сохранён ({len(class_map)} классов)")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Подготовка датасета: все болезни как отдельные классы"
    )
    parser.add_argument("--ham",       default=None, help="Путь к папке HAM10000")
    parser.add_argument("--scin",      default=None, help="Путь к папке SCIN (Google)")
    parser.add_argument("--fitz",      default=None, help="Путь к папке Fitzpatrick17k")
    parser.add_argument("--out",       default="./dataset", help="Выходная папка датасета")
    parser.add_argument("--min_count", type=int, default=50,
                        help="Минимум фото для отдельного класса (default: 50)")
    args = parser.parse_args()

    random.seed(RANDOM_SEED)

    # ── Шаг 1: Собираем все файлы по условиям ───────────────────────────────
    all_counts = defaultdict(list)

    if args.ham:
        print("\n📂 HAM10000...")
        for label, files in collect_ham(args.ham).items():
            all_counts[label].extend(files)
    else:
        print("⚠️  --ham не указан, пропускаю HAM10000")

    if args.scin:
        print("\n📂 SCIN (Google)...")
        for label, files in collect_scin(args.scin).items():
            all_counts[label].extend(files)
    else:
        print("⚠️  --scin не указан, пропускаю SCIN")

    if args.fitz:
        print("\n📂 Fitzpatrick17k...")
        for label, files in collect_fitzpatrick(args.fitz).items():
            all_counts[label].extend(files)
    else:
        print("⚠️  --fitz не указан, пропускаю Fitzpatrick17k")

    if not all_counts:
        print("\n❌ Нет данных! Укажи хотя бы один датасет.")
        exit(1)

    # ── Шаг 2: Определяем valid классы ──────────────────────────────────────
    valid_classes = determine_valid_classes(all_counts, args.min_count)

    # ── Шаг 3: Создаём папки и копируем файлы ───────────────────────────────
    print(f"\n📁 Выходная папка: {args.out}")
    make_dirs(args.out, list(valid_classes))
    copy_all(all_counts, valid_classes, args.out)

    # ── Шаг 4: Статистика и сохранение class_map.json ───────────────────────
    print_stats(args.out, valid_classes)
    save_class_map(valid_classes, "class_map.json")

    print("\n🚀 Датасет готов! Запускай train.py")
