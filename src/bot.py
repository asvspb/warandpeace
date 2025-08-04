import asyncio
import logging
import threading
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_ID
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local
from database import init_db, add_article, is_article_posted
from healthcheck import run_health_check_server

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def send_admin_notification(message: str):
    """Отправляет уведомление администратору бота."""
    logger.info(f"Попытка отправить уведомление администратору. TELEGRAM_ADMIN_ID: {TELEGRAM_ADMIN_ID}")
    if TELEGRAM_ADMIN_ID:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        try:
            await application.bot.send_message(chat_id=TELEGRAM_ADMIN_ID, text=f"[КРИТИЧЕСКАЯ ОШИБКА]\n\n{message}")
            logger.info(f"Уведомление администратору отправлено: {message[:50]}...")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление администратору (ID: {TELEGRAM_ADMIN_ID}): {e}")
    else:
        logger.warning("TELEGRAM_ADMIN_ID не установлен. Уведомления администратору не будут отправляться.")

async def check_and_post_news():
    """Проверяет наличие новых статей и публикует не более 3 самых свежих."""
    logger.info("Начинаю проверку новостей...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    all_articles = await asyncio.to_thread(get_articles_from_page, 1)
    if not all_articles:
        logger.info("Не удалось получить список статей.")
        return

    logger.info(f"Найдено {len(all_articles)} статей на странице. Идет фильтрация новых...")

    new_articles = []
    for article in all_articles:
        if not is_article_posted(article['link']):
            new_articles.append(article)
    
    if not new_articles:
        logger.info("Новых статей не найдено.")
        return

    logger.info(f"Найдено {len(new_articles)} новых статей. Публикуем не более 3 самых свежих.")

    articles_to_post = sorted(new_articles, key=lambda x: (x['date'], x['time']))[-3:]

    # Получаем @username канала для подписи
    try:
        chat = await application.bot.get_chat(chat_id=TELEGRAM_CHANNEL_ID)
        channel_username = f"@{chat.username}"
    except Exception as e:
        logger.error(f"Не удалось получить username канала: {e}. Использую ID.")
        channel_username = TELEGRAM_CHANNEL_ID

    for article in articles_to_post:
        logger.info(f"Обрабатывается новая статья: {article['title']}")
        
        full_text = await asyncio.to_thread(get_article_text, article['link'])
        
        if not full_text:
            logger.warning(f"Не удалось получить текст для статьи: {article['title']}")
            continue

        summary = await asyncio.to_thread(summarize_text_local, full_text)
        
        if not summary:
            logger.warning(f"Не удалось суммировать статью: {article['title']}")
            continue

        # Формируем сообщение: Заголовок, резюме, подпись
        message = f"<b>{article['title']}</b>\n\n{summary} {channel_username}"
        
        try:
            await application.bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID, 
                text=message,
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Статья успешно отправлена в канал: {article['title']}")
            add_article(article['link'], article['title'])
            await asyncio.sleep(15)
        except Exception as e:
            logger.error(f"Ошибка при отправке статьи '{article['title']}': {e}")

    logger.info("Проверка новостей завершена.")

async def main():
    """Основная функция, запускающая бота в бесконечном цикле."""
    logger.info("Бот запускается в штатном режиме...")
    init_db()

    # Запуск health check сервера в отдельном потоке
    try:
        health_check_thread = threading.Thread(target=run_health_check_server, daemon=True)
        health_check_thread.start()
        logger.info("Сервер для health check успешно запущен.")
    except Exception as e:
        logger.critical(f"Не удалось запустить сервер для health check: {e}")
        await send_admin_notification(f"Не удалось запустить сервер для health check: {e}")

    while True:
        try:
            await check_and_post_news()
        except Exception as e:
            logger.critical(f"Произошла критическая ошибка в основном цикле: {e}")
            await send_admin_notification(f"Критическая ошибка в основном цикле бота: {e}")
        
        logger.info("Следующая проверка через 5 минут.")
        await asyncio.sleep(300)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")