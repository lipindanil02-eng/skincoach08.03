# SkinCoach — контекст проекта для Claude

## Что это
Telegram-бот для диагностики кожных заболеваний и 28-дневного протокола лечения.
Пользователь присылает фото кожи → бот анализирует → даёт рекомендации + программу.

## Стек
- **Язык:** Python 3.12
- **Бот:** python-telegram-bot 22.6
- **ML модель:** EfficientNet-B3, обучена на HAM10000 (~20k фото), хранится на HuggingFace
  - HuggingFace repo: `danyil163/SCINCOACH`
  - Скачивается автоматически при старте если нет локального файла
- **LLM:** OpenRouter API (Gemini, Nemotron, Arcee, StepFun через fallback-цепочки)
- **Деплой:** Railway (web + bot в одном процессе через Procfile)
- **Upload сервер:** `upload_server.py` — принимает фото для дообучения

## Архитектура пайплайна (8 слоёв)
1. `1_quality.txt` — проверка качества фото
2. `2_vision.txt` — визуальный анализ (vision модель)
3. `3_reasoning.txt` — рассуждение (два реазонера A и B)
4. `4_questions.txt` — уточняющие вопросы пользователю
5. `5_triage.txt` — триаж (срочность)
6. `6_recommendations.txt` — рекомендации
7. `7_safety.txt` — безопасность / дисклеймеры
8. `8_response.txt` — финальный ответ

## Модели OpenRouter
- VISION_MODEL: nvidia/nemotron-nano-12b-v2-vl:free
- REASONER_A + B: arcee-ai/trinity-large-preview:free, stepfun/step-3.5-flash:free
- JUDGE_MODEL: mistralai/mistral-small-3.1-24b-instruct:free
- CHAT_MODEL: arcee-ai/trinity-large-preview:free
- Fallbacks настроены в env.txt

## Ключевые файлы
- `bot.py` — основной файл бота (503 строки), состояния: name→dur→tried→photo→questions→active
- `inference.py` — ML предсказание, загрузка модели с HuggingFace
- `class_map.json` — маппинг классов кожных заболеваний
- `upload_server.py` — HTTP сервер для загрузки фото
- `prepare_dataset.py` — подготовка датасета для обучения
- `env.txt` — переменные окружения (НЕ коммитить в git!)
- `Procfile` — `web: sh -c "python upload_server.py & python -u bot.py"`

## 28-дневная программа
4 недели × 7 дней:
- Неделя 1: Питание
- Неделя 2: Наружный уход
- Неделя 3: Эмоции / стресс
- Неделя 4: Анализы

## Текущий статус и цели
- MVP работает на Railway
- Цель: улучшить качество анализа, добавить Derm Foundation как второй backbone
- Рассматривается ensemble: наша модель + Derm Foundation (google/derm-foundation на HuggingFace)
- Лицензия Derm Foundation: некоммерческая для MVP ок, потом уточнить

## Важные ограничения
- Railway: бесплатный тариф — ограничение RAM ~512MB, CPU
- Модель EfficientNet-B3 загружается с HuggingFace при каждом cold start
- env.txt содержит реальные ключи — не пушить в публичный репозиторий

## Команды для запуска локально
```bash
pip install -r requirements.txt
# Настроить переменные из env.txt
python bot.py
```

## Git
- Основная ветка разработки: указывается в задаче
- Репозиторий: /home/user/skincoach08.03
