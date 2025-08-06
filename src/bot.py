import asyncio
import logging
from datetime import datetime
from functools import partial

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID
from database import (
    init_db,
    add_article,
    get_articles_by_status,
    set_article_status,
    update_article_summary,
    get_summaries_for_period,
    get_digests_for_period,
    add_digest,
    get_stats,
    get_article_by_url
)
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local, create_digest, create_annual_digest
from healthcheck import check_parser_health

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Конвейер обработки статей ---

async def find_new_articles_task(context: ContextTypes.DEFAULT_TYPE):
    """Задача: ищет новые статьи на сайте и добавляет их в БД со статусом 'new'."""
    logger.info("[TASK] Запущена задача поиска новых статей...")
    try:
        articles_from_site = await asyncio.to_thread(get_articles_from_page, 1)
        if not articles_from_site:
            logger.warning("Парсер не вернул статей с главной страницы.")
            return

        added_count = 0
        for article_data in articles_from_site:
            # Проверяем, нет ли уже такой статьи, чтобы избежать лишних запросов
            if not get_article_by_url(article_data["link"]):
                add_article(article_data["link"], article_data["title"], article_data["published_at"])
                added_count += 1
        
        if added_count > 0:
            logger.info(f"[TASK] Добавлено {added_count} новых статей со статусом 'new'.")
        else:
            logger.info("[TASK] Новых статей для добавления не найдено.")

    except Exception as e:
        logger.error(f"[TASK] Ошибка в задаче поиска статей: {e}", exc_info=True)

async def summarize_articles_task(context: ContextTypes.DEFAULT_TYPE):
    """Задача: находит статьи со статусом 'new' и генерирует для них резюме."""
    logger.info("[TASK] Запущена задача суммирования статей...")
    articles_to_process = get_articles_by_status('new', limit=5) # Берем по 5, чтобы не перегружать API

    if not articles_to_process:
        logger.info("[TASK] Нет статей для суммирования.")
        return

    logger.info(f"[TASK] Найдено {len(articles_to_process)} статей для суммирования.")
    for article in articles_to_process:
        set_article_status(article['id'], 'summarizing')
        try:
            full_text = await asyncio.to_thread(get_article_text, article["url"])
            if not full_text:
                logger.error(f"Не удалось получить текст статьи: {article['url']}")
                set_article_status(article['id'], 'failed')
                continue

            summary = await asyncio.to_thread(summarize_text_local, full_text)
            if not summary:
                logger.error(f"Не удалось сгенерировать резюме: {article['url']}")
                set_article_status(article['id'], 'failed')
                continue
            
            update_article_summary(article['id'], summary)
            set_article_status(article['id'], 'summarized')
            logger.info(f"Статья #{article['id']} успешно обработана и готова к публикации.")

        except Exception as e:
            logger.error(f"[TASK] Критическая ошибка при обработке статьи #{article['id']}: {e}", exc_info=True)
            set_article_status(article['id'], 'failed')

async def post_articles_task(context: ContextTypes.DEFAULT_TYPE):
    """Задача: публикует статьи со статусом 'summarized' в Telegram канал."""
    logger.info("[TASK] Запущена задача публикации статей...")
    articles_to_post = get_articles_by_status('summarized', limit=3) # Не более 3 за раз

    if not articles_to_post:
        logger.info("[TASK] Нет статей для публикации.")
        return

    logger.info(f"[TASK] Найдено {len(articles_to_post)} статей для публикации.")
    chat = await context.bot.get_chat(chat_id=TELEGRAM_CHANNEL_ID)
    channel_username = f"@{chat.username}"

    for article in articles_to_post:
        try:
            message = f"<b>{article['title']}</b>\n\n{article['summary_text']} {channel_username}"
            await context.bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode=ParseMode.HTML
            )
            set_article_status(article['id'], 'posted')
            logger.info(f"Статья #{article['id']} успешно опубликована в канале.")
            await asyncio.sleep(10) # Пауза между публикациями
        except Exception as e:
            logger.error(f"[TASK] Ошибка при публикации статьи #{article['id']}: {e}", exc_info=True)
            set_article_status(article['id'], 'failed')

# --- Команды бота ---

async def post_init(application: Application):
    """Устанавливает команды и запускает фоновые задачи."""
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
            BotCommand("healthcheck", "Проверить работоспособность парсера"),
        ]
        try:
            await application.bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=int(TELEGRAM_ADMIN_ID))
            )
        except Exception as e:
            logger.error(f"Не удалось установить команды для администратора: {e}")

    # Запуск конвейера задач
    application.job_queue.run_repeating(find_new_articles_task, interval=300, first=10, name="FindNewArticles")
    application.job_queue.run_repeating(summarize_articles_task, interval=120, first=20, name="SummarizeArticles")
    application.job_queue.run_repeating(post_articles_task, interval=180, first=30, name="PostArticles")
    logger.info("Фоновые задачи для поиска, суммирования и публикации статей запущены.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение."""
    await update.message.reply_text("Привет! Я бот для новостного канала 'Война и мир'.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику из базы данных."""
    stats = get_stats()
    by_status = stats.get('by_status', {})
    
    status_text = (
        f"**Статистика базы данных:**\n\n"
        f"Всего статей: **{stats.get('total_articles', 0)}**\n"
        f"- Новые: `{by_status.get('new', 0)}`\n"
        f"- В обработке: `{by_status.get('summarizing', 0)}`\n"
        f"- Обработаны: `{by_status.get('summarized', 0)}`\n"
        f"- Опубликованы: `{by_status.get('posted', 0)}`\n"
        f"- Ошибки: `{by_status.get('failed', 0)}`\n\n"
    )
    
    last_posted = stats.get('last_posted_article', {})
    if last_posted and last_posted.get('title') != 'Нет':
        try:
            dt_obj = datetime.fromisoformat(last_posted['published_at'])
            date_str = dt_obj.strftime('%d %B %Y в %H:%M')
        except (ValueError, TypeError):
            date_str = last_posted['published_at']
        
        status_text += (
            f"**Последняя опубликованная статья:**\n"
            f"- *{last_posted['title']}*\n"
            f"- *{date_str}*"
        )
    
    await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)

async def healthcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет работоспособность парсера."""
    is_ok = await asyncio.to_thread(check_parser_health)
    message = "✅ Парсер работает корректно." if is_ok else "❌ ОБНАРУЖЕНА ПРОБЛЕМА! Селекторы парсера не работают."
    await update.message.reply_text(message)

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
