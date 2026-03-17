# tests/test_gamification_competition.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gamification import ensure_fields


def test_ensure_fields_adds_competition_defaults():
    u = {"state": "active", "name": "Анна"}
    u = ensure_fields(u)
    assert u["skin_score_last"] is None
    assert u["skin_score_components"] is None
    assert u["skin_score_history"] == []
    assert u["best_score_natural"] is None
    assert u["best_score_makeup"] is None
    assert u["compete_date"] is None
    assert u["challenge_code"] is None
    assert u["challenge_date"] is None
    assert u["compete_retry_count"] == 0


def test_ensure_fields_does_not_overwrite_existing():
    u = {"skin_score_last": 74, "best_score_natural": 80}
    u = ensure_fields(u)
    assert u["skin_score_last"] == 74
    assert u["best_score_natural"] == 80

from unittest.mock import patch
from datetime import datetime, timezone
import re
from gamification import get_weekly_key, can_compete_today, on_regular_photo_score, on_compete_photo, format_skinrank


def test_get_weekly_key_format():
    key = get_weekly_key()
    assert re.match(r"^\d{4}-W\d{2}$", key), f"Bad format: {key}"


def test_can_compete_today_false_when_no_date():
    u = {"compete_date": None}
    assert can_compete_today(u) is False


def test_can_compete_today_true_when_same_utc_date():
    fixed = datetime(2026, 3, 16, 12, 0, 0)
    with patch("gamification.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed
        u = {"compete_date": "2026-03-16"}
        assert can_compete_today(u) is True


def test_can_compete_today_false_when_different_date():
    fixed = datetime(2026, 3, 17, 12, 0, 0)
    with patch("gamification.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed
        u = {"compete_date": "2026-03-16"}
        assert can_compete_today(u) is False


SAMPLE_COMPONENTS = {
    "tone": 12, "hydration": 13, "texture": 11,
    "vitality": 10, "cleanliness": 13, "youth": 12, "eye_area": 3,
    "total": 74
}


def test_on_regular_photo_score_updates_last():
    u = ensure_fields({})
    u = on_regular_photo_score(u, SAMPLE_COMPONENTS, has_makeup=False)
    assert u["skin_score_last"] == 74
    assert u["skin_score_components"]["tone"] == 12
    assert len(u["skin_score_history"]) == 1
    assert u["skin_score_history"][0]["verified"] is False


def test_on_regular_photo_score_caps_history_at_30():
    u = ensure_fields({})
    u["skin_score_history"] = [{"date": "2020-01-01", "score": 50, "verified": False}] * 30
    u = on_regular_photo_score(u, SAMPLE_COMPONENTS, has_makeup=False)
    assert len(u["skin_score_history"]) == 30


def test_on_compete_photo_updates_best_natural():
    u = ensure_fields({})
    u = on_compete_photo(u, SAMPLE_COMPONENTS, has_makeup=False)
    assert u["best_score_natural"] == 74
    assert u["best_score_makeup"] is None
    assert len(u["skin_score_history"]) == 1
    assert u["skin_score_history"][0]["verified"] is True


def test_on_compete_photo_updates_best_makeup():
    u = ensure_fields({})
    u = on_compete_photo(u, SAMPLE_COMPONENTS, has_makeup=True)
    assert u["best_score_makeup"] == 74
    assert u["best_score_natural"] is None


def test_on_compete_photo_only_improves_best():
    u = ensure_fields({})
    u["best_score_natural"] = 90
    u = on_compete_photo(u, SAMPLE_COMPONENTS, has_makeup=False)
    assert u["best_score_natural"] == 90


def test_on_compete_photo_null_score_noop():
    u = ensure_fields({})
    null_comp = dict(SAMPLE_COMPONENTS)
    null_comp["total"] = None
    result = on_compete_photo(u, null_comp, has_makeup=False)
    assert result["best_score_natural"] is None


def _make_history(score, has_makeup, verified=True, edate="2026-03-16"):
    return [{"date": edate, "score": score, "has_makeup": has_makeup, "verified": verified, "components": SAMPLE_COMPONENTS}]


def test_format_skinrank_empty():
    result = format_skinrank({}, viewer_uid="999")
    assert "пуст" in result or "участвовал" in result


def test_format_skinrank_shows_natural_section():
    all_users = {"1": {**ensure_fields({}), "name": "Анна", "skin_score_history": _make_history(87, has_makeup=False)}}
    result = format_skinrank(all_users, viewer_uid="999")
    assert "БЕЗ МАКИЯЖА" in result
    assert "Анна" in result
    assert "87" in result


def test_format_skinrank_shows_makeup_section():
    all_users = {"1": {**ensure_fields({}), "name": "Вика", "skin_score_history": _make_history(95, has_makeup=True)}}
    result = format_skinrank(all_users, viewer_uid="999")
    assert "С МАКИЯЖЕМ" in result
    assert "Вика" in result
    assert "95" in result


def test_format_skinrank_viewer_footer_no_history():
    all_users = {"1": {**ensure_fields({}), "name": "Анна", "skin_score_history": _make_history(87, has_makeup=False)}}
    result = format_skinrank(all_users, viewer_uid="999")
    assert "не участвовал" in result or "/compete" in result


def test_format_skinrank_viewer_footer_with_history():
    u = ensure_fields({})
    u["best_score_natural"] = 74
    u["best_score_makeup"] = 88
    all_users = {"999": u}
    result = format_skinrank(all_users, viewer_uid="999")
    assert "74" in result
    assert "88" in result


def test_format_skinrank_unverified_not_counted():
    all_users = {"1": {**ensure_fields({}), "name": "Фейк", "skin_score_history": _make_history(99, has_makeup=False, verified=False)}}
    result = format_skinrank(all_users, viewer_uid="999")
    assert "Фейк" not in result
