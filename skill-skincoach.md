# Скилл для Claude.ai — SkinCoach Context

## Как установить этот скилл

1. Открой [claude.ai](https://claude.ai)
2. Нажми **Customize** (левая панель)
3. Выбери **Skills**
4. Нажми **+** (плюс в правом верхнем углу)
5. Вставь содержимое ниже и сохрани

---

## Название скилла
```
skincoach-context
```

## Описание
```
Контекст проекта SkinCoach — Telegram-бот диагностики кожи
```

## Содержимое скилла (вставить в поле)

```markdown
# SkinCoach Project Context

## Project
Telegram bot for skin disease diagnosis + 28-day treatment protocol.
Stack: Python 3.12, python-telegram-bot, EfficientNet-B3, OpenRouter API, Railway deploy.

## Key files
- bot.py — main bot (503 lines), states: name→dur→tried→photo→questions→active
- inference.py — ML prediction, auto-downloads model from HuggingFace (danyil163/SCINCOACH)
- upload_server.py — HTTP server for photo uploads
- CLAUDE.md — full project context (always read this first)

## Pipeline (8 layers)
1_quality → 2_vision → 3_reasoning → 4_questions → 5_triage → 6_recommendations → 7_safety → 8_response

## LLM via OpenRouter
- Vision: nvidia/nemotron-nano-12b-v2-vl:free
- Reasoners: arcee-ai/trinity-large-preview:free + stepfun/step-3.5-flash:free
- Judge: mistralai/mistral-small-3.1-24b-instruct:free

## Current goal
Improve model quality: add Derm Foundation (google/derm-foundation) as second backbone,
build ensemble with current EfficientNet-B3 model.

## Rules
- Always read CLAUDE.md before making changes
- Never commit env.txt (contains real API keys)
- Deploy target: Railway free tier (~512MB RAM limit)
```

---

## Как использовать после установки

В любом чате Claude.ai напиши:
> "Используй скилл skincoach-context и помоги мне с..."

Или просто начни чат — если скилл включён, он автоматически даст Claude контекст проекта.
