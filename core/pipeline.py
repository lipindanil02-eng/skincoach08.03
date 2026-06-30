"""
SkinCoach 8-layer analysis pipeline.
Telegram-independent core logic extracted from bot.py.
"""
import json
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# ─── Config ────────────────────────────────────────────────────────────────
OR_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
VISION_M = os.getenv("VISION_MODEL", "openai/gpt-4o-mini").strip()
REASON_M = os.getenv("REASON_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
STRONG_M = os.getenv("STRONG_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
REASONER_A_M = os.getenv("REASONER_A_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
REASONER_B_M = os.getenv("REASONER_B_MODEL", "qwen/qwen3-next-80b-a3b-instruct:free").strip()
JUDGE_M = os.getenv("JUDGE_MODEL", "openai/gpt-oss-120b:free").strip()
VIS_FB = [m.strip() for m in os.getenv("VISION_FALLBACKS", "google/gemma-4-31b-it:free,google/gemma-4-26b-a4b-it:free").split(",") if m.strip()]
TXT_FB = [m.strip() for m in os.getenv("TEXT_FALLBACKS", "qwen/qwen3-next-80b-a3b-instruct:free,openai/gpt-oss-120b:free,nvidia/nemotron-3-super-120b-a12b:free").split(",") if m.strip()]
TEMP = float(os.getenv("TEMPERATURE", "0.3"))
TOUT = int(os.getenv("TIMEOUT", "120"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s|%(levelname)s|%(message)s")
log = logging.getLogger("skincoach.pipeline")

# ─── Project root ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ─── Constants ─────────────────────────────────────────────────────────────
WEEKS = {
    1: "ПИТАНИЕ — убираем провокаторы",
    2: "НАРУЖНЫЙ УХОД — мыло, масло, крем",
    3: "ЭМОЦИИ — стресс-протокол",
    4: "АНАЛИЗЫ — контроль и коррекция",
}
W_EMOJI = {1: "🥗", 2: "🧴", 3: "🧠", 4: "🔬"}
FOCUSES = {
    1: {1: "Список что ел за 3 дня", 2: "Исключи молочку", 3: "Убери сахар",
        4: "Добавь куркуму", 5: "8 стаканов воды", 6: "Анти-воспалительный смузи", 7: "Итог недели"},
    2: {1: "Серное мыло НЕ при остром", 2: "Тёплая вода до 37C", 3: "Крем с мочевиной на влажную кожу",
        4: "Масло точечно после крема", 5: "Серное мыло 1 раз если можно", 6: "Полная схема утро+вечер", 7: "Фото для сравнения"},
    3: {1: "Дыхание 4-7-8", 2: "3 ситуации обострения", 3: "Точечный массаж",
        4: "Аффирмация 10 раз", 5: "Мышечное расслабление", 6: "Письмо коже", 7: "Связь стресс-кожа?"},
    4: {1: "Запись: ОАК, D, ферритин, ТТГ", 2: "Копрограмма", 3: "Цинк и селен",
        4: "Расшифровка результатов", 5: "Коррекция добавок", 6: "Персональный протокол", 7: "Финальное фото"},
}

# ─── Helpers ───────────────────────────────────────────────────────────────
def rp(f: str, d: str = "") -> str:
    """Read prompt file from project root or prompts/ subdirectory."""
    for base in (PROJECT_ROOT, PROJECT_ROOT / "prompts"):
        p = base / f
        if p.exists():
            return p.read_text("utf-8").strip()
    return d


def cm(t: str) -> str:
    """Clean markdown formatting for Telegram-safe text."""
    t = t.replace("**", "").replace("__", "").replace("```", "").replace("`", "")
    return "\n".join(
        line.lstrip("#").strip() if line.lstrip().startswith("#") else line
        for line in t.split("\n")
    )


def xj(t: str):
    """Extract and parse JSON from model response."""
    t = t.strip()
    for prefix in ["```json", "```"]:
        if t.startswith(prefix):
            t = t[len(prefix):]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except Exception:
            pass
    raise ValueError(f"No JSON: {t[:300]}")


def score_bar(pct: int) -> str:
    filled = min(10, max(0, pct // 10))
    return "█" * filled + "░" * (10 - filled)


def score_grade(pct: int) -> str:
    if pct >= 90:
        return "Отличная"
    if pct >= 75:
        return "Хорошая"
    if pct >= 60:
        return "Средняя"
    if pct >= 45:
        return "Требует внимания"
    return "Нужна программа"


def format_fallback(recs: dict, reason: dict, triage: dict, u: dict) -> str:
    nm = u.get("name", "")
    dy = u.get("day", 1)
    wk = u.get("week", 1)
    parts = [f"🔍 {nm}, вот что я вижу:"]
    ds = recs.get("diagnosis_summary", "")
    if ds:
        parts.append(ds)
    hyps = reason.get("hypotheses", [])
    if hyps:
        for h in hyps[:3]:
            parts.append(f"  {h.get('diagnosis', '?')} — {h.get('probability', 0)}%")
    parts.append(f"\nДень {dy}/28 — Неделя {wk} {W_EMOJI.get(wk, '📋')}")
    mr = recs.get("morning_routine", [])
    if mr:
        parts.append("\n🧴 Утро:")
        parts.extend(f"  {x}" for x in mr[:3])
    er = recs.get("evening_routine", [])
    if er:
        parts.append("\n🌙 Вечер:")
        parts.extend(f"  {x}" for x in er[:3])
    ps = recs.get("psycho", {})
    af = ps.get("affirmation", "")
    if af:
        parts.append(f"\n💫 {af}")
    parts.append("\n📝 Вечером напиши: что сделал, как кожа, ощущения.")
    return "\n".join(parts)


# ─── API ───────────────────────────────────────────────────────────────────
def hdr() -> dict:
    return {
        "Authorization": f"Bearer {OR_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://t.me/skincoach_bot",
        "X-Title": "SkinCoach",
    }


async def call_raw(msgs, mdl, fb, mt=800):
    last_e = None
    async with httpx.AsyncClient(timeout=TOUT) as c:
        for m in [mdl] + fb:
            try:
                log.info(f"  -> {m}")
                r = await c.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=hdr(),
                    json={"model": m, "messages": msgs, "temperature": TEMP, "max_tokens": mt},
                )
                if r.status_code == 200:
                    d = r.json()
                    if "choices" in d and d["choices"]:
                        content = d["choices"][0]["message"].get("content") or ""
                        if isinstance(content, list):
                            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                        if not content.strip():
                            log.warning(f"  {m}: empty")
                            continue
                        if content.strip().upper().startswith("ERROR"):
                            log.warning(f"  {m}: error msg: {content[:100]}")
                            last_e = f"{m}:{content[:100]}"
                            continue
                        log.info(f"  OK: {m}")
                        return content
                log.warning(f"  {m}: {r.status_code}")
                last_e = f"{m}:{r.status_code}"
            except httpx.TimeoutException:
                log.warning(f"  {m}: timeout")
                last_e = f"{m}:timeout"
            except Exception as e:
                log.warning(f"  {m}: {e}")
                last_e = str(e)
    raise Exception(f"All down. {last_e}")


async def cj(msgs, mdl, fb, mt=800):
    return xj(await call_raw(msgs, mdl, fb, mt))


async def ct(msgs, mdl, fb, mt=800):
    return cm(await call_raw(msgs, mdl, fb, mt))


# ─── 8-STEP PIPELINE ───────────────────────────────────────────────────────
async def pipeline_photo(b64: str, cap: str, u: dict):
    """Steps 1-4: analyze photo and generate questions."""
    nm = u.get("name", "друг")
    dur = u.get("duration", "?")
    tri = u.get("tried", "?")
    uctx = f"Имя:{nm}, давность:{dur}, пробовали:{tri}"

    # STEP 1: Quality Check
    log.info("📸 1/8 Quality...")
    try:
        qp = rp("1_quality.txt", "Проверь качество фото. JSON.")
        q = await cj(
            [
                {"role": "system", "content": qp},
                {"role": "user", "content": [
                    {"type": "text", "text": "Оцени качество фото кожи"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]},
            ],
            VISION_M, VIS_FB, 300,
        )
        if not q.get("usable", True):
            return "ask_reshoot", q.get("suggestion", "Пересними при дневном свете, крупным планом.")
    except Exception as e:
        log.warning(f"Quality skip: {e}")

    # STEP 2: Vision Description
    log.info("👁 2/8 Vision...")
    vp = rp("2_vision.txt", "Опиши что видно на фото кожи. JSON.")
    try:
        vis = await cj(
            [
                {"role": "system", "content": vp},
                {"role": "user", "content": [
                    {"type": "text", "text": cap or "Опиши что видишь на коже"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]},
            ],
            VISION_M, VIS_FB, 500,
        )
    except Exception as e:
        log.error(f"Vision fail: {e}")
        return "error", "Не удалось проанализировать фото. Попробуй ещё раз."
    u["vision_data"] = vis

    # STEP 3a: Dermatology Reasoning (Reasoner A)
    log.info("🔬 3a/8 Reasoner A...")
    rp3 = rp("3_reasoning.txt", "Дифференциальная диагностика. JSON.")
    prev_diag = u.get("diagnosis")
    prev_conf = u.get("reasoning_data", {}).get("confidence") if u.get("reasoning_data") else None
    ctx3 = json.dumps(
        {"vision": vis, "patient": uctx,
         "previous_diagnosis": prev_diag if prev_diag else None,
         "previous_confidence": prev_conf},
        ensure_ascii=False,
    )
    try:
        reason_a = await cj(
            [{"role": "system", "content": rp3}, {"role": "user", "content": ctx3}],
            REASONER_A_M, TXT_FB, 600,
        )
    except Exception as e:
        log.error(f"Reasoner A fail: {e}")
        reason_a = {
            "hypotheses": [{"diagnosis": "требуется уточнение", "probability": 100, "reasoning": "не удалось провести анализ"}],
            "primary_diagnosis": "требуется уточнение", "stage": "unknown", "phase": "unknown",
            "severity": "unknown", "soap_safe": False, "confidence": 0,
        }
    u["reasoner_a"] = reason_a
    u["diagnosis"] = reason_a.get("primary_diagnosis", "не определено")

    # STEP 3b: Psychosomatic Reasoning (Reasoner B)
    log.info("🧠 3b/8 Reasoner B...")
    rp3b = rp("reasoner_b_prompt.txt", "Психосоматический анализ. JSON.")
    ctx3b = json.dumps({"vision": vis, "reasoner_a": reason_a, "patient": uctx}, ensure_ascii=False)
    try:
        reason_b = await cj(
            [{"role": "system", "content": rp3b}, {"role": "user", "content": ctx3b}],
            REASONER_B_M, TXT_FB, 500,
        )
    except Exception as e:
        log.error(f"Reasoner B fail: {e}")
        reason_b = {"emotional_factor": "не удалось определить", "psychosomatic_pattern": "нет данных",
                    "stress_level": "unknown", "recommendations": []}
    u["reasoner_b"] = reason_b

    # Объединяем результаты A + B для передачи дальше
    reason = reason_a  # совместимость со старыми шагами
    u["reasoning_data"] = reason

    # STEP 4: Clinical Questions
    log.info("❓ 4/8 Questions...")
    rp4 = rp("4_questions.txt", "Задай 1-2 вопроса. JSON.")
    ctx4 = json.dumps({"vision": vis, "reasoning": reason, "patient": uctx}, ensure_ascii=False)
    try:
        qs = await cj(
            [{"role": "system", "content": rp4}, {"role": "user", "content": ctx4}],
            REASON_M, TXT_FB, 400,
        )
    except Exception:
        qs = {"questions": [], "intro": f"{nm}, я проанализировал фото."}
    u["pending_questions"] = qs
    return "questions", qs


async def pipeline_final(u: dict, answers_text: str = ""):
    """Steps 5-8: after questions answered, generate final plan."""
    nm = u.get("name", "друг")
    dur = u.get("duration", "?")
    tri = u.get("tried", "?")
    vis = u.get("vision_data", {})
    reason = u.get("reasoning_data", {})
    dy = u.get("day", 1)
    wk = u.get("week", 1)
    wt = WEEKS.get(wk, "Программа")
    diw = ((dy - 1) % 7) + 1
    df = FOCUSES.get(wk, {}).get(diw, "Следуй программе")

    all_data = json.dumps(
        {"vision": vis, "reasoning": reason, "patient_answers": answers_text,
         "patient": f"Имя:{nm}, давность:{dur}, пробовали:{tri}",
         "day": dy, "week": wk, "week_theme": wt, "day_focus": df},
        ensure_ascii=False,
    )

    # STEP 5: Risk Triage
    log.info("⚠️ 5/8 Triage...")
    rp5 = rp("5_triage.txt", "Определи уровень риска. JSON.")
    try:
        triage = await cj(
            [{"role": "system", "content": rp5}, {"role": "user", "content": all_data}],
            REASON_M, TXT_FB, 300,
        )
    except Exception:
        triage = {"risk_level": "green", "urgency": "routine"}
    u["risk"] = triage

    # STEP 6: Recommendations
    log.info("📋 6/8 Recommendations...")
    rp6 = rp("6_recommendations.txt", "Составь рекомендации. JSON.")
    soap_note = ""
    if u.get("source") == "soap":
        soap_note = "\n\nВАЖНО: пользователь пришёл с упаковки мыла SkinCoach (сера+дёготь). Обязательно включи soap_protocol: конкретную схему применения мыла — сколько раз в день, как долго держать пену, чем увлажнять после, когда сделать паузу."
    ctx6 = json.dumps(
        {"all_data": json.loads(all_data) if isinstance(all_data, str) else all_data,
         "triage": triage, "soap_user": u.get("source") == "soap",
         "reasoner_b": u.get("reasoner_b", {})},
        ensure_ascii=False,
    ) + soap_note
    try:
        recs = await cj(
            [{"role": "system", "content": rp6}, {"role": "user", "content": ctx6}],
            REASONER_A_M, TXT_FB, 800,
        )
    except Exception as e:
        log.error(f"Recs fail: {e}")
        recs = {"diagnosis_summary": "Анализ выполнен", "morning_routine": ["Мягкое очищение"],
                "evening_routine": ["Увлажнение"], "day_focus": df}
    u["recommendations"] = recs

    # STEP 7: Safety Filter
    log.info("🛡️ 7/8 Safety...")
    rp7 = rp("7_safety.txt", "Проверь безопасность. JSON.")
    try:
        safety = await cj(
            [{"role": "system", "content": rp7},
             {"role": "user", "content": json.dumps({"recs": recs, "triage": triage, "reasoning": reason}, ensure_ascii=False)}],
            REASON_M, TXT_FB, 300,
        )
        if not safety.get("approved", True):
            log.warning(f"Safety issues: {safety.get('issues')}")
    except Exception:
        pass

    # STEP 8: Format Response
    log.info("💬 8/8 Response...")
    rp8 = rp("judge_prompt.txt", "Синтезируй ответ.")
    rp8 = rp8.replace("{name}", nm).replace("{day}", str(dy)).replace("{week}", str(wk))
    ctx8 = json.dumps(
        {"recommendations": recs, "triage": triage,
         "reasoner_a": u.get("reasoner_a", {}), "reasoner_b": u.get("reasoner_b", {}),
         "reasoning": reason, "vision": vis, "name": nm, "day": dy, "week": wk, "week_theme": wt,
         "soap_user": u.get("source") == "soap"},
        ensure_ascii=False,
    )
    try:
        final = await ct(
            [{"role": "system", "content": rp8}, {"role": "user", "content": ctx8}],
            JUDGE_M, TXT_FB, 900,
        )
    except Exception as e:
        log.error(f"Response fail: {e}")
        final = format_fallback(recs, reason, triage, u)
    return final
