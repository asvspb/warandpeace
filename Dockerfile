# 1. Базовый образ с нужной версией Python
FROM python:3.10-slim

# 2. Установка рабочей директории внутри контейнера
WORKDIR /app

# 3. Копирование файла с зависимостями и их установка
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Копирование всего остального кода проекта
COPY . .

# 5. Команда, которая будет выполняться при запуске контейнера
CMD ["python", "src/bot.py"]
