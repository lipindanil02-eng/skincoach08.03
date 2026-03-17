"""
SkinCoach v7 — 8-слойный пайплайн + уточняющие вопросы + 28-дневная программа
"""
import tempfile, os
try:
    from inference import predict_image
    INFERENCE_AVAILABLE = True
except Exception as _inf_err:
    predict_image = None
    INFERENCE_AVAILABLE = False
    import logging as _l; _l.getLogger("skincoach").warning(f"inference not available: {_inf_err}")
from gamification import (ensure_fields, on_first_photo, update_streak,
    on_program_complete, on_referral_success, on_detailed_answer,
    format_achievements, format_leaderboard, format_skinrank,
    on_regular_photo_score, on_compete_photo, can_compete_today,
    add_points, award_badge, POINTS)
from payments import (is_access_allowed, can_ask_question, use_question,
                      apply_migration_defaults, PAYWALL_MESSAGE,
                      activate_subscription, revoke_subscription,
                      is_trial_active, days_left_trial, MAX_QUESTIONS_PER_WEEK)
from competition import generate_challenge_code, verify_liveness_response
import asyncio,json,os,sys,base64,logging
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any,Dict,List
import httpx
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,ContextTypes,filters

load_dotenv()

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
OR_KEY=os.getenv("OPENROUTER_API_KEY","").strip()
VISION_M=os.getenv("VISION_MODEL","google/gemini-2.0-flash-lite-001").strip()
REASON_M=os.getenv("REASON_MODEL","google/gemini-2.0-flash-lite-001").strip()
STRONG_M=os.getenv("STRONG_MODEL","google/gemini-2.5-flash-preview").strip()
VIS_FB=[m.strip() for m in os.getenv("VISION_FALLBACKS","google/gemini-2.5-flash-preview").split(",") if m.strip()]
TXT_FB=[m.strip() for m in os.getenv("TEXT_FALLBACKS","google/gemini-2.5-flash-preview,arcee-ai/trinity-large-preview:free").split(",") if m.strip()]
TEMP=float(os.getenv("TEMPERATURE","0.3"))
TOUT=int(os.getenv("TIMEOUT","120"))

logging.basicConfig(level=logging.INFO,format="%(asctime)s|%(levelname)s|%(message)s")
log=logging.getLogger("skincoach")

# States
S_NAME="name";S_DUR="dur";S_TRIED="tried";S_PHOTO="photo";S_QUESTIONS="questions";S_ACTIVE="active"
S_LABS="labs"
S_COMPETE="compete"
S_FACE="face"

# Labs — списки анализов
LABS_BASE=[
    "ОАК (общий анализ крови)",
    "СОЭ и CRP (воспаление)",
    "Витамин D",
    "Цинк",
    "IgE общий",
    "Гистамин",
    "Копрограмма",
    "Анализ на паразитов (3-кратный)",
    "Дисбактериоз",
    "Ревматоидный фактор (RF)",
]

DIAGNOSIS_NORM={
    "меланом":"melanoma","melanoma":"melanoma",
    "невус":"nevus","родинк":"nevus","nevus":"nevus",
    "акне":"acne","прыщ":"acne","угрев":"acne","acne":"acne",
    "атоп":"atopy","экзем":"atopy","atopy":"atopy",
    "себоре":"seborrhea","seborrhea":"seborrhea",
}

LABS_BY_DIAGNOSIS={
    "melanoma":["Онкомаркеры (LDH, S100B)","Биопсия (консультация дерматолога)"],
    "nevus":["Дерматоскопия (консультация)"],
    "acne":["ДГЭАС, тестостерон, ЛГ/ФСГ (гормоны)","Глюкоза, инсулин (сахар)"],
    "atopy":["Специфические IgE (аллергопанель)","Панель пищевой непереносимости"],
    "seborrhea":["ТТГ, Т3, Т4 (щитовидная)","Ферритин"],
    "other":["Ферритин","ТТГ"],
}

def normalize_diagnosis(text:str)->str:
    # Note: DIAGNOSIS_NORM is checked in insertion order — first match wins.
    # More specific keywords should come before shorter/broader ones.
    t=(text or "").lower()
    for kw,key in DIAGNOSIS_NORM.items():
        if kw in t: return key
    return "other"

def format_labs_message(diagnosis:str)->str:
    dk=normalize_diagnosis(diagnosis)
    base="\n".join(f"• {x}" for x in LABS_BASE)
    extras=LABS_BY_DIAGNOSIS.get(dk,[])
    extra_text=""
    if extras:
        extra_text=f"\n\n⚠️ Дополнительно для твоего диагноза:\n"+"\n".join(f"• {x}" for x in extras)
    urgent=""
    if dk=="melanoma":
        urgent="\n\n🚨 ВАЖНО: При подозрении на меланому — обратись к дерматологу немедленно, не откладывай!"
    return (
        "🔬 По твоему диагнозу рекомендую сдать:\n\n"
        f"📋 Базовые (важны для всех):\n{base}"
        f"{extra_text}"
        f"{urgent}\n\n"
        "Уже есть готовые анализы? Пришли фото бланка или напиши значения\n"
        "(пример: D=18, цинк=7.2, IgE=145)\n\n"
        "Нет анализов пока — напиши пропустить"
    )

WEEKS={1:"ПИТАНИЕ — убираем провокаторы",2:"НАРУЖНЫЙ УХОД — мыло, масло, крем",
       3:"ЭМОЦИИ — стресс-протокол",4:"АНАЛИЗЫ — контроль и коррекция"}
W_EMOJI={1:"🥗",2:"🧴",3:"🧠",4:"🔬"}
FOCUSES={
    1:{1:"Список что ел за 3 дня",2:"Исключи молочку",3:"Убери сахар",
       4:"Добавь куркуму",5:"8 стаканов воды",6:"Анти-воспалительный смузи",7:"Итог недели"},
    2:{1:"Серное мыло НЕ при остром",2:"Тёплая вода до 37C",3:"Крем с мочевиной на влажную кожу",
       4:"Масло точечно после крема",5:"Серное мыло 1 раз если можно",6:"Полная схема утро+вечер",7:"Фото для сравнения"},
    3:{1:"Дыхание 4-7-8",2:"3 ситуации обострения",3:"Точечный массаж",
       4:"Аффирмация 10 раз",5:"Мышечное расслабление",6:"Письмо коже",7:"Связь стресс-кожа?"},
    4:{1:"Запись: ОАК, D, ферритин, ТТГ",2:"Копрограмма",3:"Цинк и селен",
       4:"Расшифровка результатов",5:"Коррекция добавок",6:"Персональный протокол",7:"Финальное фото"},
}

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

# Utils
def rp(f,d=""):
    p=Path(f)
    if p.exists(): return p.read_text("utf-8").strip()
    p2=Path("prompts")/f
    if p2.exists(): return p2.read_text("utf-8").strip()
    return d

def cm(t):
    t=t.replace("**","").replace("__","").replace("```","").replace("`","")
    return "\n".join(l.lstrip("#").strip() if l.lstrip().startswith("#") else l for l in t.split("\n"))

def xj(t):
    t=t.strip()
    for prefix in ["```json","```"]:
        if t.startswith(prefix): t=t[len(prefix):]
    if t.endswith("```"): t=t[:-3]
    t=t.strip()
    try: return json.loads(t)
    except: pass
    s,e=t.find("{"),t.rfind("}")
    if s!=-1 and e>s:
        try: return json.loads(t[s:e+1])
        except: pass
    raise ValueError(f"No JSON: {t[:300]}")

# History — хранить в /data/ если задан HIST_PATH (Railway Volume), иначе локально
HIST=os.getenv("HIST_PATH","history.json")
def lh():
    if os.path.exists(HIST):
        try:
            data=json.load(open(HIST,"r",encoding="utf-8"))
            if isinstance(data,dict): return data
        except: pass
    return {}
def sh(h):
    try:
        with open(HIST,"w",encoding="utf-8") as f: json.dump(h,f,ensure_ascii=False,indent=2)
    except Exception as e: log.error(f"Save:{e}")
def gu(h,uid):
    u=str(uid)
    if u not in h: h[u]={"state":S_NAME,"name":None,"duration":None,"tried":None,
        "vision_data":None,"reasoning_data":None,"diagnosis":None,"risk":None,
        "recommendations":None,"pending_questions":None,"photo_b64":None,
        "day":0,"week":1,"msgs":[],"created":datetime.now().isoformat(),
        "last_active":datetime.now().isoformat(),"last_reengagement":None,
        "labs_raw":None,"labs_submitted_at":None}
    h[u]=ensure_fields(h[u])
    # Migration for existing users (ensure_fields doesn't know about labs fields)
    if "labs_raw" not in h[u]: h[u]["labs_raw"]=None
    if "labs_submitted_at" not in h[u]: h[u]["labs_submitted_at"]=None
    apply_migration_defaults(h[u])
    return h[u]
def tm(m): return m[-30:] if len(m)>30 else m

# API
def hdr(): return {"Authorization":f"Bearer {OR_KEY}","Content-Type":"application/json",
    "HTTP-Referer":"https://t.me/skincoach_bot","X-Title":"SkinCoach"}

async def call_raw(msgs,mdl,fb,mt=800):
    last_e=None
    async with httpx.AsyncClient(timeout=TOUT) as c:
        for m in [mdl]+fb:
            try:
                log.info(f"  -> {m}")
                r=await c.post("https://openrouter.ai/api/v1/chat/completions",headers=hdr(),
                    json={"model":m,"messages":msgs,"temperature":TEMP,"max_tokens":mt})
                if r.status_code==200:
                    d=r.json()
                    if "choices" in d and d["choices"]:
                        ct=d["choices"][0]["message"].get("content") or ""
                        if isinstance(ct,list): ct="".join(p.get("text","") for p in ct if isinstance(p,dict))
                        if not ct.strip():
                            log.warning(f"  {m}: empty"); continue
                        log.info(f"  OK: {m}")
                        return ct
                log.warning(f"  {m}: {r.status_code}"); last_e=f"{m}:{r.status_code}"
            except httpx.TimeoutException: log.warning(f"  {m}: timeout"); last_e=f"{m}:timeout"
            except Exception as e: log.warning(f"  {m}: {e}"); last_e=str(e)
    raise Exception(f"All down. {last_e}")

async def cj(msgs,mdl,fb,mt=800): return xj(await call_raw(msgs,mdl,fb,mt))
async def ct(msgs,mdl,fb,mt=800): return cm(await call_raw(msgs,mdl,fb,mt))

# ════════════════════════════════════
#  8-STEP PIPELINE
# ════════════════════════════════════
async def pipeline_photo(b64,cap,u):
    """Steps 1-4: analyze photo and generate questions"""
    nm=u.get("name","друг");dur=u.get("duration","?");tri=u.get("tried","?")
    uctx=f"Имя:{nm}, давность:{dur}, пробовали:{tri}"

    # STEP 1: Quality Check
    log.info("📸 1/8 Quality...")
    try:
        qp=rp("1_quality.txt","Проверь качество фото. JSON.")
        q=await cj([{"role":"system","content":qp},
            {"role":"user","content":[{"type":"text","text":"Оцени качество фото кожи"},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            VISION_M,VIS_FB,300)
        if not q.get("usable",True):
            return "ask_reshoot",q.get("suggestion","Пересними при дневном свете, крупным планом.")
    except Exception as e:
        log.warning(f"Quality skip: {e}")

    # STEP 2: Vision Description
    log.info("👁 2/8 Vision...")
    vp=rp("2_vision.txt","Опиши что видно на фото кожи. JSON.")
    try:
        vis=await cj([{"role":"system","content":vp},
            {"role":"user","content":[{"type":"text","text":cap or "Опиши что видишь на коже"},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
            VISION_M,VIS_FB,500)
    except Exception as e:
        log.error(f"Vision fail: {e}")
        return "error","Не удалось проанализировать фото. Попробуй ещё раз."
    u["vision_data"]=vis

    # STEP 3: Dermatology Reasoning
    log.info("🔬 3/8 Reasoning...")
    rp3=rp("3_reasoning.txt","Дифференциальная диагностика. JSON.")
    prev_diag=u.get("diagnosis")
    prev_conf=u.get("reasoning_data",{}).get("confidence") if u.get("reasoning_data") else None
    ctx3=json.dumps({"vision":vis,"patient":uctx,
        "previous_diagnosis":prev_diag if prev_diag else None,
        "previous_confidence":prev_conf},ensure_ascii=False)
    try:
        reason=await cj([{"role":"system","content":rp3},{"role":"user","content":ctx3}],
            STRONG_M,TXT_FB,600)
    except Exception as e:
        log.error(f"Reasoning fail: {e}")
        reason={"hypotheses":[{"diagnosis":"требуется уточнение","probability":100,"reasoning":"не удалось провести анализ"}],
                "primary_diagnosis":"требуется уточнение","stage":"unknown","phase":"unknown",
                "severity":"unknown","soap_safe":False,"confidence":0}
    u["reasoning_data"]=reason
    u["diagnosis"]=reason.get("primary_diagnosis","не определено")

    # STEP 4: Clinical Questions
    log.info("❓ 4/8 Questions...")
    rp4=rp("4_questions.txt","Задай 1-2 вопроса. JSON.")
    ctx4=json.dumps({"vision":vis,"reasoning":reason,"patient":uctx},ensure_ascii=False)
    try:
        qs=await cj([{"role":"system","content":rp4},{"role":"user","content":ctx4}],
            REASON_M,TXT_FB,400)
    except:
        qs={"questions":[],"intro":f"{nm}, я проанализировал фото."}
    u["pending_questions"]=qs
    return "questions",qs

async def pipeline_final(u,answers_text=""):
    """Steps 5-8: after questions answered, generate final plan"""
    nm=u.get("name","друг");dur=u.get("duration","?");tri=u.get("tried","?")
    vis=u.get("vision_data",{});reason=u.get("reasoning_data",{})
    dy=u.get("day",1);wk=u.get("week",1)
    wt=WEEKS.get(wk,"Программа");diw=((dy-1)%7)+1
    df=FOCUSES.get(wk,{}).get(diw,"Следуй программе")

    all_data=json.dumps({"vision":vis,"reasoning":reason,"patient_answers":answers_text,
        "patient":f"Имя:{nm}, давность:{dur}, пробовали:{tri}",
        "day":dy,"week":wk,"week_theme":wt,"day_focus":df},ensure_ascii=False)

    # STEP 5: Risk Triage
    log.info("⚠️ 5/8 Triage...")
    rp5=rp("5_triage.txt","Определи уровень риска. JSON.")
    try:
        triage=await cj([{"role":"system","content":rp5},{"role":"user","content":all_data}],
            REASON_M,TXT_FB,300)
    except:
        triage={"risk_level":"green","urgency":"routine"}
    u["risk"]=triage

    # STEP 6: Recommendations
    log.info("📋 6/8 Recommendations...")
    rp6=rp("6_recommendations.txt","Составь рекомендации. JSON.")
    ctx6=json.dumps({"all_data":json.loads(all_data) if isinstance(all_data,str) else all_data,
        "triage":triage},ensure_ascii=False)
    try:
        recs=await cj([{"role":"system","content":rp6},{"role":"user","content":ctx6}],
            STRONG_M,TXT_FB,800)
    except Exception as e:
        log.error(f"Recs fail: {e}")
        recs={"diagnosis_summary":"Анализ выполнен","morning_routine":["Мягкое очищение"],
              "evening_routine":["Увлажнение"],"day_focus":df}
    u["recommendations"]=recs

    # STEP 7: Safety Filter
    log.info("🛡️ 7/8 Safety...")
    rp7=rp("7_safety.txt","Проверь безопасность. JSON.")
    try:
        safety=await cj([{"role":"system","content":rp7},
            {"role":"user","content":json.dumps({"recs":recs,"triage":triage,"reasoning":reason},ensure_ascii=False)}],
            REASON_M,TXT_FB,300)
        if not safety.get("approved",True):
            log.warning(f"Safety issues: {safety.get('issues')}")
    except:
        pass  # If safety check fails, proceed anyway

    # STEP 8: Format Response
    log.info("💬 8/8 Response...")
    rp8=rp("8_response.txt","Собери ответ для Telegram.")
    rp8=rp8.replace("{name}",nm).replace("{day}",str(dy)).replace("{week}",str(wk))
    ctx8=json.dumps({"recommendations":recs,"triage":triage,"reasoning":reason,
        "vision":vis,"name":nm,"day":dy,"week":wk,"week_theme":wt},ensure_ascii=False)
    try:
        final=await ct([{"role":"system","content":rp8},{"role":"user","content":ctx8}],
            REASON_M,TXT_FB,900)
    except Exception as e:
        log.error(f"Response fail: {e}")
        final=format_fallback(recs,reason,triage,u)
    return final

def format_fallback(recs,reason,triage,u):
    nm=u.get("name","");dy=u.get("day",1);wk=u.get("week",1)
    p=[f"🔍 {nm}, вот что я вижу:"]
    ds=recs.get("diagnosis_summary","")
    if ds: p.append(ds)
    hyps=reason.get("hypotheses",[])
    if hyps:
        for h in hyps[:3]:
            p.append(f"  {h.get('diagnosis','?')} — {h.get('probability',0)}%")
    p.append(f"\nДень {dy}/28 — Неделя {wk} {W_EMOJI.get(wk,'📋')}")
    mr=recs.get("morning_routine",[])
    if mr: p.append("\n🧴 Утро:"); p.extend(f"  {x}" for x in mr[:3])
    er=recs.get("evening_routine",[])
    if er: p.append("\n🌙 Вечер:"); p.extend(f"  {x}" for x in er[:3])
    ps=recs.get("psycho",{})
    af=ps.get("affirmation","")
    if af: p.append(f"\n💫 {af}")
    p.append("\n📝 Вечером напиши: что сделал, как кожа, ощущения.")
    return "\n".join(p)

# Send
async def send(msg,txt):
    if len(txt)<=4000: await msg.reply_text(txt); return
    parts,cur=[],""
    for l in txt.split("\n"):
        if len(cur)+len(l)+1>4000:
            if cur: parts.append(cur)
            cur=l
        else: cur=cur+"\n"+l if cur else l
    if cur: parts.append(cur)
    for p in parts: await msg.reply_text(p)

# ════════════════════════════════════
#  HANDLERS
# ════════════════════════════════════
async def cmd_start(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    # Handle referral link: /start REF_12345
    args = ctx.args
    if args and args[0].startswith("REF_"):
        ref_code = args[0]
        referrer_uid = None
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
    h[str(uid)]["state"]=S_NAME
    h[str(uid)]["msgs"]=[]
    sh(h)
    await upd.message.reply_text("Привет! Я SkinCoach — твой персональный ИИ-коуч по коже.\nКак тебя зовут?")

async def handle_text(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;txt=upd.message.text;h=lh();u=gu(h,uid)
    u["last_active"]=datetime.now().isoformat()
    await upd.message.chat.send_action(ChatAction.TYPING)

    # Onboarding
    if u["state"]==S_NAME:
        u["name"]=txt.strip();u["state"]=S_DUR;sh(h)
        await upd.message.reply_text(f"{u['name']}, какая у тебя проблема с кожей и как давно беспокоит?")
        return
    if u["state"]==S_DUR:
        u["duration"]=txt.strip();u["state"]=S_TRIED;sh(h)
        await upd.message.reply_text("Что уже пробовал(а)? Мази, диеты, народные средства, фототерапия?")
        return
    if u["state"]==S_TRIED:
        u["tried"]=txt.strip();u["state"]=S_PHOTO;sh(h)
        await upd.message.reply_text(
            f"Отлично, {u['name']}.\n\n📸 Отправь фото проблемного участка.\n"
            "Дневной свет, крупный план.\nМой 8-ступенчатый анализ определит тип, стадию и составит план.")
        return
    if u["state"]==S_PHOTO:
        sh(h)
        await upd.message.reply_text(f"{u.get('name','')}, мне нужно фото. 📸")
        return

    # Answers to clinical questions
    if u["state"]==S_QUESTIONS:
        u["state"]=S_ACTIVE
        if u["day"]==0: u["day"]=1;u["week"]=1
        st=await upd.message.reply_text("Принял ответы. Генерирую персональный план... ⏳")
        try:
            reply=await pipeline_final(u,txt)
        except Exception as e:
            reply=f"Ошибка генерации плана. Попробуй /next"; log.error(f"Final:{e}")
        u["msgs"].append({"role":"user","content":txt})
        u["msgs"].append({"role":"assistant","content":reply})
        u["msgs"]=tm(u["msgs"])
        try: await st.delete()
        except: pass
        await send(upd.message,reply)
        # Offer lab tests after diagnosis
        labs_msg=format_labs_message(u.get("diagnosis",""))
        u["state"]=S_LABS;sh(h)
        await upd.message.reply_text(labs_msg)
        return

    # Labs input
    if u["state"]==S_LABS:
        t_lower=txt.strip().lower()
        # Exit without saving
        if any(kw in t_lower for kw in ("пропустить","skip","нет","не сейчас","позже")):
            u["state"]=S_ACTIVE;sh(h)
            await upd.message.reply_text("Хорошо, продолжай программу! Когда сдашь анализы — напиши /labs")
            return
        # Looks like lab results (digits, = or :, or keywords)
        has_numbers=any(c.isdigit() for c in txt)
        has_separator=("=" in txt or ":" in txt)
        has_keywords=any(kw in t_lower for kw in ("витамин","цинк","ферритин","ттг","иге","igg","соэ","crp","ige"))
        if has_numbers or has_separator or has_keywords:
            u["labs_raw"]=txt.strip()
            u["labs_submitted_at"]=datetime.now().isoformat()
            u["state"]=S_ACTIVE;sh(h)
            st2=await upd.message.reply_text("Принял анализы. Интерпретирую... ⏳")
            await interpret_labs(u,upd.message)
            try: await st2.delete()
            except: pass
            return
        # Unknown message — prompt user
        await upd.message.reply_text(
            "Пришли фото бланка, напиши значения (D=18, цинк=7) или напиши пропустить")
        return

    if u["state"]==S_COMPETE:
        code=u.get("challenge_code","????")
        await upd.message.reply_text(
            f"Жду фото с кодом {code} на бумажке. "
            "Отправь фото или напиши /start чтобы выйти.")
        sh(h); return

    # Active program - chat
    if u["state"]==S_ACTIVE:
        # Free users after trial: 3 questions/week limit
        if not is_access_allowed(u):
            if not can_ask_question(u):
                await upd.message.reply_text(
                    "💬 Ты использовал 3 вопроса на этой неделе.\n"
                    "Безлимитный чат — в подписке.\n\n"
                    + PAYWALL_MESSAGE
                )
                sh(h)
                return
            use_question(u)
            sh(h)
        u["msgs"].append({"role":"user","content":txt});u["msgs"]=tm(u["msgs"])
        wt=WEEKS.get(u["week"],"Программа")
        diag=(u.get("diagnosis") or "не определено")[:200]
        cp=rp("chat.txt","Ты SkinCoach.").format(
            name=u.get("name","друг"),duration=u.get("duration","?"),
            tried=u.get("tried","?"),diagnosis=diag,
            day=u["day"],week=u["week"],week_theme=wt)
        msgs=[{"role":"system","content":cp}]+u["msgs"]
        try: reply=await ct(msgs,REASON_M,TXT_FB,600)
        except: reply="Модели заняты. Через минуту."
        # Gamification: бонус за детальный ответ
        u, det_notifs = on_detailed_answer(u, len(txt))
        if det_notifs:
            reply += "\n" + "".join(det_notifs)
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"]);sh(h)
        await send(upd.message,reply)
        return

    u["state"]=S_NAME;sh(h)
    await upd.message.reply_text("Как тебя зовут?")

async def interpret_labs(u, msg):
    """Call 4b_labs.txt prompt and send interpretation to user"""
    labs_raw=u.get("labs_raw","")
    if not labs_raw: return
    pr=rp("4b_labs.txt","Интерпретируй анализы.")
    pr=pr.replace("{name}",u.get("name","друг"))
    pr=pr.replace("{diagnosis}",u.get("diagnosis","не определено"))
    pr=pr.replace("{duration}",u.get("duration","?"))
    pr=pr.replace("{labs_raw}",labs_raw)
    try:
        reply=await ct([{"role":"system","content":pr},
            {"role":"user","content":"Интерпретируй мои анализы."}],
            REASON_M,TXT_FB,800)
    except Exception as e:
        log.error(f"interpret_labs fail: {e}")
        reply="Не удалось интерпретировать анализы. Попробуй позже или задай вопрос текстом."
    await send(msg,reply)

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

async def handle_photo(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    is_compete_photo=(u["state"]==S_COMPETE)
    if u["state"] in (S_NAME,S_DUR,S_TRIED):
        await upd.message.reply_text("Сначала познакомимся. /start"); return

    # If waiting for labs — do OCR, not skin diagnosis
    if u["state"]==S_LABS:
        st=await upd.message.reply_text("🔬 Читаю бланк анализов... ⏳")
        await upd.message.chat.send_action(ChatAction.TYPING)
        try:
            ph=upd.message.photo[-1];f=await ctx.bot.get_file(ph.file_id)
            b=await f.download_as_bytearray();b64=base64.b64encode(b).decode()
            ocr_prompt="Это фото бланка лабораторных анализов. Извлеки все показатели и их значения в формате: Название = значение единица. Только показатели, без лишнего текста."
            raw=await call_raw([{"role":"system","content":ocr_prompt},
                {"role":"user","content":[{"type":"text","text":"Извлеки показатели"},
                    {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{b64}"}}]}],
                VISION_M,VIS_FB,500)
            u["labs_raw"]=raw.strip()
            u["labs_submitted_at"]=datetime.now().isoformat()
        except Exception as e:
            log.error(f"Labs OCR fail: {e}")
            try: await st.delete()
            except: pass
            await upd.message.reply_text("Не удалось прочитать бланк. Напиши значения текстом (D=18, цинк=7.2)")
            sh(h); return
        try: await st.delete()
        except: pass
        u["state"]=S_ACTIVE
        sh(h)
        await upd.message.reply_text(f"Прочитал анализы:\n{u['labs_raw']}\n\nИнтерпретирую... ⏳")
        await interpret_labs(u,upd.message)
        return

    # Access gate — not for face photos (S_FACE handled separately)
    if u.get("state") != "face" and not is_access_allowed(u):
        await upd.message.reply_text(PAYWALL_MESSAGE)
        return

    st=await upd.message.reply_text(
        "📸 Фото получено. Запускаю 8-ступенчатый анализ...\n\n"
        "1️⃣ Проверка качества фото...\n2️⃣ Описание кожи...\n"
        "3️⃣ Диагностика с вероятностями...\n4️⃣ Подготовка вопросов...\n\n"
        "30-60 сек ⏳")
    await upd.message.chat.send_action(ChatAction.TYPING)

    result_type=None
    try:
        ph=upd.message.photo[-1];f=await ctx.bot.get_file(ph.file_id)
        b=await f.download_as_bytearray();b64=base64.b64encode(b).decode()

        # Локальная модель
        if INFERENCE_AVAILABLE and predict_image:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                tmp.write(b)
                tmp_path = tmp.name
            try:
                skin_result = predict_image(tmp_path)
                u["local_model_result"] = skin_result
            except Exception as e:
                log.warning(f"Local model skip: {e}")
                u["local_model_result"] = None
            finally:
                try: os.unlink(tmp_path)
                except: pass
        else:
            u["local_model_result"] = None

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
                    try: await st.delete()
                    except: pass
                    await upd.message.reply_text("Превышен лимит попыток. Попробуй /compete завтра.")
                else:
                    sh(h)
                    try: await st.delete()
                    except: pass
                    await upd.message.reply_text(
                        f"Код не найден. Убедись что цифры {code} видны на бумаге "
                        f"рядом с кожей. Попытка {retries}/3.")
                return

        cap=(upd.message.caption or "").strip()
        u["photo_b64"]=b64[:100]
        u["last_active"]=datetime.now().isoformat()
        is_first_photo = not u.get("badges") or "first_photo" not in u.get("badges",[])
        result_type,result=await pipeline_photo(b64,cap,u)
    except Exception as e:
        log.error(f"handle_photo error: {e}")
        try: await st.delete()
        except: pass
        await upd.message.reply_text("Не удалось обработать фото. Попробуй ещё раз или пришли другое фото.")
        sh(h); return
    finally:
        try: await st.delete()
        except: pass

    if result_type=="ask_reshoot":
        await upd.message.reply_text(f"📸 {result}")
        sh(h); return

    if result_type=="error":
        await upd.message.reply_text(result)
        sh(h); return

    # result_type == "questions"
    qs=result
    intro=qs.get("intro",f"{u.get('name','')}, я проанализировал фото.")
    questions=qs.get("questions",[])

    # Show diagnosis preview
    reason=u.get("reasoning_data",{})
    hyps=reason.get("hypotheses",[])
    diag_text=""
    if hyps:
        diag_text="\n\n🔬 Предварительный анализ:\n"
        for hp in hyps[:3]:
            diag_text+=f"  {hp.get('diagnosis','?')} — {hp.get('probability',0)}%\n"

    if questions:
        q_text="\n\nЧтобы дать точные рекомендации, мне нужно уточнить:\n\n"
        for i,q in enumerate(questions):
            q_text+=f"{i+1}. {q.get('question','')}\n"
            opts=q.get("options",[])
            if opts: q_text+="   "+", ".join(opts)+"\n"
        q_text+="\nОтветь на вопросы одним сообщением."
        u["state"]=S_QUESTIONS
    else:
        q_text=""
        u["state"]=S_ACTIVE
        if u["day"]==0: u["day"]=1;u["week"]=1

    # Extract skin score from vision data
    vis=u.get("vision_data") or {}
    skin_sc=vis.get("skin_score") if isinstance(vis,dict) else None
    has_makeup=vis.get("has_makeup",False) if isinstance(vis,dict) else False
    visual_age=vis.get("visual_age") if isinstance(vis,dict) else None
    if skin_sc and skin_sc.get("total") is not None:
        u=on_regular_photo_score(u,skin_sc,has_makeup)

    # Gamification: первое фото
    gam_msgs = []
    if is_first_photo and result_type not in ("error", "ask_reshoot"):
        u, notifs = on_first_photo(u)
        gam_msgs.extend(notifs)

    # Competition result
    score_line=""
    if is_compete_photo and skin_sc and skin_sc.get("total") is not None:
        u=on_compete_photo(u,skin_sc,has_makeup)
        u["state"]=S_ACTIVE
        t=skin_sc.get("total",0)
        score_line=(f"\n\n✅ Результат засчитан в рейтинг!\n📊 Оценка: {t}/100"
                    f"{' (с макияжем)' if has_makeup else ' (без макияжа)'}\n/skinrank — посмотреть рейтинг")
    elif is_compete_photo and (not skin_sc or skin_sc.get("total") is None):
        u["state"]=S_ACTIVE
        sh(h)
        await upd.message.reply_text("Фото не подходит для оценки. Попробуй ещё раз с хорошим освещением.")
        return
    elif skin_sc and skin_sc.get("total") is not None:
        t=skin_sc.get("total",0)
        makeup_note=" (с макияжем)" if has_makeup else " (без макияжа)"
        age_note=f" · Визуальный возраст: {visual_age}" if visual_age else ""
        score_line=f"\n\n📊 Оценка кожи: {t}/100{makeup_note}{age_note}\n/compete — участвовать в рейтинге"

    sh(h)
    msg=intro+diag_text+q_text+score_line
    if gam_msgs:
        msg += "\n" + "".join(gam_msgs)
    await send(upd.message,msg)

    # If no questions — proceed to final immediately
    if not questions:
        st2=await upd.message.reply_text("Генерирую план... ⏳")
        try: reply=await pipeline_final(u,"")
        except Exception as e: reply="Ошибка. /next"; log.error(f"Final:{e}")
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"])
        try: await st2.delete()
        except: pass
        await send(upd.message,reply)
        # Offer lab tests after diagnosis
        labs_msg=format_labs_message(u.get("diagnosis",""))
        u["state"]=S_LABS;sh(h)
        await send(upd.message,labs_msg)

async def cmd_next(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    if u["state"] not in (S_ACTIVE,S_LABS): await upd.message.reply_text("/start"); return
    if not is_access_allowed(u):
        await upd.message.reply_text(PAYWALL_MESSAGE)
        return
    await upd.message.chat.send_action(ChatAction.TYPING)
    u["day"]+=1
    if u["day"]>28:
        u, notifs = on_program_complete(u)
        sh(h)
        msg = f"🎉 {u.get('name','')}, программа пройдена! Отправь фото для сравнения."
        if notifs: msg += "\n" + "".join(notifs)
        await upd.message.reply_text(msg); return
    u["week"]=((u["day"]-1)//7)+1
    wt=WEEKS.get(u["week"],"Программа");diw=((u["day"]-1)%7)+1
    df=FOCUSES.get(u["week"],{}).get(diw,"Следуй программе")
    diag=(u.get("diagnosis") or "не определено")[:200]
    last=u["msgs"][-4:] if u["msgs"] else []
    context="".join(f"{'Человек' if m['role']=='user' else 'Коуч'}: {(m['content'] if isinstance(m['content'],str) else '')[:150]}\n" for m in last)
    pr=rp("next_day.txt","План на день.").format(
        day=u["day"],week=u["week"],week_theme=wt,week_emoji=W_EMOJI.get(u["week"],"📋"),
        name=u.get("name","друг"),diagnosis=diag,day_focus=df,context=context)
    try: plan=await ct([{"role":"system","content":pr},{"role":"user","content":f"План на день {u['day']}."}],REASON_M,TXT_FB,600)
    except: plan="Не удалось. /next через минуту."

    # Gamification: стрик + очки за день
    u, streak_notifs = update_streak(u)
    u, pts_notifs = add_points(u, POINTS["daily_next"])
    gam_suffix = "".join(streak_notifs + pts_notifs)

    # Сюрпризы по дням
    surprises = {
        7:  "\n\n🎁 Сюрприз! Антивоспалительный смузи: шпинат + куркума + имбирь + кокосовое молоко. Попробуй сегодня!",
        14: "\n\n🎁 День 14! Разблокирован стресс-протокол: дыхание 4-7-8 перед сном, 5 минут.",
        21: "\n\n🎁 3 недели! Ты молодец. Посмотри на первое фото — кожа меняется. Продолжай!",
        28: "\n\n🏆 28 дней пройдено! Это победа. Напиши что изменилось и отправь финальное фото.",
    }
    if u["day"] in surprises:
        gam_suffix += surprises[u["day"]]

    u["msgs"].append({"role":"assistant","content":plan});u["msgs"]=tm(u["msgs"])
    await send(upd.message, plan + (f"\n\n⭐ +{POINTS['daily_next']} очков" if not gam_suffix else "") + gam_suffix)
    if u["day"]==22:
        if u.get("labs_raw"):
            await upd.message.reply_text(
                "🔬 Прошло 3 недели! Обнови анализы для точных рекомендаций.\n"
                "Пришли новые результаты или напиши пропустить.")
        else:
            await upd.message.reply_text(
                "🔬 Неделя 4 — время анализов!\n\n"
                "Ты прошёл 3 недели программы. Сдай анализы чтобы скорректировать план.\n\n"
                + format_labs_message(u.get("diagnosis","")))
        u["state"]=S_LABS
    sh(h)

async def cmd_status(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
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
    diag = u.get("diagnosis","не определено")
    day = u.get("day",0)
    lines.append(f"\n📋 Диагноз: {diag}")
    lines.append(f"📅 День программы: {day}/28")
    if u.get("skin_score_last"):
        lines.append(f"📊 Последняя оценка: {u['skin_score_last']}%")
    await upd.message.reply_text("\n".join(lines))

async def cmd_achievements(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();u=gu(h,upd.effective_user.id)
    await upd.message.reply_text(format_achievements(u))

async def cmd_leaderboard(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh()
    await upd.message.reply_text(format_leaderboard(h))

async def cmd_bonus(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton,InlineKeyboardMarkup
    h=lh();uid=upd.effective_user.id;u=gu(h,str(uid))
    if u.get("group_bonus_claimed"):
        await upd.message.reply_text("Ты уже получил бонус за вступление в группу 👥")
        return
    GROUP = os.getenv("COMMUNITY_GROUP","@skincoach_community")
    try:
        member=await ctx.bot.get_chat_member(chat_id=GROUP,user_id=uid)
        if member.status in ("member","administrator","creator","restricted"):
            u["group_member"]=True
            u["group_bonus_claimed"]=True
            u,notifs=add_points(u,POINTS["group_join"])
            u,badge_msg=award_badge(u,"group_member")
            # +7 дней к триалу
            from datetime import timedelta
            ts=u.get("trial_start",datetime.now().isoformat())
            trial_dt=datetime.fromisoformat(ts)
            u["trial_start"]=(trial_dt-timedelta(days=7)).isoformat()
            sh(h)
            msg="✅ Ты в группе! Бонус начислен:\n+7 дней к пробному периоду\n+50 очков"
            if badge_msg: msg+=badge_msg
            await upd.message.reply_text(msg)
        else:
            raise Exception("not member")
    except:
        keyboard=InlineKeyboardMarkup([[
            InlineKeyboardButton("👥 Вступить в группу",url=f"https://t.me/{GROUP.lstrip('@')}")
        ]])
        await upd.message.reply_text(
            f"Вступи в группу SkinCoach и получи +7 дней бесплатно!\n\nПосле вступления нажми /bonus ещё раз.",
            reply_markup=keyboard)

async def cmd_labs(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();u=gu(h,upd.effective_user.id)
    if u["state"] in (S_NAME,S_DUR,S_TRIED,S_PHOTO,S_QUESTIONS):
        await upd.message.reply_text("Сначала заверши диагностику — пришли фото кожи 📸"); return
    labs_msg=format_labs_message(u.get("diagnosis",""))
    u["state"]=S_LABS;sh(h)
    await upd.message.reply_text(labs_msg)

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

async def cmd_skinrank(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();uid=str(upd.effective_user.id)
    await upd.message.reply_text(format_skinrank(h,viewer_uid=uid))

async def cmd_help(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    await upd.message.reply_text(
        "SkinCoach — 8-ступенчатый анализ кожи:\n\n"
        "📸 Фото — полный анализ с диагнозом и вероятностями\n"
        "💬 Текст — вопросы, отчёты\n\n"
        "/next — следующий день\n/status — прогресс + диагноз\n"
        "/achievements — бейджи, уровень, очки\n"
        "/bonus — бонус за вступление в группу\n"
        "/labs — ввести или обновить анализы\n"
        "/leaderboard — топ участников\n"
        "/start — заново")

async def send_weekly_notifications(context: ContextTypes.DEFAULT_TYPE):
    """Еженедельное утреннее уведомление для активных пользователей (раз в 7 дней)"""
    h = lh()
    now = datetime.now()
    changed = False
    for uid, u in list(h.items()):
        if u.get("state") != S_ACTIVE: continue
        day = u.get("day", 0)
        if day == 0 or day > 28: continue
        # Отправляем не чаще раза в 7 дней
        last_notif = u.get("last_weekly_notify")
        if last_notif:
            try:
                days_since = (now - datetime.fromisoformat(last_notif)).total_seconds() / 86400
                if days_since < 7: continue
            except: pass
        try: chat_id = int(uid)
        except: continue
        week = u.get("week", 1)
        wt = WEEKS.get(week, "Программа")
        diw = ((day - 1) % 7) + 1
        df = FOCUSES.get(week, {}).get(diw, "Следуй программе")
        name = u.get("name", "друг")
        msg = (f"☀️ Привет, {name}! Напоминаю о программе.\n\n"
               f"День {day}/28 — {W_EMOJI.get(week,'📋')} Неделя {week}: {wt}\n\n"
               f"🎯 Фокус этой недели: {df}\n\n"
               f"📸 Пришли фото или напиши как кожа — продолжим вместе.")
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg)
            u["last_weekly_notify"] = now.isoformat()
            changed = True
            log.info(f"Weekly notify → {uid}")
        except Exception as e:
            log.warning(f"Weekly notify {uid}: {e}")
    if changed: sh(h)

async def send_reengagement(context: ContextTypes.DEFAULT_TYPE):
    """Напоминание пользователям которые молчат 48+ часов"""
    h = lh()
    now = datetime.now()
    changed = False
    for uid, u in list(h.items()):
        if u.get("state") not in (S_ACTIVE, S_QUESTIONS): continue
        if u.get("day", 0) == 0: continue
        try: chat_id = int(uid)
        except: continue
        last = u.get("last_active")
        if not last: continue
        try:
            hours_silent = (now - datetime.fromisoformat(last)).total_seconds() / 3600
        except: continue
        if hours_silent < 48: continue
        last_notif = u.get("last_reengagement")
        if last_notif:
            try:
                if (now - datetime.fromisoformat(last_notif)).total_seconds() < 86400:
                    continue
            except: pass
        name = u.get("name", "друг")
        msg = f"👋 {name}, как твоя кожа?\n\nПришли фото или напиши как ты — продолжим вместе."
        try:
            await context.bot.send_message(chat_id=chat_id, text=msg)
            u["last_reengagement"] = now.isoformat()
            changed = True
            log.info(f"Reengagement → {uid}")
        except Exception as e:
            log.warning(f"Reengagement {uid}: {e}")
    if changed: sh(h)

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

async def cmd_grant(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    admin_id = os.getenv("ADMIN_ID","").strip()
    if not admin_id or str(upd.effective_user.id) != admin_id:
        return
    args=ctx.args
    if not args:
        await upd.message.reply_text("Usage: /grant <user_id> [days]"); return
    target_uid=args[0]
    days=int(args[1]) if len(args)>1 else 30
    h=lh()
    if target_uid not in h:
        await upd.message.reply_text(f"User {target_uid} not found"); return
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
    if not admin_id or str(upd.effective_user.id) != admin_id:
        return
    args=ctx.args
    if not args:
        await upd.message.reply_text("Usage: /revoke <user_id>"); return
    target_uid=args[0]
    h=lh()
    if target_uid not in h:
        await upd.message.reply_text(f"User {target_uid} not found"); return
    revoke_subscription(h[target_uid])
    sh(h)
    await upd.message.reply_text(f"✅ Подписка отозвана у {target_uid}")

async def cmd_ref(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    # Generate ref_code if not set
    if not u.get("ref_code"):
        u["ref_code"] = f"REF_{uid}"
        sh(h)
    bot_username = (await ctx.bot.get_me()).username
    ref_code = u["ref_code"]
    link = f"https://t.me/{bot_username}?start={ref_code}"
    msg = (
        f"🎁 Твоя реферальная ссылка:\n{link}\n\n"
        f"Поделись с другом — вы оба получите скидку 50% на первый месяц.\n"
        f"То есть всего 245₽ вместо 490₽!\n\n"
        f"Твоих приглашений: {u.get('ref_count',0)}"
    )
    await upd.message.reply_text(msg)

def main():
    if not TOKEN: raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not OR_KEY: raise RuntimeError("OPENROUTER_API_KEY not set")
    if sys.platform=="win32": asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start","🔄 Начать заново / регистрация"),
            BotCommand("help","ℹ️ Справка по боту"),
            BotCommand("status","📊 Мой прогресс и диагноз"),
            BotCommand("next","➡️ Следующий день программы"),
            BotCommand("achievements","🏆 Мои бейджи и очки"),
            BotCommand("leaderboard","🥇 Топ участников"),
            BotCommand("bonus","🎁 Бонус за вступление в группу"),
            BotCommand("labs","🔬 Анализы — ввести или обновить"),
            BotCommand("compete","🏆 Участвовать в рейтинге кожи"),
            BotCommand("skinrank","🥇 Рейтинг кожи"),
            BotCommand("face","✨ Оценка кожи лица"),
            BotCommand("subscribe","💳 Оформить подписку"),
            BotCommand("ref","🎁 Пригласить друга"),
        ])
        notify_hour = int(os.getenv("NOTIFY_HOUR_UTC", "6"))  # 6 UTC = 9 MSK
        application.job_queue.run_daily(
            send_weekly_notifications,
            time=dtime(hour=notify_hour, minute=0)
        )
        application.job_queue.run_repeating(
            send_reengagement,
            interval=43200,   # каждые 12 часов
            first=3600        # первый запуск через 1 час после старта
        )
        log.info(f"Scheduler: daily at {notify_hour}:00 UTC, reengagement every 12h")
    app=ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("help",cmd_help))
    app.add_handler(CommandHandler("next",cmd_next))
    app.add_handler(CommandHandler("status",cmd_status))
    app.add_handler(CommandHandler("achievements",cmd_achievements))
    app.add_handler(CommandHandler("bonus",cmd_bonus))
    app.add_handler(CommandHandler("labs",cmd_labs))
    app.add_handler(CommandHandler("leaderboard",cmd_leaderboard))
    app.add_handler(CommandHandler("compete",cmd_compete))
    app.add_handler(CommandHandler("skinrank",cmd_skinrank))
    app.add_handler(CommandHandler("subscribe",cmd_subscribe))
    app.add_handler(CommandHandler("grant",cmd_grant))
    app.add_handler(CommandHandler("revoke",cmd_revoke))
    app.add_handler(CommandHandler("ref",cmd_ref))
    app.add_handler(MessageHandler(filters.PHOTO,handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text))
    log.info("="*50);log.info("  SkinCoach v7 — 8-step pipeline");log.info("="*50)
    app.run_polling()

if __name__=="__main__": main()
