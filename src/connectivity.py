# -*- coding: utf-8 -*-
"""
Модуль для управления состоянием соединения с Telegram.

Реализует механизм "предохранителя" (Circuit Breaker) для предотвращения
лавинообразных ошибок при длительной недоступности API Telegram.
"""
import logging
import os
import time
from threading import RLock

# --- Состояния предохранителя ---
STATE_CLOSED = "CLOSED"  # Соединение считается стабильным, запросы разрешены.
STATE_OPEN = "OPEN"      # Соединение разорвано, запросы блокируются.
STATE_HALF_OPEN = "HALF_OPEN" # Пробный период, разрешен один запрос для проверки.

logger = logging.getLogger()

class TelegramCircuitBreaker:
    """
    Отслеживает состояние доступности Telegram API.
    """
    def __init__(self):
        # Загрузка настроек из переменных окружения с разумными дефолтами
        self.failure_threshold = int(os.getenv("TG_CB_FAILURE_THRESHOLD", 5))
        self.failure_window_sec = int(os.getenv("TG_CB_FAILURE_WINDOW_SEC", 60))
        self.open_state_cooldown_sec = int(os.getenv("TG_CB_OPEN_COOLDOWN_SEC", 30))

        self._lock = RLock()
        self.reset()

    def reset(self):
        """Сбрасывает предохранитель в исходное состояние."""
        with self._lock:
            self._state = STATE_CLOSED
            self._failures = []
            self._opened_at = 0
            logger.info("Соединение стабильно, запросы к Telegram разрешены.")

    @property
    def state(self):
        """Возвращает текущее состояние."""
        with self._lock:
            return self._state

    def note_failure(self):
        """
        Регистрирует сбой при вызове API. Если количество сбоев превышает
        порог, предохранитель переходит в состояние OPEN.
        """
        with self._lock:
            if self._state == STATE_OPEN:
                return  # Уже в открытом состоянии, ничего не делаем

            current_time = time.time()
            self._failures.append(current_time)

            # Удаляем старые сбои, которые вышли за пределы временного окна
            window_start_time = current_time - self.failure_window_sec
            self._failures = [t for t in self._failures if t >= window_start_time]

            # Если в окне набралось достаточно сбоев, размыкаем цепь
            if len(self._failures) >= self.failure_threshold:
                self._state = STATE_OPEN
                self._opened_at = current_time
                logger.critical(
                    f"Circuit Breaker перешел в состояние OPEN. "
                    f"Обнаружено {len(self._failures)} сбоев за последние {self.failure_window_sec} сек."
                )

    def note_success(self):
        """
        Регистрирует успешный вызов. Если предохранитель был в состоянии
        OPEN или HALF_OPEN, он сбрасывается в CLOSED.
        """
        with self._lock:
            if self._state != STATE_CLOSED:
                logger.info("Соединение с Telegram восстановлено. Запросы к Telegram снова разрешены.")
                self.reset()

    def is_open(self) -> bool:
        """
        Проверяет, разрешены ли в данный момент вызовы к API.

        Returns:
            True, если вызовы заблокированы (состояние OPEN).
            False, если вызовы разрешены (состояние CLOSED или HALF_OPEN).
        """
        with self._lock:
            if self._state == STATE_CLOSED:
                return False

            if self._state == STATE_OPEN:
                # Проверяем, прошел ли период "остывания"
                if time.time() - self._opened_at >= self.open_state_cooldown_sec:
                    self._state = STATE_HALF_OPEN
                    logger.warning("Circuit Breaker перешел в состояние HALF_OPEN. Будет предпринята пробная попытка.")
                    return False  # Разрешаем один пробный вызов
                else:
                    return True # Все еще "остываем", вызовы блокированы

            # В состоянии HALF_OPEN мы уже разрешили один вызов,
            # поэтому для всех последующих считаем цепь разомкнутой,
            # пока не будет вызван note_success() или note_failure().
            return False


# Глобальный экземпляр предохранителя для всего приложения
circuit_breaker = TelegramCircuitBreaker()
