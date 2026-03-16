# Skin Competition Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a skin competition feature where users earn a daily verified skin score and compete on separate weekly/all-time leaderboards for natural skin and with makeup.

**Architecture:** Hybrid model — every photo computes a skin score (7 components, shown privately); `/compete` issues a daily 4-digit challenge code; only photos containing the code (verified via vision model liveness check) count on the `/skinrank` leaderboard. Makeup is auto-detected, producing two categories. Anti-cheat allows max 3 retries per day.

**Tech Stack:** Python 3.12, python-telegram-bot 22.6, OpenRouter vision API (existing `call_raw`/`cj` helpers), pytest, `history.json` flat-file storage.

**Spec:** `docs/superpowers/specs/2026-03-16-skin-competition-design.md`

---

## Chunk 1: Prompt Files

### Task 1: Update `2_vision.txt` — 7-component skin score schema

**Files:**
- Modify: `2_vision.txt`

The prompt currently uses 5 components (each 0–20, including `radiance`). Replace with 7 components with new max values, rename `radiance` → `vitality`, add `youth` and `eye_area`, and add `has_makeup`/`visual_age` fields that are **always** populated.

- [ ] **Step 1: Update the prompt**

Replace the full contents of `2_vision.txt` with:

```
Ты — дерматолог-диагност. Твоя задача — описать что видно на фото кожи.
НЕ ставь диагноз. Только наблюдения.

Сначала определи: есть ли на фото видимые проблемы с кожей?

Если кожа выглядит ЗДОРОВОЙ — оцени по 7 параметрам:
1. ТОН (0-15): равномерность цвета, пигментация, покраснения, сосудистая сеть
2. УВЛАЖНЁННОСТЬ (0-15): эластичность, блеск, признаки сухости или обезвоженности
3. ТЕКСТУРА (0-15): гладкость, размер пор, шелушение, рельеф
4. ЖИВОСТЬ (0-15): яркость, свежесть, усталый/тусклый вид, здоровый цвет
5. ЧИСТОТА (0-15): отсутствие воспалений, комедонов, высыпаний, черных точек
6. МОЛОДОСТЬ (0-15): насколько кожа выглядит молодо — тонус, упругость, морщины
7. ОБЛАСТЬ ГЛАЗ (0-10): мешки под глазами, тёмные круги, отёки

Также проверь косметические особенности ДАЖЕ при здоровой коже:
- Морщины (тип: мимические, возрастные, обезвоживания)
- Мешки под глазами / тёмные круги
- Пигментация / веснушки / пятна
- Расширенные поры
- Тусклость / неравномерный тон
- Отметь "healthy": true

Если есть ПРОБЛЕМЫ с кожей — опиши детально:
1. Цвет поражённых участков (розовый, красный, серебристый, белый, коричневый)
2. Текстура (гладкая, шершавая, чешуйчатая, мокнущая, сухая, потрескавшаяся)
3. Форма элементов (бляшки, пятна, папулы, пузырьки, корочки, комедоны, угри)
4. Границы (чёткие, размытые, приподнятые)
5. Расположение (локти, колени, лицо, лоб, щёки, нос, подбородок, шея, туловище)
6. Площадь (точечно, отдельные участки, обширно)
7. Дополнительное (расчёсы, кровоточивость, отёк, трещины, черные точки, белые угри)
8. Признаки гормонального акне: высыпания вдоль линии челюсти, подбородка, шеи — отметить отдельно

Верни ТОЛЬКО JSON:
{
  "healthy": true/false,
  "skin_type": "normal/dry/oily/combination",
  "skin_score": {
    "tone": 0-15,
    "hydration": 0-15,
    "texture": 0-15,
    "vitality": 0-15,
    "cleanliness": 0-15,
    "youth": 0-15,
    "eye_area": 0-10,
    "total": 0-100
  },
  "has_makeup": true/false,
  "visual_age": число (визуальный возраст кожи),
  "color": ["перечисли цвета или общий тон"],
  "texture": ["перечисли текстуры"],
  "shapes": ["формы элементов или особенности"],
  "borders": "чёткие/размытые/приподнятые/н.а.",
  "location": ["где расположено"],
  "area": "точечно/отдельные участки/обширно/вся поверхность",
  "cosmetic_concerns": ["морщины/мешки/пигментация/тусклость/поры — если видны"],
  "hormonal_acne_signs": true/false,
  "additional": ["расчёсы, трещины, комедоны и тд если есть"],
  "raw_description": "2-3 предложения свободным текстом что видишь"
}

При healthy=true: заполни skin_score по всем 7 параметрам, total = сумма всех семи.
При healthy=true: даже если кожа здоровая, обязательно заполни cosmetic_concerns если видны морщины, мешки или пигментация.
При healthy=false: skin_score можно не заполнять (поставь null).
has_makeup и visual_age — заполнять ВСЕГДА, независимо от healthy.

Будь точным. Описывай ТОЛЬКО то что реально видно. Верни ТОЛЬКО JSON.
```

- [ ] **Step 2: Commit**

```bash
git add 2_vision.txt
git commit -m "feat: update vision prompt to 7-component skin score schema"
```

---

### Task 2: Update `3_reasoning.txt` — sync skin_score echo template

**Files:**
- Modify: `3_reasoning.txt`

The reasoning prompt echoes back `skin_score` fields from vision. Update field names and max annotations to match the new 7-component schema.

- [ ] **Step 1: Update the skin_score block in Scenario A**

Find this block in `3_reasoning.txt` (lines 19–27):
```
  "skin_score": {
    "tone": число из vision,
    "hydration": число из vision,
    "texture": число из vision,
    "radiance": число из vision,
    "cleanliness": число из vision,
    "total": сумма,
    "grade": "Отличная/Хорошая/Средняя/Требует внимания"
  },
```

Replace with:
```
  "skin_score": {
    "tone": число из vision (0-15),
    "hydration": число из vision (0-15),
    "texture": число из vision (0-15),
    "vitality": число из vision (0-15),
    "cleanliness": число из vision (0-15),
    "youth": число из vision (0-15),
    "eye_area": число из vision (0-10),
    "total": сумма,
    "grade": "Отличная/Хорошая/Средняя/Требует внимания"
  },
```

Grade thresholds remain unchanged (85–100 / 70–84 / 50–69 / 0–49).

- [ ] **Step 2: Commit**

```bash
git add 3_reasoning.txt
git commit -m "feat: sync reasoning prompt skin_score to 7-component schema"
```

---

### Task 3: Update `8_response.txt` — display new components

**Files:**
- Modify: `8_response.txt`

The final response template renders individual skin score fields. Update line 36 to use new field names and add `youth`/`eye_area`.

- [ ] **Step 1: Update the score display line**

Find this line in `8_response.txt` (line 36):
```
Тон: {skin_score.tone}/20 · Увлажнённость: {skin_score.hydration}/20 · Текстура: {skin_score.texture}/20 · Сияние: {skin_score.radiance}/20 · Чистота: {skin_score.cleanliness}/20
```

Replace with:
```
Тон: {skin_score.tone}/15 · Увлажнённость: {skin_score.hydration}/15 · Текстура: {skin_score.texture}/15 · Живость: {skin_score.vitality}/15 · Чистота: {skin_score.cleanliness}/15 · Молодость: {skin_score.youth}/15 · Глаза: {skin_score.eye_area}/10
```

The current file has no `visual_age` line. Insert the following on a new line immediately after the score line (i.e., after the line you just replaced, before the empty line that follows it):
```
Визуальный возраст кожи: {visual_age} лет
```

- [ ] **Step 2: Commit**

```bash
git add 8_response.txt
git commit -m "feat: update response template for 7-component skin score display"
```

---

## Chunk 2: `competition.py` — New Helper Module

### Task 4: Create `competition.py`

**Files:**
- Create: `competition.py`
- Create: `tests/test_competition.py`

This module handles challenge code generation and liveness verification. It depends on `call_raw` from `bot.py` — but to keep it testable, `check_liveness` accepts an injected async callable for the API call.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_competition.py`:

```python
# tests/test_competition.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import AsyncMock, patch

from competition import generate_challenge_code, verify_liveness_response


def test_generate_challenge_code_is_4_digits():
    code = generate_challenge_code()
    assert len(code) == 4
    assert code.isdigit()


def test_generate_challenge_code_varies():
    codes = {generate_challenge_code() for _ in range(20)}
    assert len(codes) > 1  # not always the same


def test_verify_liveness_true():
    assert verify_liveness_response('{"code_visible": true}', "4823") is True


def test_verify_liveness_false():
    assert verify_liveness_response('{"code_visible": false}', "4823") is False


def test_verify_liveness_parse_error():
    assert verify_liveness_response("not json", "4823") is False


def test_verify_liveness_missing_field():
    assert verify_liveness_response('{"other": "stuff"}', "4823") is False


def test_verify_liveness_null():
    assert verify_liveness_response(None, "4823") is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_competition.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'competition'`

- [ ] **Step 3: Create `competition.py`**

```python
"""
competition.py — Skin competition helpers: challenge code generation and liveness check.
"""
import random
import json


def generate_challenge_code() -> str:
    """Return a random 4-digit string, e.g. '4823'."""
    return str(random.randint(1000, 9999))


def verify_liveness_response(raw_response, expected_code: str) -> bool:
    """
    Parse the vision model's liveness check response.
    Returns True only if {"code_visible": true} is present.
    expected_code is accepted for future fuzzy-match extension but unused in v1.
    """
    if raw_response is None:
        return False
    try:
        if isinstance(raw_response, str):
            data = json.loads(raw_response.strip())
        else:
            data = raw_response
        return bool(data.get("code_visible", False))
    except Exception:
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_competition.py -v
```

Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add competition.py tests/test_competition.py
git commit -m "feat: add competition.py with challenge code generation and liveness response parser"
```

---

## Chunk 3: `gamification.py` — Competition Functions

### Task 5: Add competition defaults to `ensure_fields`

**Files:**
- Modify: `gamification.py`
- Modify: `tests/test_gamification_competition.py` (new test file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_gamification_competition.py`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py::test_ensure_fields_adds_competition_defaults -v
```

Expected: FAIL — `assert u["skin_score_last"] is None` (key missing)

- [ ] **Step 3: Add defaults to `ensure_fields` in `gamification.py`**

In `gamification.py`, find the `defaults` dict inside `ensure_fields` (around line 49) and add these entries:

```python
        "skin_score_last": None,
        "skin_score_components": None,
        "skin_score_history": [],
        "best_score_natural": None,
        "best_score_makeup": None,
        "compete_date": None,
        "challenge_code": None,
        "challenge_date": None,
        "compete_retry_count": 0,
```

- [ ] **Step 4: Run to verify pass**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py -v
```

Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add gamification.py tests/test_gamification_competition.py
git commit -m "feat: add competition field defaults to ensure_fields"
```

---

### Task 6: Add `_today_utc`, `get_weekly_key`, `can_compete_today`

**Files:**
- Modify: `gamification.py`
- Modify: `tests/test_gamification_competition.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gamification_competition.py`:

```python
from unittest.mock import patch
from datetime import datetime, timezone
from gamification import get_weekly_key, can_compete_today


def test_get_weekly_key_format():
    key = get_weekly_key()
    # e.g. "2026-W11"
    import re
    assert re.match(r"^\d{4}-W\d{2}$", key), f"Bad format: {key}"


def test_can_compete_today_false_when_no_date():
    u = {"compete_date": None}
    assert can_compete_today(u) is False


def test_can_compete_today_true_when_same_utc_date():
    fixed = datetime(2026, 3, 16, 12, 0, 0, tzinfo=timezone.utc)
    with patch("gamification.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed
        u = {"compete_date": "2026-03-16"}
        assert can_compete_today(u) is True


def test_can_compete_today_false_when_different_date():
    fixed = datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)
    with patch("gamification.datetime") as mock_dt:
        mock_dt.utcnow.return_value = fixed
        u = {"compete_date": "2026-03-16"}
        assert can_compete_today(u) is False
```

- [ ] **Step 2: Run to verify fail**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py::test_get_weekly_key_format -v
```

Expected: FAIL — `ImportError` or `AttributeError`

- [ ] **Step 3: Add functions to `gamification.py`**

At the top of `gamification.py`, ensure `datetime` is imported (it already is). Then update `_today()` and add new functions after it:

```python
def _today() -> str:
    """UTC date string YYYY-MM-DD. Used for streak/activity tracking."""
    return datetime.utcnow().date().isoformat()


def get_weekly_key() -> str:
    """Return ISO 8601 week key, e.g. '2026-W11'. Always UTC."""
    return datetime.utcnow().strftime("%G-W%V")


def can_compete_today(u: dict) -> bool:
    """Return True if user has already submitted a verified competition photo today (UTC)."""
    compete_date = u.get("compete_date")
    if compete_date is None:
        return False
    return compete_date == datetime.utcnow().date().isoformat()
```

- [ ] **Step 4: Run to verify pass**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add gamification.py tests/test_gamification_competition.py
git commit -m "feat: add get_weekly_key, can_compete_today, fix _today to UTC"
```

---

### Task 7: Add `on_regular_photo_score` and `on_compete_photo`

**Files:**
- Modify: `gamification.py`
- Modify: `tests/test_gamification_competition.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gamification_competition.py`:

```python
from gamification import on_regular_photo_score, on_compete_photo, ensure_fields


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
    assert u["skin_score_history"][0]["has_makeup"] is False


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
    assert u["compete_date"] == datetime.utcnow().date().isoformat()
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
    # 74 < 90, so best stays 90
    assert u["best_score_natural"] == 90


def test_on_compete_photo_null_score_raises():
    u = ensure_fields({})
    null_components = dict(SAMPLE_COMPONENTS)
    null_components["total"] = None
    # Should return u unchanged without crashing
    result = on_compete_photo(u, null_components, has_makeup=False)
    assert result["best_score_natural"] is None
```

- [ ] **Step 2: Run to verify fail**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py -k "on_regular or on_compete" -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Add functions to `gamification.py`**

Append after `on_referral_success`:

```python
def on_regular_photo_score(u: dict, score_components: dict, has_makeup: bool) -> dict:
    """
    Called after every photo analysis. Stores unverified skin score entry.
    Updates skin_score_last and skin_score_components. Does NOT affect leaderboard.
    """
    u = ensure_fields(u)
    total = score_components.get("total") if score_components else None
    if total is None:
        return u

    u["skin_score_last"] = total
    u["skin_score_components"] = score_components

    entry = {
        "date": _today(),
        "score": total,
        "has_makeup": has_makeup,
        "verified": False,
        "components": score_components,
    }
    u["skin_score_history"].append(entry)
    # Cap at 30 entries
    if len(u["skin_score_history"]) > 30:
        u["skin_score_history"] = u["skin_score_history"][-30:]

    return u


def on_compete_photo(u: dict, score_components: dict, has_makeup: bool) -> dict:
    """
    Called after a verified competition photo. Stores verified entry and updates
    best scores. Sets compete_date to today UTC. Caps history at 30.
    If total is None (bad photo), returns u unchanged.
    """
    u = ensure_fields(u)
    total = score_components.get("total") if score_components else None
    if total is None:
        return u

    u["skin_score_last"] = total
    u["skin_score_components"] = score_components
    u["compete_date"] = datetime.utcnow().date().isoformat()

    entry = {
        "date": _today(),
        "score": total,
        "has_makeup": has_makeup,
        "verified": True,
        "components": score_components,
    }
    u["skin_score_history"].append(entry)
    if len(u["skin_score_history"]) > 30:
        u["skin_score_history"] = u["skin_score_history"][-30:]

    # Update best scores
    if has_makeup:
        if u["best_score_makeup"] is None or total > u["best_score_makeup"]:
            u["best_score_makeup"] = total
    else:
        if u["best_score_natural"] is None or total > u["best_score_natural"]:
            u["best_score_natural"] = total

    return u
```

- [ ] **Step 4: Run to verify pass**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add gamification.py tests/test_gamification_competition.py
git commit -m "feat: add on_regular_photo_score and on_compete_photo to gamification"
```

---

### Task 8: Add `format_skinrank`

**Files:**
- Modify: `gamification.py`
- Modify: `tests/test_gamification_competition.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gamification_competition.py`:

```python
from gamification import format_skinrank


def _make_history(score, has_makeup, verified=True, date="2026-03-16"):
    """Create a history entry. date must be in current ISO week for weekly tests."""
    return [{
        "date": date, "score": score, "has_makeup": has_makeup,
        "verified": verified,
        "components": SAMPLE_COMPONENTS
    }]


def test_format_skinrank_empty():
    result = format_skinrank({}, viewer_uid="999")
    assert "пока пуст" in result or "участвовал" in result


def test_format_skinrank_shows_natural_section():
    all_users = {
        "1": {**ensure_fields({}), "name": "Анна",
              "skin_score_history": _make_history(87, has_makeup=False)},
    }
    result = format_skinrank(all_users, viewer_uid="999")
    assert "БЕЗ МАКИЯЖА" in result
    assert "Анна" in result
    assert "87" in result


def test_format_skinrank_shows_makeup_section():
    all_users = {
        "1": {**ensure_fields({}), "name": "Вика",
              "skin_score_history": _make_history(95, has_makeup=True)},
    }
    result = format_skinrank(all_users, viewer_uid="999")
    assert "С МАКИЯЖЕМ" in result
    assert "Вика" in result
    assert "95" in result


def test_format_skinrank_viewer_footer_no_history():
    all_users = {"1": {**ensure_fields({}), "name": "Анна",
                       "skin_score_history": _make_history(87, has_makeup=False)}}
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
    all_users = {
        "1": {**ensure_fields({}), "name": "Фейк",
              "skin_score_history": _make_history(99, has_makeup=False, verified=False)},
    }
    result = format_skinrank(all_users, viewer_uid="999")
    assert "Фейк" not in result
```

- [ ] **Step 2: Run to verify fail**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py -k "skinrank" -v
```

Expected: FAIL — `ImportError`

- [ ] **Step 3: Add `format_skinrank` to `gamification.py`**

Append after `format_leaderboard`:

```python
def format_skinrank(all_users: dict, viewer_uid: str) -> str:
    """
    Format /skinrank leaderboard: 4 sections (natural/makeup × week/alltime).
    Only verified=True entries count. Best score per user per week.
    Tie-break: earlier date wins.
    """
    current_week = get_weekly_key()
    medals = ["🥇", "🥈", "🥉"]

    # Collect best scores per user per category
    week_natural = {}   # uid -> (score, date, name)
    week_makeup = {}
    alltime_natural = {}
    alltime_makeup = {}

    def _better(current, new_score, new_date):
        if current is None:
            return True
        if new_score > current[0]:
            return True
        if new_score == current[0] and new_date < current[1]:
            return True
        return False

    for uid, u in all_users.items():
        name = u.get("name") or "Аноним"
        for entry in u.get("skin_score_history", []):
            if not entry.get("verified"):
                continue
            score = entry.get("score", 0)
            date = entry.get("date", "")
            makeup = entry.get("has_makeup", False)
            # Compute ISO week from stored date at query time (per spec)
            try:
                from datetime import date as _date
                entry_week = _date.fromisoformat(date).strftime("%G-W%V")
            except Exception:
                entry_week = ""

            if makeup:
                if _better(alltime_makeup.get(uid), score, date):
                    alltime_makeup[uid] = (score, date, name)
                if entry_week == current_week and _better(week_makeup.get(uid), score, date):
                    week_makeup[uid] = (score, date, name)
            else:
                if _better(alltime_natural.get(uid), score, date):
                    alltime_natural[uid] = (score, date, name)
                if entry_week == current_week and _better(week_natural.get(uid), score, date):
                    week_natural[uid] = (score, date, name)

    def _render_top(data: dict, label: str) -> list:
        top = sorted(data.values(), key=lambda x: (-x[0], x[1]))[:10]
        if not top:
            return [f"{label}: пока нет участников"]
        lines = [f"{label}:"]
        for i, (score, _, name) in enumerate(top):
            medal = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"{medal} {name} — {score}")
        return lines

    has_any = any([week_natural, week_makeup, alltime_natural, alltime_makeup])
    if not has_any:
        return "🏆 Рейтинг кожи пока пуст — попробуй /compete первым!"

    lines = ["🏆 РЕЙТИНГ КОЖИ", ""]
    lines.append("─── БЕЗ МАКИЯЖА ───────────────")
    lines.extend(_render_top(week_natural, "Эта неделя"))
    lines.append("")
    lines.extend(_render_top(alltime_natural, "Всё время"))
    lines.append("")
    lines.append("─── С МАКИЯЖЕМ ──────────────────")
    lines.extend(_render_top(week_makeup, "Эта неделя"))
    lines.append("")
    lines.extend(_render_top(alltime_makeup, "Всё время"))
    lines.append("")
    lines.append("───────────────────────────────")

    # Viewer footer
    viewer = all_users.get(str(viewer_uid), {})
    best_nat = viewer.get("best_score_natural")
    best_mak = viewer.get("best_score_makeup")
    if best_nat is not None or best_mak is not None:
        nat_str = str(best_nat) if best_nat is not None else "—"
        mak_str = str(best_mak) if best_mak is not None else "—"
        lines.append(f"Твой лучший: {nat_str} (без макияжа) | {mak_str} (с макияжем)")
    else:
        lines.append("Ты ещё не участвовал — попробуй /compete!")

    lines.append("📸 /compete — участвовать сегодня")
    lines.append("👉 /leaderboard — рейтинг по очкам и стрику")

    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_gamification_competition.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Run full test suite to check no regressions**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v
```

Expected: all existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add gamification.py tests/test_gamification_competition.py
git commit -m "feat: add format_skinrank leaderboard function"
```

---

## Chunk 4: `bot.py` — State Machine & Handlers

### Task 9: Add `S_COMPETE` state and update `handle_text`

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: Add `S_COMPETE` constant**

Find the constants block at line 41:
```python
S_NAME="name";S_DUR="dur";S_TRIED="tried";S_PHOTO="photo";S_QUESTIONS="questions";S_ACTIVE="active"
S_LABS="labs"
```

Add after:
```python
S_COMPETE="compete"
```

- [ ] **Step 2: Add `S_COMPETE` branch in `handle_text`**

In `handle_text`, find the `if u["state"]==S_PHOTO:` block (around line 396). After the `S_LABS` block (around line 446), before the `# Active program - chat` comment, add:

```python
    if u["state"]==S_COMPETE:
        code=u.get("challenge_code","????")
        await upd.message.reply_text(
            f"Жду фото с кодом {code} на бумажке. "
            "Отправь фото или напиши /start чтобы выйти.")
        sh(h); return
```

- [ ] **Step 3: Run existing tests to check nothing is broken**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add bot.py
git commit -m "feat: add S_COMPETE state and handle_text branch"
```

---

### Task 10: Add `/compete` command handler

**Files:**
- Modify: `bot.py`

- [ ] **Step 1: Add imports at the top of `bot.py`**

Find the import for `gamification` (line 12–14):
```python
from gamification import (ensure_fields, on_first_photo, update_streak,
    on_program_complete, on_referral_success, on_detailed_answer,
    format_achievements, format_leaderboard, add_points, award_badge, POINTS)
```

Replace with:
```python
from gamification import (ensure_fields, on_first_photo, update_streak,
    on_program_complete, on_referral_success, on_detailed_answer,
    format_achievements, format_leaderboard, format_skinrank,
    on_regular_photo_score, on_compete_photo, can_compete_today,
    add_points, award_badge, POINTS)
from competition import generate_challenge_code, verify_liveness_response
```

- [ ] **Step 2: Add `cmd_compete` handler function**

After `cmd_labs` (around line 745), add:

```python
async def cmd_compete(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();uid=upd.effective_user.id;u=gu(h,uid)
    if u["state"] not in (S_ACTIVE,S_LABS,S_COMPETE):
        await upd.message.reply_text("Сначала сделай анализ кожи — пришли фото 📸"); return

    if can_compete_today(u):
        best_nat=u.get("best_score_natural")
        best_mak=u.get("best_score_makeup")
        nat_str=str(best_nat) if best_nat is not None else "—"
        mak_str=str(best_mak) if best_mak is not None else "—"
        await upd.message.reply_text(
            f"Ты уже участвовал сегодня!\n\n"
            f"Твой лучший: {nat_str} (без макияжа) | {mak_str} (с макияжем)\n\n"
            "Посмотри /skinrank для рейтинга."); return

    code=generate_challenge_code()
    u["challenge_code"]=code
    u["challenge_date"]=datetime.utcnow().date().isoformat()
    u["compete_retry_count"]=0
    u["state"]=S_COMPETE
    sh(h)
    await upd.message.reply_text(
        f"Для рейтинга напиши на бумажке:\n\n"
        f"        {code}\n\n"
        "и сфотографируй кожу рядом с ней 📸\n\n"
        "Код должен быть чётко виден. Попытки: 3.")
```

- [ ] **Step 3: Add `cmd_skinrank` handler function**

After `cmd_compete`, add:

```python
async def cmd_skinrank(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();uid=str(upd.effective_user.id)
    await upd.message.reply_text(format_skinrank(h, viewer_uid=uid))
```

- [ ] **Step 4: Register handlers in `main()`**

In `main()`, find the block of `app.add_handler(CommandHandler(...))` calls and add:

```python
    app.add_handler(CommandHandler("compete",cmd_compete))
    app.add_handler(CommandHandler("skinrank",cmd_skinrank))
```

- [ ] **Step 5: Register commands in `post_init`**

In `post_init`, find `set_my_commands` list and add:

```python
            BotCommand("compete","🏆 Участвовать в рейтинге кожи"),
            BotCommand("skinrank","🥇 Рейтинг кожи"),
```

- [ ] **Step 6: Run tests**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add bot.py
git commit -m "feat: add /compete and /skinrank command handlers"
```

---

### Task 11: Update `handle_photo` — skin score on every photo + competition liveness check

**Files:**
- Modify: `bot.py`

This is the most complex change. Two additions:
1. After step 2 (vision), always call `on_regular_photo_score` and append score to reply
2. If state is `S_COMPETE`, run liveness check before the normal pipeline

- [ ] **Step 1: Declare `is_compete_photo` flag at the top of `handle_photo` and add liveness helper**

**Important:** `is_compete_photo` must be declared **before** the `try` block in `handle_photo` (around line 489, before `st = await upd.message.reply_text(...)`), so it remains in scope in the `finally` and after the `try`:

```python
    is_compete_photo = (u["state"] == S_COMPETE)
```

Also add the liveness check helper function after the `interpret_labs` function (around line 471):

```python
async def check_liveness(b64: str, code: str) -> bool:
    """Call vision model to verify challenge code is visible in photo."""
    prompt = (f'Is the handwritten number {code} visible on paper or a hand in this photo? '
              f'Reply JSON only: {{"code_visible": true}}  or  {{"code_visible": false}}')
    try:
        raw = await call_raw(
            [{"role":"system","content":"You verify if a specific number is handwritten in a photo."},
             {"role":"user","content":[
                 {"type":"text","text":prompt},
                 {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
             ]}],
            VISION_M, VIS_FB, mt=100)
        return verify_liveness_response(raw, code)
    except Exception as e:
        log.warning(f"Liveness check failed: {e}")
        return False
```

- [ ] **Step 2: Update `handle_photo` — add skin score extraction and display**

In `handle_photo`, find the section after `pipeline_photo` returns `result_type, result` (around line 555, inside the try block). After `result_type,result=await pipeline_photo(b64,cap,u)`, the `vis` data is in `u["vision_data"]`.

Locate the `sh(h)` just after the gamification section (around line 607) and add before it:

```python
    # Extract and store skin score from vision data (every photo)
    vis=u.get("vision_data") or {}
    skin_sc=vis.get("skin_score") if isinstance(vis,dict) else None
    has_makeup=vis.get("has_makeup",False) if isinstance(vis,dict) else False
    visual_age=vis.get("visual_age") if isinstance(vis,dict) else None
    if skin_sc and skin_sc.get("total") is not None:
        u=on_regular_photo_score(u,skin_sc,has_makeup)
```

- [ ] **Step 3: Append skin score to the reply message**

In `handle_photo`, find where `msg=intro+diag_text+q_text` is assembled (around line 608). After the gamification block and before `await send(upd.message,msg)`, add the score display:

```python
    score_line=""
    if skin_sc and skin_sc.get("total") is not None:
        t=skin_sc.get("total",0)
        makeup_note=" (с макияжем)" if has_makeup else " (без макияжа)"
        age_note=f" · Визуальный возраст: {visual_age}" if visual_age else ""
        score_line=f"\n\n📊 Оценка кожи: {t}/100{makeup_note}{age_note}\n/compete — участвовать в рейтинге"
    msg=intro+diag_text+q_text+score_line
```

- [ ] **Step 4: Add competition liveness check at the top of `handle_photo`**

In `handle_photo`, find the main try block that downloads the photo (around line 529–555). After `b64=base64.b64encode(b).decode()` and before calling `pipeline_photo`, add:

```python
        # Competition liveness check
        if u["state"]==S_COMPETE:
            code=u.get("challenge_code","????")
            code_ok=await check_liveness(b64,code)
            if not code_ok:
                retries=u.get("compete_retry_count",0)+1
                u["compete_retry_count"]=retries
                if retries>=3:
                    u["state"]=S_ACTIVE
                    sh(h)
                    await upd.message.reply_text(
                        "Превышен лимит попыток. Попробуй /compete завтра.")
                else:
                    sh(h)
                    await upd.message.reply_text(
                        f"Код не найден. Убедись что цифры {code} видны на бумаге "
                        f"рядом с кожей. Попытка {retries}/3.")
                try: await st.delete()
                except: pass
                return
```

- [ ] **Step 5: Store verified competition result after pipeline**

After the `on_regular_photo_score` call added in Step 2, add:

```python
    if u.get("state_before_compete") or u["state"]==S_ACTIVE:
        pass  # handled below
    # If this was a competition photo (state was S_COMPETE when photo arrived)
    # Note: state is checked BEFORE pipeline runs, so we track it via flag
```

Actually — simpler approach: track whether this photo was a competition photo using a local variable. At the top of `handle_photo` (before the try block), add:

```python
    is_compete_photo = (u["state"] == S_COMPETE)
```

Then after the skin score storage (Step 2), add:

```python
    if is_compete_photo and skin_sc and skin_sc.get("total") is not None:
        u=on_compete_photo(u,skin_sc,has_makeup)
        u["state"]=S_ACTIVE
        score_line=f"\n\n✅ Результат засчитан в рейтинг!\n📊 Оценка: {skin_sc.get('total')}/100{' (с макияжем)' if has_makeup else ' (без макияжа)'}\n/skinrank — посмотреть рейтинг"
    elif is_compete_photo and (not skin_sc or skin_sc.get("total") is None):
        # Bad quality photo, don't consume a retry
        u["state"]=S_ACTIVE
        sh(h)
        try: await st.delete()
        except: pass
        await upd.message.reply_text(
            "Фото не подходит для оценки. Попробуй ещё раз с хорошим освещением.")
        return
```

- [ ] **Step 6: Run tests**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add bot.py
git commit -m "feat: integrate skin score and competition liveness check into handle_photo"
```

---

## Chunk 5: Integration & Final Verification

### Task 12: Full test run and push

- [ ] **Step 1: Run the complete test suite**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v
```

Expected: all tests PASS with no failures.

- [ ] **Step 2: Verify bot.py imports cleanly**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```

Expected: `OK` (no import errors)

- [ ] **Step 3: Verify gamification.py imports cleanly**

```bash
cd /home/user/skincoach08.03 && python -c "import gamification; print(gamification.get_weekly_key()); print(gamification.can_compete_today({}))"
```

Expected: prints something like `2026-W11` then `False`

- [ ] **Step 4: Verify competition.py imports cleanly**

```bash
cd /home/user/skincoach08.03 && python -c "from competition import generate_challenge_code; print(generate_challenge_code())"
```

Expected: prints a 4-digit number

- [ ] **Step 5: Final commit and push**

```bash
git add -A
git status  # verify only expected files
git push -u origin claude/review-changes-mmlsibhrp59z2mh3-Xqk1T
```

---

## File Map Summary

| File | Action | Responsibility |
|---|---|---|
| `2_vision.txt` | Modify | 7-component skin score schema, `has_makeup`, `visual_age` |
| `3_reasoning.txt` | Modify | Sync skin_score echo to new field names |
| `8_response.txt` | Modify | Display new components (`vitality`, `youth`, `eye_area`) |
| `competition.py` | Create | `generate_challenge_code()`, `verify_liveness_response()` |
| `gamification.py` | Modify | `ensure_fields` defaults, UTC date helpers, score storage, `format_skinrank` |
| `bot.py` | Modify | `S_COMPETE` state, `/compete`, `/skinrank` handlers, photo flow |
| `tests/test_competition.py` | Create | Tests for competition helpers |
| `tests/test_gamification_competition.py` | Create | Tests for all new gamification functions |
