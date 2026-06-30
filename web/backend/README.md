# SkinCoach Web

Веб-версия SkinCoach на FastAPI + HTML/JS фронтенд.

## Установка

```bash
cd web/backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Запуск

```bash
cd web/backend
uvicorn main:app --reload
```

Открой http://127.0.0.1:8000/static/index.html

## Переменные окружения

Скопируй `.env.example` → `.env` и заполни:

- `TELEGRAM_BOT_TOKEN` — для валидации Telegram WebApp
- `OPENROUTER_API_KEY` — для LLM-пайплайна
- `ADMIN_USERNAME` — username админа (по умолчанию kinesispro)

## Что пока заглушено

- `/api/analyze/` — возвращает структуру, но без реального LLM/ML анализа. Следующий шаг — интеграция 8-слойного пайплайна из `bot.py`.
