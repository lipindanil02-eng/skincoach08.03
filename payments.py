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
        "ref_code": None,
        "ref_by": None,
        "ref_count": 0,
        "discount_pct": 0,
        "notify_daily": None,  # None=not asked, True=yes, False=no
        "bonus_days": 0,
        "photo_history": [],
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
        total_days = TRIAL_DAYS + u.get("bonus_days", 0)
        return (today - start).days < total_days
    except Exception:
        return True


def days_left_trial(u: dict) -> int:
    trial_start = u.get("trial_start")
    if not trial_start:
        return TRIAL_DAYS
    try:
        start = datetime.fromisoformat(trial_start).date()
        today = datetime.utcnow().date()
        total_days = TRIAL_DAYS + u.get("bonus_days", 0)
        remaining = total_days - (today - start).days
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
    current_until = u.get("paid_until")
    if current_until and u.get("subscription") == "paid":
        try:
            base = max(today, datetime.fromisoformat(current_until).date())
        except Exception:
            base = today
    else:
        base = today
    paid_until = (base + timedelta(days=days)).isoformat()
    u["subscription"] = "paid"
    u["paid_until"] = paid_until
    u["discount_pct"] = 0  # consume discount after activation
    log.info(f"Subscription activated: until {paid_until}, discount was {discount_pct}%")


def revoke_subscription(u: dict) -> None:
    u["subscription"] = "free"
    u["paid_until"] = None
