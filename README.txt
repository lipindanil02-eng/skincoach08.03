SkinCoach v6 — Консилиум + 28-дневная программа "Чистая кожа"
================================================================

ФАЙЛЫ:
  bot.py                  — бот
  env.txt                 — шаблон настроек (переименуй в .env)
  vision_prompt.txt       — промпт анализа фото
  reasoner_a_prompt.txt   — промпт дерматолога
  reasoner_b_prompt.txt   — промпт кинезиолога
  judge_prompt.txt        — промпт судьи
  requirements.txt        — зависимости

КАК РАБОТАЕТ:
  Фото → [1] Vision → [2] Дерматолог + [3] Кинезиолог → [4] Судья → План на день

УСТАНОВКА НА СВОЁМ ПК:
  1. Скопируй папку skincoach куда удобно
  2. Переименуй env.txt в .env
  3. В .env вставь свои ключи
  4. Терминал:
     cd путь\к\skincoach
     python -m venv venv
     .\venv\Scripts\Activate
     pip install -r requirements.txt
     python bot.py

ЗАПУСК НА RAILWAY (бесплатно, 24/7):
  1. Зайди на railway.app и войди через GitHub
  2. New Project → Deploy from GitHub repo
  3. Загрузи файлы через GitHub
  4. В Settings → Variables добавь:
     TELEGRAM_BOT_TOKEN = твой_токен
     OPENROUTER_API_KEY = твой_ключ
  5. Railway сам установит зависимости и запустит бота

ЗАПУСК НА RENDER (бесплатно):
  1. Зайди на render.com
  2. New → Background Worker
  3. Подключи GitHub
  4. Build Command: pip install -r requirements.txt
  5. Start Command: python bot.py
  6. В Environment добавь ключи

КОМАНДЫ:
  /start  — регистрация
  /next   — следующий день
  /status — прогресс
  /help   — справка

ПРОМПТЫ:
  Редактируй txt-файлы — код менять не нужно.
  Промпты перечитываются при каждом запросе.
