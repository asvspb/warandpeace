import subprocess
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_full_database_sync():
    """
    Запускает полный процесс синхронизации новостной базы данных.

    Этот скрипт выполняет два этапа:
    1. Быстрое обновление по основной новостной ленте (главные 15 страниц).
    2. Полная сверка с архивом для заполнения любых пробелов.
    """
    logger.info("Запускаю скрипт полной синхронизации: scripts/sync_news_database.py")
    
    # Убедимся, что мы запускаем скрипт из корневой директории проекта
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    script_path = os.path.join(project_root, 'scripts', 'sync_news_database.py')

    if not os.path.exists(script_path):
        logger.error(f"Скрипт не найден по пути: {script_path}")
        return

    try:
        # Запускаем скрипт и ждем его завершения, захватывая вывод
        process = subprocess.run(
            ['python3', script_path],
            capture_output=True,
            text=True,
            check=True,  # Вызовет исключение, если скрипт завершится с ошибкой
            cwd=project_root # Устанавливаем рабочую директорию
        )
        logger.info("Вывод скрипта синхронизации:\n" + process.stdout)
        if process.stderr:
            logger.warning("Ошибки скрипта синхронизации:\n" + process.stderr)
        
        logger.info("Синхронизация успешно завершена.")

    except FileNotFoundError:
        logger.error("Ошибка: 'python3' не найден. Убедитесь, что Python 3 установлен и доступен в PATH.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Скрипт синхронизации завершился с ошибкой (код возврата: {e.returncode}).")
        logger.error("STDOUT:\n" + e.stdout)
        logger.error("STDERR:\n" + e.stderr)
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при запуске скрипта синхронизации: {e}")

if __name__ == '__main__':
    # Этот блок позволяет запустить функцию напрямую для тестирования
    run_full_database_sync()
