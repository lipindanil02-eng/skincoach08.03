"""
inference.py — Предсказание кожного заболевания по фото
Подключается к боту как модуль
"""
import json
import os
import torch
from PIL import Image
from core.model_loader import load_model as _load_model_shared, TRANSFORM

CONFIDENCE_THRESHOLD = 0.5

CLASS_LABELS_RU = {
    # Онкологические / предраковые
    "melanoma":                     "Меланома",
    "basal_cell_carcinoma":         "Базальноклеточный рак",
    "squamous_cell_carcinoma":      "Плоскоклеточный рак",
    "actinic_keratosis":            "Актинический кератоз",
    # Доброкачественные образования
    "melanocytic_nevus":            "Меланоцитарный невус (родинка)",
    "nevus":                        "Невус (родинка)",
    "seborrheic_keratosis":         "Себорейный кератоз",
    "keratosis":                    "Себорейный кератоз",
    "dermatofibroma":               "Дерматофиброма",
    "vascular_lesion":              "Сосудистое образование",
    "keloid":                       "Келоид",
    "lipoma":                       "Липома",
    # Воспалительные
    "psoriasis":                    "Псориаз",
    "plaque_psoriasis":             "Псориаз (бляшечный)",
    "guttate_psoriasis":            "Каплевидный псориаз",
    "eczema":                       "Экзема",
    "atopic_dermatitis":            "Атопический дерматит",
    "dyshidrotic_eczema":           "Дисгидротическая экзема",
    "nummular_eczema":              "Нуммулярная экзема",
    "dermatitis":                   "Дерматит",
    "contact_dermatitis":           "Контактный дерматит",
    "allergic_contact_dermatitis":  "Аллергический контактный дерматит",
    "seborrheic_dermatitis":        "Себорейный дерматит",
    "perioral_dermatitis":          "Периоральный дерматит",
    "drug_eruption":                "Лекарственная сыпь",
    "rosacea":                      "Розацеа",
    "erythema_multiforme":          "Многоформная эритема",
    # Акнеформные
    "acne":                         "Акне",
    "acne_vulgaris":                "Акне вульгарис",
    "cystic_acne":                  "Кистозное акне",
    "folliculitis":                 "Фолликулит",
    "hidradenitis":                 "Гнойный гидраденит",
    "milia":                        "Милиумы",
    # Пигментация
    "vitiligo":                     "Витилиго",
    "melasma":                      "Мелазма",
    "lentigo":                      "Лентиго",
    # Инфекционные
    "tinea":                        "Тинея (грибковая инфекция)",
    "tinea_versicolor":             "Отрубевидный лишай",
    "tinea_corporis":               "Микоз туловища",
    "tinea_pedis":                  "Грибок стопы",
    "warts":                        "Бородавки",
    "molluscum_contagiosum":        "Контагиозный моллюск",
    "impetigo":                     "Импетиго",
    "cellulitis":                   "Целлюлит (инфекционный)",
    "herpes_simplex":               "Простой герпес",
    "herpes_zoster":                "Опоясывающий герпес",
    "scabies":                      "Чесотка",
    # Аутоиммунные / системные
    "lichen_planus":                "Красный плоский лишай",
    "lupus_erythematosus":          "Красная волчанка",
    "scleroderma":                  "Склеродермия",
    "urticaria":                    "Крапивница",
    "pityriasis_rosea":             "Розовый лишай",
    "pemphigus":                    "Пузырчатка",
    # Другое
    "other":                        "Другое заболевание",
}


def get_label_ru(class_name: str) -> str:
    """Получить русское название болезни. Если нет — форматирует из кода."""
    if class_name in CLASS_LABELS_RU:
        return CLASS_LABELS_RU[class_name]
    # Fallback: "basal_cell_carcinoma" → "Basal Cell Carcinoma"
    return class_name.replace("_", " ").title()

_model = None
_class_map = None
_device = None

def load_model():
    global _model, _class_map, _device
    if _model is not None:
        return
    _model, _class_map, device_str = _load_model_shared()
    _device = torch.device(device_str)


# Трансформации — используются из core.model_loader.TRANSFORM
# (_transform определён ниже для обратной совместимости)


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

    tensor = TRANSFORM(img).unsqueeze(0).to(_device)

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
    diagnosis_ru = get_label_ru(best_class)
    reliable = best_prob >= CONFIDENCE_THRESHOLD

    top3 = []
    for idx, prob in zip(top_idx, top_probs):
        cls = idx_to_class.get(int(idx), f"class_{idx}")
        top3.append({
            "diagnosis": cls,
            "diagnosis_ru": get_label_ru(cls),
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
