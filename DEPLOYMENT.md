# Руководство по развертыванию

Это руководство поможет вам развернуть и запустить Telegram-бота "Война и мир".

## 1. Предварительные требования

- **Docker:** Убедитесь, что на вашем сервере установлен [Docker](https://docs.docker.com/engine/install/).
- **Docker Compose:** Установите [Docker Compose](https://docs.docker.com/compose/install/).

## 2. Настройка

1.  **Клонируйте репозиторий:**
    ```bash
    git clone <URL репозитория>
    cd <папка проекта>
    ```

2.  **Создайте файл `.env`:**

    Скопируйте `.env.example` (если он есть) или создайте файл `.env` вручную в корне проекта и добавьте в него следующие переменные:

    ```
    # Токен вашего Telegram-бота (получается у @BotFather)
    TELEGRAM_BOT_TOKEN=12345:your_bot_token_here

    # ID вашего Telegram-канала (например, -1001234567890)
    TELEGRAM_CHANNEL_ID=@your_channel_username

    # (Опционально) ID вашего Telegram-аккаунта для получения уведомлений об ошибках
    TELEGRAM_ADMIN_ID=123456789

    # Ключи API для суммирования
    # Можно указать несколько ключей через запятую для Google API
    GOOGLE_API_KEYS=your_google_api_key_1,your_google_api_key_2
    OPENROUTER_API_KEY=your_openrouter_api_key
    ```

## 3. Запуск и управление

-   **Сборка и запуск (в фоновом режиме):**

    ```bash
    docker-compose up --build -d
    ```

-   **Просмотр логов:**

    ```bash
    docker-compose logs -f
    ```

-   **Проверка статуса контейнера:**

    ```bash
    docker-compose ps
    ```

    Вы должны увидеть, что состояние (State) контейнера `warandpeace-bot` - `Up (healthy)`.

-   **Остановка:**

    ```bash
    docker-compose down
    ```

## 4. Мониторинг

-   **Health Check:** Docker автоматически проверяет работоспособность бота каждые 90 секунд. Если бот не отвечает, он будет автоматически перезапущен.
-   **Логи:** Все события и ошибки записываются в логи Docker. Используйте `docker-compose logs -f` для их просмотра в реальном времени.
-   **Уведомления:** В случае критических ошибок, бот отправит уведомление на `TELEGRAM_ADMIN_ID`, если он указан в `.env`.
