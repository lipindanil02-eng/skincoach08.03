"""
SkinCoach v7 — 8-слойный пайплайн + уточняющие вопросы + 28-дневная программа
"""
import tempfile, os
from inference import predict_image
import asyncio,json,os,sys,base64,logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,ContextTypes,filters

from core.pipeline import (pipeline_photo, pipeline_final, call_raw, rp, cm, cj, ct,
                           format_fallback, WEEKS, W_EMOJI, FOCUSES)

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
    h[uid]["state"]=S_NAME;h[uid]["msgs"]=[]
    sh(h)
    await upd.message.reply_text(
        "🔬 Бесплатный AI-анализ кожи по фото.\n\n"
        "Я определяю акне, экзему, псориаз, дерматит и ещё 50+ состояний.\n"
        "8-ступенчатый анализ + программа ухода 28 дней.\n\n"
        "Для начала — как тебя зовут?")
    # Share button on start
    share_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("👥 Пригласить друга", url="https://t.me/share/url?url=https://t.me/Bottestvghh_bot&text=%F0%9F%94%AC%20%D0%91%D0%B5%D1%81%D0%BF%D0%BB%D0%B0%D1%82%D0%BD%D1%8B%D0%B9%20AI-%D0%B0%D0%BD%D0%B0%D0%BB%D0%B8%D0%B7%20%D0%BA%D0%BE%D0%B6%D0%B8%20%D0%BF%D0%BE%20%D1%84%D0%BE%D1%82%D0%BE")
    ]])
    await upd.message.reply_text("Знаешь кого-то с проблемами кожи? Поделись ботом 👇", reply_markup=share_kb)

async def handle_text(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;txt=upd.message.text;h=lh();u=gu(h,uid)
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
        u["msgs"]=tm(u["msgs"]);sh(h)
        try: await st.delete()
        except: pass
        await send(upd.message,reply)
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
    if u["state"] in (S_NAME,S_DUR,S_TRIED):
        await upd.message.reply_text("Сначала познакомимся. /start"); return

    st=await upd.message.reply_text(
        "📸 Фото получено. Запускаю 8-ступенчатый анализ...\n\n"
        "1️⃣ Проверка качества фото...\n2️⃣ Описание кожи...\n"
        "3️⃣ Диагностика с вероятностями...\n4️⃣ Подготовка вопросов...\n\n"
        "30-60 сек ⏳")
    await upd.message.chat.send_action(ChatAction.TYPING)

    ph=upd.message.photo[-1];f=await ctx.bot.get_file(ph.file_id)
    b=await f.download_as_bytearray();b64=base64.b64encode(b).decode()

    # Локальная модель
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(b)
        tmp_path = tmp.name
    try:
        skin_result = predict_image(tmp_path)
        u["local_model_result"] = skin_result
    finally:
        os.unlink(tmp_path)

    cap=(upd.message.caption or "").strip()
    u["photo_b64"]=b64[:100]
    result_type,result=await pipeline_photo(b64,cap,u)

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

    sh(h)
    msg=intro+diag_text+q_text
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
        # Generate + send share card
        try:
            from gen_card import generate_card
            rd = u.get("reasoning_data", {}) or {}
            hyps = rd.get("hypotheses", []) or []
            top3 = [(h.get("diagnosis_ru", h.get("diagnosis", "?")), h.get("probability", 0)) for h in hyps[:3]]
            card_path = await asyncio.to_thread(
                generate_card,
                rd.get("primary_diagnosis", "Анализ завершён") or "Анализ завершён",
                f"{rd.get('confidence', 85)}%",
                rd.get("severity", "low") or "low",
                top3,
                str(upd.effective_user.id),
            )
            if os.path.exists(card_path):
                with open(card_path, "rb") as f:
                    await upd.message.reply_photo(f, caption="🔬 SkinCoach — результат анализа")
                os.unlink(card_path)
        except Exception as ce:
            log.warning(f"Card gen fail: {ce}")
        # Share button after analysis
        share_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("👥 Поделиться с другом", url="https://t.me/share/url?url=https://t.me/kinesispro01_bot&text=%F0%9F%94%AC%20%D0%91%D0%B5%D1%81%D0%BF%D0%BB%D0%B0%D1%82%D0%BD%D1%8B%D0%B9%20AI-%D0%B0%D0%BD%D0%B0%D0%BB%D0%B8%D0%B7%20%D0%BA%D0%BE%D0%B6%D0%B8%20%D0%BF%D0%BE%20%D1%84%D0%BE%D1%82%D0%BE")
        ]])
        await upd.message.reply_text("👆 Поделись результатом с другом!", reply_markup=share_kb)

async def cmd_next(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    uid=upd.effective_user.id;h=lh();u=gu(h,uid)
    if u["state"]!=S_ACTIVE: await upd.message.reply_text("/start"); return
    await upd.message.chat.send_action(ChatAction.TYPING)
    u["day"]+=1
    if u["day"]>28:
        await upd.message.reply_text(f"🎉 {u.get('name','')}, программа пройдена! Отправь фото для сравнения.")
        sh(h); return
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
        "/next — следующий день\n/status — прогресс + диагноз\n/start — заново")

def main():
    if not TOKEN: raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    if not OR_KEY: raise RuntimeError("OPENROUTER_API_KEY not set")
    if sys.platform=="win32": asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",cmd_start))
    app.add_handler(CommandHandler("help",cmd_help))
    app.add_handler(CommandHandler("next",cmd_next))
    app.add_handler(CommandHandler("status",cmd_status))
    app.add_handler(MessageHandler(filters.PHOTO,handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text))
    log.info("="*50);log.info("  SkinCoach v7 — 8-step pipeline");log.info("="*50)
    app.run_polling()

if __name__=="__main__": main()
