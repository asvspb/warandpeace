import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
import requests

from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut, RetryAfter, BadRequest, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, filters, JobQueue
from telegram.request import HTTPXRequest

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    TELEGRAM_ADMIN_ID,
    NEWS_URL,
    APP_TZ,
)
from time_utils import now_msk, to_utc, utc_to_local
from metrics import start_metrics_server, JOB_DURATION, ARTICLES_POSTED, ERRORS_TOTAL, update_last_article_age
from database import (
    init_db,
    add_article,
    is_article_posted,
    get_summaries_for_date_range,
    get_digests_for_period,
    add_digest,
    get_stats,
    get_last_posted_article,
    set_article_summary,
    enqueue_publication,
    dequeue_batch,
    delete_sent_publication,
    increment_attempt_count,
)
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local, create_digest, create_annual_digest, summarize_with_mistral
from notifications import notify_admin

# Настройка логирования (тихий режим для сторонних библиотек и управляемый уровень для приложения)
log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_name, logging.INFO)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%d-%m.%y - [%H:%M]",
    force=True,
)

# Явно переназначаем форматтер всем текущим обработчикам корневого логгера
_root = logging.getLogger()
_formatter = logging.Formatter(
    fmt="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%d-%m.%y - [%H:%M]",
)
for _h in list(_root.handlers):
    try:
        _h.setFormatter(_formatter)
    except Exception:
        pass

# Селективно подавляем шумные ошибки DNS от петли polling PTB
class _SuppressUpdaterDnsErrors(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover (зависит от окружения)
        try:
            if record.name.startswith("telegram.ext"):
                msg = record.getMessage()
                if (
                    "Error while getting Updates" in msg
                    and "Temporary failure in name resolution" in msg
                ):
                    return False
        except Exception:
            # В сомнительных случаях не фильтруем
            return True
        return True

logging.getLogger("telegram.ext._updater").addFilter(_SuppressUpdaterDnsErrors())

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

# Импортируем предохранитель после настройки логирования,
# чтобы первое сообщение тоже было в новом формате
from connectivity import circuit_breaker, log_network_context  # noqa: E402

# --- Утилиты с ретраями и Circuit Breaker ---

class CircuitBreakerOpenError(Exception):
    """Исключение, выбрасываемое, когда Circuit Breaker находится в состоянии OPEN."""
    pass

def _on_retry_before_sleep(retry_state):
    """Логирует информацию перед повторной попыткой и фиксирует сбой для CB."""
    exc = retry_state.outcome.exception()
    logger.warning(
        "Retrying Telegram API call due to %s. Attempt #%d...",
        exc,
        retry_state.attempt_number,
    )
    circuit_breaker.note_failure()

# Ретраим только сетевые/временные ошибки Telegram
_retry_condition = retry_if_exception_type((NetworkError, TimedOut, RetryAfter))

# Настройка для повторных попыток с экспоненциальной задержкой
telegram_api_retry = retry(
    stop=stop_after_attempt(int(os.getenv("TG_RETRY_ATTEMPTS", "4"))),  # 1 основная + 3 повторных
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=_retry_condition,
    before_sleep=_on_retry_before_sleep,
)

async def _execute_telegram_call(func, **kwargs):
    """
    Выполняет вызов к Telegram API, проверяя состояние Circuit Breaker.
    """
    if circuit_breaker.is_open():
        logger.warning("Circuit Breaker is OPEN. Skipping Telegram API call.")
        raise CircuitBreakerOpenError("Circuit Breaker is open")
    
    try:
        result = await func(**kwargs)
        circuit_breaker.note_success()
        return result
    except (NetworkError, TimedOut, RetryAfter) as e:
        # Отметим сбой и пробросим для ретраев tenacity
        circuit_breaker.note_failure()
        raise e
    except Exception:
        # Другие ошибки (например, BadRequest) — без ретраев
        raise

@telegram_api_retry
async def send_message_with_retry(bot, **kwargs):
    """Обертка для bot.send_message с логикой Circuit Breaker и ретраями."""
    return await _execute_telegram_call(bot.send_message, **kwargs)

@telegram_api_retry
async def get_chat_with_retry(bot, **kwargs):
    """Обертка для bot.get_chat с логикой Circuit Breaker и ретраями."""
    return await _execute_telegram_call(bot.get_chat, **kwargs)

# --- Основная задача ---

async def check_and_post_news(context: ContextTypes.DEFAULT_TYPE):
    """
    Основная задача: проверяет наличие новых статей, обрабатывает и публикует их.
    """
    logger.debug("[TASK] Запущена задача проверки и публикации новостей...")
    try:
        log_network_context("NET: check_and_post_news")
    except Exception:
        pass
    
    if circuit_breaker.is_open():
        logger.warning("[TASK] Circuit Breaker находится в состоянии OPEN. Пропуск основного цикла задачи.")
        return
        
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
        logger.info(f"Найдены новые статьи: {len(new_articles)} шт. [{examples_str}]")

        # 4. Обработка и публикация
        posted_count = 0
        max_posts_per_run = int(os.getenv("MAX_POSTS_PER_RUN", 3))

        try:
            chat = await get_chat_with_retry(bot=context.bot, chat_id=TELEGRAM_CHANNEL_ID)
            channel_username = f"@{chat.username}"
        except Exception as e:
            logger.error(f"Не удалось получить информацию о канале после нескольких попыток: {e}", exc_info=True)
            channel_username = f"@{TELEGRAM_CHANNEL_ID}"  # Fallback

        for article_data in new_articles:
            if posted_count >= max_posts_per_run:
                logger.info(f"Достигнут лимит публикаций ({max_posts_per_run}) за один запуск.")
                break

            logger.debug(f"Обработка статьи: {article_data['title']}")
            
            published_at_utc_iso = to_utc(article_data["published_at"], APP_TZ).isoformat()

            try:
                full_text = None
                summary = None
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
                await send_message_with_retry(
                    bot=context.bot, chat_id=TELEGRAM_CHANNEL_ID, text=message, parse_mode=ParseMode.HTML
                )
                logger.info(f"Статья '{article_data['title']}' успешно опубликована.")
                ARTICLES_POSTED.inc()

                await asyncio.to_thread(
                    add_article,
                    article_data["link"],
                    article_data["title"],
                    published_at_utc_iso,
                    summary,
                )
                posted_count += 1
                await asyncio.sleep(10)  # Пауза

            except CircuitBreakerOpenError:
                logger.warning(f"Отправка статьи '{article_data['title']}' отложена (Circuit Breaker OPEN).")
                # Добавляем в очередь только если у нас есть резюме
                # Если резюме нет, оно будет сгенерировано при обработке очереди
                await asyncio.to_thread(
                    enqueue_publication,
                    url=article_data["link"],
                    title=article_data["title"],
                    published_at=published_at_utc_iso,
                    summary_text=(summary if summary else "")
                )
            except Exception as e:
                error_message = f"Ошибка при обработке статьи {article_data['link']}: {e}"
                logger.error(error_message, exc_info=True)
                # Добавляем в очередь. Если резюме отсутствует, оно будет сгенерировано позже
                await asyncio.to_thread(
                    enqueue_publication,
                    url=article_data["link"],
                    title=article_data["title"],
                    published_at=published_at_utc_iso,
                    summary_text=(summary if summary else "")
                )
                await notify_admin(
                    context.bot,
                    f"❗ Ошибка обработки статьи (статья добавлена в очередь): {type(e).__name__}: {str(e)[:200]}",
                    throttle_key=f"error:process:{article_data['link']}",
                )

        if posted_count > 0:
            duration = time.time() - start_time
            logger.info(
                f"Публикация завершена: опубликовано={posted_count}; "
                f"кандидатов={len(new_articles)}; длительность={duration:.2f}с"
            )
            # Обновляем метрику возраста последней статьи
            try:
                from database import get_stats
                stats = await asyncio.to_thread(get_stats)
                last = stats.get('last_posted_article', {})
                update_last_article_age(last.get('published_at'))
            except Exception:
                pass

    except Exception as e:
        logger.error(f"[TASK] Критическая ошибка в задаче 'check_and_post_news': {e}", exc_info=True)
        ERRORS_TOTAL.labels(type=type(e).__name__).inc()
        await notify_admin(
            context.bot,
            f"⛔ Критическая ошибка задачи: {type(e).__name__}: {str(e)[:200]}",
            throttle_key="error:check_and_post_news",
        )


# --- Команды бота ---

async def flush_pending_publications(context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет отложенные публикации из очереди.
    """
    logger.debug("[TASK] Запущена задача отправки отложенных публикаций...")
    try:
        log_network_context("NET: flush_pending")
    except Exception:
        pass
    
    if circuit_breaker.is_open():
        logger.warning("[TASK] Circuit Breaker находится в состоянии OPEN. Пропуск отправки из очереди.")
        return

    pending_articles = await asyncio.to_thread(dequeue_batch, limit=5)
    if not pending_articles:
        logger.debug("[TASK] Очередь отложенных публикаций пуста.")
        return

    logger.info(f"Найдено {len(pending_articles)} отложенных публикаций. Начинаю отправку.")
    
    try:
        chat = await get_chat_with_retry(bot=context.bot, chat_id=TELEGRAM_CHANNEL_ID)
        channel_username = f"@{chat.username}"
    except Exception as e:
        logger.error(f"Не удалось получить информацию о канале для отправки из очереди: {e}", exc_info=True)
        channel_username = f"@{TELEGRAM_CHANNEL_ID}"  # Fallback

    for article in pending_articles:
        try:
            # Проверяем наличие резюме и генерируем его при необходимости
            summary_text = article.get('summary_text', '').strip()
            
            if not summary_text:
                logger.info(f"Резюме отсутствует для статьи '{article['title']}'. Генерирую...")
                
                # Получаем полный текст статьи
                full_text = await asyncio.to_thread(get_article_text, article["url"])
                if not full_text:
                    logger.error(f"Не удалось получить текст статьи для генерации резюме: {article['url']}")
                    # Пропускаем эту статью и увеличиваем счетчик попыток
                    await asyncio.to_thread(increment_attempt_count, article["id"], "Failed to fetch article text")
                    continue
                
                # Генерируем резюме
                summary_text = await asyncio.to_thread(summarize_text_local, full_text)
                if not summary_text:
                    logger.warning(f"Резюме от Gemini не получено, пробую Mistral: {article['url']}")
                    summary_text = await asyncio.to_thread(summarize_with_mistral, full_text)
                
                if not summary_text:
                    logger.error(f"Не удалось сгенерировать резюме для отложенной статьи: {article['url']}")
                    # Пропускаем эту статью и увеличиваем счетчик попыток
                    await asyncio.to_thread(increment_attempt_count, article["id"], "Failed to generate summary")
                    continue
                
                logger.info(f"Резюме успешно сгенерировано для статьи '{article['title']}'")
                
                # Сохраняем сгенерированное резюме обратно в очередь
                from database import update_publication_summary
                await asyncio.to_thread(update_publication_summary, article["id"], summary_text)
            
            # Формируем и отправляем сообщение
            message = f"<b>{article['title']}</b>\n\n{summary_text} {channel_username}"
            await send_message_with_retry(
                bot=context.bot,
                chat_id=TELEGRAM_CHANNEL_ID,
                text=message,
                parse_mode=ParseMode.HTML
            )
            
            # Если успешно, добавляем в основную таблицу и удаляем из очереди
            # published_at уже в UTC из очереди
            await asyncio.to_thread(
                add_article,
                article["url"],
                article["title"],
                article["published_at"],
                summary_text,  # Используем актуальное резюме
            )
            await asyncio.to_thread(delete_sent_publication, article["id"])
            logger.info(f"Отложенная статья '{article['title']}' успешно опубликована.")
            ARTICLES_POSTED.inc()
            await asyncio.sleep(10) # Пауза

        except Exception as e:
            error_message = f"Не удалось отправить отложенную статью ID {article['id']}: {e}"
            logger.error(error_message, exc_info=True)
            await asyncio.to_thread(increment_attempt_count, article["id"], str(e))
            # Если это была ошибка из-за Circuit Breaker, прерываем цикл, чтобы не долбиться в закрытую дверь
            if isinstance(e, CircuitBreakerOpenError):
                logger.warning("Останавливаю задачу отправки из очереди, т.к. Circuit Breaker перешел в OPEN.")
                break


async def post_init(application: Application):
    """Устанавливает команды и запускает фоновую задачу."""
    user_commands = [
        BotCommand("start", "Запустить бота и показать приветствие"),
        BotCommand("status", "Показать текущий статус (статистика)"),
    ]
    await application.bot.set_my_commands(user_commands)

    if TELEGRAM_ADMIN_ID:
        admin_commands = user_commands + [
            BotCommand("reissue", "Перевыпуск новости"),
            BotCommand("daily_digest", "Дайджест за вчерашний день"),
            BotCommand("weekly_digest", "Дайджест за прошлую неделю"),
            # BotCommand("monthly_digest", "Дайджест за прошлый месяц"),
            # BotCommand("annual_digest", "Итоговая годовая сводка"),
            # BotCommand("healthcheck", "Проверить доступность сайта"),
        ]
        try:
            await application.bot.set_my_commands(
                admin_commands, scope=BotCommandScopeChat(chat_id=int(TELEGRAM_ADMIN_ID))
            )
        except Exception as e:
            logger.error(f"Не удалось установить команды для администратора: {e}")

    # Запуск единой задачи
    job_kwargs = {
        "misfire_grace_time": int(os.getenv("JOB_MISFIRE_GRACE", "60")),
        "coalesce": True,
        "max_instances": 1,
        "jitter": int(os.getenv("JOB_JITTER", "3")),
    }
    application.job_queue.run_repeating(
        check_and_post_news,
        interval=300,
        first=10,
        name="CheckAndPostNews",
        job_kwargs=job_kwargs,
    )
    logger.info("Единая фоновая задача для проверки и публикации новостей запущена.")

    # Запуск задачи для отправки из очереди
    application.job_queue.run_repeating(
        flush_pending_publications,
        interval=120,  # Каждые 2 минуты
        first=20,
        name="FlushPendingPublications",
        job_kwargs=job_kwargs,
    )
    logger.info("Фоновая задача для отправки отложенных публикаций запущена.")

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
            # Строка из БД — в UTC. Конвертируем в aware datetime UTC, затем в MSK.
            utc_dt = datetime.fromisoformat(last_posted['published_at'].replace("Z", "+00:00"))
            local_dt = utc_to_local(utc_dt, APP_TZ)
            date_str = local_dt.strftime('%d %B %Y в %H:%M')
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

async def reissue_last_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перевыпускает последнюю опубликованную новость: пересуммаризация и повторная отправка."""
    user_id = update.effective_user.id
    await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Перевыпускаю последнюю новость...")

    try:
        last = await asyncio.to_thread(get_last_posted_article)
        if not last or not last.get("url"):
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Нет опубликованных статей для перевыпуска.")
            return

        # Получаем полный текст снова (вдруг статья изменилась)
        full_text = await asyncio.to_thread(get_article_text, last["url"])
        if not full_text:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Не удалось получить текст статьи для пересуммаризации.")
            return

        # Генерация резюме с фолбэком на Mistral
        summary = await asyncio.to_thread(summarize_text_local, full_text)
        if not summary:
            summary = await asyncio.to_thread(summarize_with_mistral, full_text)
        if not summary:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Не удалось сгенерировать новое резюме.")
            return

        # Получим username канала (для хвостовой подписи) с ретраями
        try:
            chat = await get_chat_with_retry(bot=context.bot, chat_id=TELEGRAM_CHANNEL_ID)
            channel_username = f"@{chat.username}"
        except Exception:
            channel_username = f"@{TELEGRAM_CHANNEL_ID}"

        message = f"<b>{last['title']}</b>\n\n{summary} {channel_username}"
        await send_message_with_retry(
            bot=context.bot,
            chat_id=TELEGRAM_CHANNEL_ID,
            text=message,
            parse_mode=ParseMode.HTML,
        )

        # Обновляем резюме в БД
        await asyncio.to_thread(set_article_summary, int(last["id"]), summary)

        await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Готово: новость перевыпущена.")
    except Exception as e:
        logger.error(f"Ошибка при перевыпуске новости: {e}", exc_info=True)
        await send_message_with_retry(bot=context.bot, chat_id=user_id, text=f"Ошибка перевыпуска: {e}")

async def daily_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет дайджест за предыдущий календарный день."""
    user_id = update.effective_user.id
    await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Начинаю подготовку дайджеста за вчерашний день...")

    try:
        now = now_msk(APP_TZ)
        yesterday = now - timedelta(days=1)
        start_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

        start_utc_iso = to_utc(start_date, APP_TZ).isoformat()
        end_utc_iso = to_utc(end_date, APP_TZ).isoformat()

        summaries = await asyncio.to_thread(
            get_summaries_for_date_range,
            start_utc_iso,
            end_utc_iso
        )

        if not summaries:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text=f"За {yesterday.strftime('%d.%m.%Y')} не найдено статей для создания дайджеста.")
            return

        period_name = f"вчера, {yesterday.strftime('%d %B %Y')}"
        digest_content = await asyncio.to_thread(create_digest, summaries, period_name)

        if not digest_content:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Не удалось создать аналитическую сводку.")
            return

        await asyncio.to_thread(add_digest, f"daily_{yesterday.strftime('%Y-%m-%d')}", digest_content)
        await send_message_with_retry(
            bot=context.bot,
            chat_id=user_id,
            text=f"**Аналитический дайджест за {period_name}:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании суточного дайджеста: {e}", exc_info=True)
        await send_message_with_retry(bot=context.bot, chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


async def weekly_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет дайджест за предыдущую полную неделю (Пн-Вс)."""
    user_id = update.effective_user.id
    await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Начинаю подготовку дайджеста за прошлую неделю...")

    try:
        now = now_msk(APP_TZ)
        last_sunday = now - timedelta(days=now.isoweekday())
        end_of_last_week = last_sunday.replace(hour=23, minute=59, second=59, microsecond=999999)
        start_of_last_week = (end_of_last_week - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

        start_utc_iso = to_utc(start_of_last_week, APP_TZ).isoformat()
        end_utc_iso = to_utc(end_of_last_week, APP_TZ).isoformat()

        summaries = await asyncio.to_thread(
            get_summaries_for_date_range,
            start_utc_iso,
            end_utc_iso
        )

        if not summaries:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="За прошлую неделю не найдено статей для создания дайджеста.")
            return

        period_name = f"прошлую неделю ({start_of_last_week.strftime('%d.%m')} - {end_of_last_week.strftime('%d.%m.%Y')})"
        digest_content = await asyncio.to_thread(create_digest, summaries, period_name)

        if not digest_content:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Не удалось создать аналитическую сводку.")
            return

        await asyncio.to_thread(add_digest, f"weekly_{start_of_last_week.strftime('%Y-%m-%d')}", digest_content)
        await send_message_with_retry(
            bot=context.bot,
            chat_id=user_id,
            text=f"**Аналитический дайджест за {period_name}:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании недельного дайджеста: {e}", exc_info=True)
        await send_message_with_retry(bot=context.bot, chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


async def monthly_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет дайджест за предыдущий полный месяц."""
    user_id = update.effective_user.id
    await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Начинаю подготовку дайджеста за прошлый месяц...")

    try:
        now = now_msk(APP_TZ)
        first_day_of_current_month = now.replace(day=1)
        last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)

        start_date = first_day_of_last_month.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = last_day_of_last_month.replace(hour=23, minute=59, second=59, microsecond=999999)

        start_utc_iso = to_utc(start_date, APP_TZ).isoformat()
        end_utc_iso = to_utc(end_date, APP_TZ).isoformat()

        summaries = await asyncio.to_thread(
            get_summaries_for_date_range,
            start_utc_iso,
            end_utc_iso
        )

        if not summaries:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="За прошлый месяц не найдено статей для создания дайджеста.")
            return

        period_name = f"прошлый месяц ({start_date.strftime('%B %Y')})"
        digest_content = await asyncio.to_thread(create_digest, summaries, period_name)

        if not digest_content:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Не удалось создать аналитическую сводку.")
            return

        await asyncio.to_thread(add_digest, f"monthly_{start_date.strftime('%Y-%m')}", digest_content)
        await send_message_with_retry(
            bot=context.bot,
            chat_id=user_id,
            text=f"**Аналитический дайджест за {period_name}:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании месячного дайджеста: {e}", exc_info=True)
        await send_message_with_retry(bot=context.bot, chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


async def annual_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает и отправляет годовой дайджест на основе дайджестов за год."""
    user_id = update.effective_user.id
    await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Начинаю подготовку итоговой годовой сводки...")

    try:
        digests = await asyncio.to_thread(get_digests_for_period, 365)
        if not digests:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Нет дайджестов за год для анализа.")
            return

        digest_content = await asyncio.to_thread(create_annual_digest, digests)
        if not digest_content:
            await send_message_with_retry(bot=context.bot, chat_id=user_id, text="Не удалось создать годовую сводку.")
            return

        year = datetime.now().year - 1
        await asyncio.to_thread(add_digest, f"annual_{year}", digest_content)
        await send_message_with_retry(
            bot=context.bot,
            chat_id=user_id,
            text=f"**Итоговая аналитическая сводка за {year} год:**\n\n{digest_content}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка при создании годового дайджеста: {e}", exc_info=True)
        await send_message_with_retry(bot=context.bot, chat_id=user_id, text=f"Произошла ошибка при создании сводки: {e}")


def main():
    """Основная функция, запускающая бота."""
    logger.info("Инициализация базы данных...")
    init_db()

    logger.info("Создание и запуск приложения-бота...")
    try:
        log_network_context("NET: startup")
    except Exception:
        pass
    start_metrics_server()
    # Тюнинг HTTP-клиента Telegram для устойчивости к сетевым сбоям
    request = HTTPXRequest(
        read_timeout=float(os.getenv("TG_READ_TIMEOUT", "60")),
        write_timeout=float(os.getenv("TG_WRITE_TIMEOUT", "60")),
        connect_timeout=float(os.getenv("TG_CONNECT_TIMEOUT", "30")),
        pool_timeout=float(os.getenv("TG_POOL_TIMEOUT", "60")),
        http_version=os.getenv("TG_HTTP_VERSION", "1.1"),
    )
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(request)
        .job_queue(JobQueue())
        .post_init(post_init)
        .build()
    )

    # Глобальный обработчик ошибок PTB
    async def on_error(update: Update, context: ContextTypes.DEFAULT_TYPE):
        err = context.error
        # Игнорируем временные DNS‑сбои при polling — они самовосстанавливаются
        if isinstance(err, NetworkError) and "Temporary failure in name resolution" in str(err):
            logger.warning("Polling: временная ошибка DNS, продолжаю без уведомлений")
            return
        if err is not None:
            # Логируем стек конкретного исключения, не "NoneType: None"
            logger.error(
                "Global handler caught an exception",
                exc_info=(type(err), err, getattr(err, "__traceback__", None)),
            )
        else:
            logger.error("Global handler caught an exception, but context.error is None")

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
        application.add_handler(CommandHandler("reissue", reissue_last_command, filters=admin_filter))
        application.add_handler(CommandHandler("daily_digest", daily_digest_command, filters=admin_filter))
        application.add_handler(CommandHandler("weekly_digest", weekly_digest_command, filters=admin_filter))
        application.add_handler(CommandHandler("monthly_digest", monthly_digest_command, filters=admin_filter))
        application.add_handler(CommandHandler("annual_digest", annual_digest_command, filters=admin_filter))

    # Более агрессивные таймауты и короткий интервал опроса, чтобы переживать временные сбои DNS
    application.run_polling(
        drop_pending_updates=True,
        close_loop=False,
        poll_interval=float(os.getenv("TG_POLL_INTERVAL", "1.0")),
        allowed_updates=None,
        timeout=int(os.getenv("TG_LONG_POLL_TIMEOUT", "10")),
    )

if __name__ == "__main__":
    main()
