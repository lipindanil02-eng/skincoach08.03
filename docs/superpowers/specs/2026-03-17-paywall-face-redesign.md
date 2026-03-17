# SkinCoach — Paywall + /face + UX redesign

**Date:** 2026-03-17
**Status:** Approved

---

## Scope

Four changes in one release:

1. `/face` command — instant face skin score (always free)
2. Free vs Paid access gate — 7-day trial, then paywall
3. Referral system — invite friend, both get 50% off
4. Score format — change X/15 → % with progress bars
5. Long message → split into 3 messages (split only for paid flow)

---

## 1. Access Tiers

### Trial (days 1–7)
Full access. `trial_start` set on first `/start`.

### Free (day 8+)
Blocked: photo analysis + recommendations + `/nextday`
Allowed: `/face`, `/ref`, `/status`, `/subscribe`, 3 chat questions/week

### Paid
Full access. `paid_until` date tracked in `history.json`.

### history.json additions per user
```json
{
  "trial_start": "2026-03-17",
  "subscription": "free",
  "paid_until": null,
  "questions_this_week": 0,
  "week_start": "2026-03-17",
  "ref_code": "REF_12345",
  "ref_by": null,
  "ref_count": 0,
  "discount_pct": 0
}
```

---

## 2. Access Gate Function

New `payments.py`:

```python
def is_access_allowed(user: dict) -> bool
def is_trial_active(user: dict) -> bool
def days_left_trial(user: dict) -> int
def can_ask_question(user: dict) -> bool   # 3/week limit
def use_question(user: dict) -> None       # decrement counter
def activate_subscription(user, days, discount_pct) -> None
def revoke_subscription(user) -> None
```

Gate applied in `bot.py` before:
- `handle_photo` (analysis + recommendations)
- text handler in `S_ACTIVE` (chat questions)
- `/nextday` handler

`/face` handler — NO gate, always allowed.

---

## 3. Paywall Message

Shown when gate blocks access:

```
💭 Ты уже чувствуешь — что-то не так с кожей.
Именно поэтому ты здесь.

За 7 дней я изучил твою кожу. Я знаю, что происходит.
Но без подписки — я не могу вести тебя дальше.

Каждый день без программы — кожа продолжает страдать. То, что сейчас решается за 2 недели,
через месяц потребует дорогой косметологии.

Представь: через 28 дней смотришь в зеркало
и видишь другую кожу. Это реально.

Я знаю как — мне нужно только твоё разрешение продолжить.
490₽/мес — меньше одной чашки кофе в день.
Персональный ИИ-коуч, который помнит твою кожу
и ведёт тебя каждый день.

👉 /subscribe — продолжить восстановление
```

---

## 4. Commands

### `/subscribe`
Shows payment instructions + requisites (hardcoded in env/config).
Applies 50% discount if `discount_pct > 0`.
Instructions: "После оплаты пришли скриншот этому боту".

### `/grant <user_id> [days]` (admin only)
Activates subscription for `days` (default 30).
Admin user_id stored in env as `ADMIN_ID`.

### `/revoke <user_id>` (admin only)
Sets `subscription=free`, clears `paid_until`.

### `/status`
Shows: trial days left OR subscription active until OR free tier with questions left.

### `/ref`
Generates referral link: `t.me/skincoach_bot?start=REF_<user_id>`
When friend registers via link:
- Referrer gets `discount_pct = 50`
- New user gets `discount_pct = 50`
- Referrer notified: "Друг зарегистрировался! Твоя скидка 50% активирована"

---

## 5. `/face` Command

**State:** New `S_FACE` state in bot.py
**Flow:**
1. `/face` → `S_FACE` → "Пришли фото лица при дневном свете"
2. Photo received in `S_FACE` → `handle_face_photo()`
3. Pipeline: quality check (1_quality.txt) + vision score (2_vision.txt)
4. Returns ONE message with score only (no recommendations, no program)
5. Score auto-submitted to skinrank

**Response format:**
```
✨ {name}, вот оценка твоей кожи:

📊 {score}% — {grade}
████████░░ Тон: {tone_pct}%
███████░░░ Увлажн.: {hydration_pct}%
███████░░░ Текстура: {texture_pct}%
███████░░░ Живость: {vitality_pct}%
████████░░ Чистота: {cleanliness_pct}%
███████░░░ Молодость: {youth_pct}%
████████░░ Глаза: {eye_pct}%

👁 Визуальный возраст: {visual_age} лет
🔎 {cosmetic_concern if any}
```

After score message, if user is free/trial show:
```
💡 Хочешь программу ухода под эту оценку?
👉 /subscribe — 490₽/мес
```

**Grades:**
- 90–100%: Отличная
- 75–89%: Хорошая
- 60–74%: Средняя
- 45–59%: Требует внимания
- <45%: Нужна программа

---

## 6. Score Format Change (global)

Everywhere `X/15` or `X/10` appears — replace with `%`:
- `tone/15 * 100` → round to int
- `eye_area/10 * 100` → round to int
- Progress bar: `"█" * (pct // 10) + "░" * (10 - pct // 10)`

Affected files: `bot.py`, `8_response.txt`, `gamification.py`

---

## 7. Message Split (paid flow)

Current: one giant message
New: 3 messages sent sequentially

**Message 1** — Diagnosis + Score (≤400 chars)
**Message 2** — Daily care routine: morning + evening + nutrition (≤400 chars)
**Message 3** — Psychosomatics + affirmation + evening check-in (≤300 chars)

Update `8_response.txt` to output JSON with 3 fields:
```json
{"msg1": "...", "msg2": "...", "msg3": "..."}
```
`bot.py` sends them sequentially with 0.5s delay.

---

## 8. Files Changed

| File | Change |
|------|--------|
| `bot.py` | Add S_FACE state, handle_face_photo(), access gate calls, /grant /revoke /status /ref /subscribe handlers |
| `payments.py` | New file: all access logic |
| `8_response.txt` | Output 3-part JSON, shorten text |
| `gamification.py` | Score format X/15 → % |
| `history.json` | Schema additions (auto-migrated on load) |

---

## 9. Out of Scope

- Automated payment processing (CryptoBot, Telegram Stars) — later
- Push notifications / scheduler — later
- ML model improvements — separate task
