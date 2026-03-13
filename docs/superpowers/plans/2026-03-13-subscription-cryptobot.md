# Subscription via CryptoBot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 7-day free trial + 499 RUB/month (~5.5 USDT) subscription via CryptoBot (@CryptoBot Telegram API).

**Architecture:** Add subscription state to existing `history.json` per user. New `payments.py` module handles CryptoBot API. Gate photo analysis and `/nextday` behind `is_access_allowed()` check. Poll CryptoBot for payment confirmation.

**Tech Stack:** Python 3.12, httpx (already in requirements), CryptoBot API (no extra package needed), existing history.json storage.

---

## Prerequisites (manual, before coding)

- [ ] Open @CryptoBot in Telegram → `/start` → `Create App` → name it "SkinCoach"
- [ ] Copy API Token → add to `env.txt` as `CRYPTOBOT_TOKEN=your_token_here`
- [ ] Decide USDT amount: 499 RUB ÷ ~90 RUB/USDT = **5.5 USDT** (update if rate changes)

---

## Chunk 1: Subscription state + access check

### Task 1: Add subscription fields to user state

**Files:**
- Modify: `bot.py:89-92` (user init dict)
- Modify: `bot.py:286` (/start handler — set trial_start)

- [ ] **Step 1: Add fields to new user init dict** (`bot.py` line ~89)

```python
if u not in h:
    h[u] = {
        "state": S_NAME, "name": None, "duration": None, "tried": None,
        "day": 0, "week": 1, "msgs": [], "created": datetime.now().isoformat(),
        "trial_start": datetime.now().isoformat(),   # <-- добавить
        "sub_end": None,                              # <-- добавить ISO string или None
        "sub_active": False                           # <-- добавить
    }
```

- [ ] **Step 2: Ensure trial_start set for existing users** (migration patch, same function)

```python
# после загрузки пользователя
if "trial_start" not in h[u]:
    h[u]["trial_start"] = h[u].get("created", datetime.now().isoformat())
    h[u]["sub_end"] = None
    h[u]["sub_active"] = False
    sh(h)
```

- [ ] **Step 3: Commit**

```bash
git add bot.py
git commit -m "feat: add subscription fields to user state"
```

---

### Task 2: Create payments.py module

**Files:**
- Create: `payments.py`

- [ ] **Step 1: Create payments.py**

```python
"""
payments.py — CryptoBot API integration + subscription access check
"""
import os
import httpx
from datetime import datetime, timedelta

CRYPTOBOT_TOKEN = os.getenv("CRYPTOBOT_TOKEN", "")
CRYPTOBOT_API = "https://pay.crypt.bot/api"
TRIAL_DAYS = 7
SUB_PRICE_USDT = "5.50"
SUB_DAYS = 30

def _headers():
    return {"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN}

def is_access_allowed(u: dict) -> tuple[bool, str]:
    """
    Returns (allowed: bool, reason: str)
    reason: 'trial' | 'subscribed' | 'trial_expired' | 'sub_expired'
    """
    now = datetime.now()

    # Проверка активной подписки
    if u.get("sub_active") and u.get("sub_end"):
        sub_end = datetime.fromisoformat(u["sub_end"])
        if sub_end > now:
            return True, "subscribed"
        else:
            return False, "sub_expired"

    # Проверка триала
    trial_start = datetime.fromisoformat(u.get("trial_start", datetime.now().isoformat()))
    trial_end = trial_start + timedelta(days=TRIAL_DAYS)
    if now < trial_end:
        days_left = (trial_end - now).days + 1
        return True, f"trial:{days_left}"

    return False, "trial_expired"

async def create_invoice(user_id: int) -> dict:
    """Создаёт счёт в CryptoBot. Возвращает {'invoice_id', 'pay_url'}"""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{CRYPTOBOT_API}/createInvoice",
            headers=_headers(),
            json={
                "asset": "USDT",
                "amount": SUB_PRICE_USDT,
                "description": "SkinCoach — подписка на 30 дней",
                "payload": str(user_id),
                "expires_in": 3600,
            },
            timeout=30
        )
        r.raise_for_status()
        data = r.json()
        inv = data["result"]
        return {"invoice_id": inv["invoice_id"], "pay_url": inv["pay_url"]}

async def check_invoice(invoice_id: int) -> bool:
    """Проверяет оплачен ли счёт. Возвращает True если paid."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{CRYPTOBOT_API}/getInvoices",
            headers=_headers(),
            params={"invoice_ids": str(invoice_id), "status": "paid"},
            timeout=30
        )
        r.raise_for_status()
        items = r.json()["result"].get("items", [])
        return len(items) > 0

def activate_subscription(u: dict) -> dict:
    """Активирует подписку на 30 дней, возвращает обновлённый u."""
    u["sub_active"] = True
    u["sub_end"] = (datetime.now() + timedelta(days=SUB_DAYS)).isoformat()
    return u
```

- [ ] **Step 2: Commit**

```bash
git add payments.py
git commit -m "feat: add payments.py with CryptoBot API and access check"
```

---

## Chunk 2: Bot integration — gate + payment flow

### Task 3: Gate photo analysis and /nextday

**Files:**
- Modify: `bot.py` — import payments, add gate before photo handler and /nextday

- [ ] **Step 1: Add import at top of bot.py**

```python
from payments import is_access_allowed, create_invoice, check_invoice, activate_subscription
```

- [ ] **Step 2: Add helper function for paywall message** (добавить после импортов)

```python
async def send_paywall(update, u: dict):
    """Отправляет сообщение о подписке с кнопкой оплаты."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    uid = update.effective_user.id
    inv = await create_invoice(uid)
    # сохранить invoice_id в u для проверки
    u["pending_invoice"] = inv["invoice_id"]
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 Оплатить 5.5 USDT (~499₽)", url=inv["pay_url"]),
    ]])
    await update.message.reply_text(
        "⏰ Бесплатная неделя завершена.\n\n"
        "Подписка SkinCoach — 499₽/месяц (5.5 USDT)\n"
        "Доступ на 30 дней сразу после оплаты.\n\n"
        "После оплаты нажми /check_payment",
        reply_markup=keyboard
    )
```

- [ ] **Step 3: Add gate in photo handler** (найти `if u["state"]==S_PHOTO:`, добавить перед обработкой)

```python
if u["state"] == S_PHOTO:
    allowed, reason = is_access_allowed(u)
    if not allowed:
        await send_paywall(update, u)
        sh(h)
        return
    # ... существующий код
```

- [ ] **Step 4: Add gate in /nextday handler** (найти `async def nextday`, добавить в начало)

```python
allowed, reason = is_access_allowed(u)
if not allowed:
    await send_paywall(update, u)
    sh(h)
    return
```

- [ ] **Step 5: Add trial_left hint для активных триальных пользователей**

В начале photo handler, после проверки доступа:
```python
if reason.startswith("trial:"):
    days_left = reason.split(":")[1]
    await update.message.reply_text(f"ℹ️ Пробный период: осталось {days_left} дн.")
```

- [ ] **Step 6: Commit**

```bash
git add bot.py
git commit -m "feat: gate photo analysis and /nextday behind subscription check"
```

---

### Task 4: /check_payment command

**Files:**
- Modify: `bot.py` — добавить новый хендлер

- [ ] **Step 1: Add handler function**

```python
async def check_payment(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(upd.effective_user.id)
    h = lh(); u = gh(h, uid)
    invoice_id = u.get("pending_invoice")
    if not invoice_id:
        await upd.message.reply_text("У тебя нет ожидающих платежей. Напиши /start")
        return
    await upd.message.reply_text("🔄 Проверяю оплату...")
    paid = await check_invoice(invoice_id)
    if paid:
        u = activate_subscription(u)
        u.pop("pending_invoice", None)
        h[uid] = u
        sh(h)
        await upd.message.reply_text(
            "✅ Оплата получена! Подписка активна на 30 дней.\n"
            f"Действует до: {u['sub_end'][:10]}\n\n"
            "Отправь фото кожи для анализа 👇"
        )
    else:
        await upd.message.reply_text(
            "⏳ Оплата ещё не поступила.\n"
            "Попробуй через минуту или нажми /check_payment снова."
        )
```

- [ ] **Step 2: Register handler** (в блоке где регистрируются остальные handlers)

```python
app.add_handler(CommandHandler("check_payment", check_payment))
```

- [ ] **Step 3: Commit**

```bash
git add bot.py
git commit -m "feat: add /check_payment command for subscription activation"
```

---

## Chunk 3: env.txt + requirements + deploy

### Task 5: Update env and requirements

**Files:**
- Modify: `env.txt`
- Modify: `requirements.txt` (httpx уже есть — ничего добавлять не нужно)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add to env.txt**

```
CRYPTOBOT_TOKEN=your_token_here
SUB_PRICE_USDT=5.50
TRIAL_DAYS=7
```

- [ ] **Step 2: Update CLAUDE.md — добавить в секцию "Текущий статус"**

```
- Монетизация: 7 дней бесплатно → 499₽/мес через CryptoBot (USDT)
- payments.py — модуль оплаты и проверки доступа
```

- [ ] **Step 3: Commit**

```bash
git add env.txt CLAUDE.md
git commit -m "docs: add CryptoBot token to env, update CLAUDE.md"
```

---

## Финальная проверка перед деплоем

- [ ] Локально: `python -c "from payments import is_access_allowed; print('OK')"`
- [ ] Проверить что `CRYPTOBOT_TOKEN` добавлен в Railway environment variables
- [ ] Задеплоить: `git push` → Railway auto-deploy
- [ ] Протестировать: создать тестовый invoice через @CryptoBot testnet

---

## Итог

| Файл | Изменение |
|------|-----------|
| `payments.py` | Новый — CryptoBot API + access check |
| `bot.py` | Gate в photo + /nextday + /check_payment handler |
| `env.txt` | CRYPTOBOT_TOKEN |
| `CLAUDE.md` | Обновить документацию |

**Время реализации:** ~2-3 часа
**Зависимость от пользователя:** получить CRYPTOBOT_TOKEN из @CryptoBot
