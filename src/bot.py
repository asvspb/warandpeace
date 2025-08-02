import asyncio
import logging
from telegram import Bot
from telegram.constants import ParseMode
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
from parser import get_articles_from_page, get_article_text
from summarizer import summarize_text_local

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
    
    articles = await asyncio.to_thread(get_articles_from_page, 1)
    if not articles:
        logger.info("Не удалось получить список статей.")
        return

    logger.info(f"Найдено {len(articles)} статей на странице. Начинаю обработку...")

    for article in list(reversed(articles))[:5]:
        if article['link'] not in posted_links:
            logger.info(f"Найдена новая статья: {article['title']}")
            
            full_text = await asyncio.to_thread(get_article_text, article['link'])
            
            if not full_text:
                logger.warning(f"Не удалось получить текст для статьи: {article['title']}")
                continue

            summary = await asyncio.to_thread(summarize_text_local, full_text)
            
            if not summary:
                logger.warning(f"Не удалось суммировать статью: {article['title']}")
                continue

            message = f"{summary}\n{TELEGRAM_CHANNEL_ID}"
            
            try:
                await bot.send_message(
                    chat_id=TELEGRAM_CHANNEL_ID, 
                    text=message, 
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Статья успешно отправлена в канал: {article['title']}")
                save_posted_link(article['link'])
                await asyncio.sleep(10)
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
        await asyncio.sleep(300)

if __name__ == "__main__":
    try:
        # --- ТЕСТОВЫЙ РЕЖИМ: Запускаем проверку только один раз ---
        print("--- ЗАПУСК БОТА В ТЕСТОВОМ РЕЖИМЕ (ОДИН ПРОХОД) ---")
        asyncio.run(check_and_post_news())
        print("--- ТЕСТОВЫЙ ПРОХОД ЗАВЕРШЕН ---")
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")