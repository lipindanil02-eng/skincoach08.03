"""
analyze_datasets.py — Подсчёт фото по болезням в HAM10000, Fitzpatrick17k, SCIN.

Запускать на Kaggle ПЕРЕД prepare_dataset.py чтобы видеть полный список болезней
и их количество в датасетах.

Использование:
    python analyze_datasets.py \
        --ham  /kaggle/input/ham10000 \
        --fitz /path/to/fitzpatrick17k \
        --scin /path/to/scin \
        [--threshold 50]
"""

import os
import csv
import json
import argparse
from collections import defaultdict

# HAM10000: коды → читаемые имена болезней
HAM_LABEL_MAP = {
    "mel":   "melanoma",
    "nv":    "melanocytic_nevus",
    "bcc":   "basal_cell_carcinoma",
    "akiec": "actinic_keratosis",
    "bkl":   "seborrheic_keratosis",
    "df":    "dermatofibroma",
    "vasc":  "vascular_lesion",
}


def normalize(label: str) -> str:
    """'Acne Vulgaris' → 'acne_vulgaris'"""
    return (label.strip().lower()
            .replace(" ", "_").replace("-", "_")
            .replace("/", "_").replace("(", "").replace(")", ""))


def _find_csv(base, names):
    for name in names:
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    # Любой CSV в папке
    for fname in os.listdir(base):
        if fname.endswith(".csv"):
            return os.path.join(base, fname)
    return None


def count_ham(ham_dir: str, counts: dict):
    csv_path = _find_csv(ham_dir, ["HAM10000_metadata.csv", "metadata.csv"])
    if not csv_path:
        print("  ❌ HAM10000: metadata.csv не найден")
        return
    n = 0
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dx = row.get("dx", "").strip().lower()
            label = HAM_LABEL_MAP.get(dx, dx)
            counts[label] += 1
            n += 1
    print(f"  ✅ HAM10000: {n} строк")


def count_fitzpatrick(fitz_dir: str, counts: dict):
    csv_path = _find_csv(fitz_dir, ["fitzpatrick17k.csv", "fitzpatrick17k_labels.csv", "data.csv"])
    if not csv_path:
        print("  ❌ Fitzpatrick17k: CSV не найден в", fitz_dir)
        return
    n = 0
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label = (row.get("label") or row.get("condition") or
                     row.get("three_partition_label") or "").strip()
            if label:
                counts[normalize(label)] += 1
                n += 1
    print(f"  ✅ Fitzpatrick17k: {n} строк")


def count_scin(scin_dir: str, counts: dict):
    csv_path = _find_csv(scin_dir, [
        "scin_labels.csv", "labels.csv", "scin_data.csv",
        "train.csv", "scin_train_labels.csv"
    ])
    if not csv_path:
        print("  ❌ SCIN: CSV не найден в", scin_dir)
        return
    n = 0
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label = (row.get("label") or row.get("condition") or
                     row.get("skin_condition") or row.get("diagnosis") or "").strip()
            if label:
                counts[normalize(label)] += 1
                n += 1
    print(f"  ✅ SCIN: {n} строк")


def print_report(counts: dict, thresholds=(20, 50, 100, 200)):
    print("\n" + "=" * 65)
    print("📊 БОЛЕЗНИ ПО КОЛИЧЕСТВУ ФОТО (все источники)")
    print("=" * 65)
    sorted_items = sorted(counts.items(), key=lambda x: -x[1])
    for condition, count in sorted_items:
        bar = "█" * min(40, count // 20)
        print(f"  {count:5d}  {condition:<40s}  {bar}")

    print("\n" + "=" * 65)
    print("📊 КЛАССОВ ПРИ РАЗНЫХ ПОРОГАХ")
    print("=" * 65)
    for t in thresholds:
        classes = [c for c, n in counts.items() if n >= t]
        print(f"  Порог ≥ {t:4d} фото → {len(classes):3d} классов: "
              f"{', '.join(sorted(classes)[:5])}{'...' if len(classes) > 5 else ''}")

    print()


def save_class_map(counts: dict, threshold: int, out_path: str):
    valid = sorted(c for c, n in counts.items() if n >= threshold)
    if "other" not in valid:
        valid.append("other")
    valid.sort()
    class_map = {str(i): cls for i, cls in enumerate(valid)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(class_map, f, indent=2, ensure_ascii=False)
    print(f"✅ Сохранено {out_path} с {len(class_map)} классами (порог ≥ {threshold})")
    return valid


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Анализ болезней в датасетах дерматологии"
    )
    parser.add_argument("--ham",       default=None, help="Путь к HAM10000")
    parser.add_argument("--fitz",      default=None, help="Путь к Fitzpatrick17k")
    parser.add_argument("--scin",      default=None, help="Путь к SCIN (Google)")
    parser.add_argument("--threshold", type=int, default=50,
                        help="Минимум фото для отдельного класса (default: 50)")
    parser.add_argument("--save_map",  default=None,
                        help="Если указан — сохранить class_map.json по этому пути")
    args = parser.parse_args()

    counts = defaultdict(int)

    if args.ham:
        print("\n📂 HAM10000...")
        count_ham(args.ham, counts)
    else:
        print("⚠️  --ham не указан")

    if args.fitz:
        print("\n📂 Fitzpatrick17k...")
        count_fitzpatrick(args.fitz, counts)
    else:
        print("⚠️  --fitz не указан")

    if args.scin:
        print("\n📂 SCIN...")
        count_scin(args.scin, counts)
    else:
        print("⚠️  --scin не указан")

    if not counts:
        print("\n❌ Датасеты не найдены! Укажи хотя бы один из --ham, --fitz, --scin")
    else:
        print_report(counts)
        if args.save_map:
            save_class_map(dict(counts), args.threshold, args.save_map)
        else:
            valid = [c for c, n in counts.items() if n >= args.threshold]
            print(f"💡 Запусти с --save_map class_map.json чтобы сохранить список "
                  f"({len(valid)} классов при пороге ≥ {args.threshold})")
