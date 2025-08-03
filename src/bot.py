import asyncio
import logging
from telegram import Bot
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local
from database import init_db, add_article, is_article_posted

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def check_and_post_news():
    """Проверяет наличие новых статей и публикует их в Telegram-канал."""
    logger.info("Начинаю проверку новостей...")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    articles = await asyncio.to_thread(get_articles_from_page, 1)
    if not articles:
        logger.info("Не удалось получить список статей.")
        return

    logger.info(f"Найдено {len(articles)} статей на странице. Начинаю обработку...")

    for article in reversed(articles):
        if not is_article_posted(article['link']):
            logger.info(f"Найдена новая статья: {article['title']}")
            
            full_text = await asyncio.to_thread(get_article_text, article['link'])
            
            if not full_text:
                logger.warning(f"Не удалось получить текст для статьи: {article['title']}")
                continue

            summary = await asyncio.to_thread(summarize_text_local, full_text)
            
            if not summary:
                logger.warning(f"Не удалось суммировать статью: {article['title']}")
                continue

            message = f"{summary}" # Только резюме
            
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID, 
                    text=message, 
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Статья успешно отправлена в канал: {article['title']}")
                add_article(article['link'], article['title'])
                await asyncio.sleep(10) # Задержка между постами
            except Exception as e:
                logger.error(f"Ошибка при отправке статьи '{article['title']}': {e}")

        else:
            logger.info(f"Статья уже была опубликована: {article['title']}")

    logger.info("Проверка новостей завершена.")

async def main():
    """Основная функция, запускающая бота в бесконечном цикле."""
    logger.info("Бот запускается...")
    init_db()
    while True:
        try:
            await check_and_post_news()
        except Exception as e:
            logger.critical(f"Произошла критическая ошибка в основном цикле: {e}")
        
        logger.info("Следующая проверка через 5 минут.")
        await asyncio.sleep(300)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")