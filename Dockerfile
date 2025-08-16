# 1. Базовый образ с нужной версией Python
FROM python:3.10-slim

# 2. Установка системных зависимостей (curl для healthcheck, tzdata для часовых поясов)
RUN apt-get update && apt-get install -y curl tzdata age postgresql-client sqlite3 && rm -rf /var/lib/apt/lists/*

# 3. Установка рабочей директории внутри контейнера
WORKDIR /app

# 4. Копирование файла с зависимостями и их установка
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копирование всего остального кода проекта
COPY . .

# 6. Публикация порта метрик и переменные окружения по умолчанию
ENV METRICS_ENABLED=true \
    METRICS_PORT=8000
EXPOSE 8000

# 7. Команда, которая будет выполняться при запуске контейнера
CMD ["python", "src/bot.py"]
LABEL last_build="2025-08-14 00:00:00"
