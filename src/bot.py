import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
import requests

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut, RetryAfter, BadRequest, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID, NEWS_URL
from database import (
    init_db,
    add_article,
    is_article_posted,
    get_summaries_for_date_range,
    get_digests_for_period,
    add_digest,
    get_stats,
)
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local, create_digest, create_annual_digest, summarize_with_mistral
from notifications import notify_admin

# Настройка логирования (тихий режим для сторонних библиотек и управляемый уровень для приложения)
log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

verbose_lib_logs = os.getenv("ENABLE_VERBOSE_LIB_LOGS", "false").lower() in {"1", "true", "yes"}
if not verbose_lib_logs:
    for noisy in [
        "telegram",
        "telegram.ext",
        "telegram.request",
        "httpx",
        "httpcore",
        "aiohttp",
        "apscheduler",
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- Основная задача ---

async def check_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    """
    Основная задача: проверяет наличие новых статей, обрабатывает и публикует их.
    """
    logger.debug("[TASK] Запущена задача проверки и публикации новостей...")
    start_time = time.time()
    try:
        # 1. Получаем последние статьи с сайта
        articles_from_site = await asyncio.to_thread(get_articles_from_page, 1)
        if not articles_from_site:
            logger.warning("Парсер не вернул статей с главной страницы.")
            return

        # Сортируем статьи от старых к новым, чтобы публиковать в хронологическом порядке
        articles_from_site.reverse()

        # 2. Отбираем только новые статьи
        new_articles = []
        for article in articles_from_site:
            if not await asyncio.to_thread(is_article_posted, article["link"]):
                new_articles.append(article)

        if not new_articles:
            logger.debug("[TASK] Новых статей для публикации не найдено.")
            return

        # 3. Логируем информацию о найденных статьях
        log_post_examples = int(os.getenv("LOG_POST_EXAMPLES", 3))
        examples = [f'"{a["title"]}" ({a["link"]})' for a in new_articles[:log_post_examples]]
        hidden_count = len(new_articles) - len(examples)
        examples_str = ", ".join(examples)
        if hidden_count > 0:
            examples_str += f" и еще {hidden_count} скрыто."
        logger.info(f"Найдены новые статьи: {len(new_articles)} шт. Примеры: [{examples_str}]")

        # 4. Обработка и публикация
        posted_count = 0
        max_posts_per_run = int(os.getenv("MAX_POSTS_PER_RUN", 3))

        try:
            chat = await context.bot.get_chat(chat_id=TELEGRAM_CHANNEL_ID)
            channel_username = f"@{chat.username}"
        except Exception as e:
            logger.error(f"Не удалось получить информацию о канале: {e}", exc_info=True)
            channel_username = f"@{TELEGRAM_CHANNEL_ID}"  # Fallback

        for article_data in new_articles:
            if posted_count >= max_posts_per_run:
                logger.info(f"Достигнут лимит публикаций ({max_posts_per_run}) за один запуск.")
                break

            logger.debug(f"Обработка статьи: {article_data['title']}")
            try:
                full_text = await asyncio.to_thread(get_article_text, article_data["link"])
                if not full_text:
                    logger.error(f"Не удалось получить текст статьи: {article_data['link']}")
                    continue

                summary = await asyncio.to_thread(summarize_text_local, full_text)
                if not summary:
                    logger.warning(f"Резюме от Gemini не получено, пробую Mistral: {article_data['link']}")
                    summary = await asyncio.to_thread(summarize_with_mistral, full_text)

                if not summary:
                    logger.error(f"Не удалось сгенерировать резюме: {article_data['link']}")
                    continue

                message = f"<b>{article_data['title']}</b>\n\n{summary} {channel_username}"
                await context.bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode=ParseMode.HTML
                )
                logger.info(f"Статья '{article_data['title']}' успешно опубликована.")

                await asyncio.to_thread(
                    add_article,
                    article_data["link"],
                    article_data["title"],
                    article_data["published_at"],
                    summary,
                )
                posted_count += 1
                await asyncio.sleep(10)  # Пауза

            except Exception as e:
                logger.error(f"Ошибка при обработке статьи {article_data['link']}: {e}", exc_info=True)
                await notify_admin(
                    context.bot,
                    f"❗ Ошибка обработки статьи: {type(e).__name__}: {str(e)[:200]}",
                    throttle_key=f"error:process:{article_data['link']}",
                )

        if posted_count > 0:
            duration = time.time() - start_time
            logger.info(
                f"Публикация завершена: опубликовано={posted_count}; "
                f"кандидатов={len(new_articles)}; длительность={duration:.2f}с"
            )

    except Exception as e:
        logger.error(f"[TASK] Критическая ошибка в задаче 'check_and_post_news': {e}", exc_info=True)
        await notify_admin(
            context.bot,
            f"⛔ Критическая ошибка задачи: {type(e).__name__}: {str(e)[:200]}",
            throttle_key="error:check_and_post_news",
        )



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
            BotCommand("daily_digest", "Дайджест за вчерашний день"),
            BotCommand("weekly_digest", "Дайджест за прошлую неделю"),
            BotCommand("monthly_digest", "Дайджест за прошлый месяц"),
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
    stats = await asyncio.to_thread(get_stats)
    
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
        response = await asyncio.to_thread(requests.get, NEWS_URL, timeout=10)
        if response.status_code == 200:
            await update.message.reply_text("✅ Сайт warandpeace.ru доступен.")
        else:
            await update.message.reply_text(f"❌ Сайт вернул статус-код: {response.status_code}.")
    except Exception as e:
        logger.error(f"Ошибка при проверке доступности сайта: {e}")
        await update.message.reply_text(f"❌ Не удалось подключиться к сайту: {e}")
        await notify_admin(
            context.bot,
            f"⚠️ Healthcheck: недоступен сайт новостей: {type(e).__name__}: {str(e)[:200]}",
            throttle_key="error:healthcheck",
        )


# --- Digest Commands ---

async def daily_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет дайджест за предыдущий календарный день."""
    user_id = update.effective_user.id
    await context.bot.send_message(chat_id=user_id, text="Начинаю подготовку дайджеста за вчерашний день...")

    try:
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

        summaries = await asyncio.to_thread(
            get_summaries_for_date_range,
            start_date.isoformat(),
            end_date.isoformat()
        )

        if not summaries:
            await context.bot.send_message(chat_id=user_id, text=f"За {yesterday.strftime('%d.%m.%Y')} не найдено статей для создания дайджеста.")
            return

        period_name = f"вчера, {yesterday.strftime('%d %B %Y')}"
        digest_content = await asyncio.to_thread(create_digest, summaries, period_name)

        if not digest_content:
            await context.bot.send_message(chat_id=user_id, text="Не удалось создать аналитическую сводку.")
            return

        await asyncio.to_thread(add_digest, f"daily_{yesterday.strftime('%Y-%m-%d')}", digest_content)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Аналитический дайджест за {period_name}:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании суточного дайджеста: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


async def weekly_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет дайджест за предыдущую полную неделю (Пн-Вс)."""
    user_id = update.effective_user.id
    await context.bot.send_message(chat_id=user_id, text="Начинаю подготовку дайджеста за прошлую неделю...")

    try:
        today = datetime.now()
        last_sunday = today - timedelta(days=today.isoweekday())
        end_of_last_week = last_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
        start_of_last_week = (end_of_last_week - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

        summaries = await asyncio.to_thread(
            get_summaries_for_date_range,
            start_of_last_week.isoformat(),
            end_of_last_week.isoformat()
        )

        if not summaries:
            await context.bot.send_message(chat_id=user_id, text="За прошлую неделю не найдено статей для создания дайджеста.")
            return

        period_name = f"прошлую неделю ({start_of_last_week.strftime('%d.%m')} - {end_of_last_week.strftime('%d.%m.%Y')})"
        digest_content = await asyncio.to_thread(create_digest, summaries, period_name)

        if not digest_content:
            await context.bot.send_message(chat_id=user_id, text="Не удалось создать аналитическую сводку.")
            return

        await asyncio.to_thread(add_digest, f"weekly_{start_of_last_week.strftime('%Y-%m-%d')}", digest_content)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Аналитический дайджест за {period_name}:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании недельного дайджеста: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


async def monthly_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет дайджест за предыдущий полный месяц."""
    user_id = update.effective_user.id
    await context.bot.send_message(chat_id=user_id, text="Начинаю подготовку дайджеста за прошлый месяц...")

    try:
        today = datetime.now()
        first_day_of_current_month = today.replace(day=1)
        last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)

        start_date = first_day_of_last_month.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = last_day_of_last_month.replace(hour=23, minute=59, second=59, microsecond=999999)

        summaries = await asyncio.to_thread(
            get_summaries_for_date_range,
            start_date.isoformat(),
            end_date.isoformat()
        )

        if not summaries:
            await context.bot.send_message(chat_id=user_id, text="За прошлый месяц не найдено статей для создания дайджеста.")
            return

        period_name = f"прошлый месяц ({start_date.strftime('%B %Y')})"
        digest_content = await asyncio.to_thread(create_digest, summaries, period_name)

        if not digest_content:
            await context.bot.send_message(chat_id=user_id, text="Не удалось создать аналитическую сводку.")
            return

        await asyncio.to_thread(add_digest, f"monthly_{start_date.strftime('%Y-%m')}", digest_content)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Аналитический дайджест за {period_name}:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании месячного дайджеста: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


async def annual_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет годовой дайджест на основе дайджестов за год."""
    user_id = update.effective_user.id
    await context.bot.send_message(chat_id=user_id, text="Начинаю подготовку итоговой годовой сводки...")

    try:
        digests = await asyncio.to_thread(get_digests_for_period, 365)
        if not digests:
            await context.bot.send_message(chat_id=user_id, text="Нет дайджестов за год для анализа.")
            return

        digest_content = await asyncio.to_thread(create_annual_digest, digests)
        if not digest_content:
            await context.bot.send_message(chat_id=user_id, text="Не удалось создать годовую сводку.")
            return

        year = datetime.now().year - 1
        await asyncio.to_thread(add_digest, f"annual_{year}", digest_content)
        await context.bot.send_message(
            chat_id=user_id,
            text=f"**Итоговая аналитическая сводка за {year} год:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании годового дайджеста: {e}", exc_info=True)
        await context.bot.send_message(chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


def main():
    """Основная функция, запускающая бота."""
    logger.info("Инициализация базы данных...")
    init_db()

    logger.info("Создание и запуск приложения-бота...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Глобальный обработчик ошибок PTB
    async def on_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
        err = context.error
        logger.error("Global handler caught an exception", exc_info=True)

        throttle_key = "error:generic"
        if isinstance(err, RetryAfter):
            throttle_key = "error:retry_after"
        elif isinstance(err, TimedOut):
            throttle_key = "error:timeout"
        elif isinstance(err, NetworkError):
            throttle_key = "error:network"
        elif isinstance(err, BadRequest):
            throttle_key = "error:bad_request"

        summary = f"❗ Ошибка бота: {type(err).__name__}: {str(err)[:300]}"
        try:
            await notify_admin(application.bot, summary, throttle_key=throttle_key)
        except Exception:
            logger.exception("Не удалось уведомить администратора об ошибке")

    application.add_error_handler(on_error)

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))

    if TELEGRAM_ADMIN_ID:
        admin_filter = filters.User(user_id=int(TELEGRAM_ADMIN_ID))
        application.add_handler(CommandHandler("healthcheck", healthcheck, filters=admin_filter))
        application.add_handler(CommandHandler("daily_digest", daily_digest_command, filters=admin_filter))
        application.add_handler(CommandHandler("weekly_digest", weekly_digest_command, filters=admin_filter))
        application.add_handler(CommandHandler("monthly_digest", monthly_digest_command, filters=admin_filter))
        application.add_handler(CommandHandler("annual_digest", annual_digest_command, filters=admin_filter))

    application.run_polling()

if __name__ == "__main__":
    main()