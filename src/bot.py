import asyncio
import logging
from telegram import Bot
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_async

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

POSTED_ARTICLES_FILE = "posted_links.txt"

def load_posted_links() -> set:
    """Загружает уже опубликованные ссылки из файла."""
    try:
        with open(POSTED_ARTICLES_FILE, 'r') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_posted_link(link: str):
    """Сохраняет новую опубликованную ссылку в файл."""
    with open(POSTED_ARTICLES_FILE, 'a') as f:
        f.write(link + '\n')

async def check_and_post_news():
    """Проверяет наличие новых статей и публикует их в Telegram-канал."""
    logger.info("Начинаю проверку новостей...")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    posted_links = load_posted_links()
    
    # Получаем статьи с первой страницы
    articles = get_articles_from_page(1)
    if not articles:
        logger.info("Не удалось получить список статей.")
        return

    logger.info(f"Найдено {len(articles)} статей на странице. Начинаю обработку...")

    for article in reversed(articles):
        if article['link'] not in posted_links:
            logger.info(f"Найдена новая статья: {article['title']}")
            
            # Получаем полный текст статьи
            full_text = get_article_text(article['link'])
            
            if not full_text:
                logger.warning(f"Не удалось получить текст для статьи: {article['title']}")
                continue

            # Суммируем текст
            summary = await summarize_text_async(full_text)
            
            if not summary:
                logger.warning(f"Не удалось суммировать статью: {article['title']}")
                continue

            # Формируем и отправляем сообщение
            message = f"<b>{article['title']}</b>\n\n{summary}\n\n<a href='{article['link']}'>Источник</a>"
            
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID, 
                    text=message, 
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Статья успешно отправлена в канал: {article['title']}")
                save_posted_link(article['link'])
                await asyncio.sleep(10)  # Пауза между постами
            except Exception as e:
                logger.error(f"Ошибка при отправке статьи '{article['title']}': {e}")

        else:
            logger.info(f"Статья уже была опубликована: {article['title']}")

    logger.info("Проверка новостей завершена.")

async def main():
    """Основная функция, запускающая бота в бесконечном цикле."""
    logger.info("Бот запускается...")
    while True:
        try:
            await check_and_post_news()
        except Exception as e:
            logger.critical(f"Произошла критическая ошибка в основном цикле: {e}")
        
        logger.info("Следующая проверка через 5 минут.")
        await asyncio.sleep(300) # Пауза 5 минут

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")