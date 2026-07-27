"""
SkinCoach v7 — 8-слойный пайплайн + уточняющие вопросы + 28-дневная программа
"""
import tempfile, os
import asyncio,json,os,sys,base64,logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder,CommandHandler,CallbackQueryHandler,MessageHandler,ContextTypes,filters

from core.pipeline import (pipeline_photo, pipeline_final, call_raw, rp, cm, cj, ct,
                           format_fallback, WEEKS, W_EMOJI, FOCUSES)

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
OR_KEY=os.getenv("OPENROUTER_API_KEY","").strip()
VISION_M=os.getenv("VISION_MODEL","google/gemini-2.0-flash-lite-001").strip()
REASON_M=os.getenv("REASON_MODEL","google/gemini-2.0-flash-lite-001").strip()
STRONG_M=os.getenv("STRONG_MODEL","google/gemini-2.5-flash-preview").strip()
VIS_FB=[m.strip() for m in os.getenv("VISION_FALLBACKS","google/gemini-2.5-flash-preview").split(",") if m.strip()]
TXT_FB=[m.strip() for m in os.getenv("TEXT_FALLBACKS","google/gemini-2.5-flash-preview,arcee-ai/trinity-large-preview:free").split(",") if m.strip()]
TEMP=float(os.getenv("TEMPERATURE","0.3"))
TOUT=int(os.getenv("TIMEOUT","120"))
PUBLIC_BOT_USERNAME=os.getenv("PUBLIC_BOT_USERNAME","kinesispro01_bot").strip().lstrip("@")

logging.basicConfig(level=logging.INFO,format="%(asctime)s|%(levelname)s|%(message)s")
log=logging.getLogger("skincoach")

# States
S_NAME="name";S_DUR="dur";S_TRIED="tried";S_PHOTO="photo";S_QUESTIONS="questions";S_ACTIVE="active"

# History
HIST = str(Path(__file__).parent / ".hermes" / "history.json")
def lh():
    if os.path.exists(HIST):
        try:
            with open(HIST,"r",encoding="utf-8") as f: return json.load(f)
        except: return {}
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
        "day":0,"week":1,"msgs":[],"created":datetime.now().isoformat()}
    return h[u]
def tm(m): return m[-30:] if len(m)>30 else m

def pct(v, default=0):
    try:
        n=float(str(v).replace("%","").strip())
        if n<=1: n*=100
        return max(0,min(100,n))
    except (ValueError,TypeError):
        return default

def reset_analysis(u):
    for k in ("vision_data","reasoning_data","diagnosis","risk","recommendations",
              "pending_questions","photo_b64","local_model_result"):
        u[k]=None
    u["day"]=0;u["week"]=1;u["msgs"]=[]

def share_kb(text="Бесплатный AI-анализ кожи по фото"):
    bot_url=f"https://t.me/{PUBLIC_BOT_USERNAME}"
    url=f"https://t.me/share/url?url={quote(bot_url)}&text={quote(text)}"
    return InlineKeyboardMarkup([[InlineKeyboardButton("👥 Поделиться", url=url)]])

async def send_program_cta(msg):
    await msg.reply_text(
        "Готово. Дальше веду тебя по программе:\n\n"
        "/next — следующий день\n"
        "/status — прогресс\n"
        "📸 новое фото — повторный анализ",
        reply_markup=share_kb("Я прошел бесплатный AI-анализ кожи в SkinCoach")
    )

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
    h=lh();uid=str(upd.effective_user.id)
    h[uid]=gu(h,upd.effective_user.id)
    tg_user=upd.effective_user
    h[uid]["state"]=S_PHOTO;h[uid]["msgs"]=[]
    h[uid]["name"]=tg_user.first_name or tg_user.username or "друг"
    h[uid]["duration"]=h[uid].get("duration") or "пока не указано"
    h[uid]["tried"]=h[uid].get("tried") or "пока не указано"
    reset_analysis(h[uid])
    sh(h)
    await upd.message.reply_text(
        "🔬 Бесплатный AI-анализ кожи по фото.\n\n"
        "Отправь фото проблемного участка кожи — сразу покажу результат и соберу первый шаг программы.\n\n"
        "Как снять:\n"
        "• дневной свет\n"
        "• крупный план\n"
        "• без фильтров и размытия")
    # Share button on start
    await upd.message.reply_text("Знаешь кого-то с проблемами кожи? Поделись ботом 👇", reply_markup=share_kb())

async def handle_text(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;txt=upd.message.text;h=lh();u=gu(h,uid)
    await upd.message.chat.send_action(ChatAction.TYPING)

    # Name change from /settings
    if u.get("awaiting_name"):
        u["name"]=txt.strip()[:30] or u.get("name")
        u["awaiting_name"]=False;sh(h)
        await upd.message.reply_text(f"Ок, {u['name']} ✌️")
        return

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
        await upd.message.reply_text(
            f"{u.get('name','')}, сначала пришли фото кожи 📸\n\n"
            "После анализа я задам один уточняющий вопрос и соберу план."
        )
        return

    # Answers to clinical questions
    if u["state"]==S_QUESTIONS:
        u["state"]=S_ACTIVE
        if u["day"]==0: u["day"]=1;u["week"]=1
        st=await upd.message.reply_text("Принял ответы. Генерирую персональный план... ⏳")
        answers_text=txt
        pending=u.get("pending_questions") or []
        if pending:
            q_lines=[]
            for i,q in enumerate(pending,1):
                q_lines.append(f"Вопрос {i}: {q.get('question','')}")
            answers_text="\n".join(q_lines)+f"\n\nОтвет пользователя: {txt}"
        try:
            reply=await pipeline_final(u,answers_text)
        except Exception as e:
            reply=f"Ошибка генерации плана. Попробуй /next"; log.error(f"Final:{e}")
        u["pending_questions"]=None
        u["msgs"].append({"role":"user","content":txt})
        u["msgs"].append({"role":"assistant","content":reply})
        u["msgs"]=tm(u["msgs"]);sh(h)
        try: await st.delete()
        except: pass
        await send(upd.message,reply)
        await send_program_cta(upd.message)
        return

    # Active program - chat
    if u["state"]==S_ACTIVE:
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
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"]);sh(h)
        await send(upd.message,reply)
        return

    u["state"]=S_NAME;sh(h)
    await upd.message.reply_text("Как тебя зовут?")

async def handle_photo(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    if not u.get("name"):
        tg_user=upd.effective_user
        u["name"]=tg_user.first_name or tg_user.username or "друг"
    if not u.get("duration"):
        u["duration"]="пока не указано"
    if not u.get("tried"):
        u["tried"]="пока не указано"

    st=await upd.message.reply_text(
        "📸 Фото получено. Запускаю 8-ступенчатый анализ...\n\n"
        "1️⃣ Проверка качества фото...\n2️⃣ Описание кожи...\n"
        "3️⃣ Диагностика с вероятностями...\n4️⃣ Подготовка вопросов...\n\n"
        "30-60 сек ⏳")
    await upd.message.chat.send_action(ChatAction.TYPING)

    ph=upd.message.photo[-1];f=await ctx.bot.get_file(ph.file_id)
    b=await f.download_as_bytearray();b64=base64.b64encode(b).decode()

    # Локальная модель (опционально — если файла нет, пропускаем)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(b)
        tmp_path = tmp.name
    try:
        try:
            from inference import predict_image
            skin_result = predict_image(tmp_path)
            u["local_model_result"] = skin_result
        except Exception as ml_err:
            log.warning(f"ML model skipped: {ml_err}")
            u["local_model_result"] = None
    finally:
        os.unlink(tmp_path)

    cap=(upd.message.caption or "").strip()
    u["photo_b64"]=b64[:100]
    try:
        result_type,result=await pipeline_photo(b64,cap,u)
    except Exception as e:
        log.error(f"Photo pipeline:{e}")
        try: await st.delete()
        except: pass
        await upd.message.reply_text("Анализ сейчас не прошёл. Попробуй отправить фото ещё раз через минуту.")
        sh(h)
        return

    try: await st.delete()
    except: pass

    if result_type=="ask_reshoot":
        await upd.message.reply_text(f"📸 {result}")
        sh(h); return

    if result_type=="error":
        await upd.message.reply_text(result)
        sh(h); return

    # Send diagnosis card immediately after analysis (unique per photo)
    try:
        import uuid
        from gen_card import generate_card
        rd = u.get("reasoning_data", {}) or {}
        hyps = rd.get("hypotheses", []) or []
        top3 = [(h.get("diagnosis_ru", h.get("diagnosis", "?")), f"{pct(h.get('probability', 0)):.0f}%") for h in hyps[:3]]
        diag = rd.get("primary_diagnosis") or (hyps[0].get("diagnosis_ru", hyps[0].get("diagnosis", "?")) if hyps else "Анализ завершён")
        # Normalise confidence: 0-1 → 0-100
        conf = f"{int(pct(rd.get('confidence', 85),85))}%"
        card_id = f"{upd.effective_user.id}_{uuid.uuid4().hex[:8]}"
        card_path = await asyncio.to_thread(
            generate_card, diag, conf,
            rd.get("severity", "low") or "low", top3, card_id,
        )
        if os.path.exists(card_path):
            with open(card_path, "rb") as f:
                await upd.message.reply_photo(f, caption="🔬 SkinCoach — результат анализа")
            os.unlink(card_path)
    except Exception as ce:
        log.warning(f"Card gen fail: {ce}")

    # result_type == "questions"
    qs=result
    intro=qs.get("intro","🔬 Ваш анализ кожи:")
    questions=qs.get("questions",[])

    # Show diagnosis preview
    reason=u.get("reasoning_data",{})
    hyps=reason.get("hypotheses",[])
    is_healthy = reason.get("healthy", False) or reason.get("primary_diagnosis") == "здоровая кожа"
    skin_assess = reason.get("skin_assessment", "") or ""
    visual_age = reason.get("visual_age")
    diag_text=""
    if visual_age:
        diag_text += f"\n🔬 Кожа выглядит на ~{visual_age} лет\n"
    if is_healthy and skin_assess:
        diag_text += f"{skin_assess}\n"
    elif hyps:
        diag_text += "\n\n🔬 Предварительный анализ:\n"
        for hp in hyps[:3]:
            pct_text = f"{pct(hp.get('probability', 0)):.0f}%"
            name = hp.get('diagnosis_ru', hp.get('diagnosis', '?'))
            diag_text+=f"  {name} — {pct_text}\n"

    if questions:
        questions=questions[:1]
        q_text="\n\n"
        q_text+="Один короткий вопрос, чтобы собрать точнее день 1:\n"
        for i,q in enumerate(questions,1):
            q_text+=f"\n{q.get('question','')}"

        u["state"]=S_QUESTIONS
        u["pending_questions"]=questions
    else:
        q_text=""
        u["state"]=S_ACTIVE
        if u["day"]==0: u["day"]=1;u["week"]=1

    sh(h)
    program_cta=(
        "\n\n🎯 Дальше я соберу 28-дневную программу: утро, день, вечер и фокус дня."
        "\nНачнем с простого первого шага."
    )
    msg=intro+diag_text+program_cta+q_text
    await send(upd.message,msg)

    # If no questions — proceed to final immediately
    if not questions:
        st2=await upd.message.reply_text("Генерирую план... ⏳")
        try: reply=await pipeline_final(u,"")
        except Exception as e: reply="Ошибка. /next"; log.error(f"Final:{e}")
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"]);sh(h)
        try: await st2.delete()
        except: pass
        await send(upd.message,reply)
        await send_program_cta(upd.message)

async def cmd_next(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    if u["state"]==S_QUESTIONS:
        await upd.message.reply_text("Сначала ответь на вопрос после анализа, потом я соберу день 1.")
        return
    if u["state"]!=S_ACTIVE: await upd.message.reply_text("/start"); return
    await upd.message.chat.send_action(ChatAction.TYPING)
    if u["day"]>=28:
        u["day"]=28
        await upd.message.reply_text(f"🎉 {u.get('name','')}, программа пройдена! Отправь фото для сравнения.")
        sh(h); return
    u["day"]+=1
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
    u["msgs"].append({"role":"assistant","content":plan});u["msgs"]=tm(u["msgs"]);sh(h)
    await send(upd.message,plan)

async def cmd_status(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();u=gu(h,upd.effective_user.id)
    if u["state"]!=S_ACTIVE: await upd.message.reply_text("/start"); return
    wt=WEEKS.get(u["week"],"Программа");pct=int((u["day"]/28)*100)
    bar="▓"*(pct//10)+"░"*(10-pct//10)
    diag=u.get("diagnosis","не определено")
    reason=u.get("reasoning_data",{})
    hyps=reason.get("hypotheses",[])
    diag_info=""
    if hyps:
        diag_info="\n\nДиагноз:\n"
        for hp in hyps[:3]:
            diag_info+=f"  {hp.get('diagnosis','?')} — {hp.get('probability',0)}%\n"
    await upd.message.reply_text(
        f"📊 {u.get('name','')}{diag_info}\n"
        f"День {u['day']}/28\nНеделя {u['week']}/4 — {wt}\n[{bar}] {pct}%\n\n"
        f"/next — следующий день\n📸 Фото — повторный анализ")

async def cmd_help(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    await upd.message.reply_text(
        "SkinCoach — 8-ступенчатый анализ кожи:\n\n"
        "📸 Фото — полный анализ с диагнозом и вероятностями\n"
        "💬 Текст — вопросы, отчёты\n\n"
        "/next — следующий день\n/status — прогресс + диагноз\n"
        "/rank — оценка кожи\n/profile — профиль\n/settings — настройки\n/start — заново")

async def cmd_rank(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();u=gu(h,upd.effective_user.id)
    vis=u.get("vision_data") or {}
    ss=vis.get("skin_score") or {}
    total=ss.get("total")
    if total is None:
        await upd.message.reply_text("Пока нет оценки кожи — пришли фото для анализа 📸")
        return
    total=int(pct(total))
    bar="█"*(total//10)+"░"*(10-total//10)
    grade=("Отличная" if total>=90 else "Хорошая" if total>=75 else "Средняя" if total>=60
           else "Требует внимания" if total>=45 else "Нужна программа")
    lines=[f"🏆 Оценка кожи: {total}/100\n[{bar}] {grade}\n"]
    for k,lbl in (("tone","Тон"),("hydration","Увлажнённость"),("texture","Текстура"),
                  ("vitality","Сияние"),("cleanliness","Чистота"),("youth","Молодость")):
        v=ss.get(k)
        if v is not None: lines.append(f"  {lbl}: {v}/15")
    ea=ss.get("eye_area")
    if ea is not None: lines.append(f"  Зона глаз: {ea}/10")
    va=vis.get("visual_age")
    if va: lines.append(f"\nВизуальный возраст: ~{va}")
    lines.append("\n📸 Новое фото — обновлю оценку")
    await upd.message.reply_text("\n".join(lines))

async def cmd_profile(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();u=gu(h,upd.effective_user.id)
    day=u.get("day",0);wk=u.get("week",1)
    wt=WEEKS.get(wk,"Программа") if day>0 else "ещё не начата"
    diag=u.get("diagnosis") or "нет — пришли фото 📸"
    vis=u.get("vision_data") or {}
    ss=(vis.get("skin_score") or {}).get("total")
    score_line=f"\nОценка кожи: {int(pct(ss))}/100" if ss is not None else ""
    created=(u.get("created") or "")[:10]
    await upd.message.reply_text(
        f"👤 {u.get('name','друг')}\n\n"
        f"Диагноз: {diag}{score_line}\n"
        f"Программа: день {day}/28, неделя {wk} — {wt}\n"
        f"С нами с: {created}\n\n"
        "/rank — детали оценки\n/settings — настройки")

async def cmd_settings(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Сменить имя",callback_data="set:name")],
        [InlineKeyboardButton("🔄 Сбросить программу",callback_data="set:reset")],
    ])
    await upd.message.reply_text("⚙️ Настройки:",reply_markup=kb)

async def handle_settings_cb(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    q=upd.callback_query
    await q.answer()
    h=lh();u=gu(h,q.from_user.id)
    if q.data=="set:name":
        u["awaiting_name"]=True;sh(h)
        await q.message.reply_text("Как тебя теперь называть?")
    elif q.data=="set:reset":
        reset_analysis(u);u["state"]=S_PHOTO;sh(h)
        await q.message.reply_text("Программа сброшена. Пришли новое фото 📸")

def main():
    if not TOKEN: raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not OR_KEY: raise RuntimeError("OPENROUTER_API_KEY not set")
    if sys.platform=="win32": asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("help",cmd_help))
    app.add_handler(CommandHandler("next",cmd_next))
    app.add_handler(CommandHandler("status",cmd_status))
    app.add_handler(CommandHandler("rank",cmd_rank))
    app.add_handler(CommandHandler("profile",cmd_profile))
    app.add_handler(CommandHandler("settings",cmd_settings))
    app.add_handler(CallbackQueryHandler(handle_settings_cb,pattern="^set:"))
    app.add_handler(MessageHandler(filters.PHOTO,handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text))
    log.info("="*50);log.info("  SkinCoach v7 — 8-step pipeline");log.info("="*50)
    app.run_polling()

if __name__=="__main__": main()
