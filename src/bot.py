import asyncio
import logging
import threading
import time
from datetime import datetime
from functools import partial
import google.generativeai as genai

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, filters
from apscheduler.schedulers.background import BackgroundScheduler

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_ADMIN_ID,
    GOOGLE_API_KEYS,
)
from scripts.sync_news_database import sync_news_database
from src.parser import get_articles_from_page, get_article_text
from summarizer import (
    summarize_text_local,
    create_digest,
    create_annual_digest,
)
from database import (
    init_db,
    add_article,
    is_article_posted,
    add_digest,
    get_summaries_for_period,
    get_digests_for_period,
    get_stats,
    add_summary,
)
from src.healthcheck import check_parser_health

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    """Устанавливает команды меню после инициализации бота."""
    user_commands = [
        BotCommand("start", "Запустить бота и показать приветствие"),
        BotCommand("status", "Показать текущий статус бота"),
    ]
    await application.bot.set_my_commands(user_commands)

    if TELEGRAM_ADMIN_ID:
        admin_commands = user_commands + [
            BotCommand("check_now", "Принудительно проверить новости"),
            BotCommand("sync_db", "Запустить полную синхронизацию БД"),
            BotCommand("daily_digest", "Сводка за последние 24 часа"),
            BotCommand("weekly_digest", "Сводка за последние 7 дней"),
            BotCommand("monthly_digest", "Сводка за последние 30 дней"),
            BotCommand("annual_digest", "Итоговая годовая сводка"),
            BotCommand("check_keys", "Проверить работоспособность API ключей"),
            BotCommand("healthcheck", "Проверить работоспособность парсера"),
            BotCommand("posted_stats", "Статистика по опубликованным статьям"),
        ]
        try:
            await application.bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=int(TELEGRAM_ADMIN_ID))
            )
            logger.info(f"Установлены расширенные команды для администратора (ID: {TELEGRAM_ADMIN_ID}).")
        except Exception as e:
            logger.error(f"Не удалось установить команды для администратора: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение и список команд."""
    welcome_text = (
        "Приветствую Вас, сударь! Вас ждет великий бот от Gemini и прибыльный новостной канал \"Война и мир!\"\n\n"
        "Доступные команды можно посмотреть в меню."
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус бота, включая время последней и следующей проверки."""
    last_check_time = context.bot_data.get("last_check_time", "Никогда")
    next_check_time = "Не запланировано"

    jobs = context.job_queue.jobs()
    if jobs:
        next_check_time = jobs[0].next_t.strftime("%Y-%m-%d %H:%M:%S")

    google_keys_status = "Активны" if GOOGLE_API_KEYS else "Не найдены"

    status_text = (
        f"Бот работает.\n"
        f"Последняя проверка новостей: {last_check_time}\n"
        f"Следующая проверка новостей: {next_check_time}\n\n"
        f"Статус ключей:\n"
        f"- Google API: {google_keys_status}"
    )
    await update.message.reply_text(status_text)


async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно запускает проверку новостей."""
    await update.message.reply_text("Начинаю принудительную проверку новостей...")
    context.job_queue.run_once(check_and_post_news, 1, user_id=update.effective_user.id)


async def sync_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принудительно запускает полную синхронизацию базы данных."""
    await update.message.reply_text("Начинаю полную синхронизацию базы данных. Это может занять некоторое время...")
    # Запускаем синхронизацию в фоновом потоке, чтобы не блокировать бота
    threading.Thread(target=sync_news_database).start()
    await update.message.reply_text("Процесс синхронизации запущен в фоновом режиме. По завершении в консоли появятся логи.")


async def healthcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполняет проверку работоспособности парсера по запросу."""
    await update.message.reply_text("Начинаю проверку селекторов парсера...")
    is_ok = await asyncio.to_thread(check_parser_health)
    if is_ok:
        await update.message.reply_text("✅ Проверка прошла успешно. Селекторы парсера в порядке.")
    else:
        await update.message.reply_text("❌ ОБНАРУЖЕНА ПРОБЛЕМА! Селекторы парсера не работают. Проверьте логи.")


async def posted_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет статистику по опубликованным статьям."""
    stats = await asyncio.to_thread(get_stats)
    
    last_article_title = stats['last_article']['title']
    last_article_date = stats['last_article']['published_at']
    
    # Преобразуем дату в читаемый формат, если она есть
    if last_article_date != "Нет":
        try:
            # Пример формата из БД: 2025-08-04 18:30:00
            dt_obj = datetime.fromisoformat(last_article_date)
            last_article_date = dt_obj.strftime('%d %B %Y в %H:%M')
        except (ValueError, TypeError):
            # Если формат отличается, оставляем как есть
            pass

    stats_text = (
        f"**Статистика публикаций:**\n\n"
        f"Всего опубликовано статей: **{stats['total_articles']}**\n\n"
        f"**Последняя опубликованная статья:**\n"
        f"- *Заголовок:* {last_article_title}\n"
        f"- *Дата публикации:* {last_article_date}"
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)


async def check_api_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет работоспособность всех ключей Google API."""
    await update.message.reply_text(f"Начинаю проверку {len(GOOGLE_API_KEYS)} ключей Google API...")
    
    async def check_single_key(api_key: str, key_index: int):
        key_identifier = f"Ключ #{key_index + 1} ('{api_key[:4]}...')"
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            response = await model.generate_content_async("Напиши 'привет'")
            if response.text and response.text.strip():
                return f"✅ {key_identifier}: Работает"
            else:
                return f"⚠️ {key_identifier}: Не вернул контент"
        except Exception as e:
            return f"❌ {key_identifier}: Ошибка - {type(e).__name__}"

    results = await asyncio.gather(*[check_single_key(key, i) for i, key in enumerate(GOOGLE_API_KEYS)])
    
    report = "**Отчет по ключам Google API:**\n" + "\n".join(results)
    await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)


async def send_admin_notification(context: ContextTypes.DEFAULT_TYPE, message: str):
    """Отправляет уведомление администратору бота."""
    if TELEGRAM_ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=int(TELEGRAM_ADMIN_ID), text=f"[УВЕДОМЛЕНИЕ]\n\n{message}"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление администратору: {e}")


async def check_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    """Основная логика проверки и публикации новостей с улучшенным мониторингом."""
    logger.info("Начинаю проверку новостей...")
    user_id = context.job.user_id if context.job and hasattr(context.job, 'user_id') else None

    try:
        all_articles = await asyncio.to_thread(get_articles_from_page, 1)
        if not all_articles:
            logger.warning("Парсер не вернул ни одной статьи с главной страницы.")
            await send_admin_notification(
                context,
                "**Сбой парсера: get_articles_from_page**\n\n"
                "Парсер не смог получить список статей с главной страницы. "
                "Возможные причины:\n"
                "- Изменилась верстка сайта.\n"
                "- Сайт временно недоступен.\n"
                "Рекомендуется запустить `/healthcheck` для проверки селекторов."
            )
            if user_id:
                await context.bot.send_message(chat_id=user_id, text="Не удалось получить список статей. Администратор уведомлен.")
            return

        new_articles = [a for a in all_articles if not is_article_posted(a["link"])]
        context.bot_data["last_check_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not new_articles:
            logger.info("Новых статей не найдено.")
            if user_id:
                await context.bot.send_message(chat_id=user_id, text="Новых статей не найдено.")
            return

        logger.info(f"Найдено {len(new_articles)} новых статей. Публикуем не более 3.")
        articles_to_post = sorted(new_articles, key=lambda x: x["published_at"])[:3]

        chat = await context.bot.get_chat(chat_id=TELEGRAM_CHANNEL_ID)
        channel_username = f"@{chat.username}"

        posted_count = 0
        for article in articles_to_post:
            full_text = await asyncio.to_thread(get_article_text, article["link"])
            if not full_text:
                logger.error(f"Не удалось получить текст статьи: {article['link']}")
                await send_admin_notification(
                    context,
                    f"**Сбой парсера: get_article_text**\n\n"
                    f"Не удалось получить полный текст для статьи:\n"
                    f"[{article['title']}]({article['link']})\n\n"
                    f"Статья пропущена. Вероятно, изменилась верстка страницы статьи."
                )
                continue

            summary = await asyncio.to_thread(summarize_text_local, full_text)
            if not summary:
                logger.error(f"Не удалось сгенерировать резюме для статьи: {article['link']}")
                await send_admin_notification(
                    context,
                    f"**Сбой суммаризатора**\n\n"
                    f"Не удалось сгенерировать резюме для статьи:\n"
                    f"[{article['title']}]({article['link']})\n\n"
                    f"Статья пропущена. Проверьте логи и состояние API ключей (`/check_keys`)."
                )
                continue

            message = f"<b>{article['title']}</b>\n\n{summary} {channel_username}"
            await context.bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode=ParseMode.HTML
            )
            article_id = add_article(article["link"], article["title"], article["published_at"])
            if article_id:
                add_summary(article_id, summary)
                posted_count += 1
            await asyncio.sleep(15)
        
        if user_id:
            await context.bot.send_message(chat_id=user_id, text=f"Успешно опубликовано {posted_count} новых статей.")

        logger.info("Проверка новостей успешно завершена.")

    except Exception as e:
        logger.critical(f"Критическая ошибка при проверке новостей: {e}", exc_info=True)
        await send_admin_notification(context, f"**Критическая ошибка в `check_and_post_news`**\n\n`{e}`")
        if user_id:
            await context.bot.send_message(chat_id=user_id, text=f"Произошла критическая ошибка: {e}")


async def handle_digest_request(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, period_name: str, is_annual: bool = False):
    """Общая логика для создания и отправки дайджестов администратору."""
    user_id = update.effective_user.id
    await context.bot.send_message(chat_id=user_id, text=f"Начинаю подготовку сводки за {period_name}...")

    try:
        if is_annual:
            logger.info("Запрошен годовой дайджест.")
            source_digests = await asyncio.to_thread(get_digests_for_period, 365)
            if not source_digests:
                await context.bot.send_message(chat_id=user_id, text="Нет дайджестов за год для анализа.")
                return
            
            logger.info(f"Найдено {len(source_digests)} дайджестов для годового анализа.")
            digest_content = await asyncio.to_thread(create_annual_digest, source_digests)
            period_db_name = "annual"
        else:
            logger.info(f"Запрошен дайджест за {days} дней.")
            summaries = await asyncio.to_thread(get_summaries_for_period, days)
            if not summaries:
                await context.bot.send_message(chat_id=user_id, text=f"Нет статей за указанный период ({period_name}).")
                return

            logger.info(f"Найдено {len(summaries)} сводок для дайджеста.")
            digest_content = await asyncio.to_thread(create_digest, summaries, period_name)
            period_db_name = period_name.lower()

        if not digest_content:
            await context.bot.send_message(chat_id=user_id, text="Не удалось создать аналитическую сводку. Попробуйте позже.")
            return

        await asyncio.to_thread(add_digest, period_db_name, digest_content)
        logger.info(f"Дайджест за {period_name} успешно создан и сохранен в БД.")

        await context.bot.send_message(chat_id=user_id, text=f"**Ваша аналитическая сводка за {period_name}:**\n\n{digest_content}", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Ошибка при создании дайджеста за {period_name}: {e}")
        await context.bot.send_message(chat_id=user_id, text=f"Произошла серьезная ошибка при создании сводки: {e}")


def main():
    """Основная функция, запускающая бота и планировщик."""
    logger.info("Бот запускается...")
    init_db()

    # --- Первичная синхронизация при запуске ---
    logger.info("Запуск первичной синхронизации базы данных перед стартом...")
    sync_news_database()
    scheduler = BackgroundScheduler(timezone="Europe/Moscow")
    scheduler.add_job(sync_news_database, 'interval', hours=4, id="full_db_sync")
    scheduler.start()
    logger.info("Планировщик для полной синхронизации БД запущен (каждые 4 часа).")

    # --- Настройка и запуск Telegram-бота ---
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.bot_data["last_check_time"] = "Никогда"

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))

    if TELEGRAM_ADMIN_ID:
        try:
            admin_id_int = int(TELEGRAM_ADMIN_ID)
            admin_filter = filters.User(user_id=admin_id_int)
            
            application.add_handler(CommandHandler("check_now", check_now, filters=admin_filter))
            application.add_handler(CommandHandler("sync_db", sync_db_command, filters=admin_filter))
            application.add_handler(CommandHandler("check_keys", check_api_keys, filters=admin_filter))
            application.add_handler(CommandHandler("healthcheck", healthcheck, filters=admin_filter))
            application.add_handler(CommandHandler("posted_stats", posted_stats, filters=admin_filter))

            daily_digest_handler = partial(handle_digest_request, days=1, period_name="сутки")
            weekly_digest_handler = partial(handle_digest_request, days=7, period_name="неделю")
            monthly_digest_handler = partial(handle_digest_request, days=30, period_name="месяц")
            annual_digest_handler = partial(handle_digest_request, days=365, period_name="год", is_annual=True)

            application.add_handler(CommandHandler("daily_digest", daily_digest_handler, filters=admin_filter))
            application.add_handler(CommandHandler("weekly_digest", weekly_digest_handler, filters=admin_filter))
            application.add_handler(CommandHandler("monthly_digest", monthly_digest_handler, filters=admin_filter))
            application.add_handler(CommandHandler("annual_digest", annual_digest_handler, filters=admin_filter))
        except (ValueError, TypeError):
            logger.error(f"TELEGRAM_ADMIN_ID ('{TELEGRAM_ADMIN_ID}') имеет неверный формат. Админ-команды не будут загружены.")

    # 5-минутная проверка главной страницы для быстрой публикации
    application.job_queue.run_repeating(check_and_post_news, interval=300, first=10)
    
    logger.info("Запускаю бота в режиме polling...")
    application.run_polling()

    # Чистое завершение работы планировщика при остановке бота
    scheduler.shutdown()

if __name__ == "__main__":
    main()