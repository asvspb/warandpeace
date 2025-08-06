# 1. Базовый образ с нужной версией Python
FROM python:3.10-slim

# 2. Установка curl
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# 3. Установка рабочей директории внутри контейнера
WORKDIR /app

# 4. Копирование файла с зависимостями и их установка
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копирование всего остального кода проекта
COPY . .

# 6. Запуск скрипта миграции базы данных
RUN python scripts/migrate_db_to_status_model.py

# 7. Команда, которая будет выполняться при запуске контейнера
CMD ["python", "src/bot.py"]
