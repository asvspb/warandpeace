import logging
import os
from collections import defaultdict
from time import monotonic
from typing import List

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Кэш админских ID и троттлинг-стейт
_cached_admin_ids: List[int] | None = None
_last_sent_at = defaultdict(float)  # throttle_key -> timestamp


def _load_admin_ids() -> List[int]:
    """Загружает список администраторов из окружения.

    Поддерживает обе формы: TELEGRAM_ADMIN_ID (один ID) и TELEGRAM_ADMIN_IDS (через запятую).
    Исключает дубликаты, игнорирует некорректные значения.
    """
    global _cached_admin_ids
    if _cached_admin_ids is not None:
        return _cached_admin_ids

    ids: set[int] = set()

    single_id = os.getenv("TELEGRAM_ADMIN_ID")
    if single_id:
        try:
            ids.add(int(single_id))
        except Exception:
            logger.warning("TELEGRAM_ADMIN_ID не является целым числом: %s", single_id)

    list_ids = os.getenv("TELEGRAM_ADMIN_IDS", "")
    if list_ids:
        for token in list_ids.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                ids.add(int(token))
            except Exception:
                logger.warning("Некорректный ID в TELEGRAM_ADMIN_IDS: %s", token)

    _cached_admin_ids = list(ids)
    return _cached_admin_ids


async def notify_admin(
    bot: Bot,
    message: str,
    *,
    throttle_key: str,
    cooldown_sec: int | None = None,
):
    """Отправляет уведомление администраторам с троттлингом.

    - bot: активный экземпляр Telegram-бота
    - message: текст уведомления (кратко, без PII)
    - throttle_key: ключ события для раздельного троттлинга
    - cooldown_sec: интервал подавления повторов (по умолчанию из ADMIN_ALERTS_COOLDOWN_SEC или 900)
    """
    admin_ids = _load_admin_ids()
    if not admin_ids:
        logger.debug("Список администраторов пуст — уведомление пропущено")
        return

    if cooldown_sec is None:
        try:
            cooldown_sec = int(os.getenv("ADMIN_ALERTS_COOLDOWN_SEC", "900"))
        except Exception:
            cooldown_sec = 900

    now = monotonic()
    last_time = _last_sent_at[throttle_key]
    if now - last_time < cooldown_sec:
        return

    for admin_id in admin_ids:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=message,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error("Не удалось отправить уведомление админу %s: %s", admin_id, e)
            # Не сбрасываем троттлинг, чтобы при флаппинге не спамить
        else:
            _last_sent_at[throttle_key] = now
