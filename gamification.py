"""
gamification.py — Система очков, уровней, бейджей и стриков для SkinCoach
Octalysis-based motivation framework
"""
from datetime import datetime, date, timezone

# ─── Уровни ────────────────────────────────────────────────────────────────

LEVELS = [
    {"level": 1, "min_points": 0,   "name": "🌱 Новичок",      "bonus": None},
    {"level": 2, "min_points": 100, "name": "🌿 Практик",      "bonus": "+3 дня подписки"},
    {"level": 3, "min_points": 300, "name": "🌟 Знаток",       "bonus": "Бонус-протокол «Питание»"},
    {"level": 4, "min_points": 600, "name": "💎 Мастер кожи",  "bonus": "Протокол «Детокс» + скидка 20%"},
]

# ─── Бейджи ────────────────────────────────────────────────────────────────

BADGES = {
    "first_photo":   {"emoji": "📸", "name": "Первый шаг",    "desc": "Первый анализ фото"},
    "streak_7":      {"emoji": "🔥", "name": "Неделя огня",   "desc": "7 дней подряд"},
    "streak_14":     {"emoji": "🔥🔥","name": "Две недели",   "desc": "14 дней подряд"},
    "program_done":  {"emoji": "💎", "name": "Мастер кожи",   "desc": "Пройти все 28 дней"},
    "group_member":  {"emoji": "👥", "name": "Свой человек",  "desc": "Вступить в группу"},
    "mentor":        {"emoji": "🤝", "name": "Наставник",     "desc": "Привести 3 друзей"},
    "detailed_7":    {"emoji": "📝", "name": "Дотошный",      "desc": "7 развёрнутых ответов подряд"},
}

# ─── Очки ──────────────────────────────────────────────────────────────────

POINTS = {
    "first_photo": 50,
    "daily_next": 10,
    "streak_7": 100,
    "streak_14": 200,
    "program_done": 500,
    "group_join": 50,
    "referral": 100,
    "detailed_answer": 15,
    "quality_report": 10,
}

# ─── Helpers ───────────────────────────────────────────────────────────────

def _today() -> str:
    """UTC date string YYYY-MM-DD."""
    return datetime.utcnow().date().isoformat()


def get_weekly_key() -> str:
    """Return ISO 8601 week key, e.g. '2026-W11'. Always UTC."""
    return datetime.utcnow().strftime("%G-W%V")


def can_compete_today(u: dict) -> bool:
    """Return True if user already submitted a verified competition photo today (UTC)."""
    compete_date = u.get("compete_date")
    if compete_date is None:
        return False
    return compete_date == datetime.utcnow().date().isoformat()

def ensure_fields(u: dict) -> dict:
    """Добавить недостающие поля геймификации к существующему юзеру."""
    defaults = {
        "points": 0,
        "streak": 0,
        "last_activity_date": None,
        "badges": [],
        "level": 1,
        "group_member": False,
        "group_bonus_claimed": False,
        "quality_bonus_today": False,
        "detailed_streak": 0,
        "skin_score_last": None,
        "skin_score_components": None,
        "skin_score_history": [],
        "best_score_natural": None,
        "best_score_makeup": None,
        "compete_date": None,
        "challenge_code": None,
        "challenge_date": None,
        "compete_retry_count": 0,
    }
    for k, v in defaults.items():
        if k not in u:
            u[k] = v
    return u

def get_level(points: int) -> dict:
    """Вернуть текущий уровень по очкам."""
    current = LEVELS[0]
    for lvl in LEVELS:
        if points >= lvl["min_points"]:
            current = lvl
    return current

def next_level(points: int) -> dict | None:
    """Вернуть следующий уровень или None если максимальный."""
    for lvl in LEVELS:
        if points < lvl["min_points"]:
            return lvl
    return None

# ─── Основные функции ──────────────────────────────────────────────────────

def add_points(u: dict, amount: int, reason: str = "") -> tuple[dict, list[str]]:
    """
    Начислить очки. Возвращает (обновлённый u, список уведомлений).
    Уведомления — строки для отправки пользователю.
    """
    u = ensure_fields(u)
    old_level = get_level(u["points"])
    u["points"] += amount
    new_level = get_level(u["points"])

    notifications = []

    # Уровень вырос?
    if new_level["level"] > old_level["level"]:
        msg = f"\n🎉 Новый уровень: {new_level['name']}!"
        if new_level["bonus"]:
            msg += f"\nБонус: {new_level['bonus']}"
        notifications.append(msg)
        u["level"] = new_level["level"]

    return u, notifications

def award_badge(u: dict, badge_id: str) -> tuple[dict, str | None]:
    """
    Выдать бейдж если ещё не выдан. Возвращает (u, сообщение или None).
    """
    u = ensure_fields(u)
    if badge_id in u["badges"]:
        return u, None
    if badge_id not in BADGES:
        return u, None
    u["badges"].append(badge_id)
    b = BADGES[badge_id]
    return u, f"\n🏆 Новый бейдж: {b['emoji']} {b['name']} — {b['desc']}"

def update_streak(u: dict) -> tuple[dict, list[str]]:
    """
    Обновить стрик. Вызывать при каждом /next.
    Возвращает (u, список уведомлений).
    """
    u = ensure_fields(u)
    today = _today()
    notifications = []

    if u["last_activity_date"] is None:
        u["streak"] = 1
    else:
        last = date.fromisoformat(u["last_activity_date"])
        delta = (date.today() - last).days
        if delta == 1:
            u["streak"] += 1
        elif delta == 0:
            pass  # уже сегодня
        else:
            u["streak"] = 1  # стрик сломан

    u["last_activity_date"] = today

    # Бонус за стрик 7
    if u["streak"] == 7:
        u, pts_notifs = add_points(u, POINTS["streak_7"])
        notifications.extend(pts_notifs)
        u, badge_msg = award_badge(u, "streak_7")
        if badge_msg:
            notifications.append(badge_msg)
        notifications.append(f"\n🔥 Стрик 7 дней! +{POINTS['streak_7']} очков")

    # Бонус за стрик 14
    if u["streak"] == 14:
        u, pts_notifs = add_points(u, POINTS["streak_14"])
        notifications.extend(pts_notifs)
        u, badge_msg = award_badge(u, "streak_14")
        if badge_msg:
            notifications.append(badge_msg)
        notifications.append(f"\n🔥🔥 Стрик 14 дней! +{POINTS['streak_14']} очков")

    return u, notifications

def on_first_photo(u: dict) -> tuple[dict, list[str]]:
    """Вызвать при первом анализе фото."""
    u = ensure_fields(u)
    notifications = []
    if "first_photo" not in u["badges"]:
        u, pts_notifs = add_points(u, POINTS["first_photo"])
        notifications.extend(pts_notifs)
        u, badge_msg = award_badge(u, "first_photo")
        if badge_msg:
            notifications.append(badge_msg)
        notifications.append(f"\n+{POINTS['first_photo']} очков за первый анализ!")
    return u, notifications

def on_detailed_answer(u: dict, text_length: int) -> tuple[dict, list[str]]:
    """
    Вызвать когда пользователь даёт развёрнутый ответ.
    text_length — длина ответа в символах.
    """
    u = ensure_fields(u)
    notifications = []
    today = _today()

    threshold = 40
    if text_length < threshold:
        return u, notifications

    # Не более одного бонуса в день
    if u.get("quality_bonus_date") == today:
        return u, notifications

    u["quality_bonus_date"] = today
    u, pts_notifs = add_points(u, POINTS["detailed_answer"])
    notifications.extend(pts_notifs)
    notifications.append(f"+{POINTS['detailed_answer']} очков за детальный ответ 📝")

    # Счётчик детальных ответов для бейджа
    u["detailed_streak"] = u.get("detailed_streak", 0) + 1
    if u["detailed_streak"] >= 7:
        u, badge_msg = award_badge(u, "detailed_7")
        if badge_msg:
            notifications.append(badge_msg)

    return u, notifications

def on_program_complete(u: dict) -> tuple[dict, list[str]]:
    """Вызвать когда пользователь завершил 28 дней."""
    u = ensure_fields(u)
    notifications = []
    u, pts_notifs = add_points(u, POINTS["program_done"])
    notifications.extend(pts_notifs)
    u, badge_msg = award_badge(u, "program_done")
    if badge_msg:
        notifications.append(badge_msg)
    notifications.append(f"🎊 +{POINTS['program_done']} очков за завершение программы!")
    return u, notifications

def on_referral_success(u: dict) -> tuple[dict, list[str]]:
    """Вызвать когда друг зарегистрировался по реф-ссылке."""
    u = ensure_fields(u)
    notifications = []
    u, pts_notifs = add_points(u, POINTS["referral"])
    notifications.extend(pts_notifs)
    notifications.append(f"🤝 Друг присоединился! +{POINTS['referral']} очков")

    ref_count = u.get("ref_count", 0)
    if ref_count >= 3:
        u, badge_msg = award_badge(u, "mentor")
        if badge_msg:
            notifications.append(badge_msg)

    return u, notifications

def format_achievements(u: dict) -> str:
    """Сформировать текст для команды /achievements."""
    u = ensure_fields(u)
    lvl = get_level(u["points"])
    nxt = next_level(u["points"])

    lines = [
        f"🏆 Твои достижения",
        f"",
        f"{lvl['name']}",
        f"⭐ Очки: {u['points']}",
        f"🔥 Стрик: {u['streak']} дн.",
        f"📅 День программы: {u.get('day', 0)}/28",
    ]

    if nxt:
        needed = nxt["min_points"] - u["points"]
        lines.append(f"➡️ До уровня {nxt['name']}: {needed} очков")

    badges = u.get("badges", [])
    if badges:
        lines.append("")
        lines.append("🎖 Бейджи:")
        for bid in badges:
            if bid in BADGES:
                b = BADGES[bid]
                lines.append(f"  {b['emoji']} {b['name']}")
    else:
        lines.append("")
        lines.append("Бейджей пока нет — отправь фото для первого! 📸")

    return "\n".join(lines)

def format_leaderboard(all_users: dict) -> str:
    """
    Сформировать топ-10 по стрику.
    all_users — dict {uid: user_data}
    """
    scored = []
    for uid, u in all_users.items():
        if u.get("state") == "active" or u.get("day", 0) > 0:
            scored.append((u.get("streak", 0), u.get("name", "Аноним"), u.get("points", 0)))

    scored.sort(reverse=True)
    top = scored[:10]

    if not top:
        return "📊 Рейтинг пока пуст — начни программу первым!"

    lines = ["📊 Топ-10 по стрику:"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (streak, name, pts) in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} {name} — 🔥{streak} дн. / ⭐{pts} очков")

    return "\n".join(lines)


def on_regular_photo_score(u: dict, score_components: dict, has_makeup: bool) -> dict:
    """Called after every photo analysis. Stores unverified skin score entry."""
    u = ensure_fields(u)
    total = score_components.get("total") if score_components else None
    if total is None:
        return u
    u["skin_score_last"] = total
    u["skin_score_components"] = score_components
    entry = {"date": _today(), "score": total, "has_makeup": has_makeup, "verified": False, "components": score_components}
    u["skin_score_history"].append(entry)
    if len(u["skin_score_history"]) > 30:
        u["skin_score_history"] = u["skin_score_history"][-30:]
    return u


def on_compete_photo(u: dict, score_components: dict, has_makeup: bool) -> dict:
    """Called after a verified competition photo. Stores verified entry, updates best scores."""
    u = ensure_fields(u)
    total = score_components.get("total") if score_components else None
    if total is None:
        return u
    u["skin_score_last"] = total
    u["skin_score_components"] = score_components
    u["compete_date"] = datetime.utcnow().date().isoformat()
    entry = {"date": _today(), "score": total, "has_makeup": has_makeup, "verified": True, "components": score_components}
    u["skin_score_history"].append(entry)
    if len(u["skin_score_history"]) > 30:
        u["skin_score_history"] = u["skin_score_history"][-30:]
    if has_makeup:
        if u["best_score_makeup"] is None or total > u["best_score_makeup"]:
            u["best_score_makeup"] = total
    else:
        if u["best_score_natural"] is None or total > u["best_score_natural"]:
            u["best_score_natural"] = total
    return u


def format_skinrank(all_users: dict, viewer_uid: str) -> str:
    """Format /skinrank leaderboard: 4 sections (natural/makeup × week/alltime)."""
    current_week = get_weekly_key()
    medals = ["🥇", "🥈", "🥉"]

    week_natural = {}
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
            edate = entry.get("date", "")
            makeup = entry.get("has_makeup", False)
            try:
                entry_week = date.fromisoformat(edate).strftime("%G-W%V")
            except Exception:
                entry_week = ""
            if makeup:
                if _better(alltime_makeup.get(uid), score, edate):
                    alltime_makeup[uid] = (score, edate, name)
                if entry_week == current_week and _better(week_makeup.get(uid), score, edate):
                    week_makeup[uid] = (score, edate, name)
            else:
                if _better(alltime_natural.get(uid), score, edate):
                    alltime_natural[uid] = (score, edate, name)
                if entry_week == current_week and _better(week_natural.get(uid), score, edate):
                    week_natural[uid] = (score, edate, name)

    def _render_top(data: dict, label: str) -> list:
        top = sorted(data.values(), key=lambda x: (-x[0], x[1]))[:10]
        if not top:
            return [f"{label}: пока нет участников"]
        lines = [f"{label}:"]
        for i, (score, _, name) in enumerate(top):
            medal = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"{medal} {name} — {score}%")
        return lines

    viewer = all_users.get(str(viewer_uid), {})
    has_any = any([week_natural, week_makeup, alltime_natural, alltime_makeup])
    if not has_any:
        best_nat = viewer.get("best_score_natural")
        best_mak = viewer.get("best_score_makeup")
        if best_nat is not None or best_mak is not None:
            nat_str = str(best_nat) if best_nat is not None else "—"
            mak_str = str(best_mak) if best_mak is not None else "—"
            return (f"🏆 Рейтинг кожи пока пуст — стань первым!\n\n"
                    f"Твой лучший: {nat_str} (без макияжа) | {mak_str} (с макияжем)\n"
                    "📸 /compete — участвовать сегодня")
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
