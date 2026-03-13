# Labs Feature Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** После фото-диагностики бот рекомендует персонализированный список анализов, принимает результаты (текстом или фото бланка), интерпретирует их через LLM, и напоминает о анализах в 4-ю неделю.

**Architecture:** Гибрид — хардкод для списка анализов (LABS_BASE + LABS_BY_DIAGNOSIS) с нормализацией диагноза через keyword-маппинг; LLM-интерпретация через новый промпт `4b_labs.txt`; новое состояние `S_LABS` встраивается в существующий конечный автомат bot.py.

**Tech Stack:** Python 3.12, python-telegram-bot 22.6, OpenRouter API (REASON_M + TXT_FB fallbacks), pytest для unit-тестов.

---

## File Map

| Файл | Действие | Что меняется |
|------|----------|-------------|
| `bot.py` | Modify | Константы, normalize_diagnosis(), gu(), handle_photo(), handle_text(), cmd_next(), cmd_labs(), main() |
| `4b_labs.txt` | Create | Промпт интерпретации анализов (корень проекта, как все другие `.txt` промпты) |
| `tests/test_labs.py` | Create | Unit-тесты для normalize_diagnosis() и format_labs_message() |

**Примечание:** Файл промпта создаётся в корне проекта (как `1_quality.txt`, `chat.txt` и др.), не в подпапке `prompts/`. Функция `rp()` проверяет корень первым.

**Примечание по ensure_fields:** `gamification.py::ensure_fields()` добавляет поля геймификации. Поля `labs_raw`/`labs_submitted_at` добавляются через миграцию в `gu()` — это единственный механизм, `gamification.py` трогать не нужно.

---

## Chunk 1: Константы и normalize_diagnosis()

### Предварительные шаги

- [ ] **Step 0a: Создать папку tests/ и убедиться что pytest доступен**

```bash
cd /home/user/skincoach08.03 && mkdir -p tests && python -m pytest --version 2>/dev/null || pip install pytest
```
Ожидаем: строка с версией pytest, например `pytest 7.x.x`.

---

### Task 1: Создать тесты для normalize_diagnosis()

**Files:**
- Create: `tests/test_labs.py`

- [ ] **Step 1: Создать файл тестов**

```python
# tests/test_labs.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Импортируем после того как добавим в bot.py
from bot import normalize_diagnosis, LABS_BASE, LABS_BY_DIAGNOSIS, format_labs_message

def test_normalize_melanoma():
    assert normalize_diagnosis("меланома кожи") == "melanoma"
    assert normalize_diagnosis("melanoma") == "melanoma"

def test_normalize_acne():
    assert normalize_diagnosis("акне") == "acne"
    assert normalize_diagnosis("угревая сыпь") == "acne"
    assert normalize_diagnosis("прыщи на коже") == "acne"

def test_normalize_atopy():
    assert normalize_diagnosis("атопический дерматит") == "atopy"
    assert normalize_diagnosis("экзема") == "atopy"

def test_normalize_nevus():
    assert normalize_diagnosis("невус") == "nevus"
    assert normalize_diagnosis("родинка") == "nevus"

def test_normalize_seborrhea():
    assert normalize_diagnosis("себорейный дерматит") == "seborrhea"

def test_normalize_fallback():
    assert normalize_diagnosis("неизвестное заболевание") == "other"
    assert normalize_diagnosis("") == "other"
    assert normalize_diagnosis("требуется уточнение") == "other"

def test_normalize_none_safe():
    # normalize_diagnosis должна не падать на None
    assert normalize_diagnosis(None) == "other"

def test_labs_base_not_empty():
    assert len(LABS_BASE) >= 8

def test_labs_by_diagnosis_has_all_keys():
    for key in ("melanoma", "nevus", "acne", "atopy", "seborrhea", "other"):
        assert key in LABS_BY_DIAGNOSIS

def test_format_labs_message_contains_base():
    msg = format_labs_message("акне")
    assert "ОАК" in msg
    assert "Витамин D" in msg

def test_format_labs_message_contains_diagnosis_extras():
    msg = format_labs_message("акне")
    assert "ДГЭАС" in msg or "тестостерон" in msg.lower()

def test_format_labs_message_no_extras_for_unknown():
    msg = format_labs_message("требуется уточнение")
    assert "Ферритин" in msg or "ТТГ" in msg

def test_format_labs_message_melanoma_urgent_warning():
    msg = format_labs_message("меланома")
    assert "дерматолог" in msg.lower()
    assert "срочно" in msg.lower() or "немедленно" in msg.lower() or "обратись" in msg.lower()
```

- [ ] **Step 2: Запустить тесты — убедиться что падают с ImportError**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_labs.py -v 2>&1 | head -20
```
Ожидаем: `ImportError` или `cannot import name` — функции ещё не существуют.

---

### Task 2: Добавить константы и normalize_diagnosis() в bot.py

**Files:**
- Modify: `bot.py:35` (строка с состояниями)

- [ ] **Step 3: Заменить строку с состояниями (строка 35) на расширенный блок**

Найти:
```python
# States
S_NAME="name";S_DUR="dur";S_TRIED="tried";S_PHOTO="photo";S_QUESTIONS="questions";S_ACTIVE="active"
```

Заменить на:
```python
# States
S_NAME="name";S_DUR="dur";S_TRIED="tried";S_PHOTO="photo";S_QUESTIONS="questions";S_ACTIVE="active"
S_LABS="labs"

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
    "акне":"acne","прыщ":"acne","угр":"acne","acne":"acne",
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
```

- [ ] **Step 4: Запустить тесты — убедиться что все проходят**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_labs.py -v
```
Ожидаем: все тесты PASSED.

- [ ] **Step 5: Commit**

```bash
git add bot.py tests/test_labs.py
git commit -m "feat: add labs constants, normalize_diagnosis(), format_labs_message() with tests"
```

---

## Chunk 2: Промпт 4b_labs.txt

### Task 3: Создать промпт интерпретации анализов

**Files:**
- Create: `4b_labs.txt` (в корне проекта)

- [ ] **Step 1: Создать файл промпта**

Содержимое файла `4b_labs.txt`:
```
Ты — помощник дерматолога-нутрициолога. Пользователь прошёл 8-ступенчатую диагностику кожи.

Диагноз пользователя: {diagnosis}
Имя: {name}
Давность симптомов: {duration}

Анализы пользователя:
{labs_raw}

Задача:
1. Интерпретируй каждый показатель из анализов относительно нормы
2. Объясни что каждое отклонение значит конкретно для кожи при диагнозе {diagnosis}
3. Дай 2-3 конкретных корректировки (добавки, питание, режим)
4. Если показатель в норме — напиши "в норме, продолжай"

Тон: понятный, без медицинского жаргона, тёплый и поддерживающий.
Структура ответа: по каждому показателю отдельный абзац, затем итоговые рекомендации.

ВАЖНО: Это информационная поддержка, не медицинская консультация. В конце добавь одну строку:
"Для точного лечения обратись к дерматологу."
```

- [ ] **Step 2: Проверить что файл читается через rp()**

```bash
cd /home/user/skincoach08.03 && python -c "
from pathlib import Path
p = Path('4b_labs.txt')
print('exists:', p.exists())
txt = p.read_text('utf-8')
print('has {labs_raw}:', '{labs_raw}' in txt)
print('has {diagnosis}:', '{diagnosis}' in txt)
print('len:', len(txt))
"
```
Ожидаем: `exists: True`, оба `has ...: True`, `len > 200`.

- [ ] **Step 3: Commit**

```bash
git add 4b_labs.txt
git commit -m "feat: add 4b_labs.txt prompt for lab results interpretation"
```

---

## Chunk 3: Обновить gu() и добавить interpret_labs()

### Task 4: Обновить gu() для labs полей

**Files:**
- Modify: `bot.py:90-98`

- [ ] **Step 1: В функции `gu()` добавить поля labs_raw и labs_submitted_at**

Найти (строка 92-96):
```python
    if u not in h: h[u]={"state":S_NAME,"name":None,"duration":None,"tried":None,
        "vision_data":None,"reasoning_data":None,"diagnosis":None,"risk":None,
        "recommendations":None,"pending_questions":None,"photo_b64":None,
        "day":0,"week":1,"msgs":[],"created":datetime.now().isoformat(),
        "last_active":datetime.now().isoformat(),"last_reengagement":None}
    h[u]=ensure_fields(h[u])
    return h[u]
```

Заменить на:
```python
    if u not in h: h[u]={"state":S_NAME,"name":None,"duration":None,"tried":None,
        "vision_data":None,"reasoning_data":None,"diagnosis":None,"risk":None,
        "recommendations":None,"pending_questions":None,"photo_b64":None,
        "day":0,"week":1,"msgs":[],"created":datetime.now().isoformat(),
        "last_active":datetime.now().isoformat(),"last_reengagement":None,
        "labs_raw":None,"labs_submitted_at":None}
    h[u]=ensure_fields(h[u])
    # Миграция для существующих пользователей (ensure_fields не знает о labs полях)
    if "labs_raw" not in h[u]: h[u]["labs_raw"]=None
    if "labs_submitted_at" not in h[u]: h[u]["labs_submitted_at"]=None
    return h[u]
```

- [ ] **Step 2: Добавить функцию interpret_labs() перед handle_photo()**

Добавить перед строкой `async def handle_photo(` (строка 367):
```python
async def interpret_labs(u, msg):
    """Вызвать 4b_labs.txt промпт и отправить интерпретацию пользователю"""
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
```

- [ ] **Step 3: Проверить синтаксис**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```
Ожидаем: `OK`

- [ ] **Step 4: Запустить тесты**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_labs.py -v
```
Ожидаем: все PASSED.

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: add labs_raw fields to gu(), add interpret_labs() helper"
```

---

## Chunk 4: S_LABS в handle_photo и handle_text

### Task 5: Добавить OCR-ветку в handle_photo()

**Files:**
- Modify: `bot.py:367-408`

**Примечание:** `call_raw()` возвращает строку (extracted content из OpenRouter response) — это правильный выбор для OCR, так как `ct()` дополнительно чистит markdown-символы через `cm()`, что для OCR-данных лишнее.

- [ ] **Step 1: В handle_photo() добавить ветку S_LABS после проверки онбординга**

Найти (строка 369-370):
```python
    if u["state"] in (S_NAME,S_DUR,S_TRIED):
        await upd.message.reply_text("Сначала познакомимся. /start"); return
```

Добавить ПОСЛЕ этих строк:
```python
    # Если ждём анализы — делаем OCR, не диагностику кожи
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
```

- [ ] **Step 2: Проверить синтаксис**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```
Ожидаем: `OK`

---

### Task 6: Добавить S_LABS ветку в handle_text()

**Files:**
- Modify: `bot.py:302-365`

- [ ] **Step 3: В handle_text() добавить ветку S_LABS перед блоком S_ACTIVE (строка 344)**

Найти строку:
```python
    # Active program - chat
    if u["state"]==S_ACTIVE:
```

Добавить ПЕРЕД ней:
```python
    # Labs input
    if u["state"]==S_LABS:
        t_lower=txt.strip().lower()
        # Выход без ввода
        if any(kw in t_lower for kw in ("пропустить","skip","нет","не сейчас","позже")):
            u["state"]=S_ACTIVE;sh(h)
            await upd.message.reply_text("Хорошо, продолжай программу! Когда сдашь анализы — напиши /labs")
            return
        # Похоже на анализы (цифры, =, :, или ключевые слова)
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
        # Непонятное сообщение
        await upd.message.reply_text(
            "Пришли фото бланка, напиши значения (D=18, цинк=7) или напиши пропустить")
        return
```

- [ ] **Step 4: Проверить синтаксис**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```
Ожидаем: `OK`

- [ ] **Step 5: Запустить все тесты**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_labs.py -v
```
Ожидаем: все PASSED.

- [ ] **Step 6: Commit**

```bash
git add bot.py
git commit -m "feat: add S_LABS branch to handle_photo (OCR) and handle_text"
```

---

## Chunk 5: Переход в S_LABS после диагностики

### Task 7: Отправлять список анализов и переводить в S_LABS после pipeline_final

**Files:**
- Modify: `bot.py` — две точки вызова pipeline_final

Когда вопросы ЕСТЬ, pipeline_final вызывается в handle_text (строка 328-342).
Когда вопросов НЕТ, pipeline_final вызывается в handle_photo (строка 461-468).

- [ ] **Step 1: Обновить handle_text — после pipeline_final добавить переход в S_LABS**

Найти в handle_text (строка 328-342):
```python
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
```

Заменить на:
```python
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
        # Предложить сдать анализы
        labs_msg=format_labs_message(u.get("diagnosis",""))
        u["state"]=S_LABS;sh(h)
        await upd.message.reply_text(labs_msg)
        return
```

- [ ] **Step 2: Обновить handle_photo — ветку "нет вопросов" добавить переход в S_LABS**

Найти в handle_photo:
```python
    # If no questions — proceed to final immediately
    if not questions:
        st2=await upd.message.reply_text("Генерирую план... ⏳")
        try: reply=await pipeline_final(u,"")
        except Exception as e: reply="Ошибка. /next"; log.error(f"Final:{e}")
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"]);sh(h)
        try: await st2.delete()
        except: pass
        await send(upd.message,reply)
```

Заменить на:
```python
    # If no questions — proceed to final immediately
    if not questions:
        st2=await upd.message.reply_text("Генерирую план... ⏳")
        try: reply=await pipeline_final(u,"")
        except Exception as e: reply="Ошибка. /next"; log.error(f"Final:{e}")
        u["msgs"].append({"role":"assistant","content":reply});u["msgs"]=tm(u["msgs"])
        try: await st2.delete()
        except: pass
        await send(upd.message,reply)
        # Предложить сдать анализы
        labs_msg=format_labs_message(u.get("diagnosis",""))
        u["state"]=S_LABS;sh(h)
        await send(upd.message,labs_msg)
```

- [ ] **Step 3: Проверить синтаксис**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```
Ожидаем: `OK`

- [ ] **Step 4: Запустить тесты**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_labs.py -v
```
Ожидаем: все PASSED.

- [ ] **Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: transition to S_LABS after pipeline_final, send lab recommendations"
```

---

## Chunk 6: /labs команда и напоминание неделя 4

### Task 8: Добавить /labs команду

**Files:**
- Modify: `bot.py` — добавить cmd_labs и зарегистрировать в main()

- [ ] **Step 1: Добавить функцию cmd_labs перед cmd_help (строка 570)**

```python
async def cmd_labs(upd:Update,ctx:ContextTypes.DEFAULT_TYPE):
    h=lh();u=gu(h,upd.effective_user.id)
    onboarding=(S_NAME,S_DUR,S_TRIED,S_PHOTO,S_QUESTIONS)
    if u["state"] in onboarding:
        await upd.message.reply_text("Сначала заверши диагностику — пришли фото кожи 📸"); return
    labs_msg=format_labs_message(u.get("diagnosis",""))
    u["state"]=S_LABS;sh(h)
    await upd.message.reply_text(labs_msg)
```

---

### Task 9: Добавить напоминание на день 22 в cmd_next()

**Files:**
- Modify: `bot.py:470-509`

**Важно:** Напоминание отправляется ПОСЛЕ генерации дневного плана, не вместо него. Функция НЕ возвращается досрочно — пользователь получает и план, и напоминание об анализах.

Также: guard на строке 472 `if u["state"]!=S_ACTIVE` нужно расширить чтобы пропускать и `S_LABS`, иначе пользователь не сможет перейти к следующему дню пока ждёт анализы.

- [ ] **Step 2: Обновить guard в cmd_next для S_LABS**

Найти (строка 472):
```python
    if u["state"]!=S_ACTIVE: await upd.message.reply_text("/start"); return
```

Заменить на:
```python
    if u["state"] not in (S_ACTIVE,S_LABS): await upd.message.reply_text("/start"); return
```

- [ ] **Step 3: Добавить напоминание об анализах на день 22 — в конце cmd_next после отправки плана**

Найти в конце cmd_next (строка ~508):
```python
    u["msgs"].append({"role":"assistant","content":plan});u["msgs"]=tm(u["msgs"]);sh(h)
    await send(upd.message, plan + (f"\n\n⭐ +{POINTS['daily_next']} очков" if not gam_suffix else "") + gam_suffix)
```

Заменить на:
```python
    u["msgs"].append({"role":"assistant","content":plan});u["msgs"]=tm(u["msgs"])
    await send(upd.message, plan + (f"\n\n⭐ +{POINTS['daily_next']} очков" if not gam_suffix else "") + gam_suffix)
    # Напоминание об анализах на неделю 4
    if u["day"]==22:
        if u.get("labs_raw"):
            await upd.message.reply_text(
                "🔬 Прошло 3 недели! Обнови анализы для точных рекомендаций.\n"
                "Пришли новые результаты или напиши пропустить.")
        else:
            await upd.message.reply_text(
                "🔬 Неделя 4 — время анализов!\n\n"
                "Ты прошёл 3 недели программы. Теперь важно сдать анализы,\n"
                "чтобы оценить прогресс и скорректировать план.\n\n"
                + format_labs_message(u.get("diagnosis","")))
        u["state"]=S_LABS
    sh(h)
```

- [ ] **Step 4: Зарегистрировать /labs в main() — в set_my_commands**

Найти `BotCommand("bonus","🎁 Бонус за вступление в группу")` и добавить ПОСЛЕ:
```python
            BotCommand("labs","🔬 Анализы — ввести или обновить"),
```

- [ ] **Step 5: Зарегистрировать /labs обработчик в main()**

Найти `app.add_handler(CommandHandler("bonus",cmd_bonus))` и добавить ПОСЛЕ:
```python
    app.add_handler(CommandHandler("labs",cmd_labs))
```

- [ ] **Step 6: Обновить текст /help — добавить /labs**

Найти в cmd_help строку:
```python
        "/bonus — бонус за вступление в группу\n"
```

Заменить на:
```python
        "/bonus — бонус за вступление в группу\n"
        "/labs — ввести или обновить анализы\n"
```

- [ ] **Step 7: Проверить синтаксис**

```bash
cd /home/user/skincoach08.03 && python -c "import bot; print('OK')"
```
Ожидаем: `OK`

- [ ] **Step 8: Запустить все тесты**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/test_labs.py -v
```
Ожидаем: все PASSED.

- [ ] **Step 9: Commit**

```bash
git add bot.py
git commit -m "feat: add /labs command, week-4 reminder on day 22, fix cmd_next guard for S_LABS"
```

---

## Chunk 7: Финальная проверка

### Task 10: Smoke-test и push

- [ ] **Step 1: Полный синтаксис-чек**

```bash
cd /home/user/skincoach08.03 && python -m py_compile bot.py && echo "Syntax OK"
```
Ожидаем: `Syntax OK`

- [ ] **Step 2: Запустить все тесты**

```bash
cd /home/user/skincoach08.03 && python -m pytest tests/ -v
```
Ожидаем: все PASSED.

- [ ] **Step 3: Проверить что все ключевые символы присутствуют в bot.py**

```bash
cd /home/user/skincoach08.03 && grep -n "S_LABS\|normalize_diagnosis\|format_labs_message\|interpret_labs\|cmd_labs\|labs_raw\|4b_labs" bot.py
```
Ожидаем: по несколько строк на каждый ключевой символ.

- [ ] **Step 4: Push**

```bash
git push -u origin claude/review-changes-mmlsibhrp59z2mh3-Xqk1T
```

---

## Итог: что добавили

| Что | Где |
|-----|-----|
| `S_LABS` — новое состояние | `bot.py:35` |
| `LABS_BASE`, `LABS_BY_DIAGNOSIS`, `DIAGNOSIS_NORM` | `bot.py:37+` |
| `normalize_diagnosis()` | `bot.py:~70` |
| `format_labs_message()` — с urgent warning для melanoma | `bot.py:~80` |
| `interpret_labs()` | `bot.py:~367` |
| OCR-ветка в `handle_photo()` | `bot.py:~372` |
| S_LABS-ветка в `handle_text()` | `bot.py:~344` |
| Переход в S_LABS после `pipeline_final` (2 места) | `bot.py:~332`, `~462` |
| Напоминание в день 22 в `cmd_next()` (после плана) | `bot.py:~508` |
| Guard `cmd_next` расширен на `S_LABS` | `bot.py:~472` |
| `cmd_labs()` | `bot.py:~570` |
| Регистрация `/labs` в `main()` | `bot.py:~664` |
| `4b_labs.txt` | корень проекта |
| `tests/test_labs.py` | `tests/` |
