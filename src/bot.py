import asyncio
import logging
from datetime import datetime
from functools import partial
import requests

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID, NEWS_URL
from database import (
    init_db,
    add_article,
    is_article_posted,
    get_summaries_for_period,
    get_digests_for_period,
    add_digest,
    get_stats,
)
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local, create_digest, create_annual_digest

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Основная задача ---

async def check_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    """
    Основная задача: проверяет наличие новых статей, обрабатывает и публикует их.
    """
    logger.info("[TASK] Запущена задача проверки и публикации новостей...")
    try:
        # 1. Получаем последние статьи с сайта
        articles_from_site = await asyncio.to_thread(get_articles_from_page, 1)
        if not articles_from_site:
            logger.warning("Парсер не вернул статей с главной страницы.")
            return

        # Сортируем статьи от старых к новым, чтобы публиковать в хронологическом порядке
        articles_from_site.reverse()
        
        posted_count = 0
        # Ограничение, чтобы не публиковать слишком много за раз
        max_posts_per_run = 3 

        chat = await context.bot.get_chat(chat_id=TELEGRAM_CHANNEL_ID)
        channel_username = f"@{chat.username}"

        for article_data in articles_from_site:
            if posted_count >= max_posts_per_run:
                logger.info(f"Достигнут лимит публикаций ({max_posts_per_run}) за один запуск.")
                break

            # 2. Проверяем, была ли статья уже опубликована
            if await asyncio.to_thread(is_article_posted, article_data["link"]):
                continue

            logger.info(f"Найдена новая статья для обработки: {article_data['title']}")
            
            try:
                # 3. Полный цикл обработки и публикации
                full_text = await asyncio.to_thread(get_article_text, article_data["link"])
                if not full_text:
                    logger.error(f"Не удалось получить текст статьи: {article_data['link']}")
                    continue

                summary = await asyncio.to_thread(summarize_text_local, full_text)
                if not summary:
                    logger.error(f"Не удалось сгенерировать резюме: {article_data['link']}")
                    continue
                
                # 4. Публикация в Telegram
                message = f"<b>{article_data['title']}</b>\n\n{summary} {channel_username}"
                await context.bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode=ParseMode.HTML
                )
                logger.info(f"Статья '{article_data['title']}' успешно опубликована.")
                
                # 5. Сохранение в БД ПОСЛЕ публикации
                await asyncio.to_thread(
                    add_article, 
                    article_data["link"], 
                    article_data["title"], 
                    article_data["published_at"],
                    summary
                )
                
                posted_count += 1
                await asyncio.sleep(10) # Пауза между публикациями

            except Exception as e:
                logger.error(f"Ошибка при полной обработке статьи {article_data['link']}: {e}", exc_info=True)
        
        if posted_count == 0:
            logger.info("[TASK] Новых статей для публикации не найдено.")

    except Exception as e:
        logger.error(f"[TASK] Критическая ошибка в задаче 'check_and_post_news': {e}", exc_info=True)


# --- Команды бота ---

async def post_init(application: Application):
    """Устанавливает команды и запускает фоновую задачу."""
    user_commands = [
        BotCommand("start", "Запустить бота и показать приветствие"),
        BotCommand("status", "Показать текущий статус (статистика)"),
    ]
    await application.bot.set_my_commands(user_commands)

    if TELEGRAM_ADMIN_ID:
        admin_commands = user_commands + [
            BotCommand("daily_digest", "Сводка за последние 24 часа"),
            BotCommand("weekly_digest", "Сводка за последние 7 дней"),
            BotCommand("monthly_digest", "Сводка за последние 30 дней"),
            BotCommand("annual_digest", "Итоговая годовая сводка"),
            BotCommand("healthcheck", "Проверить доступность сайта"),
        ]
        try:
            await application.bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=int(TELEGRAM_ADMIN_ID))
            )
        except Exception as e:
            logger.error(f"Не удалось установить команды для администратора: {e}")

    # Запуск единой задачи
    application.job_queue.run_repeating(check_and_post_news, interval=300, first=10, name="CheckAndPostNews")
    logger.info("Единая фоновая задача для проверки и публикации новостей запущена.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение."""
    await update.message.reply_text("Привет! Я бот для новостного канала 'Война и мир'.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику из базы данных."""
    stats = get_stats()
    
    status_text = (
        f"**Статистика базы данных:**\n\n"
        f"Всего опубликованных статей: **{stats.get('total_articles', 0)}**\n\n"
    )
    
    last_posted = stats.get('last_posted_article', {})
    if last_posted and last_posted.get('title') != 'Нет':
        try:
            # Преобразование строки ISO в объект datetime
            dt_obj = datetime.fromisoformat(last_posted['published_at'])
            # Форматирование для вывода
            date_str = dt_obj.strftime('%d %B %Y в %H:%M')
        except (ValueError, TypeError):
            date_str = last_posted['published_at'] # Fallback
        
        status_text += (
            f"**Последняя опубликованная статья:**\n"
            f"- *{last_posted['title']}*\n"
            f"- *{date_str}*"
        )
    
    await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)

async def healthcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет доступность сайта новостей."""
    message = "Проверяю доступность сайта..."
    await update.message.reply_text(message)
    try:
        response = await asyncio.to_thread(requests.get, NEWS_URL, {'timeout': 10})
        if response.status_code == 200:
            await update.message.reply_text("✅ Сайт warandpeace.ru доступен.")
        else:
            await update.message.reply_text(f"❌ Сайт вернул статус-код: {response.status_code}.")
    except Exception as e:
        logger.error(f"Ошибка при проверке доступности сайта: {e}")
        await update.message.reply_text(f"❌ Не удалось подключиться к сайту: {e}")


async def handle_digest_request(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, period_name: str, is_annual: bool = False):
    """Общая логика для создания и отправки дайджестов."""
    user_id = update.effective_user.id
    await context.bot.send_message(chat_id=user_id, text=f"Начинаю подготовку сводки за {period_name}...")

    try:
        if is_annual:
            source_data = get_digests_for_period(365)
            if not source_data:
                await context.bot.send_message(chat_id=user_id, text="Нет дайджестов за год для анализа.")
                return
            digest_content = await asyncio.to_thread(create_annual_digest, source_data)
            period_db_name = "annual"
        else:
            source_data = get_summaries_for_period(days)
            if not source_data:
                await context.bot.send_message(chat_id=user_id, text=f"Нет статей за указанный период ({period_name}).")
                return
            digest_content = await asyncio.to_thread(create_digest, source_data, period_name)
            period_db_name = period_name.lower()

        if not digest_content:
            await context.bot.send_message(chat_id=user_id, text="Не удалось создать аналитическую сводку.")
            return

        add_digest(period_db_name, digest_content)
        await context.bot.send_message(chat_id=user_id, text=f"**Аналитическая сводка за {period_name}:**\n\n{digest_content}", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Ошибка при создании дайджеста за {period_name}: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")

def main():
    """Основная функция, запускающая бота."""
    logger.info("Инициализация базы данных...")
    init_db()

    logger.info("Создание и запуск приложения-бота...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))

    if TELEGRAM_ADMIN_ID:
        admin_filter = filters.User(user_id=int(TELEGRAM_ADMIN_ID))
        application.add_handler(CommandHandler("healthcheck", healthcheck, filters=admin_filter))
        application.add_handler(CommandHandler("daily_digest", partial(handle_digest_request, days=1, period_name="сутки"), filters=admin_filter))
        application.add_handler(CommandHandler("weekly_digest", partial(handle_digest_request, days=7, period_name="неделю"), filters=admin_filter))
        application.add_handler(CommandHandler("monthly_digest", partial(handle_digest_request, days=30, period_name="месяц"), filters=admin_filter))
        application.add_handler(CommandHandler("annual_digest", partial(handle_digest_request, days=365, period_name="год", is_annual=True), filters=admin_filter))

    application.run_polling()

if __name__ == "__main__":
    main()
