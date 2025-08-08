import asyncio
import logging
import threading
from datetime import datetime

from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, filters
from telegram import Update

from config import (
    TELEGRAM_BOT_TOKEN, 
    TELEGRAM_CHANNEL_ID, 
    TELEGRAM_ADMIN_ID, 
    GOOGLE_API_KEYS, 
    OPENROUTER_API_KEY
)
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local
from database import init_db, add_article, is_article_posted
from healthcheck import run_health_check_server

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение и список команд."""
    welcome_text = (
        "Приветствую Вас, сударь! Вас ждет великий бот от Gemini и прибыльный новостной канал \"Война и мир!\"\n\n"
        "Доступные команды:\n"
        "/start - показать это сообщение\n"
        "/check_now - принудительно проверить новости\n"
        "/status - показать статус бота"
    )
    await update.message.reply_text(welcome_text)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус бота, включая время последней и следующей проверки."""
    last_check_time = context.bot_data.get("last_check_time", "Никогда")
    next_check_time = "Не запланировано"

    jobs = context.job_queue.jobs()
    if jobs:
        next_check_time = jobs[0].next_t.strftime("%Y-%m-%d %H:%M:%S")

    google_keys_status = "Активны" if GOOGLE_API_KEYS else "Не найдены"
    openrouter_key_status = "Активен" if OPENROUTER_API_KEY else "Не найден"

    status_text = (
        f"Бот работает.\n"
        f"Последняя проверка новостей: {last_check_time}\n"
        f"Следующая проверка новостей: {next_check_time}\n\n"
        f"Статус ключей:\n"
        f"- Google API: {google_keys_status}\n"
        f"- OpenRouter API: {openrouter_key_status}"
    )
    await update.message.reply_text(status_text)


async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно запускает проверку новостей."""
    await update.message.reply_text("Начинаю принудительную проверку новостей...")
    context.job_queue.run_once(check_and_post_news, 1, user_id=update.effective_user.id)


async def send_admin_notification(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Отправляет уведомление администратору бота."""
    if TELEGRAM_ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=TELEGRAM_ADMIN_ID, text=f"[УВЕДОМЛЕНИЕ]\n\n{message}"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление администратору: {e}")


async def fetch_new_articles(hours: int = 24) -> list:
    """Получает все статьи со страницы и фильтрует те, что уже есть в БД."""
    logger.info(f"Получение статей за последние {hours} часов...")
    all_articles = await asyncio.to_thread(get_articles_from_page, 1)
    if not all_articles:
        logger.info("Не удалось получить список статей с сайта.")
        return []
    
    new_articles = [a for a in all_articles if not is_article_posted(a["link"])]
    logger.info(f"Найдено {len(new_articles)} новых статей.")
    return new_articles

async def summarize_and_prepare(article: dict, channel_username: str) -> str | None:
    """Получает полный текст, суммирует и форматирует сообщение для телеграм."""
    full_text = await asyncio.to_thread(get_article_text, article["link"])
    if not full_text:
        logger.warning(f"Не удалось получить полный текст для статьи: {article['link']}")
        return None

    summary = await asyncio.to_thread(summarize_text_local, full_text)
    if not summary:
        logger.warning(f"Не удалось создать резюме для статьи: {article['link']}")
        return None

    return f"<b>{article['title']}</b>\n\n{summary} {channel_username}"

async def publish_article(context: ContextTypes.DEFAULT_TYPE, article: dict, message: str):
    """Публикует одну статью в телеграм и сохраняет в БД."""
    await context.bot.send_message(
        chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode=ParseMode.HTML
    )
    add_article(article["link"], article["title"])
    logger.info(f"Опубликована статья: {article['title']}")

async def check_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    """Основная логика проверки и публикации новостей (оркестратор)."""
    logger.info("Начинаю проверку новостей...")
    user_id = context.job.user_id if context.job and hasattr(context.job, 'user_id') else None

    try:
        new_articles = await fetch_new_articles()
        context.bot_data["last_check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not new_articles:
            logger.info("Новых статей для публикации нет.")
            if user_id:
                await context.bot.send_message(chat_id=user_id, text="Новых статей не найдено.")
            return

        articles_to_post = sorted(new_articles, key=lambda x: (x.get("date"), x.get("time")))[:3]
        logger.info(f"Будет опубликовано {len(articles_to_post)} из {len(new_articles)} новых статей.")

        chat = await context.bot.get_chat(chat_id=TELEGRAM_CHANNEL_ID)
        channel_username = f"@{chat.username}"

        published_count = 0
        for article in articles_to_post:
            message = await summarize_and_prepare(article, channel_username)
            if message:
                await publish_article(context, article, message)
                published_count += 1
                await asyncio.sleep(15)
        
        if user_id:
            await context.bot.send_message(chat_id=user_id, text=f"Успешно опубликовано {published_count} новых статей.")

        logger.info("Проверка новостей успешно завершена.")

    except Exception as e:
        logger.critical(f"Критическая ошибка при проверке новостей: {e}", exc_info=True)
        await send_admin_notification(context, f"Критическая ошибка: {e}")
        if user_id:
            await context.bot.send_message(chat_id=user_id, text=f"Произошла ошибка: {e}")


def main():
    """Основная функция, запускающая бота."""
    logger.info("Бот запускается...")
    init_db()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Инициализация данных бота
    application.bot_data["last_check_time"] = "Никогда"

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    if TELEGRAM_ADMIN_ID:
        admin_filter = filters.User(user_id=int(TELEGRAM_ADMIN_ID))
        application.add_handler(CommandHandler("check_now", check_now, filters=admin_filter))

    # Запуск фоновой задачи
    application.job_queue.run_repeating(check_and_post_news, interval=300, first=10)

    # Запуск health check сервера
    threading.Thread(target=run_health_check_server, daemon=True).start()

    application.run_polling()


if __name__ == "__main__":
    main()