# Paywall + /face + UX Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add free/paid access tiers with manual paywall, a new `/face` command for instant skin scoring, referral system, and UX improvements (score format + message splitting).

**Architecture:** New `payments.py` handles all access logic. `bot.py` calls it as a gate before protected handlers. `/face` gets its own state `S_FACE` and handler `handle_face_photo()` using a new `face_vision.txt` prompt. Score display switches from `X/15` to `%` with progress bars globally.

**Tech Stack:** Python 3.12, python-telegram-bot 22.6, httpx, existing OpenRouter API wrappers in `bot.py`

---

## Chunk 1: payments.py — Access Gate Logic

**Files:**
- Create: `payments.py`
- Create: `tests/test_payments.py`

### Task 1: Create payments.py with trial/paid logic

- [ ] **Step 1: Write failing tests**

Create `tests/test_payments.py`:

```python
import pytest
from datetime import datetime, timedelta
from payments import (
    is_trial_active, days_left_trial, is_access_allowed,
    can_ask_question, use_question, activate_subscription,
    revoke_subscription, apply_migration_defaults
)

def make_user(trial_start=None, subscription="free", paid_until=None,
              questions_this_week=0, week_start=None):
    today = datetime.utcnow().date().isoformat()
    return {
        "trial_start": trial_start or today,
        "subscription": subscription,
        "paid_until": paid_until,
        "questions_this_week": questions_this_week,
        "week_start": week_start or today,
        "ref_code": "REF_1",
        "ref_by": None,
        "ref_count": 0,
        "discount_pct": 0,
    }

def test_trial_active_day_1():
    u = make_user()
    assert is_trial_active(u) is True

def test_trial_active_day_7():
    start = (datetime.utcnow().date() - timedelta(days=6)).isoformat()
    u = make_user(trial_start=start)
    assert is_trial_active(u) is True

def test_trial_expired_day_8():
    start = (datetime.utcnow().date() - timedelta(days=7)).isoformat()
    u = make_user(trial_start=start)
    assert is_trial_active(u) is False

def test_days_left_trial():
    start = (datetime.utcnow().date() - timedelta(days=3)).isoformat()
    u = make_user(trial_start=start)
    assert days_left_trial(u) == 4

def test_access_allowed_during_trial():
    u = make_user()
    assert is_access_allowed(u) is True

def test_access_denied_after_trial():
    start = (datetime.utcnow().date() - timedelta(days=8)).isoformat()
    u = make_user(trial_start=start)
    assert is_access_allowed(u) is False

def test_access_allowed_paid():
    future = (datetime.utcnow().date() + timedelta(days=20)).isoformat()
    u = make_user(
        trial_start=(datetime.utcnow().date() - timedelta(days=8)).isoformat(),
        subscription="paid",
        paid_until=future
    )
    assert is_access_allowed(u) is True

def test_access_denied_expired_paid():
    past = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
    u = make_user(
        trial_start=(datetime.utcnow().date() - timedelta(days=40)).isoformat(),
        subscription="paid",
        paid_until=past
    )
    assert is_access_allowed(u) is False

def test_can_ask_question_fresh():
    u = make_user()
    assert can_ask_question(u) is True

def test_can_ask_question_exhausted():
    u = make_user(questions_this_week=3)
    assert can_ask_question(u) is False

def test_use_question_decrements():
    u = make_user(questions_this_week=1)
    use_question(u)
    assert u["questions_this_week"] == 2

def test_use_question_resets_on_new_week():
    old_week = (datetime.utcnow().date() - timedelta(days=7)).isoformat()
    u = make_user(questions_this_week=3, week_start=old_week)
    use_question(u)
    assert u["questions_this_week"] == 1  # reset + 1

def test_activate_subscription():
    u = make_user()
    activate_subscription(u, days=30, discount_pct=0)
    assert u["subscription"] == "paid"
    assert u["paid_until"] is not None
    future = (datetime.utcnow().date() + timedelta(days=30)).isoformat()
    assert u["paid_until"] == future

def test_activate_subscription_clears_discount():
    u = make_user()
    u["discount_pct"] = 50
    activate_subscription(u, days=30, discount_pct=50)
    assert u["discount_pct"] == 0

def test_revoke_subscription():
    future = (datetime.utcnow().date() + timedelta(days=20)).isoformat()
    u = make_user(subscription="paid", paid_until=future)
    revoke_subscription(u)
    assert u["subscription"] == "free"
    assert u["paid_until"] is None

def test_migration_defaults_missing_fields():
    u = {"state": "active", "name": "Test"}
    apply_migration_defaults(u)
    assert "trial_start" in u
    assert u["subscription"] == "free"
    assert u["questions_this_week"] == 0
    assert u["ref_count"] == 0

def test_migration_keeps_existing_trial_start():
    existing = "2026-01-01"
    u = {"trial_start": existing}
    apply_migration_defaults(u)
    assert u["trial_start"] == existing
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_payments.py -v 2>&1 | head -20
```
Expected: ImportError or multiple FAILs — `payments` module doesn't exist yet.

- [ ] **Step 3: Create payments.py**

```python
"""
payments.py — Access control: trial, paid subscription, referral discounts.
"""
from datetime import datetime, timedelta
import logging

log = logging.getLogger("skincoach")

TRIAL_DAYS = 7
MAX_QUESTIONS_PER_WEEK = 3
PRICE_RUB = 490

PAYWALL_MESSAGE = """💭 Ты уже чувствуешь — что-то не так с кожей.
Именно поэтому ты здесь.

За 7 дней я изучил твою кожу. Я знаю, что происходит.
Но без подписки — я не могу вести тебя дальше.

Каждый день без программы — кожа продолжает страдать. То, что сейчас решается за 2 недели, через месяц потребует дорогой косметологии.

Представь: через 28 дней смотришь в зеркало и видишь другую кожу. Это реально.

Я знаю как — мне нужно только твоё разрешение продолжить.
490₽/мес — меньше одной чашки кофе в день.
Персональный ИИ-коуч, который помнит твою кожу и ведёт тебя каждый день.

👉 /subscribe — продолжить восстановление"""


def _today() -> str:
    return datetime.utcnow().date().isoformat()


def apply_migration_defaults(u: dict) -> None:
    """Add new fields to existing users who don't have them yet."""
    today = _today()
    defaults = {
        "trial_start": today,
        "subscription": "free",
        "paid_until": None,
        "questions_this_week": 0,
        "week_start": today,
        "ref_code": f"REF_{id(u)}",
        "ref_by": None,
        "ref_count": 0,
        "discount_pct": 0,
    }
    for key, val in defaults.items():
        if key not in u:
            u[key] = val


def is_trial_active(u: dict) -> bool:
    trial_start = u.get("trial_start")
    if not trial_start:
        return True
    try:
        start = datetime.fromisoformat(trial_start).date()
        today = datetime.utcnow().date()
        return (today - start).days < TRIAL_DAYS
    except Exception:
        return True


def days_left_trial(u: dict) -> int:
    trial_start = u.get("trial_start")
    if not trial_start:
        return TRIAL_DAYS
    try:
        start = datetime.fromisoformat(trial_start).date()
        today = datetime.utcnow().date()
        remaining = TRIAL_DAYS - (today - start).days
        return max(0, remaining)
    except Exception:
        return 0


def is_access_allowed(u: dict) -> bool:
    if is_trial_active(u):
        return True
    if u.get("subscription") == "paid":
        paid_until = u.get("paid_until")
        if paid_until:
            try:
                until = datetime.fromisoformat(paid_until).date()
                return datetime.utcnow().date() <= until
            except Exception:
                pass
    return False


def can_ask_question(u: dict) -> bool:
    """Free users can ask 3 questions per week."""
    _reset_week_if_needed(u)
    return u.get("questions_this_week", 0) < MAX_QUESTIONS_PER_WEEK


def use_question(u: dict) -> None:
    _reset_week_if_needed(u)
    u["questions_this_week"] = u.get("questions_this_week", 0) + 1


def _reset_week_if_needed(u: dict) -> None:
    today = _today()
    week_start = u.get("week_start", today)
    try:
        ws = datetime.fromisoformat(week_start).date()
        now = datetime.utcnow().date()
        if (now - ws).days >= 7:
            u["questions_this_week"] = 0
            u["week_start"] = today
    except Exception:
        u["week_start"] = today


def activate_subscription(u: dict, days: int = 30, discount_pct: int = 0) -> None:
    today = datetime.utcnow().date()
    paid_until = (today + timedelta(days=days)).isoformat()
    u["subscription"] = "paid"
    u["paid_until"] = paid_until
    u["discount_pct"] = 0  # consume discount after activation
    log.info(f"Subscription activated: until {paid_until}, discount was {discount_pct}%")


def revoke_subscription(u: dict) -> None:
    u["subscription"] = "free"
    u["paid_until"] = None
```

- [ ] **Step 4: Run tests — all must pass**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_payments.py -v
```
Expected: all 18 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/user/skincoach08.03 && git add payments.py tests/test_payments.py && git commit -m "feat: add payments.py with trial/paid/referral access logic"
```

---

## Chunk 2: Migration + Gate in bot.py

**Files:**
- Modify: `bot.py` (gu function, handle_photo, handle_text, cmd_next)

### Task 2: Apply migration defaults on user load

- [ ] **Step 1: Update `gu()` to call migration**

In `bot.py`, find the `gu` function (line ~160). Add import at top of file and call `apply_migration_defaults`:

At the top of `bot.py`, add to imports:
```python
from payments import (is_access_allowed, can_ask_question, use_question,
                      apply_migration_defaults, PAYWALL_MESSAGE)
```

In `gu()` function, after `h[u]=ensure_fields(h[u])`, add:
```python
    from payments import apply_migration_defaults
    apply_migration_defaults(h[u])
```

Wait — the import should be at the top of the file, not inside the function. Find the import block at the top and add the payments import there.

- [ ] **Step 2: Find exact location for import**

The file imports from `gamification` on line 12. Add payments import after it:

```python
from payments import (is_access_allowed, can_ask_question, use_question,
                      apply_migration_defaults, PAYWALL_MESSAGE)
```

- [ ] **Step 3: Update gu() to call apply_migration_defaults**

Find in `bot.py` around line 168:
```python
    if "labs_raw" not in h[u]: h[u]["labs_raw"]=None
    if "labs_submitted_at" not in h[u]: h[u]["labs_submitted_at"]=None
    return h[u]
```

Add before `return h[u]`:
```python
    apply_migration_defaults(h[u])
```

- [ ] **Step 4: Verify bot still starts**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```
Expected: `OK` (no import errors)

### Task 3: Add paywall gate to handle_photo

- [ ] **Step 1: Find handle_photo gate location**

In `bot.py` line ~517, `handle_photo` starts. After the labs check (line ~524), add the access gate. The gate must fire only for regular analysis (not for `/face` which has its own handler).

Find the block after `if u["state"]==S_LABS:` that ends around line 545. After that block, before the main analysis begins, insert:

```python
    # Access gate — block full analysis for expired users
    if not is_access_allowed(u):
        await upd.message.reply_text(PAYWALL_MESSAGE)
        return
```

- [ ] **Step 2: Add gate to handle_text (S_ACTIVE chat)**

Find in `handle_text` around line 460, the `if u["state"]==S_ACTIVE:` block. At the very start of that block, add:

```python
    if u["state"]==S_ACTIVE:
        # Free users: 3 questions/week limit
        if not is_access_allowed(u):
            if not can_ask_question(u):
                await upd.message.reply_text(
                    "💬 Ты использовал 3 вопроса на этой неделе.\n"
                    "Безлимитный чат — в подписке.\n\n"
                    + PAYWALL_MESSAGE
                )
                return
            use_question(u)
            sh(h)
```

- [ ] **Step 3: Add gate to cmd_next**

Find `cmd_next` around line 705. After the state check, add:

```python
    if not is_access_allowed(u):
        await upd.message.reply_text(PAYWALL_MESSAGE)
        return
```

- [ ] **Step 4: Run existing tests to make sure nothing broke**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v 2>&1 | tail -20
```
Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit**

```bash
cd /home/user/skincoach08.03 && git add bot.py && git commit -m "feat: add paywall gate to photo analysis, chat, and /nextday"
```

---

## Chunk 3: New Commands (/subscribe, /grant, /revoke, /ref, update /status)

**Files:**
- Modify: `bot.py`

### Task 4: Add /subscribe command

- [ ] **Step 1: Find where to add the handler**

Add new function before `main()` in `bot.py` (around line 854, after `cmd_skinrank`):

```python
async def cmd_subscribe(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    price = 490
    if u.get("discount_pct",0) > 0:
        disc = u["discount_pct"]
        final = int(price * (1 - disc/100))
        price_line = f"💰 Цена: {final}₽/мес (скидка {disc}% активирована!)"
    else:
        price_line = f"💰 Цена: {price}₽/мес"

    pay_details = os.getenv("PAYMENT_DETAILS","Реквизиты не настроены — напиши администратору")
    msg = (
        f"📋 Подписка SkinCoach\n\n"
        f"{price_line}\n\n"
        f"Что входит:\n"
        f"✅ Полный анализ кожи\n"
        f"✅ 28-дневная программа\n"
        f"✅ Безлимитный чат\n"
        f"✅ Питание, уход, психосоматика\n\n"
        f"💳 Реквизиты для оплаты:\n{pay_details}\n\n"
        f"После оплаты пришли скриншот сюда — активирую доступ в течение часа."
    )
    await upd.message.reply_text(msg)
```

### Task 5: Add /grant and /revoke commands (admin only)

- [ ] **Step 1: Add grant/revoke handlers**

```python
async def cmd_grant(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    admin_id = os.getenv("ADMIN_ID","").strip()
    if not admin_id or upd.effective_user.id != int(admin_id):
        return
    args=ctx.args
    if not args:
        await upd.message.reply_text("Usage: /grant <user_id> [days]"); return
    target_uid=args[0]
    days=int(args[1]) if len(args)>1 else 30
    h=lh()
    if target_uid not in h:
        await upd.message.reply_text(f"User {target_uid} not found"); return
    from payments import activate_subscription
    disc = h[target_uid].get("discount_pct",0)
    activate_subscription(h[target_uid], days=days, discount_pct=disc)
    sh(h)
    await upd.message.reply_text(f"✅ Подписка активирована для {target_uid} на {days} дней")
    try:
        await ctx.bot.send_message(int(target_uid),
            f"🎉 Твоя подписка активирована на {days} дней!\n"
            f"Теперь у тебя полный доступ. Пришли фото — начнём программу.")
    except Exception as e:
        log.warning(f"Could not notify user {target_uid}: {e}")

async def cmd_revoke(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    admin_id = os.getenv("ADMIN_ID","").strip()
    if not admin_id or upd.effective_user.id != int(admin_id):
        return
    args=ctx.args
    if not args:
        await upd.message.reply_text("Usage: /revoke <user_id>"); return
    target_uid=args[0]
    h=lh()
    if target_uid not in h:
        await upd.message.reply_text(f"User {target_uid} not found"); return
    from payments import revoke_subscription
    revoke_subscription(h[target_uid])
    sh(h)
    await upd.message.reply_text(f"✅ Подписка отозвана у {target_uid}")
```

### Task 6: Add /ref command

- [ ] **Step 1: Add ref handler**

```python
async def cmd_ref(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    bot_username = (await ctx.bot.get_me()).username
    ref_code = u.get("ref_code") or f"REF_{uid}"
    u["ref_code"] = ref_code
    sh(h)
    link = f"https://t.me/{bot_username}?start={ref_code}"
    msg = (
        f"🎁 Твоя реферальная ссылка:\n{link}\n\n"
        f"Поделись с другом — вы оба получите скидку 50% на первый месяц.\n"
        f"То есть всего 245₽ вместо 490₽!\n\n"
        f"Твоих приглашений: {u.get('ref_count',0)}"
    )
    await upd.message.reply_text(msg)
```

### Task 7: Update cmd_start to handle referral links + set trial_start

- [ ] **Step 1: Find cmd_start (line ~366)**

Current `cmd_start` resets state. Update it to:
1. Set `trial_start` only if not already set (first-time users)
2. Handle `start=REF_xxx` args for referral

Find the body of `cmd_start` and update:

```python
async def cmd_start(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    # Handle referral link: /start REF_12345
    args = ctx.args
    if args and args[0].startswith("REF_"):
        ref_code = args[0]
        referrer_uid = None
        # Find referrer by ref_code
        for ruid, ru in h.items():
            if ru.get("ref_code") == ref_code and ruid != str(uid):
                referrer_uid = ruid
                break
        if referrer_uid and not u.get("ref_by"):
            u["ref_by"] = referrer_uid
            u["discount_pct"] = 50
            h[referrer_uid]["ref_count"] = h[referrer_uid].get("ref_count",0) + 1
            h[referrer_uid]["discount_pct"] = 50
            try:
                await ctx.bot.send_message(int(referrer_uid),
                    "🎉 Друг зарегистрировался по твоей ссылке!\n"
                    "Твоя скидка 50% активирована — используй /subscribe.")
            except Exception as e:
                log.warning(f"ref notify fail: {e}")
    # Reset for new registration
    h[str(uid)]["state"]=S_NAME
    h[str(uid)]["msgs"]=[]
    sh(h)
    await upd.message.reply_text("Привет! Я SkinCoach — твой персональный ИИ-коуч по коже.\nКак тебя зовут?")
```

### Task 8: Update /status to show subscription info

- [ ] **Step 1: Find cmd_status (line ~758) and update**

Replace the function body to add subscription info:

```python
async def cmd_status(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    from payments import is_trial_active, days_left_trial, is_access_allowed, MAX_QUESTIONS_PER_WEEK
    lines = []
    if is_trial_active(u):
        d = days_left_trial(u)
        lines.append(f"⏳ Пробный период: осталось {d} дн.")
    elif u.get("subscription") == "paid" and u.get("paid_until"):
        lines.append(f"✅ Подписка активна до: {u['paid_until']}")
    else:
        used = u.get("questions_this_week", 0)
        left = max(0, MAX_QUESTIONS_PER_WEEK - used)
        lines.append(f"🔒 Подписка не активна")
        lines.append(f"💬 Вопросов осталось на этой неделе: {left}/3")
        lines.append(f"👉 /subscribe — оформить подписку")
    # existing status info
    diag = u.get("diagnosis","не определено")
    day = u.get("day",0)
    lines.append(f"\n📋 Диагноз: {diag}")
    lines.append(f"📅 День программы: {day}/28")
    if u.get("skin_score_last"):
        lines.append(f"📊 Последняя оценка: {u['skin_score_last']}/100")
    await upd.message.reply_text("\n".join(lines))
```

### Task 9: Register all new handlers in main()

- [ ] **Step 1: Add handlers to app in main()**

Find where handlers are added (line ~964). Add:
```python
    app.add_handler(CommandHandler("subscribe",cmd_subscribe))
    app.add_handler(CommandHandler("grant",cmd_grant))
    app.add_handler(CommandHandler("revoke",cmd_revoke))
    app.add_handler(CommandHandler("ref",cmd_ref))
```

Also update BotCommands list:
```python
    BotCommand("face","✨ Оценка кожи лица"),
    BotCommand("subscribe","💳 Оформить подписку"),
    BotCommand("ref","🎁 Пригласить друга"),
```

- [ ] **Step 2: Verify bot imports cleanly**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```

- [ ] **Step 3: Run all tests**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```bash
cd /home/user/skincoach08.03 && git add bot.py && git commit -m "feat: add /subscribe /grant /revoke /ref commands and referral system"
```

---

## Chunk 4: /face Command

**Files:**
- Create: `face_vision.txt`
- Modify: `bot.py`

### Task 10: Create face_vision.txt prompt

- [ ] **Step 1: Create the prompt file**

Create `/home/user/skincoach08.03/face_vision.txt`:

```
Ты — эксперт по косметологии и состоянию кожи лица.
Анализируй ТОЛЬКО кожу лица на фото. Дай объективную оценку.

Верни СТРОГО JSON (без markdown, без пояснений):
{
  "quality_ok": true,
  "skin_score": {
    "total": <0-100>,
    "tone": <0-100>,
    "hydration": <0-100>,
    "texture": <0-100>,
    "vitality": <0-100>,
    "cleanliness": <0-100>,
    "youth": <0-100>,
    "eye_area": <0-100>
  },
  "visual_age": <число лет>,
  "cosmetic_concern": "<одна строка о главной проблеме или null>",
  "healthy": <true|false>
}

Правила оценки (каждый параметр 0-100):
- tone: ровность тона, отсутствие пигментации и покраснений
- hydration: увлажнённость, отсутствие сухости и шелушения
- texture: гладкость, минимум пор и неровностей
- vitality: сияние, живость, здоровый цвет
- cleanliness: отсутствие акне, воспалений, угрей
- youth: упругость, отсутствие морщин и провисаний
- eye_area: отсутствие мешков, тёмных кругов, морщин вокруг глаз
- total: средневзвешенная оценка (eye_area вес 0.5, остальные вес 1.0)

Если фото плохого качества или лицо не видно — верни quality_ok: false.
```

### Task 11: Add S_FACE state and handle_face_photo() to bot.py

- [ ] **Step 1: Add S_FACE constant**

Find in `bot.py` line 44-46:
```python
S_NAME="name";S_DUR="dur";S_TRIED="tried";S_PHOTO="photo";S_QUESTIONS="questions";S_ACTIVE="active"
S_LABS="labs"
S_COMPETE="compete"
```

Add:
```python
S_FACE="face"
```

- [ ] **Step 2: Add helper function score_bar()**

Add this helper near the top of bot.py after the constants:

```python
def score_bar(pct: int) -> str:
    """Return 10-char progress bar for a 0-100 score."""
    filled = min(10, max(0, pct // 10))
    return "█" * filled + "░" * (10 - filled)

def score_grade(pct: int) -> str:
    if pct >= 90: return "Отличная"
    if pct >= 75: return "Хорошая"
    if pct >= 60: return "Средняя"
    if pct >= 45: return "Требует внимания"
    return "Нужна программа"
```

- [ ] **Step 3: Add handle_face_photo() function**

Add before `main()`:

```python
async def cmd_face(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    u["state"]=S_FACE;sh(h)
    await upd.message.reply_text("✨ Пришли фото лица при дневном свете, без макияжа.")

async def handle_face_photo(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    st=await upd.message.reply_text("🔍 Анализирую кожу лица... ⏳")
    await upd.message.chat.send_action(ChatAction.TYPING)
    try:
        ph=upd.message.photo[-1];f=await ctx.bot.get_file(ph.file_id)
        b=await f.download_as_bytearray();b64=base64.b64encode(b).decode()
    except Exception as e:
        log.error(f"face photo download: {e}")
        try: await st.delete()
        except: pass
        await upd.message.reply_text("Не удалось загрузить фото. Попробуй ещё раз.")
        u["state"]=S_ACTIVE;sh(h)
        return

    # 1. Quality check
    qp=rp("1_quality.txt","Проверь качество фото.")
    try:
        qraw=await call_raw([
            {"role":"system","content":qp},
            {"role":"user","content":[
                {"type":"text","text":"Проверь качество этого фото кожи лица."},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
            ]}],VISION_M,VIS_FB,300)
        qd=xj(qraw)
        if isinstance(qd,dict) and not qd.get("quality_ok",True):
            try: await st.delete()
            except: pass
            await upd.message.reply_text("📸 Фото нечёткое или лицо не видно. Попробуй при дневном свете, поближе.")
            u["state"]=S_ACTIVE;sh(h)
            return
    except Exception as e:
        log.warning(f"face quality check failed: {e}")

    # 2. Face vision scoring
    fp=rp("face_vision.txt","Оцени кожу лица.")
    try:
        fraw=await call_raw([
            {"role":"system","content":fp},
            {"role":"user","content":[
                {"type":"text","text":"Оцени кожу лица на этом фото."},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}
            ]}],VISION_M,VIS_FB,600)
        fd=xj(fraw)
    except Exception as e:
        log.error(f"face vision fail: {e}")
        try: await st.delete()
        except: pass
        await upd.message.reply_text("Не удалось проанализировать. Попробуй позже.")
        u["state"]=S_ACTIVE;sh(h)
        return

    try: await st.delete()
    except: pass

    if not isinstance(fd,dict) or fd.get("quality_ok")==False:
        await upd.message.reply_text("📸 Не вижу лицо чётко. Попробуй при хорошем освещении.")
        u["state"]=S_ACTIVE;sh(h)
        return

    sc = fd.get("skin_score",{})
    total = sc.get("total",0)
    grade = score_grade(total)
    name = u.get("name","друг")
    visual_age = fd.get("visual_age","?")
    concern = fd.get("cosmetic_concern") or ""

    lines = [f"✨ {name}, вот оценка кожи лица:\n"]
    lines.append(f"📊 {total}% — {grade}")
    for label, key in [("Тон","tone"),("Увлажн.","hydration"),("Текстура","texture"),
                        ("Живость","vitality"),("Чистота","cleanliness"),
                        ("Молодость","youth"),("Глаза","eye_area")]:
        pct = sc.get(key,0)
        lines.append(f"{score_bar(pct)} {label}: {pct}%")
    lines.append(f"\n👁 Визуальный возраст: {visual_age} лет")
    if concern:
        lines.append(f"🔎 {concern}")

    reply = "\n".join(lines)

    # Submit to skinrank (as regular photo score)
    u = on_regular_photo_score(u, {"total": total, **sc}, False)
    u["state"]=S_ACTIVE;sh(h)
    await upd.message.reply_text(reply)

    # Upsell if not paid
    if not is_access_allowed(u):
        await asyncio.sleep(0.5)
        await upd.message.reply_text(
            "💡 Хочешь программу ухода под эту оценку?\n"
            "👉 /subscribe — 490₽/мес"
        )
```

- [ ] **Step 4: Register /face handler and S_FACE photo filter in main()**

In `main()`, add before `app.add_handler(MessageHandler(filters.PHOTO,handle_photo))`:

```python
    app.add_handler(CommandHandler("face",cmd_face))
    app.add_handler(MessageHandler(filters.PHOTO & filters.UpdateType.MESSAGE,
                                   handle_face_photo,
                                   block=False))
```

Wait — this would conflict with `handle_photo`. The correct approach is to check state inside `handle_photo` OR add state-based routing. The cleanest way: at the TOP of `handle_photo`, add:

```python
async def handle_photo(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    # Route /face photos to dedicated handler
    if u["state"] == S_FACE:
        await handle_face_photo(upd, ctx)
        return
    ...rest of existing code...
```

- [ ] **Step 5: Verify bot imports**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```

- [ ] **Step 6: Run all tests**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v 2>&1 | tail -20
```

- [ ] **Step 7: Commit**

```bash
cd /home/user/skincoach08.03 && git add bot.py face_vision.txt && git commit -m "feat: add /face command with instant skin scoring"
```

---

## Chunk 5: Score Format (X/15 → %) + Message Split

**Files:**
- Modify: `bot.py` (score_line formatting)
- Modify: `8_response.txt`
- Modify: `gamification.py` (skinrank display)

### Task 12: Update score display in bot.py

- [ ] **Step 1: Find score_line in handle_photo (line ~667-683)**

Current code builds `score_line` with `{t}/100` format. The total is already 0-100, so just update the display to use `score_bar`:

Find:
```python
        score_line=(f"\n\n✅ Результат засчитан в рейтинг!\n📊 Оценка: {t}/100"
                    f"{' (с макияжем)' if has_makeup else ' (без макияжа)'}\n/skinrank — посмотреть рейтинг")
```

Replace with:
```python
        score_line=(f"\n\n✅ Результат засчитан в рейтинг!\n📊 {score_bar(t)} {t}%"
                    f"{' (с макияжем)' if has_makeup else ' (без макияжа)'}\n/skinrank — посмотреть рейтинг")
```

Find:
```python
        score_line=f"\n\n📊 Оценка кожи: {t}/100{makeup_note}{age_note}\n/compete — участвовать в рейтинге"
```

Replace with:
```python
        score_line=f"\n\n📊 {score_bar(t)} {t}%{makeup_note}{age_note}\n/compete — участвовать в рейтинге"
```

### Task 13: Update 8_response.txt to output 3-part JSON and use % scores

- [ ] **Step 1: Rewrite 8_response.txt**

Replace the full content of `8_response.txt` with:

```
Ты — SkinCoach, финальный голос продукта. Тебе дали полный анализ от команды экспертов.
Собери из него ТРИ коротких сообщения для Telegram. Верни СТРОГО JSON:
{"msg1": "...", "msg2": "...", "msg3": "..."}

Правила (строго):
- По имени ({name})
- НЕ звёздочки, НЕ markdown, НЕ решётки
- Эмодзи как разделители
- Тёплый, уверенный тон наставника
- НЕ "обратитесь к врачу", НЕ "покажитесь специалисту" — запрещено
- Оценки ТОЛЬКО в % (не X/15, не X/10)
- Полоски прогресса: █████░░░░░ формат (10 символов)
- Максимально кратко, без воды

msg1 — Диагноз + оценка кожи (3-5 строк):
ЕСЛИ healthy=true:
✨ {name}, кожа выглядит хорошо!
(1 предложение о состоянии)
📊 {skin_score.total}% — {grade}
{score_bar} Тон: {tone}%  · Увлажн.: {hydration}%  · Текстура: {texture}%
{score_bar} Чистота: {cleanliness}%  · Молодость: {youth}%  · Глаза: {eye_area}%
👁 Визуальный возраст: {visual_age} лет

ЕСЛИ healthy=false:
🔍 {name}, вот что я вижу:
(диагноз, стадия, 1-2 предложения)
📊 {skin_score.total}% — {grade}

ЕСЛИ diagnosis_comparison.changed=true — добавь в msg1 перед всем:
🔄 Диагноз изменился: было {prev} → теперь {current}
(explanation_for_user — 1 предложение)

msg2 — Программа дня (5-7 строк):
День {day}/28 — Неделя {week}
🧴 Утро: (2 действия)
🌙 Вечер: (2 действия)
🥗 Убрать: ... Добавить: ... Добавки: ...

msg3 — Психосоматика + аффирмация (3-4 строки):
🧠 (1 практика + связь стресс→кожа, 1 предложение)
🎯 Фокус дня: (одно действие)
💫 Аффирмация: ...
📝 Вечером напиши: как кожа?

Верни ТОЛЬКО JSON. Без пояснений.
```

### Task 14: Update bot.py to parse 3-part JSON from 8_response.txt

- [ ] **Step 1: Find pipeline_final in bot.py**

Search for where the final response is sent (around line 692-703). The `reply` variable contains the LLM output. Update the sending logic to parse JSON:

Find the block:
```python
        try: reply=await pipeline_final(u,"")
        except Exception as e: reply="Ошибка. /next"; log.error(f"Final:{e}")
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"])
        try: await st2.delete()
        except: pass
        await send(upd.message,reply)
```

Replace with:
```python
        try: reply=await pipeline_final(u,"")
        except Exception as e: reply="Ошибка. /next"; log.error(f"Final:{e}")
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"])
        try: await st2.delete()
        except: pass
        # Try to parse 3-part JSON response
        try:
            parts = json.loads(reply) if reply.strip().startswith("{") else None
            if isinstance(parts, dict) and "msg1" in parts:
                await send(upd.message, parts["msg1"])
                if parts.get("msg2"):
                    await asyncio.sleep(0.5)
                    await send(upd.message, parts["msg2"])
                if parts.get("msg3"):
                    await asyncio.sleep(0.5)
                    await send(upd.message, parts["msg3"])
            else:
                await send(upd.message, reply)
        except Exception:
            await send(upd.message, reply)
```

Also apply the same pattern where `cmd_next` sends the final reply (around line ~730).

### Task 15: Update gamification.py skinrank display

- [ ] **Step 1: Find format_skinrank score display (line ~397)**

Find:
```python
            lines.append(f"{medal} {name} — {score}")
```

Replace with:
```python
            lines.append(f"{medal} {name} — {score}%")
```

- [ ] **Step 2: Run all tests**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
cd /home/user/skincoach08.03 && git add bot.py 8_response.txt gamification.py && git commit -m "feat: score % format, progress bars, 3-part message split"
```

---

## Chunk 6: Final Wiring + Push

### Task 16: Update env.txt docs and verify ADMIN_ID, PAYMENT_DETAILS

- [ ] **Step 1: Add new env vars to env.txt (if it exists as template)**

Check if `env.txt` is a template (not a real secrets file):
```bash
head -5 /home/user/skincoach08.03/env.txt
```

If it's a template, add:
```
ADMIN_ID=your_telegram_user_id
PAYMENT_DETAILS=Карта Сбербанк: 4276 XXXX XXXX XXXX (Имя Фамилия)
```

### Task 17: Full integration smoke test

- [ ] **Step 1: Run all tests**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 2: Verify bot starts without errors**

```bash
cd /home/user/skincoach08.03 && timeout 5 python bot.py 2>&1 | head -20
```
Expected: startup logs, no ImportError or AttributeError.

### Task 18: Push to remote

- [ ] **Step 1: Final commit if anything pending**

```bash
cd /home/user/skincoach08.03 && git status
```

- [ ] **Step 2: Push**

```bash
cd /home/user/skincoach08.03 && git push -u origin claude/review-changes-mmlsibhrp59z2mh3-Xqk1T
```

---

## Summary of Files Created/Modified

| File | Action |
|------|--------|
| `payments.py` | CREATE — access gate logic |
| `face_vision.txt` | CREATE — face scoring prompt |
| `tests/test_payments.py` | CREATE — unit tests |
| `bot.py` | MODIFY — migration, gate, /face, /subscribe, /grant, /revoke, /ref, score format, msg split |
| `8_response.txt` | MODIFY — 3-part JSON output, % scores |
| `gamification.py` | MODIFY — skinrank % display |
