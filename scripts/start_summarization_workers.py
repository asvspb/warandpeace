#!/usr/bin/env python3
"""
Скрипт для запуска воркеров суммаризации.
"""
import argparse
import logging
import signal
import sys
import os

# Добавляем директорию src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.queue_workers import worker_loop

def main():
    parser = argparse.ArgumentParser(description='Запуск воркеров суммаризации')
    parser.add_argument('--workers', type=int, default=1, help='Количество воркеров (по умолчанию: 1)')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Уровень логирования (по умолчанию: INFO)')
    
    args = parser.parse_args()
    
    # Настраиваем логирование
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Запуск {args.workers} воркер(ов) суммаризации")
    
    if args.workers > 1:
        logger.warning("В данной реализации поддерживается только 1 воркер. Многопроцессорная обработка требует дополнительной настройки.")
    
    def signal_handler(sig, frame):
        logger.info("Получен сигнал остановки, завершаем работу...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Запускаем воркер
    worker_loop()

if __name__ == "__main__":
    main()