import os
import sys

# --- Настройка путей для корректного импорта ---
# Этот блок должен выполняться перед импортом модулей из src.
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- Импорты ---
# Все импорты размещены здесь, после модификации пути,
# чтобы обеспечить корректную загрузку модулей из 'src'.
import logging  # noqa: E402
import click  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from src.database import (  # noqa: E402
    init_db,
    get_articles_for_backfill,
    update_article_backfill_status,
    get_stats
)
from src.parser import get_article_text  # noqa: E402
from src.summarizer import summarize_text_local as summarize  # noqa: E402

# --- Загрузка переменных окружения ---
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Настройка и инициализация ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def _process_articles(articles):
    """Общая логика для обработки списка статей."""
    if not articles:
        click.echo("Нет статей для обработки.")
        return

    total = len(articles)
    click.echo(f"Найдено {total} статей для обработки.")

    with click.progressbar(articles, label='Обработка статей') as bar:
        for article in bar:
            try:
                # 1. Парсинг
                article_text = get_article_text(article['url'])
                if not article_text:
                    raise ValueError("Текст статьи не получен")

                # 2. Суммаризация
                summary = summarize(article_text)
                if not summary:
                    raise ValueError("Резюме не было сгенерировано")

                # 3. Обновление статуса
                update_article_backfill_status(article['id'], 'success', summary)
                logging.info(f"Статья {article['url']} успешно обработана.")

            except Exception as e:
                logging.error(f"Ошибка при обработке статьи {article['url']}: {e}")
                update_article_backfill_status(article['id'], 'failed')


@click.group()
def cli():
    """Инструмент для управления новостным ботом."""
    init_db()
    pass


@cli.command()
@click.option('--force', is_flag=True, help='Запустить без интерактивного подтверждения.')
def backfill(force):
    """
    Заполняет исторические данные для всех необработанных статей.
    """
    if not force:
        # В тестах мы не можем использовать confirm, поэтому добавляем проверку
        if sys.stdin.isatty():
            click.confirm('Вы уверены, что хотите запустить полный backfill? Это может занять много времени.', abort=True)
        else:
            click.echo("Пропущен интерактивный запрос (не в терминале).")

    click.echo("Запуск процесса backfill...")
    articles_to_process = get_articles_for_backfill()
    _process_articles(articles_to_process)
    click.echo("Процесс backfill завершен.")


@cli.command()
def status():
    """Показывает статистику по базе данных."""
    click.echo("Получение статистики...")
    stats = get_stats()
    click.echo("Статистика:")
    click.echo(f"  - Всего статей: {stats.get('total_articles', 0)}")
    click.echo(f"  - Обработано успешно: {stats.get('success', 0)}")
    click.echo(f"  - Ожидает обработки: {stats.get('pending', 0)}")
    click.echo(f"  - Ошибок: {stats.get('failed', 0)}")
    click.echo(f"  - Пропущено: {stats.get('skipped', 0)}")
    last_article = stats.get('last_posted_article', {})
    click.echo(f"  - Последняя статья: \"{last_article.get('title', 'N/A')}\" ({last_article.get('published_at', 'N/A')})")


@cli.command('retry-failed')
@click.option('--force', is_flag=True, help='Запустить без интерактивного подтверждения.')
def retry_failed(force):
    """Повторяет обработку статей, завершившихся с ошибкой."""
    if not force:
        if sys.stdin.isatty():
            click.confirm('Вы уверены, что хотите повторить обработку всех ошибочных статей?', abort=True)
        else:
            click.echo("Пропущен интерактивный запрос (не в терминале).")

    click.echo("Запуск повторной обработки ошибочных статей...")
    failed_articles = get_articles_for_backfill(status='failed')
    _process_articles(failed_articles)
    click.echo("Повторная обработка завершена.")


if __name__ == '__main__':
    cli()
