"""
SkinCoach v6 — 2 reasoner + judge + 28-дневная программа "Чистая кожа"
Архитектура:
  Фото → Vision → Reasoner A (дерматолог) || Reasoner B (кинезиолог) → Judge → План на день
  Текст → Chat с полным контекстом пользователя
"""
import asyncio, json, os, sys, base64, logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

load_dotenv()

# ── КОНФИГ ──
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OR_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
VISION_M = os.getenv("VISION_MODEL", "nvidia/nemotron-nano-12b-v2-vl:free")
REASON_A = os.getenv("REASONER_A_MODEL", "arcee-ai/trinity-large-preview:free")
REASON_B = os.getenv("REASONER_B_MODEL", "stepfun/step-3.5-flash:free")
JUDGE_M = os.getenv("JUDGE_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free")
CHAT_M = os.getenv("CHAT_MODEL", "arcee-ai/trinity-large-preview:free")
V_FALL = [m.strip() for m in os.getenv("VISION_FALLBACKS", "google/gemma-3-27b-it:free,google/gemma-3-12b-it:free").split(",") if m.strip()]
T_FALL = [m.strip() for m in os.getenv("TEXT_FALLBACKS", "meta-llama/llama-3.3-70b-instruct:free,stepfun/step-3.5-flash:free,google/gemma-3-4b-it:free").split(",") if m.strip()]
MAX_TOK = int(os.getenv("MAX_TOKENS", "800"))
TEMP = float(os.getenv("TEMPERATURE", "0.3"))
TOUT = int(os.getenv("TIMEOUT", "120"))
HIST_FILE = "history.json"
MAX_HIST = 30
TG_MAX = 4000

logging.basicConfig(level=logging.INFO, format="%(asctime)s|%(levelname)s|%(message)s")
log = logging.getLogger("skincoach")

# ── СОСТОЯНИЯ ──
S_NAME = "ask_name"
S_PROBLEM = "ask_problem"
S_DURATION = "ask_duration"
S_TRIED = "ask_tried"
S_PHOTO = "ask_photo"
S_ACTIVE = "active"

WEEKS = {
    1: "Питание и триггеры",
    2: "Наружный уход",
    3: "Эмоциональная устойчивость",
    4: "Контроль и коррекция",
}

FOCUSES = {
    1: {1: "Запиши всё что ел за 3 дня — ищем провокаторы",
        2: "Исключи молочку. Замени на растительное молоко",
        3: "Убери сахар и белый хлеб",
        4: "Добавь куркуму с чёрным перцем в еду",
        5: "8 стаканов воды сегодня. Считай",
        6: "Анти-воспалительный смузи: шпинат+банан+имбирь+куркума",
        7: "Итог недели. Что изменилось в коже?"},
    2: {1: "Серное мыло НЕ при остром воспалении",
        2: "Тёплая вода до 37C. Промакивай, не три",
        3: "Крем с мочевиной 3-5% на влажную кожу после умывания",
        4: "Масло жожоба/облепиховое точечно на бляшки после крема",
        5: "Если этап позволяет — серное мыло 1 раз, наблюдай 24ч",
        6: "Полная схема утро+вечер. Запиши",
        7: "Сравни кожу с фото 7 дней назад. Отправь новое фото"},
    3: {1: "Дыхание 4-7-8: вдох 4, задержка 7, выдох 8. 5 минут утром",
        2: "Запиши 3 ситуации обострения — что было в жизни?",
        3: "Точечный массаж: виски + между бровями по 30 сек",
        4: "Аффирмация 10 раз утром вслух",
        5: "Прогрессивное мышечное расслабление 10 мин вечером",
        6: "Напиши письмо своей коже",
        7: "Итог: связь стресса и кожи?"},
    4: {1: "Запишись: ОАК, витамин D, ферритин, ТТГ",
        2: "Копрограмма — состояние кишечника",
        3: "Цинк и селен — критичны для кожи",
        4: "Результаты — отправь фото, помогу расшифровать",
        5: "Скорректируй добавки по анализам",
        6: "Составь свой протокол из всего что узнал",
        7: "Финальное фото для сравнения с первым днём"},
}

# ── УТИЛИТЫ ──
def read_prompt(f, d=""):
    p = Path(f)
    return p.read_text(encoding="utf-8").strip() if p.exists() else d

def clean_md(t):
    t = t.replace("**","").replace("__","").replace("```","").replace("`","")
    return "\n".join(l.lstrip("#").strip() if l.lstrip().startswith("#") else l for l in t.split("\n"))

def extract_json(t):
    t = t.strip()
    if t.startswith("```"): t = t.split("\n",1)[-1]
    if t.endswith("```"): t = t.rsplit("```",1)[0]
    t = t.strip()
    try: return json.loads(t)
    except: pass
    s, e = t.find("{"), t.rfind("}")
    if s!=-1 and e>s:
        try: return json.loads(t[s:e+1])
        except: pass
    raise ValueError(f"No JSON: {t[:200]}")

# ── ИСТОРИЯ ──
def load_h():
    if os.path.exists(HIST_FILE):
        try:
            with open(HIST_FILE,"r",encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def save_h(h):
    try:
        with open(HIST_FILE,"w",encoding="utf-8") as f: json.dump(h,f,ensure_ascii=False,indent=2)
    except IOError as e: log.error(f"Save: {e}")

def get_u(h, uid):
    uid = str(uid)
    if uid not in h:
        h[uid] = {"state":S_NAME,"name":None,"problem":None,"duration":None,"tried":None,
                   "vision":None,"analysis":None,"day":0,"week":1,"messages":[],
                   "start":None,"created":datetime.now().isoformat()}
    return h[uid]

def trim(m): return m[-MAX_HIST:] if len(m)>MAX_HIST else m

def ctx(u):
    last = u["messages"][-4:] if u["messages"] else []
    if not last: return ""
    return "Контекст:\n"+"\n".join(f"{'Человек' if m['role']=='user' else 'Коуч'}: {(m['content'] if isinstance(m['content'],str) else str(m['content']))[:150]}" for m in last)

# ── API ──
def headers():
    return {"Authorization":f"Bearer {OR_KEY}","Content-Type":"application/json",
            "HTTP-Referer":"https://t.me/skincoach_bot","X-Title":"SkinCoach"}

async def call_raw(msgs, model, falls, mt=MAX_TOK, to=TOUT):
    err = None
    async with httpx.AsyncClient(timeout=to) as c:
        for m in [model]+falls:
            try:
                log.info(f"  -> {m}")
                r = await c.post("https://openrouter.ai/api/v1/chat/completions",
                    headers=headers(), json={"model":m,"messages":msgs,"temperature":TEMP,"max_tokens":mt})
                if r.status_code==200:
                    d = r.json()
                    if "choices" in d and d["choices"]:
                        ct = d["choices"][0]["message"].get("content") or ""
                if isinstance(ct,list): ct="".join(p.get("text","") for p in ct if isinstance(p,dict))
                if not ct.strip():
                    log.warning(f"  {m}: пустой ответ, пробую следующую")
                    continue
                log.info(f"  OK: {m}")
                return ct
                log.warning(f"  {m}: {r.status_code}")
                err = f"{m}:{r.status_code}"
            except httpx.TimeoutException: log.warning(f"  {m}: timeout"); err=f"{m}:timeout"
            except Exception as e: log.warning(f"  {m}: {e}"); err=str(e)
    raise Exception(f"All models down. {err}")

async def call_json(msgs, model, falls, mt=MAX_TOK):
    return extract_json(await call_raw(msgs, model, falls, mt))

async def call_text(msgs, model, falls, mt=MAX_TOK):
    return clean_md(await call_raw(msgs, model, falls, mt))

# ── КОНСИЛИУМ ──
async def consilium(photo_b64, caption, u):
    name = u.get("name","")
    problem = u.get("problem","кожная проблема")
    duration = u.get("duration","?")
    tried = u.get("tried","?")
    day, week = u.get("day",1), u.get("week",1)
    wt = WEEKS.get(week,"Программа")
    diw = ((day-1)%7)+1
    focus = FOCUSES.get(week,{}).get(diw,"Следуй программе")
    uctx = f"Имя:{name}, проблема:{problem}, давность:{duration}, пробовали:{tried}, день:{day}/28, неделя:{week}, тема:{wt}"

    # 1. VISION
    log.info("👁 1/4 Vision...")
    vp = read_prompt("vision_prompt.txt","Проанализируй фото кожи. Верни JSON.")
    vm = [{"role":"system","content":vp+f"\n\nДанные: {uctx}"},
          {"role":"user","content":[{"type":"text","text":caption or "Проанализируй фото кожи."},
           {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{photo_b64}"}}]}]
    try:
        vis = await call_json(vm, VISION_M, V_FALL, 400)
    except Exception as e:
        log.error(f"Vision fail: {e}")
        return f"Не удалось проанализировать фото. Попробуй переснять при дневном свете и отправить ещё раз."
    u["vision"] = vis

    # Проверка качества фото
    if vis.get("photo_quality") == "poor":
        return f"{name}, фото получилось нечётким. Пересними при дневном свете, крупным планом, без вспышки. Так анализ будет точнее."

    jctx = json.dumps({"user":uctx,"vision":vis,"day_focus":focus}, ensure_ascii=False)

    # 2. REASONER A (дерматолог)
    log.info("🧴 2/4 Reasoner A...")
    rap = read_prompt("reasoner_a_prompt.txt","Составь план ухода. Верни JSON.")
    ram = [{"role":"system","content":rap},{"role":"user","content":jctx}]
    try: ra = await call_json(ram, REASON_A, T_FALL, 500)
    except: ra = {"summary":"Анализ недоступен","care_morning":[],"care_evening":[],"confidence":0}

    # 3. REASONER B (кинезиолог)
    log.info("🧠 3/4 Reasoner B...")
    rbp = read_prompt("reasoner_b_prompt.txt","Составь план. Верни JSON.")
    rbm = [{"role":"system","content":rbp},{"role":"user","content":jctx}]
    try: rb = await call_json(rbm, REASON_B, T_FALL, 500)
    except: rb = {"psycho_summary":"Анализ недоступен","affirmation":"","confidence":0}

    # 4. JUDGE
    log.info("📋 4/4 Judge...")
    jp = read_prompt("judge_prompt.txt","Объедини A и B. Верни JSON.")
    jdata = json.dumps({"user":uctx,"vision":vis,"answer_a":ra,"answer_b":rb,
        "day":day,"week":week,"week_theme":wt,"day_focus":focus,"name":name}, ensure_ascii=False)
    jm = [{"role":"system","content":jp},{"role":"user","content":jdata}]
    try:
        jr = await call_json(jm, JUDGE_M, T_FALL, 800)
        final = jr.get("final_answer","")
        if not final: final = fallback_fmt(vis, ra, rb, u)
    except:
        final = fallback_fmt(vis, ra, rb, u)

    u["analysis"] = final
    return clean_md(final)

def fallback_fmt(v, a, b, u):
    name, day, week = u.get("name",""), u.get("day",1), u.get("week",1)
    we = {1:"🥗",2:"🧴",3:"🧠",4:"🔬"}.get(week,"📋")
    p = [f"День {day}/28 — Неделя {week} {we}\n"]
    s = a.get("summary","")
    if s: p.append(f"{name}, {s}\n")
    cm = a.get("care_morning",[])
    if cm: p.append("🧴 Утро:"); p.extend(f"  {x}" for x in cm[:3]); p.append("")
    ce = a.get("care_evening",[])
    if ce: p.append("🌙 Вечер:"); p.extend(f"  {x}" for x in ce[:3]); p.append("")
    nr = a.get("nutrition_remove",[])
    na = a.get("nutrition_add",[])
    if nr or na:
        p.append("🥗 Питание:")
        if nr: p.append(f"  Убрать: {', '.join(nr[:3])}")
        if na: p.append(f"  Добавить: {', '.join(na[:3])}")
        p.append("")
    mp = b.get("morning_practice","")
    ep = b.get("evening_practice","")
    if mp or ep:
        p.append("🧠 Практики:")
        if mp: p.append(f"  Утро: {mp}")
        if ep: p.append(f"  Вечер: {ep}")
        p.append("")
    af = b.get("affirmation","")
    if af: p.append(f"💫 {af}\n")
    da = a.get("day_action","")
    if da: p.append(f"🎯 Фокус: {da}\n")
    sm = b.get("support_message","")
    if sm: p.append(f"💚 {sm}\n")
    p.append("📝 Вечером напиши: что сделал, как кожа, ощущения.")
    return "\n".join(p)

# ── ПРОМПТ ЧАТА ──
CHAT_P = """Ты — SkinCoach, уверенный AI-специалист по сопровождению людей с кожными проблемами.
Работаешь как персональный цифровой помощник: спокойно, чётко, без воды, с экспертностью.

Данные человека:
Имя: {name} | Проблема: {problem} | Давность: {duration} | Пробовали: {tried}
Анализ: {analysis}
День: {day}/28 | Неделя: {week}/4 — {wt}

Программа "Чистая кожа":
Н1: питание, триггеры | Н2: наружный уход | Н3: эмоции, стресс | Н4: анализы, контроль

Правила:
- Обращайся по имени ({name})
- Уверенно, спокойно, конкретно
- НЕ звёздочки, НЕ markdown
- До 1200 символов
- НЕ дисклеймеры
- Отчёт → похвали + коррекция + аффирмация + задание на завтра
- Вопрос → в контексте дня и недели
- Формат: поддержка → что вижу → что делать → следующий вопрос
- Задавай по одному вопросу
- Помни прошлые ответы
- Отвечай на языке пользователя"""

NEXT_P = """Ты — SkinCoach. День {day}/28, неделя {week} — {wt}.
Данные: {name}, проблема: {problem}, давность: {duration}, пробовали: {tried}
Анализ: {analysis}
Фокус дня: {focus}
{context}

Составь план на день. Формат (эмодзи, НЕ звёздочки):

День {day}/28 — Неделя {week} {we}

(по имени + 1 предложение)

🧴 Утро: (2-3 действия)
☀️ День: (1-2 напоминания)
🌙 Вечер: (2-3 действия)
🎯 Фокус: {focus}
💫 Аффирмация (уникальная)
📝 Вечером напиши отчёт."""

# ── ОТПРАВКА ──
async def send(msg, text):
    if len(text) <= TG_MAX: await msg.reply_text(text); return
    parts, cur = [], ""
    for ln in text.split("\n"):
        if len(cur)+len(ln)+1 > TG_MAX:
            if cur: parts.append(cur)
            cur = ln
        else: cur = cur+"\n"+ln if cur else ln
    if cur: parts.append(cur)
    for p in parts: await msg.reply_text(p)

# ── ОБРАБОТЧИКИ ──
async def cmd_start(upd: Update, ctx: ContextTypes.DEFAULT_TYPE):
    h = load_h(); uid = str(upd.effective_user.id)
    h[uid] = {"state":S_NAME,"name":None,"problem":None,"duration":None,"tried":None,
              "vision":None,"analysis":None,"day":0,"week":1,"messages":[],
              "start":None,"created":datetime.now().isoformat()}
    save_h(h)
    await upd.message.reply_text(
        "Привет. Я SkinCoach — твой персональный помощник по программе 'Чистая кожа'.\n\n"
        "Я помогу тебе понять, что влияет на состояние кожи, "
        "выстроить уход и пройти маршрут шаг за шагом.\n\n"
        "Каждое фото анализирует консилиум:\n"
        "  👁 Дерматолог-диагност\n"
        "  🧴 Специалист по уходу и питанию\n"
        "  🧠 Кинезиолог-психосоматик\n"
        "  📋 Синтезатор — собирает лучшее решение\n\n"
        "Для начала: как тебя зовут?")

async def handle_text(upd: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = upd.effective_user.id; txt = upd.message.text
    h = load_h(); u = get_u(h, uid)
    await upd.message.chat.send_action(ChatAction.TYPING)

    if u["state"] == S_NAME:
        u["name"] = txt.strip(); u["state"] = S_PROBLEM; save_h(h)
        await upd.message.reply_text(f"Рад знакомству, {u['name']}.\n\nКакая у тебя проблема с кожей?\nПсориаз, дерматит, экзема, себорея — или опиши своими словами.")
        return

    if u["state"] == S_PROBLEM:
        u["problem"] = txt.strip(); u["state"] = S_DURATION; save_h(h)
        await upd.message.reply_text("Как давно это тебя беспокоит?\nНапример: 2 года, с детства, полгода...")
        return

    if u["state"] == S_DURATION:
        u["duration"] = txt.strip(); u["state"] = S_TRIED; save_h(h)
        await upd.message.reply_text("Что уже пробовал(а)?\nГормональные мази, диеты, народные средства, фототерапия — всё что помнишь.")
        return

    if u["state"] == S_TRIED:
        u["tried"] = txt.strip(); u["state"] = S_PHOTO; save_h(h)
        await upd.message.reply_text(
            f"Понял, {u['name']}. Теперь самое важное.\n\n"
            "📸 Отправь фото проблемного участка кожи.\n\n"
            "Консилиум определит:\n"
            "  — тип и стадию\n"
            "  — этап обострения\n"
            "  — можно ли серное/дегтярное мыло\n"
            "  — персональный план на День 1\n\n"
            "Лучше при дневном свете, крупным планом.")
        return

    if u["state"] == S_PHOTO:
        await upd.message.reply_text(f"{u.get('name','')}, мне нужно фото чтобы запустить консилиум.\n📸 Отправь фото проблемного участка.")
        return

    if u["state"] == S_ACTIVE:
        u["messages"].append({"role":"user","content":txt})
        u["messages"] = trim(u["messages"])
        wt = WEEKS.get(u["week"],"Программа")
        an = (u.get("analysis") or "нет")[:300]
        pr = CHAT_P.format(name=u.get("name",""), problem=u.get("problem",""),
            duration=u.get("duration","?"), tried=u.get("tried","?"),
            analysis=an, day=u["day"], week=u["week"], wt=wt)
        msgs = [{"role":"system","content":pr}] + u["messages"]
        try: reply = await call_text(msgs, CHAT_M, T_FALL, 600)
        except Exception as e: reply = "Модели заняты. Напиши через пару минут."; log.error(f"Chat: {e}")
        u["messages"].append({"role":"assistant","content":reply})
        u["messages"] = trim(u["messages"]); save_h(h)
        await send(upd.message, reply); return

    u["state"] = S_NAME; save_h(h)
    await upd.message.reply_text("Давай начнём. Как тебя зовут?")

async def handle_photo(upd: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = upd.effective_user.id; h = load_h(); u = get_u(h, uid)
    if u["state"] in (S_NAME, S_PROBLEM, S_DURATION, S_TRIED):
        await upd.message.reply_text("Сначала познакомимся! Напиши /start"); return

    st = await upd.message.reply_text(
        "📸 Фото получено! Запускаю консилиум...\n\n"
        "👁 Дерматолог анализирует...\n"
        "🧴 Специалист подбирает уход...\n"
        "🧠 Кинезиолог оценивает...\n"
        "📋 Синтезатор собирает план...\n\n"
        "30-90 секунд ⏳")
    await upd.message.chat.send_action(ChatAction.TYPING)

    ph = upd.message.photo[-1]; f = await c.bot.get_file(ph.file_id)
    pb = await f.download_as_bytearray(); b64 = base64.b64encode(pb).decode()
    cap = (upd.message.caption or "").strip()

    if u["state"]==S_PHOTO or u["day"]==0:
        u["state"]=S_ACTIVE; u["day"]=1; u["week"]=1; u["start"]=datetime.now().isoformat()

    try: reply = await consilium(b64, cap, u)
    except Exception as e: reply="Ошибка. Попробуй через минуту."; log.error(f"Photo: {e}")

    u["messages"].append({"role":"user","content":f"[фото] {cap}"})
    u["messages"].append({"role":"assistant","content":reply})
    u["messages"]=trim(u["messages"]); save_h(h)
    try: await st.delete()
    except: pass
    await send(upd.message, reply)

async def cmd_next(upd: Update, c: ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id; h=load_h(); u=get_u(h,uid)
    if u["state"]!=S_ACTIVE: await upd.message.reply_text("Напиши /start"); return
    await upd.message.chat.send_action(ChatAction.TYPING)
    u["day"]+=1
    if u["day"]>28:
        await upd.message.reply_text(f"🎉 {u.get('name','')}, программа пройдена!\nОтправь свежее фото — сравним с первым днём.")
        save_h(h); return
    u["week"]=((u["day"]-1)//7)+1
    wt=WEEKS.get(u["week"],"Программа")
    we={1:"🥗",2:"🧴",3:"🧠",4:"🔬"}.get(u["week"],"📋")
    diw=((u["day"]-1)%7)+1; focus=FOCUSES.get(u["week"],{}).get(diw,"Следуй программе")
    an=(u.get("analysis") or "нет")[:300]
    pr=NEXT_P.format(day=u["day"],week=u["week"],wt=wt,we=we,
        name=u.get("name",""),problem=u.get("problem",""),
        duration=u.get("duration","?"),tried=u.get("tried","?"),
        analysis=an,focus=focus,context=ctx(u))
    msgs=[{"role":"system","content":pr},{"role":"user","content":f"План на день {u['day']}."}]
    try: plan=await call_text(msgs,CHAT_M,T_FALL,600)
    except: plan="Попробуй /next через минуту."
    u["messages"].append({"role":"assistant","content":plan})
    u["messages"]=trim(u["messages"]); save_h(h)
    await send(upd.message, plan)

async def cmd_status(upd: Update, c: ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id; h=load_h(); u=get_u(h,uid)
    if u["state"]!=S_ACTIVE: await upd.message.reply_text("/start"); return
    wt=WEEKS.get(u["week"],"Программа"); pct=int((u["day"]/28)*100)
    bar="▓"*(pct//10)+"░"*(10-pct//10)
    await upd.message.reply_text(
        f"📊 {u.get('name','')}, прогресс:\n\nДень: {u['day']}/28\n"
        f"Неделя: {u['week']}/4 — {wt}\n[{bar}] {pct}%\n\n"
        f"/next — следующий день\n📸 Фото — повторный консилиум")

async def cmd_help(upd: Update, c: ContextTypes.DEFAULT_TYPE):
    await upd.message.reply_text(
        "SkinCoach — как пользоваться:\n\n"
        "📸 Фото — консилиум + план на день\n"
        "💬 Текст — вопросы, отчёты\n\n"
        "/next — следующий день\n/status — прогресс\n/start — заново\n/help — справка")

# ── ЗАПУСК ──
def main():
    if not TG_TOKEN: raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в .env")
    if not OR_KEY: raise RuntimeError("OPENROUTER_API_KEY не найден в .env")
    if sys.platform=="win32": asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app=ApplicationBuilder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("help",cmd_help))
    app.add_handler(CommandHandler("next",cmd_next))
    app.add_handler(CommandHandler("status",cmd_status))
    app.add_handler(MessageHandler(filters.PHOTO,handle_photo))
    app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,handle_text))
    log.info("="*50)
    log.info("  SkinCoach v6")
    log.info(f"  Vision: {VISION_M} | A: {REASON_A}")
    log.info(f"  B: {REASON_B} | Judge: {JUDGE_M} | Chat: {CHAT_M}")
    log.info("="*50)
    app.run_polling()

if __name__=="__main__": main()
