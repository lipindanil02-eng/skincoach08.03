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
