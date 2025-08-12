import logging
from telegram import Bot
from telegram.constants import ParseMode
from config import TELEGRAM_ADMIN_IDS

logger = logging.getLogger(__name__)

bot_instance: Bot | None = None

def initialize_bot(bot: Bot):
    """Сохраняет экземпляр бота для последующего использования."""
    global bot_instance
    bot_instance = bot
    logger.info("Экземпляр бота успешно инициализирован в модуле уведомлений.")

async def send_admin_notification(message: str):
    """Отправляет асинхронное уведомление всем администраторам."""
    if not bot_instance:
        logger.error("Экземпляр бота не инициализирован. Уведомление не отправлено.")
        return

    if not TELEGRAM_ADMIN_IDS:
        logger.warning("Список ID администраторов пуст. Уведомление не отправлено.")
        return

    for admin_id in TELEGRAM_ADMIN_IDS:
        try:
            await bot_instance.send_message(
                chat_id=admin_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Уведомление успешно отправлено администратору {admin_id}.")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление администратору {admin_id}: {e}")
