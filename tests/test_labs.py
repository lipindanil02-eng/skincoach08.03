# tests/test_labs.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import normalize_diagnosis, LABS_BASE, LABS_BY_DIAGNOSIS, format_labs_message

def test_normalize_melanoma():
    assert normalize_diagnosis("меланома кожи") == "melanoma"
    assert normalize_diagnosis("melanoma") == "melanoma"

def test_normalize_acne():
    assert normalize_diagnosis("акне") == "acne"
    assert normalize_diagnosis("угревая сыпь") == "acne"
    assert normalize_diagnosis("угревой дерматит") == "acne"
    assert normalize_diagnosis("прыщи на коже") == "acne"

def test_normalize_acne_no_false_positive():
    # "угр" was too broad — "угрюмый" should not match acne
    assert normalize_diagnosis("угрюмый") == "other"

def test_normalize_atopy():
    assert normalize_diagnosis("атопический дерматит") == "atopy"
    assert normalize_diagnosis("экзема") == "atopy"

def test_normalize_nevus():
    assert normalize_diagnosis("невус") == "nevus"
    assert normalize_diagnosis("родинка") == "nevus"

def test_normalize_seborrhea():
    assert normalize_diagnosis("себорейный дерматит") == "seborrhea"

def test_normalize_fallback():
    assert normalize_diagnosis("неизвестное заболевание") == "other"
    assert normalize_diagnosis("") == "other"
    assert normalize_diagnosis("требуется уточнение") == "other"

def test_normalize_none_safe():
    assert normalize_diagnosis(None) == "other"

def test_labs_base_not_empty():
    assert len(LABS_BASE) >= 8

def test_labs_by_diagnosis_has_all_keys():
    for key in ("melanoma", "nevus", "acne", "atopy", "seborrhea", "other"):
        assert key in LABS_BY_DIAGNOSIS

def test_format_labs_message_contains_base():
    msg = format_labs_message("акне")
    assert "ОАК" in msg
    assert "Витамин D" in msg

def test_format_labs_message_contains_diagnosis_extras():
    msg = format_labs_message("акне")
    assert "ДГЭАС" in msg or "тестостерон" in msg.lower()

def test_format_labs_message_no_extras_for_unknown():
    msg = format_labs_message("требуется уточнение")
    assert "Ферритин" in msg or "ТТГ" in msg

def test_format_labs_message_melanoma_urgent_warning():
    msg = format_labs_message("меланома")
    assert "дерматолог" in msg.lower()
    assert any(w in msg.lower() for w in ("срочно", "немедленно", "обратись"))

def test_format_labs_message_none_input():
    # normalize_diagnosis(None) returns "other", so this should not crash
    msg = format_labs_message(None)
    assert "ОАК" in msg
